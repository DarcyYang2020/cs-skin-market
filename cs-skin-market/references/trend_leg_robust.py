# -*- coding: utf-8 -*-
"""A3 鲁棒性测试：S2/S3 全窗口(2025-11-02~2026-08-05)按市场状态分桶。
产出路由层依据：哪些 sent/th/cycle 桶下趋势信号期望为正。"""
import sys, io, json, statistics
from datetime import datetime
sys.path.insert(0, ".")
import os
SAVE = os.environ.get("TREND_SAVE2", "data/trend_leg_robust.json")
COST = 0.02

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

def s2(prices, i, m30):
    m7 = ma(prices, i, 7)
    if not m7 or m7 <= m30: return False
    c10 = chg(prices, i, 10)
    return prices[i] >= m30 * 0.97 and prices[i] <= m30 * 1.03 and c10 is not None and c10 >= 4

def s3(prices, in_sale, i):
    s7, s30 = roll_mean(in_sale, i, 7), roll_mean(in_sale, i, 30)
    c7 = chg(prices, i, 7)
    return (s7 is not None and s30 is not None and s30 > 0 and s7 <= s30 * 0.85
            and c7 is not None and abs(c7) <= 3)

def bucket_key(mkt):
    s = "sent%d" % (0 if mkt["sentiment"]<40 else 1 if mkt["sentiment"]<60 else 2)
    t = "th%d" % (0 if mkt["th"]<45 else 1 if mkt["th"]<60 else 2)
    return f"{s}|{t}|{mkt['cycle']}"

def run():
    from pipeline.backtest_common import build_market_context
    ctx = build_market_context("2025-09-01", end="2026-08-05")
    items = load_items()
    from collections import defaultdict
    buckets = defaultdict(lambda: {"n":0,"dates":[],"fwd14":[],"fwd30":[]})
    for iid, iname in sorted(items.items()):
        dates, prices, in_sale = load_series(iid)
        if len(prices) < 60: continue
        idx = {d: k for k, d in enumerate(dates)}
        for d in dates:
            if d < "2025-11-02" or d not in ctx: continue
            k = idx[d]
            if k < 31: continue
            mkt = ctx[d]
            m30 = ma(prices, k, 30)
            sigs = []
            if m30 and s2(prices, k, m30): sigs.append("S2")
            if s3(prices, in_sale, k): sigs.append("S3")
            if not sigs: continue
            bk = bucket_key(mkt)
            for s in sigs:
                b = buckets[(s, bk)]
                b["n"] += 1; b["dates"].append(d)
                if k+14 < len(prices): b["fwd14"].append((prices[k+14]/prices[k]-1)*100)
                if k+30 < len(prices): b["fwd30"].append((prices[k+30]/prices[k]-1)*100)
    out = {}
    for (s, bk), b in sorted(buckets.items()):
        def st(v):
            if not v: return {"n":0}
            win = sum(1 for x in v if x>0)/len(v)*100
            return {"n":len(v), "win%":round(win,1), "avg%":round(statistics.mean(v),2), "net%":round(statistics.mean(v)-COST*100,2)}
        out.setdefault(s, {})[bk] = {"signals": b["n"], "fwd14": st(b["fwd14"]), "fwd30": st(b["fwd30"])}
    # 汇总排序输出
    for s in ("S2","S3"):
        print("="*24, s, "="*24)
        rows = sorted(out.get(s, {}).items())
        for bk, v in rows:
            f30 = v["fwd30"]
            print(f"  {bk:24s} n={v['signals']:4d} 14d net={v['fwd14'].get('net%','-'):>6} 30d net={f30.get('net%','-'):>6} (win{f30.get('win%','-')}%)")
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "buckets": out}, f, ensure_ascii=False, indent=1)
    print("\nsaved:", SAVE)

run()
