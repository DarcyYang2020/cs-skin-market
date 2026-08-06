# -*- coding: utf-8 -*-
"""模拟成交量回放研究（2026-08-06）：用「真实在售量 × 周转率基准」构造代理成交量，
激活量价因子链路（_dim_volume/_analyze_cycle/score_liquidity），对比 K-2 基线 458 信号。
研究只读，不写 DB、不改引擎。输出 data/sim_vol_replay_{mode}.json。
Usage: python references/sim_vol_replay.py --mode supply|supply_ret
"""
import sys, json, io, argparse
from datetime import datetime
from statistics import median
sys.path.insert(0, ".")
import importlib.util
spec = importlib.util.spec_from_file_location("rib", "run_item_backtest.py")
rib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rib)
from pipeline import db
import pipeline.item_analysis as ia

def pool_a_items():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT i.id, i.name, MIN(p.date) first_date
           FROM items i JOIN price_history p ON p.item_id = i.id
           GROUP BY i.id HAVING first_date <= '2025-01-10'""").fetchall()
    conn.close()
    return {r["id"]: r["name"] for r in rows if r["name"] not in rib.EXCLUDED_ITEMS}

def turnover_bases():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT item_id, volume_day, in_sale_count FROM price_history
           WHERE volume_day>0 AND in_sale_count>0""").fetchall()
    conn.close()
    per = {}
    for iid, v, s in rows:
        per.setdefault(iid, []).append(v / max(s, 1))
    bases = {iid: median(vs) for iid, vs in per.items()}
    return bases, median(bases.values()) if bases else 0.02

