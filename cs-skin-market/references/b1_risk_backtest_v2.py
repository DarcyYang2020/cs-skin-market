
# -*- coding: utf-8 -*-
"""B1 风险预算层回测验证 v2：用去量引擎 v2（370 信号）复验 cap/熔断/单票敞口。

输入: data/item_backtest_full_2025.json（2026-08-07 去量 v2 回放）
口径: 仓位=position_limit、hold21（2026-08-10 组合敏感性研究对齐单品 hold_guidance，见 decision-log）、手续费2%、
      拒绝模式优先级 panic(3) > accumulate/base(2) > deep_value(1)（按 action_label 归类）。
旧版 B1（data/b1_risk_validation.json）基于旧引擎 301 信号（深值241/基础20/恐慌40）；
新引擎组合结构剧变（深值241→56、恐慌40→92、吸筹→222），需复验 cap0.8/熔断10% 是否仍成立。

用法: python references/b1_risk_backtest_v2.py [--start 2025-11-02]
结论写入 data/b1_risk_validation_v2.json。
"""
import io as _io
import json
import sys
import argparse
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, ".")

PRIORITY = {"panic": 3, "accumulate": 2, "base": 2, "oversold": 2, "deep_value": 1}
HOLD = 21
COST = 0.02


def classify(label):
    lab = label or ""
    if "恐慌" in lab:
        return "panic"
    if "深值" in lab:
        return "deep_value"
    return "accumulate"


def load_signals(start=None):
    d = json.load(_io.open("data/item_backtest_full_2025.json", encoding="utf-8"))
    out = []
    for s in d["signals"]:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        dt = date.fromisoformat(s["date"])
        if start and dt < date.fromisoformat(start):
            continue
        st = classify(s.get("action_label"))
        out.append({
            "date": dt, "item": s["name"],
            "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
            "fwd": fwd, "st": st, "prio": PRIORITY.get(st, 1),
            "net14": s.get("net14"),
        })
    return out


def simulate(sigs, cap=None, dd_breaker=None, item_cap=None, disarm_at_peak=True):
    by_day = {}
    for s in sigs:
        by_day.setdefault(s["date"], []).append(s)
    first = min(s["date"] for s in sigs)
    last = max(s["date"] for s in sigs) + timedelta(days=HOLD)
    day = first
    active = []
    total_invested = 0.0
    realized = 0.0
    rejected_cap = 0
    rejected_breaker = 0
    rejected_item = 0
    breaker_days = 0
    closed = []  # 每笔平仓盈亏（组合口径逐笔，2026-08-07 Phase 2a）
    curve = []
    max_pos = 0.0
    peak = 1.0
    prev_eq = None
    breaker_on = False
    while day <= last:
        for a in active:
            a["idx"] += 1
        if dd_breaker is not None and prev_eq is not None:
            if breaker_on:
                if prev_eq >= peak if disarm_at_peak else prev_eq >= peak * (1 - dd_breaker / 2):
                    breaker_on = False
            elif prev_eq < peak * (1 - dd_breaker):
                breaker_on = True
        gate = breaker_on and dd_breaker is not None
        if gate:
            breaker_days += 1
        for s in sorted(by_day.get(day, []), key=lambda x: -x["prio"]):
            if gate:
                rejected_breaker += 1
                continue
            if item_cap is not None and s["limit"] > item_cap + 1e-9:
                rejected_item += 1
                continue
            if cap is not None and total_invested + s["limit"] > cap + 1e-9:
                rejected_cap += 1
                continue
            active.append({"s": s, "idx": 0, "base": s["limit"]})
            total_invested += s["limit"]
        unreal = 0.0
        pos_sum = 0.0
        for a in active:
            pos_sum += a["base"]
            k = a["idx"]
            if k <= 0 or k >= HOLD:
                continue
            fwd = a["s"]["fwd"]
            if k > len(fwd):
                continue
            px = fwd[min(k - 1, len(fwd) - 1)]
            unreal += a["base"] * (px / a["s"]["entry"] - 1)
        for a in active:
            if a["idx"] >= HOLD:
                fwd = a["s"]["fwd"]
                px = fwd[min(HOLD - 1, len(fwd) - 1)]
                pnl = a["base"] * (px / a["s"]["entry"] - 1 - COST)
                realized += pnl
                closed.append(pnl)
                total_invested -= a["base"]
        active = [a for a in active if a["idx"] < HOLD]
        eq = 1.0 + realized + unreal
        peak = max(peak, eq)
        curve.append((day.isoformat(), pos_sum, eq, 1 if gate else 0, len(active)))
        max_pos = max(max_pos, pos_sum)
        prev_eq = eq
        day += timedelta(days=1)
    return {
        "curve": curve, "rejected_cap": rejected_cap,
        "rejected_breaker": rejected_breaker, "rejected_item": rejected_item,
        "max_pos": max_pos, "breaker_days": breaker_days,
        "closed": closed, "n_trades": len(closed),
    }


