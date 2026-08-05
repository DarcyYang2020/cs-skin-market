# -*- coding: utf-8 -*-
"""A3 研究脚本 v2：趋势腿可行性验证（增强版）。

v2 改动：
- 引擎 buy 信号带 recent_buy_dates 7 天去重（与生产一致），并计算 fwd14/fwd30
- 趋势信号增加 filter=off 基线，量化市场过滤（路由层）的边际价值
- 输出每个信号族的触发日期范围（看时间集中度）
"""
import sys, io, json, statistics, argparse
from datetime import datetime
sys.path.insert(0, ".")
import os
SAVE = os.environ.get("TREND_SAVE", "data/trend_leg_research.json")
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

def trend_signals(prices, in_sale, i, mkt, mkt_ok):
    out = []
    p = prices
    if not mkt_ok:
        return out
    if i < 31: return out
    m7, m30 = ma(p, i, 7), ma(p, i, 30)
    if not m7 or not m30: return out
    hi20 = max(p[i - 20:i])
    c20 = chg(p, i, 20)
    if p[i] > hi20 * 1.005 and c20 is not None and c20 >= 8:
        out.append("S1_breakout")
    if m7 > m30 and p[i] >= m30 * 0.97 and p[i] <= m30 * 1.03:
        c10 = chg(p, i, 10)
        if c10 is not None and c10 >= 4:
            out.append("S2_pullback")
    s7, s30 = roll_mean(in_sale, i, 7), roll_mean(in_sale, i, 30)
    c7 = chg(p, i, 7)
    if s7 is not None and s30 is not None and s30 > 0 and s7 <= s30 * 0.85 and c7 is not None and abs(c7) <= 3:
        out.append("S3_accum")
    return out

def cluster_stats(dates):
    if not dates: return 0, 0.0, 0
    ds = sorted(set(dates))
    clusters = []
    cur = [ds[0]]
    for d in ds[1:]:
        dd = datetime.strptime(d, "%Y-%m-%d").date()
        pd = datetime.strptime(cur[-1], "%Y-%m-%d").date()
        if (dd - pd).days <= 3:
            cur.append(d)
        else:
            clusters.append(cur); cur = [d]
    clusters.append(cur)
    mx = max(len(c) for c in clusters)
    return len(clusters), mx / len(ds), len(ds)