def load_series(item_id):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT p.date, p.price_rmb, p.volume_day, p.in_sale_count
           FROM price_history p WHERE p.item_id=? AND p.id IN (
               SELECT MAX(id) FROM price_history WHERE item_id=? GROUP BY date
           ) ORDER BY p.date""", (item_id, item_id)).fetchall()
    conn.close()
    return ([r["date"] for r in rows], [r["price_rmb"] for r in rows],
            [r["in_sale_count"] or 0 for r in rows])

def sim_volumes(prices, in_sale, base, mode, beta=2.0):
    vols = []
    for t, s in enumerate(in_sale):
        v = base * max(s, 1)
        if mode == "supply_ret" and t >= 5:
            rets = [abs(prices[j]/prices[j-1]-1) for j in range(t-4, t+1) if prices[j-1] > 0]
            r5 = (sum(rets)/len(rets)*100) if rets else 0.0
            v = v * (1.0 + beta * r5 / 100.0)
        vols.append(max(v, 1))
    return vols

def backtest_item_sim(item_id, name, start, end, warmup, market_ctx, vols_by_date, cost=0.02):
    dates, prices, in_sale = load_series(item_id)
    if len(prices) < warmup + 1:
        return {"item_id": item_id, "name": name, "days": len(dates), "signals": [], "error": "short"}
    n = len(prices)
    signals, recent_buys = [], []
    vols = [vols_by_date.get(d, 1) for d in dates]
    for i in range(warmup, n):
        d = dates[i]
        if end and d > end: break
        if d < start: continue
        if d not in market_ctx: continue
        mc = market_ctx[d]
        rib.patch_sentiment(mc["sentiment"])
        prefix = prices[:i+1]
        try:
            res = ia.run_item_analysis(
                name=name, prices=prefix, volumes=vols[:i+1], supply_hist=in_sale[:i+1],
                market_history=None, market_pct_90d=mc["pct"], market_cycle=mc["cycle"],
                market_zscore=mc["z"], market_th_score=mc["th"], market_30d_change=mc.get("chg30", 0),
                market_drop21=mc.get("drop21", 0), recent_buy_dates=recent_buys, signal_date=d)
        except Exception as exc:
            signals.append({"date": d, "error": str(exc)}); continue
        fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
        action = fd.get("action", "")
        if action not in ("buy", "oversold_buy"): continue
        recent_buys.append(d)
        fwd14 = (prices[i+14]/prices[i]-1)*100 if i+14 < n else None
        fwd30 = (prices[i+30]/prices[i]-1)*100 if i+30 < n else None
        net14 = (fwd14 - cost*100) if fwd14 is not None else None
        net30 = (fwd30 - cost*100) if fwd30 is not None else None
        dd = 0.0
        for j in range(i+1, min(i+15, n)):
            dd = min(dd, (prices[j]/prices[i]-1)*100)
        _gd = rib.signal_guidance(fd.get("action_label", action))
        th = res.trend_health or {}
        signals.append({
            "name": name, "date": d, "entry_price": round(prices[i], 2),
            "action": action, "action_label": fd.get("action_label", action),
            "signal_type": _gd["signal_type"], "type_label": _gd["type_label"],
            "hold_guidance": _gd["hold_guidance"], "position_limit": fd.get("position_limit", 0.0),
            "pct": getattr(res.position, "percentile_90d", None), "z": getattr(res.position, "zscore_90d", None),
            "th": th.get("score"), "cycle": getattr(res.cycle, "phase", "unknown"),
            "value": getattr(res.value, "score", None), "risk": res.risk_level,
            "data_quality": res.data_quality, "market_th": mc["th"], "market_cycle": mc["cycle"],
            "sentiment": round(mc["sentiment"], 1),
            "fwd14": round(fwd14, 2) if fwd14 is not None else None,
            "fwd30": round(fwd30, 2) if fwd30 is not None else None,
            "net14": round(net14, 2) if net14 is not None else None,
            "net30": round(net30, 2) if net30 is not None else None,
            "max_dd": round(dd, 2),
        })
    return {"item_id": item_id, "name": name, "days": len(dates), "signals": signals}

def seg(date):
    y, m = int(date[:4]), int(date[5:7])
    if (y, m) <= (2025, 4): return "25牛市01-04"
    if y == 2025 and m <= 7: return "25震荡05-07"
    if y == 2025 and m <= 10: return "25趋势08-10"
    if y == 2025: return "25尾11-12"
    if (y, m) <= (2026, 4): return "26初01-04"
    return "26近05-08"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="supply", choices=["supply", "supply_ret"])
    ap.add_argument("--beta", type=float, default=2.0)
    args = ap.parse_args()
    START, END, WARMUP = "2025-01-01", "2026-08-05", 30
    rib.patch_sentiment(50.0)
    market_ctx = rib.build_market_context(START, end=END)
    bases, global_med = turnover_bases()
    items = pool_a_items()
    print("pool A:", len(items), "| turnover bases:", len(bases), "| global med:", round(global_med*100,3), flush=True)
    t0 = datetime.now()
    results = []
    for n_i, (iid, iname) in enumerate(sorted(items.items()), 1):
        dates, prices, in_sale = load_series(iid)
        base = bases.get(iid, global_med)
        vols = sim_volumes(prices, in_sale, base, args.mode, args.beta)
        vols_by_date = dict(zip(dates, vols))
        r = backtest_item_sim(iid, iname, START, END, WARMUP, market_ctx, vols_by_date, cost=0.02)
        results.append(r)
        sigs = [s for s in r.get("signals", []) if s.get("fwd14") is not None]
        if n_i % 25 == 0 or sigs:
            print(f"[{n_i}/{len(items)}] {iname[:26]:28s} sig={len(sigs)} elapsed={str(datetime.now()-t0)[:8]}", flush=True)
    sigs_out = [s for r in results for s in r.get("signals", []) if s.get("fwd14") is not None]
    rows, agg = rib.summarize(results)
    from collections import Counter, defaultdict
    fam = dict(Counter(s["signal_type"] for s in sigs_out))
    segs = {}
    for s in sigs_out:
        k = seg(s["date"]); segs.setdefault(k, []).append(s)
    seg_stat = {}
    for k in sorted(segs):
        b = segs[k]
        v14 = [x["net14"] for x in b if x["net14"] is not None]
        v30 = [x["net30"] for x in b if x["net30"] is not None]
        seg_stat[k] = {"n": len(b),
                       "win14": round(sum(1 for v in v14 if v>0)/len(v14)*100,1) if v14 else None,
                       "avg14": round(sum(v14)/len(v14),2) if v14 else None,
                       "win30": round(sum(1 for v in v30 if v>0)/len(v30)*100,1) if v30 else None,
                       "avg30": round(sum(v30)/len(v30),2) if v30 else None}
    out = {"mode": args.mode, "beta": args.beta, "args": {"start": START, "end": END, "warmup": WARMUP},
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "aggregate": agg,
           "by_signal_type": fam, "by_segment": seg_stat, "signals": sigs_out}
    with open(f"data/sim_vol_replay_{args.mode}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("signals:", len(sigs_out), "| fam:", fam, flush=True)
    print("seg:", json.dumps(seg_stat, ensure_ascii=False), flush=True)
    print("agg:", json.dumps(agg, ensure_ascii=False), flush=True)