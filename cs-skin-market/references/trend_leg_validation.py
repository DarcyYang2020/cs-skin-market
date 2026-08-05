# -*- coding: utf-8 -*-
"""C1 落地前验证（2026-08-05）：S2/S3 在 v1 路由门控下的方法学重跑 + 引擎去重 + 门控平台。
输出：data/trend_leg_validation.json + 控制台摘要。"""
import sys, io, json, statistics
from datetime import datetime, timedelta
sys.path.insert(0, ".")
import os
SAVE = os.environ.get("TREND_SAVE3", "data/trend_leg_validation.json")
COST = 0.02
START, END = "2025-11-02", "2026-08-05"

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
    if i + 1 < n: return None
    s = vals[i - n + 1:i + 1]
    return sum(s) / n if len(s) == n and all(x is not None and x > 0 for x in s) else None

def chg(vals, i, n):
    if i < n or vals[i - n] <= 0: return None
    return (vals[i] / vals[i - n] - 1) * 100

def roll_mean(vals, i, n):
    s = vals[max(0, i - n + 1):i + 1]
    return sum(s) / len(s) if s else None

def s2_cond(prices, i):
    m30 = ma(prices, i, 30)
    if not m30: return False
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
    # v1-final: 禁贪婪(s<40)；允许 中性+中高TH(th>=45) 或 恐惧+深跌(s>=60&th<45)
    return not (s < 40) and (mkt["th"] >= tm or s >= sf) and mkt.get("chg30", 0) > -8

def gate_s3(mkt, sg=40, tw=45):
    return not (mkt["sentiment"] < sg and mkt["th"] < tw)

def collect(s2_gate, s3_gate):
    from pipeline.backtest_common import build_market_context
    ctx = build_market_context("2025-09-01", end="2026-08-10")
    items = load_items()
    recs = {"S2": [], "S3": []}
    for iid, iname in sorted(items.items()):
        dates, prices, in_sale = load_series(iid)
        if len(prices) < 60: continue
        idx = {d: k for k, d in enumerate(dates)}
        for d in dates:
            if d < START or d > END or d not in ctx: continue
            k = idx[d]
            if k < 31: continue
            mkt = ctx[d]
            if s2_cond(prices, k) and s2_gate(mkt):
                recs["S2"].append({"date": d, "item": iname,
                    "fwd14": (prices[k+14]/prices[k]-1)*100 if k+14 < len(prices) else None,
                    "fwd30": (prices[k+30]/prices[k]-1)*100 if k+30 < len(prices) else None})
            if s3_cond(prices, in_sale, k) and s3_gate(mkt):
                recs["S3"].append({"date": d, "item": iname,
                    "fwd14": (prices[k+14]/prices[k]-1)*100 if k+14 < len(prices) else None,
                    "fwd30": (prices[k+30]/prices[k]-1)*100 if k+30 < len(prices) else None})
    return recs

def stats(recs, field):
    v = [r[field] for r in recs if r.get(field) is not None]
    if not v: return {"n": 0}
    win = sum(1 for x in v if x > 0)/len(v)*100
    return {"n": len(v), "win%": round(win,1), "avg%": round(statistics.mean(v),2),
            "net%": round(statistics.mean(v)-COST*100,2)}

