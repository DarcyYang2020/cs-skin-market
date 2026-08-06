# -*- coding: utf-8 -*-
"""牛市段趋势腿研究（2026-08-06）：2025-01-01~2025-10-31 五合一前完整牛市。

验证 S2 回踩 / S3 吸筹在牛市段的期望、事件簇结构、v1 门控反应与路由边界。
关键设计：同物品池（98 老品，2025-01-01 起有数据）对比「牛市窗 vs 基准窗」，
避免物品池差异污染窗口对比。输出 data/trend_leg_bull.json。
"""
import sys, io, json, statistics
from datetime import datetime
sys.path.insert(0, ".")
import os

SAVE = os.environ.get("TREND_BULL_SAVE", "data/trend_leg_bull.json")
COST = 0.02
BULL_START, BULL_END = "2025-01-01", "2025-10-31"   # 五合一前完整牛市（含10月崩盘）
BASE_START, BASE_END = "2025-11-02", "2026-08-05"   # 当前基准窗口（同物品池对比）


def load_series(item_id):
    from pipeline import db
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT p.date, p.price_rmb, p.volume_day, p.in_sale_count
           FROM price_history p WHERE p.item_id = ? AND p.id IN (
               SELECT MAX(id) FROM price_history WHERE item_id = ? GROUP BY date
           ) ORDER BY p.date""", (item_id, item_id)).fetchall()
    conn.close()
    return [r["date"] for r in rows], [r["price_rmb"] for r in rows], [r["in_sale_count"] or 0 for r in rows]


def load_items():
    from run_item_backtest import load_items as _li
    return _li()


def ma(vals, i, n):
    if i + 1 < n:
        return None
    s = vals[i - n + 1:i + 1]
    return sum(s) / n if len(s) == n and all(x is not None and x > 0 for x in s) else None


def chg(vals, i, n):
    if i < n or vals[i - n] <= 0:
        return None
    return (vals[i] / vals[i - n] - 1) * 100


def roll_mean(vals, i, n):
    s = vals[max(0, i - n + 1):i + 1]
    return sum(s) / len(s) if s else None


def s2_cond(prices, i):
    m30 = ma(prices, i, 30)
    if not m30:
        return False
    m7 = ma(prices, i, 7)
    c10 = chg(prices, i, 10)
    return (m7 and m7 > m30 and prices[i] >= m30 * 0.97 and prices[i] <= m30 * 1.03
            and c10 is not None and c10 >= 4)


def s3_cond(prices, in_sale, i):
    s7, s30 = roll_mean(in_sale, i, 7), roll_mean(in_sale, i, 30)
    c7 = chg(prices, i, 7)
    return (s7 is not None and s30 is not None and s30 > 0 and s7 <= s30 * 0.85
            and c7 is not None and abs(c7) <= 3)


def gate_s2(mkt, sf=60, tm=45):
    s = mkt["sentiment"]
    return not (s < 40) and (mkt["th"] >= tm or s >= sf) and mkt.get("chg30", 0) > -8


def gate_s3(mkt, sg=40, tw=45):
    return not (mkt["sentiment"] < sg and mkt["th"] < tw)


def collect(start, end, s2_gate, s3_gate, ctx):
    items = load_items()
    recs = {"S2": [], "S3": []}
    for iid, iname in sorted(items.items()):
        dates, prices, in_sale = load_series(iid)
        if len(prices) < 60:
            continue
        idx = {d: k for k, d in enumerate(dates)}
        for d in dates:
            if d < start or d > end or d not in ctx:
                continue
            k = idx[d]
            if k < 31:
                continue
            mkt = ctx[d]
            row = {"date": d, "item": iname,
                   "fwd14": (prices[k + 14] / prices[k] - 1) * 100 if k + 14 < len(prices) else None,
                   "fwd30": (prices[k + 30] / prices[k] - 1) * 100 if k + 30 < len(prices) else None}
            if s2_cond(prices, k) and s2_gate(mkt):
                recs["S2"].append(dict(row))
            if s3_cond(prices, in_sale, k) and s3_gate(mkt):
                recs["S3"].append(dict(row))
    return recs


def stats(recs, field):
    v = [r[field] for r in recs if r.get(field) is not None]
    if not v:
        return {"n": 0}
    win = sum(1 for x in v if x > 0) / len(v) * 100
    return {"n": len(v), "win%": round(win, 1), "avg%": round(statistics.mean(v), 2),
            "net%": round(statistics.mean(v) - COST * 100, 2)}


def monthly(recs):
    from collections import Counter
    c = Counter(r["date"][:7] for r in recs)
    return {k: c[k] for k in sorted(c)}


def bucket(recs, ctx, key, field="fwd30"):
    from collections import defaultdict
    b = defaultdict(list)
    for r in recs:
        m = ctx.get(r["date"])
        if not m:
            continue
        if key == "cycle":
            lab = m["cycle"]
        elif key == "th":
            t = m["th"]
            lab = "th<45" if t < 45 else ("th45-60" if t < 60 else "th>=60")
        elif key == "sent":
            s = m["sentiment"]
            lab = "sent<40" if s < 40 else ("sent40-60" if s < 60 else "sent>=60")
        elif key == "chg30":
            c = m.get("chg30", 0)
            lab = "chg30<-8" if c < -8 else ("chg30-8~0" if c < 0 else "chg30>0")
        else:
            lab = str(m.get(key))
        v = r.get(field)
        if v is not None:
            b[lab].append(v)
    out = {}
    for lab, vals in sorted(b.items()):
        if len(vals) >= 3:
            win = sum(1 for x in vals if x > 0) / len(vals) * 100
            out[lab] = {"n": len(vals), "win%": round(win, 1),
                        "avg%": round(statistics.mean(vals), 2), "net%": round(statistics.mean(vals) - COST * 100, 2)}
        else:
            out[lab] = {"n": len(vals)}
    return out


def cluster_info(dts):
    from pipeline.backtest_methodology import signal_cluster_report
    cl = signal_cluster_report(dts)
    return {k: cl[k] for k in ("signal_count", "unique_dates", "cluster_count", "max_cluster_share", "warnings", "flagged")}


def main():
    from pipeline.backtest_common import build_market_context
    ctx = build_market_context("2024-12-20", end="2026-08-20")  # 覆盖两窗口，单次构建
    out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "note": "同物品池(98老品)对比牛市窗 vs 基准窗；2025上半年 sentiment=代理(approx, 失真风险, 真实贪婪指数仅2026-06-03起)",
           "cost": COST, "windows": {"bull": f"{BULL_START}~{BULL_END}", "base": f"{BASE_START}~{BASE_END}"}}

    for wname, wstart, wend in (("bull", BULL_START, BULL_END), ("base", BASE_START, BASE_END)):
        recs_nogate = collect(wstart, wend, lambda m: True, lambda m: True, ctx)
        recs_v1 = collect(wstart, wend, gate_s2, gate_s3, ctx)
        out[wname] = {"nogate": {}, "v1gate": {}, "buckets": {}}
        for fam in ("S2", "S3"):
            for gname, recs in (("nogate", recs_nogate[fam]), ("v1gate", recs_v1[fam])):
                dts = [x["date"] for x in recs]
                blk = {
                    "signals": len(recs), "monthly": monthly(recs),
                    "fwd14": stats(recs, "fwd14"), "fwd30": stats(recs, "fwd30"),
                }
                if len(dts) >= 2:
                    blk["cluster"] = cluster_info(dts)
                out[wname][gname][fam] = blk
            out[wname]["buckets"][fam] = {"cycle": bucket(recs_v1[fam], ctx, "cycle"),
                                          "th": bucket(recs_v1[fam], ctx, "th"),
                                          "sent": bucket(recs_v1[fam], ctx, "sent"),
                                          "chg30": bucket(recs_v1[fam], ctx, "chg30")}
        # 10月崩盘敏感段（bull 窗内）
        if wname == "bull":
            oct_s2 = [r for r in recs_v1["S2"] if r["date"] >= "2025-10-01"]
            oct_s3 = [r for r in recs_v1["S3"] if r["date"] >= "2025-10-01"]
            out["bull"]["oct_crash"] = {"S2": {"n": len(oct_s2), **stats(oct_s2, "fwd30")},
                                        "S3": {"n": len(oct_s3), **stats(oct_s3, "fwd30")}}

        print("=" * 30, wname, "=" * 30)
        for fam in ("S2", "S3"):
            ng, v1 = out[wname]["nogate"][fam], out[wname]["v1gate"][fam]
            print(f"  {fam}: 无门控 n={ng['signals']} 14d{ng['fwd14']} 30d{ng['fwd30']} | "
                  f"v1门控 n={v1['signals']} 14d{v1['fwd14']} 30d{v1['fwd30']}")
            if v1.get("cluster"):
                cl = v1["cluster"]
                print(f"    v1簇: {cl['cluster_count']}个 最大{cl['max_cluster_share']*100:.0f}% flagged={cl['flagged']}")
            print(f"    月度分布: {v1['monthly']}")

    # ---- 门控平台（bull 窗）----
    print("=" * 30, "牛市窗门控平台 (30d net%)", "=" * 30)
    plateau = {"S3": {}, "S2": {}}
    for sg in (35, 40, 45):
        for tw in (40, 45, 50):
            r3 = collect(BULL_START, BULL_END, lambda m: True, lambda m, sg=sg, tw=tw: gate_s3(m, sg, tw), ctx)["S3"]
            plateau["S3"][f"禁s<{sg}&th<{tw}"] = stats(r3, "fwd30")
    for sf in (55, 60, 65):
        for tm in (40, 45, 50):
            r2 = collect(BULL_START, BULL_END, lambda m, sf=sf, tm=tm: gate_s2(m, sf, tm), lambda m: True, ctx)["S2"]
            plateau["S2"][f"s>={sf}&th>={tm}"] = stats(r2, "fwd30")
    out["plateau_bull"] = plateau
    for fam in ("S3", "S2"):
        print(f"  {fam}:")
        for k, v in plateau[fam].items():
            print(f"    {k}: n={v['n']} net30={v.get('net%')}")

    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nsaved:", SAVE)


if __name__ == "__main__":
    main()
