# -*- coding: utf-8 -*-
"""持仓补仓分层期望回放（P1）：全量日记录回放，记录每分析日估值/趋势/大盘/情绪 + fwd。

用法（cs-skin-market 目录下）: python references/advice_layer_fit.py [--limit "A;B"]
输出: data/advice_replay_tmp.json（只读引擎，不写 DB、不覆盖 88 基准）
"""
import sys, io, json, argparse
from datetime import datetime
sys.path.insert(0, ".")

SAVE = "data/advice_replay_tmp.json"


def replay(limit=None):
    from run_item_backtest import load_items, load_item_series
    from pipeline.backtest_common import patch_sentiment, build_market_context
    import pipeline.item_analysis as ia

    START = "2025-11-02"
    WARMUP = 60
    COST = 0.02
    patch_sentiment(50.0)
    market_ctx = build_market_context(START)
    items = load_items()
    if limit:
        items = {i: n for i, n in items.items() if n in limit}
    records = []
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
                    name=iname, prices=prefix, volumes=[0] * len(prefix),
                    supply_hist=in_sale[:i + 1], market_history=None,
                    market_pct_90d=mc["pct"], market_cycle=mc["cycle"],
                    market_zscore=mc["z"], market_th_score=mc["th"],
                    market_30d_change=mc.get("chg30", 0),
                    market_drop21=mc.get("drop21", 0),
                    recent_buy_dates=[], signal_date=d,
                )
            except Exception:
                continue
            fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
            action = fd.get("action", "")
            pos = res.position
            th_obj = res.trend_health or {}
            th = th_obj.get("score", 50) if isinstance(th_obj, dict) else getattr(th_obj, "score", 50)
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 if i + 14 < n else None
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 if i + 30 < n else None
            records.append({
                "date": d, "item": iname,
                "action": action,
                "pct": pos.percentile_90d, "z": pos.zscore_90d, "th": th,
                "mth": mc["th"], "sent": mc["sentiment"], "cycle": mc["cycle"],
                "fwd14": round(fwd14, 2) if fwd14 is not None else None,
                "fwd30": round(fwd30, 2) if fwd30 is not None else None,
                "net14": round(fwd14 - COST * 100, 2) if fwd14 is not None else None,
                "net30": round(fwd30 - COST * 100, 2) if fwd30 is not None else None,
            })
        print(f"== {iname[:40]} days={n} rec={len(records)}", flush=True)
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump({"replay_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "records": records}, f, ensure_ascii=False, indent=1)
    print(f"\nsaved: {SAVE} records={len(records)}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", default="")
    args = ap.parse_args()
    limit = [x.strip() for x in args.limit.split(";") if x.strip()] or None
    replay(limit)