def metrics(res):
    vals = [c[2] for c in res["curve"]]
    peak, max_dd = 1.0, 0.0
    for v in vals:
        peak = max(peak, v)
        max_dd = min(max_dd, (v / peak - 1) * 100)
    total = (vals[-1] / 1.0 - 1) * 100
    n_days = len(vals)
    return {
        "total_return_pct": round(total, 2), "max_drawdown_pct": round(max_dd, 2),
        "max_position": round(res["max_pos"], 3),
        "rejected_cap": res["rejected_cap"], "rejected_breaker": res["rejected_breaker"],
        "rejected_item": res["rejected_item"],
        "breaker_active_pct": round(res["breaker_days"] / n_days * 100, 1) if n_days else 0,
        "days": n_days,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="只取该日期后的信号（项目原则 2025-11-02）")
    args = ap.parse_args()
    sigs = load_signals(start=args.start)
    print("signals: %d  type: %s  range: %s ~ %s" % (
        len(sigs), dict(Counter(s["st"] for s in sigs)), min(s["date"] for s in sigs),
        max(s["date"] for s in sigs)))
    print("%-20s %8s %8s %8s %8s %8s %9s" % (
        "rule", "total%", "maxDD%", "maxPos", "rejCap", "rejBrk", "brkActive%"))

    def show(label, cap, dd=None, item=None, disarm=True):
        r = simulate(sigs, cap=cap, dd_breaker=dd, item_cap=item, disarm_at_peak=disarm)
        m = metrics(r)
        print("%-20s %8.2f %8.2f %8.2f %8d %8d %8.1f%%" % (
            label, m["total_return_pct"], m["max_drawdown_pct"], m["max_position"],
            m["rejected_cap"], m["rejected_breaker"], m["breaker_active_pct"]))
        return m

    results = {}
    results["baseline_nocap"] = show("no cap", cap=None)
    results["baseline_cap06"] = show("cap0.6", cap=0.6)
    results["baseline_cap08"] = show("cap0.8", cap=0.8)
    for dd in (0.05, 0.08, 0.10, 0.15, 0.20):
        results["cap08_dd%.2f" % dd] = show("cap0.8+dd%.2f" % dd, cap=0.8, dd=dd)
    results["cap08_dd10_soft"] = show("cap0.8+dd10软解除", cap=0.8, dd=0.10, disarm=False)
    results["cap08_item10"] = show("cap0.8+单票10%", cap=0.8, item=0.10)
    results["cap08_dd10_item10"] = show("cap0.8+dd10+单票10", cap=0.8, dd=0.10, item=0.10)
    results["dd10_only"] = show("dd0.10 only", cap=None, dd=0.10)

    out = {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
        "note": "B1 v2: 去量引擎 v2 (370信号) 组合回测复验。口径: "
                "hold21/手续费2%/拒绝优先级 panic>accumulate>deep_value; 熔断前一日权益判定, 收复峰值解除。"
                "旧版 b1_risk_validation.json 基于旧引擎 301 信号(深值241/基础20/恐慌40)。",
        "start_filter": args.start,
        "signal_types": dict(Counter(s["st"] for s in sigs)),
        "results": results,
    }
    out_path = "data/b1_risk_validation_v2.json"
    with _io.open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written:", out_path)


if __name__ == "__main__":
    main()
