# -*- coding: utf-8 -*-
"""B1 风险预算层回测验证：组合回撤熔断 + 单票敞口上限（离线只读，不改引擎信号）。

数据: data/deepvalue_replay_tmp.json（301 信号, 2025-11-02~2026-07-13 组合回放）。
口径与 references/portfolio_cap_fit.py 一致：仓位=position_limit、hold14、手续费2%、
拒绝模式优先级 panic > base > deep_value。

验证目标：
1. 组合回撤熔断：组合权益（已实现+未实现）自峰值回撤 X% 时拒绝新信号，权益收复峰值后解除
   （滞回）。叠加 cap=0.8 拒绝模式（2026-08-04 现有最优）。
2. 单票敞口：单信号建议仓位 > 上限时拒绝（cap 的分量版），验证 PORTFOLIO_CAP_CONCURRENT
   之外单票上限是否还有额外价值。

结论写入 data/b1_risk_validation.json，供决策日志引用。
"""
import io
import json
import sys
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, ".")

PRIORITY = {"panic": 3, "base": 2, "deep_value": 1, "oversold": 2, "accumulate": 2}
HOLD = 14
COST = 0.02


def load_signals():
    d = json.load(io.open("data/deepvalue_replay_tmp.json", encoding="utf-8"))
    out = []
    for s in d["signals"]:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = s.get("signal_type") or "base"
        if abs((s.get("position_limit") or 0) - 0.10) < 0.001:
            st = "deep_value"
        out.append({
            "date": date.fromisoformat(s["date"]), "item": s["name"],
            "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
            "fwd": fwd, "st": st, "prio": PRIORITY.get(st, 1),
            "net14": s.get("net14"),
        })
    return out


def simulate(sigs, cap=None, dd_breaker=None, item_cap=None, disarm_at_peak=True):
    """组合模拟。dd_breaker: 权益峰值回撤触发阈值(如 0.10)；item_cap: 单票建议仓位上限。
    熔断判定用「前一日收盘权益 vs 峰值」，当日信号按该状态放行/拒绝（现实一日滞后）。"""
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
    curve = []
    max_pos = 0.0
    peak = 1.0
    prev_eq = None
    breaker_on = False
    while day <= last:
        for a in active:
            a["idx"] += 1
        # 熔断判定：基于前一交易日收盘权益
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
                realized += a["base"] * (px / a["s"]["entry"] - 1 - COST)
                total_invested -= a["base"]
        active = [a for a in active if a["idx"] < HOLD]
        eq = 1.0 + realized + unreal
        peak = max(peak, eq)
        curve.append((day.isoformat(), pos_sum, eq, 1 if gate else 0))
        max_pos = max(max_pos, pos_sum)
        prev_eq = eq
        day += timedelta(days=1)
    return {
        "curve": curve, "rejected_cap": rejected_cap,
        "rejected_breaker": rejected_breaker, "rejected_item": rejected_item,
        "max_pos": max_pos, "breaker_days": breaker_days,
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
    sigs = load_signals()
    print("signals: %d  type: %s" % (len(sigs), dict(Counter(s["st"] for s in sigs))))
    print("%-18s %8s %8s %8s %8s %8s %9s" % (
        "rule", "total%", "maxDD%", "maxPos", "rejCap", "rejBrk", "brkActive%"))

    def show(label, cap, dd=None, item=None, disarm=True):
        r = simulate(sigs, cap=cap, dd_breaker=dd, item_cap=item, disarm_at_peak=disarm)
        m = metrics(r)
        print("%-18s %8.2f %8.2f %8.2f %8d %8d %8.1f%%" % (
            label, m["total_return_pct"], m["max_drawdown_pct"], m["max_position"],
            m["rejected_cap"], m["rejected_breaker"], m["breaker_active_pct"]))
        return m

    results = {}
    results["baseline_cap08"] = show("cap0.8", cap=0.8)
    for dd in (0.05, 0.08, 0.10, 0.15, 0.20):
        results["cap08_dd%.2f" % dd] = show("cap0.8+dd%.2f" % dd, cap=0.8, dd=dd)
    results["cap08_dd10_soft"] = show("cap0.8+dd10软解除", cap=0.8, dd=0.10, disarm=False)
    results["cap08_item10"] = show("cap0.8+单票10%", cap=0.8, item=0.10)
    results["cap08_dd10_item10"] = show("cap0.8+dd10+单票10", cap=0.8, dd=0.10, item=0.10)
    results["dd10_only"] = show("dd0.10 only", cap=None, dd=0.10)

    with io.open("data/b1_risk_validation.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated": date.today().isoformat(),
            "note": "B1 风险预算层回测: 组合回撤熔断(前一日权益判定, 收复峰值解除) + 单票敞口上限",
            "results": {k: v for k, v in results.items()},
        }, f, ensure_ascii=False, indent=2)
    print("written data/b1_risk_validation.json")


if __name__ == "__main__":
    main()
