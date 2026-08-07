# -*- coding: utf-8 -*-
"""I-9 并发 cap 复验（2026-08-07）：去量 v2 370 信号，族级 cap vs 整体 cap。

背景：S3/恐慌族信号密度上升后，需确认 0.8 整体 cap 是否仍最优，或按信号族分组细化。
口径：与 b1_risk_backtest_v2 一致——hold14、手续费 2%、拒绝优先级 panic>accumulate>deep_value；
族级 cap = 同族累计敞口上限（新增），整体 cap 不变。

用法: python references/cap_family_backtest.py
结论写入 data/cap_family_backtest.json
"""
import io as _io
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import b1_risk_backtest_v2 as b1v2

ROOT = Path(__file__).resolve().parent.parent
PRIORITY = {"panic": 3, "accumulate": 2, "oversold": 2, "deep_value": 1}


def classify_action(label):
    lab = label or ""
    if "恐慌" in lab:
        return "panic"
    if "深值" in lab:
        return "deep_value"
    if "深度回调" in lab or "低吸" in lab:
        return "oversold"
    return "accumulate"


def load():
    d = json.load(_io.open(ROOT / "data" / "item_backtest_full_2025.json", encoding="utf-8"))
    out = []
    for s in d["signals"]:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = classify_action(s.get("action_label"))
        out.append({
            "date": date.fromisoformat(s["date"]), "item": s["name"],
            "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
            "fwd": fwd, "st": st, "prio": PRIORITY.get(st, 1),
            "net14": s.get("net14"),
        })
    return out


def simulate_family(sigs, cap=None, family_caps=None):
    """整体 cap + 族级累计敞口 cap（family_caps: {族: 上限}）。"""
    by_day = {}
    for s in sigs:
        by_day.setdefault(s["date"], []).append(s)
    first = min(s["date"] for s in sigs)
    last = max(s["date"] for s in sigs) + timedelta(days=b1v2.HOLD)
    day = first
    active = []
    total_invested = 0.0
    realized = 0.0
    family_inv = {}
    rejected = {"cap": 0, "family": 0}
    curve = []
    peak = 1.0
    while day <= last:
        for a in active:
            a["idx"] += 1
        for s in sorted(by_day.get(day, []), key=lambda x: -x["prio"]):
            if cap is not None and total_invested + s["limit"] > cap + 1e-9:
                rejected["cap"] += 1
                continue
            if family_caps:
                f_inv = family_inv.get(s["st"], 0.0)
                if f_inv + s["limit"] > family_caps.get(s["st"], 9e9) + 1e-9:
                    rejected["family"] += 1
                    continue
            active.append({"s": s, "idx": 0, "base": s["limit"]})
            total_invested += s["limit"]
            family_inv[s["st"]] = family_inv.get(s["st"], 0.0) + s["limit"]
        unreal = 0.0
        pos_sum = 0.0
        for a in active:
            pos_sum += a["base"]
            k = a["idx"]
            if k <= 0 or k >= b1v2.HOLD:
                continue
            fwd = a["s"]["fwd"]
            if k > len(fwd):
                continue
            px = fwd[min(k - 1, len(fwd) - 1)]
            unreal += a["base"] * (px / a["s"]["entry"] - 1)
        for a in active:
            if a["idx"] >= b1v2.HOLD:
                fwd = a["s"]["fwd"]
                px = fwd[min(b1v2.HOLD - 1, len(fwd) - 1)]
                realized += a["base"] * (px / a["s"]["entry"] - 1 - b1v2.COST)
                total_invested -= a["base"]
                family_inv[a["s"]["st"]] = family_inv.get(a["s"]["st"], 0.0) - a["base"]
        active = [a for a in active if a["idx"] < b1v2.HOLD]
        eq = 1.0 + realized + unreal
        peak = max(peak, eq)
        curve.append((day.isoformat(), pos_sum, eq))
        day += timedelta(days=1)
    vals = [c[2] for c in curve]
    peak2, max_dd = 1.0, 0.0
    for v in vals:
        peak2 = max(peak2, v)
        max_dd = min(max_dd, (v / peak2 - 1) * 100)
    return {
        "total_return_pct": round((vals[-1] / 1.0 - 1) * 100, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "max_position": round(max(pos_sum for _, pos_sum, _ in curve), 3),
        "rejected_cap": rejected["cap"], "rejected_family": rejected["family"],
        "days": len(vals),
    }


def main():
    sigs = load()
    fam = Counter(s["st"] for s in sigs)
    print("signals: %d  families: %s  range: %s ~ %s" % (
        len(sigs), dict(fam), min(s["date"] for s in sigs), max(s["date"] for s in sigs)))
    rows = [
        ("no cap", {}, None),
        ("cap0.6", {}, 0.6),
        ("cap0.8", {}, 0.8),
        ("cap1.0", {}, 1.0),
        ("cap0.8 + panic族0.3", {"panic": 0.3}, 0.8),
        ("cap0.8 + panic族0.4", {"panic": 0.4}, 0.8),
        ("cap0.8 + accumulate族0.5", {"accumulate": 0.5}, 0.8),
        ("cap0.8 + 族均0.3", {"panic": 0.3, "accumulate": 0.3, "deep_value": 0.3, "oversold": 0.3}, 0.8),
    ]
    results = {}
    print("%-28s %8s %8s %8s %8s %8s" % ("rule", "total%", "maxDD%", "maxPos", "rejCap", "rejFam"))
    for label, fc, cap in rows:
        r = simulate_family(sigs, cap=cap, family_caps=fc or None)
        results[label] = r
        print("%-28s %8.2f %8.2f %8.2f %8d %8d" % (
            label, r["total_return_pct"], r["max_drawdown_pct"], r["max_position"],
            r["rejected_cap"], r["rejected_family"]))
    out = {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
        "note": "I-9 cap 复验：去量 v2 370 信号，整体 cap vs 族级 cap。口径同 b1_risk_backtest_v2（hold14/费2%/拒绝优先级 panic>accumulate>deep_value）。",
        "families": dict(fam),
        "results": results,
    }
    out_path = ROOT / "data" / "cap_family_backtest.json"
    _io.open(out_path, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    print("written:", out_path)


if __name__ == "__main__":
    main()
