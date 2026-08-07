# -*- coding: utf-8 -*-
"""C1 落地验证：P1-0 供给收缩吸筹 在全窗口的真实引擎回放（7天去重）。
统计触发次数/时间分布/fwd14/fwd30，验证与研究的 S3 一致且不过度触发。"""
import sys, io, json, statistics
from datetime import datetime
sys.path.insert(0, ".")
import os
SAVE = os.environ.get("C1_SAVE", "data/c1_p10_replay.json")
COST = 0.02

def replay(limit=None):
    from run_item_backtest import load_items, load_item_series
    from pipeline.backtest_common import patch_sentiment, build_market_context
    import pipeline.item_analysis as ia
    START = "2025-11-02"
    WARMUP = 60
    patch_sentiment(50.0)
    market_ctx = build_market_context(START, end="2026-08-05")
    items = load_items()
    if limit:
        items = {i: n for i, n in items.items() if n in limit}
    from collections import defaultdict
    buy_hist = defaultdict(list)
    sigs = []
    for iid, iname in sorted(items.items()):
        dates, prices, in_sale = load_item_series(iid)
        if len(prices) < WARMUP + 1:
            continue
        n = len(prices)
        for i in range(WARMUP, n):
            d = dates[i]
            if d not in market_ctx:
                continue
            mc = market_ctx[d]
            patch_sentiment(mc["sentiment"])
            prefix = prices[:i + 1]
            try:
                res = ia.run_item_analysis(
                    name=iname, prices=prefix,
                    supply_hist=in_sale[:i + 1], market_history=None,
                    market_pct_90d=mc["pct"], market_cycle=mc["cycle"],
                    market_zscore=mc["z"], market_th_score=mc["th"],
                    market_30d_change=mc.get("chg30", 0),
                    market_drop21=mc.get("drop21", 0),
                    recent_buy_dates=list(buy_hist.get(iname, [])), signal_date=d,
                )
            except Exception:
                continue
            fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
            if "supply_contraction_accumulation" in (fd.get("deduction_sources") or []):
                buy_hist[iname].append(d)
                fwd14 = (prices[i + 14] / prices[i] - 1) * 100 if i + 14 < n else None
                fwd30 = (prices[i + 30] / prices[i] - 1) * 100 if i + 30 < n else None
                sigs.append({"date": d, "item": iname, "price": prices[i],
                             "fwd14": round(fwd14, 2) if fwd14 else None,
                             "fwd30": round(fwd30, 2) if fwd30 else None,
                             "net14": round(fwd14 - COST * 100, 2) if fwd14 else None,
                             "net30": round(fwd30 - COST * 100, 2) if fwd30 else None})
    out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "n": len(sigs), "items": len(items),
           "distinct_dates": len(set(s["date"] for s in sigs)),
           "date_range": [min(s["date"] for s in sigs), max(s["date"] for s in sigs)] if sigs else None}
    def st(v):
        if not v: return {"n": 0}
        win = sum(1 for x in v if x > 0) / len(v) * 100
        return {"n": len(v), "win%": round(win, 1), "avg%": round(statistics.mean(v), 2)}
    out["net14"] = st([s["net14"] for s in sigs if s["net14"] is not None])
    out["net30"] = st([s["net30"] for s in sigs if s["net30"] is not None])
    # 按日分布（前 15 个交易日）
    from collections import Counter
    daily = Counter(s["date"] for s in sigs)
    out["top_days"] = daily.most_common(15)
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("P1-0 replay:", json.dumps(out, ensure_ascii=False, indent=1)[:1500])

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", default="")
    a = ap.parse_args()
    limit = [x.strip() for x in a.limit.split(";") if x.strip()] or None
    replay(limit)
