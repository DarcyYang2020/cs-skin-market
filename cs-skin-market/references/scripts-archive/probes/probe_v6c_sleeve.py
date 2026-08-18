# -*- coding: utf-8 -*-
"""v6c 长持 sleeve 组合级验证（2026-08-16，用户决策「合纵收益最高」）。

主池 = 官方 v2-T12 产物（rise 跟踪 5% 口径，同 probe_rise_sleeve 模拟）；
长持 sleeve = C1 条件日（TH≥55 + 3<chg7≤15 + s7≤0.85s30 + sc30≤-5 + pct>40 + 正常窗）
每笔 0.05、持有 180 交易日、sleeve 独立 cap、扣 2% 双边。
注：C1 条件日为池级全样本（未过引擎守卫/存世量/地板），为结构级近似；引擎侧发射将更少。
"""
import io
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

from pipeline.backtest_common import build_market_context  # noqa: E402
from pipeline.market_macro import historical_event_impact  # noqa: E402

spec = spec_from_file_location("b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
b1v2 = module_from_spec(spec)
spec.loader.exec_module(b1v2)
spec2 = spec_from_file_location("pfb", str(ROOT / "references" / "portfolio_backtest.py"))
pfb = module_from_spec(spec2)
spec2.loader.exec_module(pfb)

OUT = ROOT / "data" / "_exp_v6c_sleeve.json"
HOLD = 180
SPLIT = "2025-08-10"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def base_curve():
    d = json.load(io.open(ROOT / "data" / "_exp_cycle_replay_2026.json", encoding="utf-8"))
    sigs = []
    for s in d.get("signals", []):
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = b1v2.classify(s.get("action_label"))
        sigs.append({"date": date.fromisoformat(s["date"]), "item": s["name"],
                     "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
                     "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1),
                     "mom": "吸筹型上涨" in (s.get("action_label") or "")})
    by_day = {}
    for s in sigs:
        by_day.setdefault(s["date"], []).append(s)
    first = min(s["date"] for s in sigs)
    last = max(s["date"] for s in sigs) + timedelta(days=21)
    day = first
    active = []
    ti = 0.0
    realized = 0.0
    curve = []
    while day <= last:
        for a in active:
            a["idx"] += 1
        for s in sorted(by_day.get(day, []), key=lambda x: -x["prio"]):
            if ti + s["limit"] > 0.8 + 1e-9:
                continue
            active.append({"s": s, "idx": 0, "base": s["limit"], "peak": 1.0})
            ti += s["limit"]
        unreal = 0.0
        closes = []
        for a in active:
            k = a["idx"]
            if k <= 0:
                continue
            fwd = a["s"]["fwd"]
            px = fwd[min(k - 1, len(fwd) - 1)]
            ret = px / a["s"]["entry"] - 1
            a["peak"] = max(a["peak"], 1 + ret)
            ex = k >= 21
            if a["s"]["mom"] and 1 + ret <= a["peak"] * 0.95:
                ex = True
            if ex:
                realized += a["base"] * (ret - 0.02)
                ti -= a["base"]
                closes.append(a)
            else:
                unreal += a["base"] * ret
        for a in closes:
            active.remove(a)
        curve.append((day.isoformat(), 1.0 + realized + unreal))
        day += timedelta(days=1)
    return curve


def c1_days():
    ctx = build_market_context("2023-11-17", end="2026-08-05")
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    c.close()
    out = []
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    for iid in items:
        rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        n = len(prices)
        sc = [None] * n
        for i in range(59, n):
            ok30 = all(x is not None for x in insale[i - 29:i + 1])
            ok30a = all(x is not None for x in insale[i - 59:i - 29])
            if ok30 and ok30a:
                s30 = sum(insale[i - 29:i + 1]) / 30
                s30a = sum(insale[i - 59:i - 29]) / 30
                if s30a > 0:
                    sc[i] = (s30 / s30a - 1) * 100
        for i in range(60, n):
            d = dates[i]
            m = ctx.get(d)
            if not m or m["th"] < 55 or historical_event_impact(d, 30):
                continue
            if pct90(prices, i) <= 40:
                continue
            chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else None
            if chg7 is None or not (3 < chg7 <= 15):
                continue
            ok7 = all(x is not None for x in insale[i - 6:i + 1])
            ok30 = all(x is not None for x in insale[i - 29:i + 1])
            if not (ok7 and ok30):
                continue
            s7 = sum(insale[i - 6:i + 1]) / 7
            s30 = sum(insale[i - 29:i + 1]) / 30
            if s30 <= 0 or s7 > s30 * 0.85:
                continue
            if sc[i] is None or sc[i] > -5:
                continue
            out.append({"date": d, "i": i, "prices": prices, "n": n})
    c.close()
    return out


def main():
    base = base_curve()
    c1 = c1_days()
    by_day = {}
    for e in c1:
        by_day.setdefault(e["date"], []).append(e)
    first = date.fromisoformat(min(base)[0])
    last = date.fromisoformat(max(base)[0])
    day = first
    active = []
    invested = 0.0
    realized = 0.0
    merged = []
    base_map = dict(base)
    while day <= last:
        d = day.isoformat()
        # 长持 sleeve：入场 + 持仓结算
        for e in by_day.get(d, []):
            if invested + 0.05 > 0.2 + 1e-9:
                continue
            active.append({"e": e, "idx": 0})
            invested += 0.05
        unreal = 0.0
        closes = []
        for a in active:
            a["idx"] += 1
            k = a["idx"]
            e = a["e"]
            if k >= HOLD or e["i"] + k >= e["n"]:
                ret = e["prices"][min(e["i"] + k, e["n"] - 1)] / e["prices"][e["i"]] - 1
                realized += 0.05 * (ret - 0.02)
                invested -= 0.05
                closes.append(a)
            else:
                ret = e["prices"][e["i"] + k] / e["prices"][e["i"]] - 1
                unreal += 0.05 * ret
        for a in closes:
            active.remove(a)
        eq = base_map[d] if d in base_map else 1.0
        merged.append((d, eq + realized + unreal))
        day += timedelta(days=1)

    def seg(pts):
        vals = [v for _, v in pts]
        if len(vals) < 2:
            return (0.0, 0.0)
        total = (vals[-1] / vals[0] - 1) * 100
        peak = vals[0]
        mdd = 0.0
        for v in vals:
            peak = max(peak, v)
            mdd = min(mdd, (v / peak - 1) * 100)
        return (round(total, 2), round(mdd, 2))

    f = seg([(d, v) for d, v in merged if d < SPLIT])
    b = seg([(d, v) for d, v in merged if d >= SPLIT])
    vals = [v for _, v in merged]
    total = (vals[-1] / vals[0] - 1) * 100
    peak = vals[0]
    mdd = 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100)
    days = (date.fromisoformat(merged[-1][0]) - date.fromisoformat(merged[0][0])).days
    ann = ((vals[-1] / vals[0]) ** (365.0 / days) - 1) * 100 if days > 0 else None
    print("C1 长持 sleeve 入场数: %d（sleeve cap 0.2, 每笔 0.05, hold180, 扣2%%）" % len(c1))
    print("合并组合: total=%.2f mdd=%.2f calmar=%.2f ann=%.2f | front=%s back=%s" % (
        total, mdd, abs(ann / mdd) if ann and mdd < 0 else 0, ann or 0, f, b))
    bv = [v for _, v in base]
    btotal = (bv[-1] / bv[0] - 1) * 100
    print("基线(v2-T12 跟踪5%%): total=%.2f" % btotal)
    out = {"probe": "v6c 长持sleeve", "c1_entries": len(c1), "merged_total": round(total, 2),
           "merged_mdd": round(mdd, 2), "front": f, "back": b, "baseline_total": round(btotal, 2)}
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