def main():
    from pipeline.backtest_methodology import signal_cluster_report, walk_forward_split, permutation_baseline
    from collections import Counter
    # 基准 v1 门控
    recs = collect(lambda m: gate_s2(m), lambda m: gate_s3(m))
    out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "window": f"{START}~{END}", "gate": {"S2": "禁贪婪(s<40) 且 禁(恐惧+中TH: s>=60&th>=45)",
                                                 "S3": "禁(贪婪+弱TH: s<40&th<45)"}}
    eng = json.load(open("data/item_backtest_latest.json", encoding="utf-8"))["signals"]
    eng_by_item = {}
    for e in eng:
        eng_by_item.setdefault(e["name"], []).append(e["date"])
    eng_dates = set(e["date"] for e in eng)
    out["engine_buys"] = {"n": len(eng), "range": [min(eng_dates), max(eng_dates)]}
    for fam in ("S2", "S3"):
        r = recs[fam]
        dts = [x["date"] for x in r]
        # 与引擎重叠（同品 ±3 天；公共窗口 2025-11-02~2026-06-21）
        overlap = 0
        s3_lead = {"n": 0, "hit": 0}
        for x in r:
            if x["date"] > "2026-06-21": continue
            hits = [d for d in eng_by_item.get(x["item"], []) if abs((datetime.strptime(d,"%Y-%m-%d")-datetime.strptime(x["date"],"%Y-%m-%d")).days) <= 3]
            if hits: overlap += 1
        cl = signal_cluster_report(dts)
        wf14 = walk_forward_split(r, return_field="fwd14")
        wf30 = walk_forward_split(r, return_field="fwd30")
        p14 = permutation_baseline([x["fwd14"] for x in r])
        p30 = permutation_baseline([x["fwd30"] for x in r])
        out[fam] = {
            "signals": len(r), "cluster": {k: cl[k] for k in ("signal_count","unique_dates","cluster_count","max_cluster_share","warnings","flagged")},
            "fwd14": stats(r,"fwd14"), "fwd30": stats(r,"fwd30"),
            "walk_forward": {"14d": {"valid": wf14["valid"], "train": wf14["train"], "test": wf14["test"]},
                             "30d": {"valid": wf30["valid"], "train": wf30["train"], "test": wf30["test"]}},
            "permutation": {"14d_p": p14["p_value"], "30d_p": p30["p_value"]},
            "engine_overlap_3d": {"n_checked": sum(1 for x in r if x["date"] <= "2026-06-21"),
                                   "overlap": overlap,
                                   "overlap_pct": round(overlap/max(1,sum(1 for x in r if x["date"] <= "2026-06-21"))*100,1)},
        }
        print("="*26, fam, "="*26)
        print(f"  signals={len(r)} 簇{cl['cluster_count']} 最大簇{cl['max_cluster_share']*100:.1f}% flagged={cl['flagged']}")
        print(f"  14d {out[fam]['fwd14']} | 30d {out[fam]['fwd30']}")
        print(f"  WF14 valid={wf14['valid']} train{ (wf14['train'] or {}).get('win_rate') } test{ (wf14['test'] or {}).get('win_rate') }")
        print(f"  WF30 valid={wf30['valid']} train{ (wf30['train'] or {}).get('win_rate') } test{ (wf30['test'] or {}).get('win_rate') }")
        print(f"  置换 p: 14d={p14['p_value']} 30d={p30['p_value']} | 引擎重叠±3d: {out[fam]['engine_overlap_3d']}")
        print(f"  warnings: {cl['warnings']}")
    # ---- 门控阈值平台 ----
    print("="*26, "门控平台验证 (30d net%)", "="*26)
    plateau = {}
    for sg in (35, 40, 45):
        for tw in (40, 45, 50):
            r3 = collect(lambda m: True, lambda m, sg=sg, tw=tw: gate_s3(m, sg, tw))["S3"]
            plateau.setdefault("S3", {})[f"s<{sg}&th<{tw}禁"] = stats(r3, "fwd30")
    for sf in (55, 60, 65):
        for tm in (40, 45, 50):
            r2 = collect(lambda m, sf=sf, tm=tm: gate_s2(m, sf, tm), lambda m: True)["S2"]
            plateau.setdefault("S2", {})[f"s>={sf}&th>={tm}禁"] = stats(r2, "fwd30")
    out["plateau"] = plateau
    print("  S3 禁(贪婪+弱TH) 邻域:")
    for k, v in plateau["S3"].items():
        print(f"    {k}: n={v['n']} net30={v.get('net%')}")
    print("  S2 禁(恐惧+中TH) 邻域:")
    for k, v in plateau["S2"].items():
        print(f"    {k}: n={v['n']} net30={v.get('net%')}")
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nsaved:", SAVE)

main()