def run(window="W1"):
    from pipeline.backtest_common import build_market_context, patch_sentiment
    import pipeline.item_analysis as ia
    W = {"W1": ("2025-11-02", "2026-01-23"), "W2": ("2026-01-23", "2026-03-17")}[window]
    start, end = W
    ctx = build_market_context("2025-09-01", end="2026-04-16")
    items = load_items()
    def newbucket():
        return {s: {"n": 0, "dates": [], "fwd14": [], "fwd30": []} for s in ("S1_breakout","S2_pullback","S3_accum")}
    sig_on, sig_off = newbucket(), newbucket()
    eng = {"n": 0, "dates": [], "fwd14": [], "fwd30": []}
    from collections import defaultdict
    buy_hist = defaultdict(list)
    for iid, iname in sorted(items.items()):
        dates, prices, in_sale = load_series(iid)
        if len(prices) < 60: continue
        idx = {d: k for k, d in enumerate(dates)}
        for d in dates:
            if d < start or d > end or d not in ctx: continue
            k = idx[d]
            if k < 31: continue
            mkt = ctx[d]
            mkt_ok = (mkt["sentiment"] <= 60) and (mkt["th"] >= 45)
            # filter on / off
            sigs_on = trend_signals(prices, in_sale, k, mkt, mkt_ok)
            sigs_off = trend_signals(prices, in_sale, k, mkt, True)
            for bucket, sigs in ((sig_on, sigs_on), (sig_off, sigs_off)):
                for s in sigs:
                    bucket[s]["n"] += 1
                    bucket[s]["dates"].append(d)
                    if k + 14 < len(prices): bucket[s]["fwd14"].append((prices[k+14]/prices[k]-1)*100)
                    if k + 30 < len(prices): bucket[s]["fwd30"].append((prices[k+30]/prices[k]-1)*100)
            # 引擎 buy（带 7 天去重，与生产一致）
            patch_sentiment(mkt["sentiment"])
            prefix = prices[:k+1]
            try:
                res = ia.run_item_analysis(name=iname, prices=prefix, volumes=[0]*len(prefix),
                    supply_hist=in_sale[:k+1], market_history=None, market_pct_90d=mkt["pct"],
                    market_cycle=mkt["cycle"], market_zscore=mkt["z"], market_th_score=mkt["th"],
                    market_30d_change=mkt.get("chg30",0), market_drop21=mkt.get("drop21",0),
                    recent_buy_dates=list(buy_hist.get(iname, [])), signal_date=d)
            except Exception:
                continue
            fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
            if fd.get("action") == "buy":
                if not buy_hist[iname] or (datetime.strptime(d,"%Y-%m-%d")-datetime.strptime(buy_hist[iname][-1],"%Y-%m-%d")).days >= 7:
                    buy_hist[iname].append(d)
                    eng["n"] += 1; eng["dates"].append(d)
                    if k + 14 < len(prices): eng["fwd14"].append((prices[k+14]/prices[k]-1)*100)
                    if k + 30 < len(prices): eng["fwd30"].append((prices[k+30]/prices[k]-1)*100)
    def stat(v):
        if not v: return {"n": 0}
        win = sum(1 for x in v if x > 0) / len(v) * 100
        avg = statistics.mean(v)
        return {"n": len(v), "win%": round(win,1), "avg%": round(avg,2), "net%(c2%)": round(avg-COST*100,2)}
    out = {"window": window, "start": start, "end": end, "items": len(items)}
    out["engine_buy"] = {"n": eng["n"], "distinct_dates": len(set(eng["dates"])), "fwd14": stat(eng["fwd14"]), "fwd30": stat(eng["fwd30"])}
    for tag, bucket in (("signals_filter_on", sig_on), ("signals_filter_off", sig_off)):
        out[tag] = {}
        for s, st in bucket.items():
            cl, mx, ev = cluster_stats(st["dates"])
            dr = (min(st["dates"]), max(st["dates"])) if st["dates"] else ("","")
            out[tag][s] = {"signals": st["n"], "clusters": cl, "max_cluster_share%": round(mx*100,1),
                "distinct_dates": ev, "date_range": dr, "fwd14": stat(st["fwd14"]), "fwd30": stat(st["fwd30"])}
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="both", choices=["W1","W2","both"])
    a = ap.parse_args()
    wins = ["W1","W2"] if a.window == "both" else [a.window]
    res = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "windows": {}}
    for w in wins:
        r = run(w)
        res["windows"][w] = r
        print("="*28, w, "="*28)
        eb = r["engine_buy"]
        print(f"[现有引擎buy(7d去重)] n={eb['n']} 交易日={eb['distinct_dates']} 14d{eb['fwd14']} 30d{eb['fwd30']}")
        for tag in ("signals_filter_on","signals_filter_off"):
            print(f"  -- {tag} --")
            for s in ("S1_breakout","S2_pullback","S3_accum"):
                x = r[tag][s]
                print(f"  {s}: n={x['signals']} 簇{x['clusters']}(最大{x['max_cluster_share%']}%) 区间{x['date_range'][0]}~{x['date_range'][1]} | "
                      f"14d n={x['fwd14']['n']} win{x['fwd14']['win%']}% avg{x['fwd14']['avg%']} net{x['fwd14']['net%(c2%)']} | "
                      f"30d n={x['fwd30']['n']} win{x['fwd30']['win%']}% avg{x['fwd30']['avg%']} net{x['fwd30']['net%(c2%)']}")
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nsaved:", SAVE)
