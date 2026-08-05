# -*- coding: utf-8 -*-
"""全量日记录回放（只读引擎，不写 DB）：
- 2026-08-05 起模拟 recent_buy_dates(按品维护 buy 历史, 7天去重与真实系统一致)
- 输出 sources/deduction 以便区分信号路径(基础/P0-5/P0-8/P0-9)
- 用于补仓/建仓触发优化验证；保存文件由调用方指定"""
import sys, io, json, argparse
from datetime import datetime
sys.path.insert(0, ".")

import os
SAVE = os.environ.get("REPLAY_SAVE", "data/topup_replay_p09.json")

def replay(limit=None, end=None):
    from run_item_backtest import load_items, load_item_series
    from pipeline.backtest_common import patch_sentiment, build_market_context
    import pipeline.item_analysis as ia

    START = "2025-11-02"
    WARMUP = 60
    COST = 0.02
    patch_sentiment(50.0)
    market_ctx = build_market_context(START, end=end)
    items = load_items()
    if limit:
        items = {i: n for i, n in items.items() if n in limit}
    records = []
    from collections import defaultdict
    buy_hist = defaultdict(list)  # iname -> [buy dates] 模拟 recent_buy_dates(7天去重)
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
                    recent_buy_dates=list(buy_hist.get(iname, [])), signal_date=d,
                )
            except Exception:
                continue
            fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
            action = fd.get("action", "")
            if action == "buy":
                buy_hist[iname].append(d)
            pos = res.position
            th_obj = res.trend_health or {}
            th = th_obj.get("score", 50) if isinstance(th_obj, dict) else getattr(th_obj, "score", 50)
            # 跌速衰减信号
            chg3d = (prices[i] / prices[i - 3] - 1) * 100 if i >= 3 else None
            no_new_low2 = (prices[i] >= prices[i - 1]) and (prices[i] >= prices[i - 2]) if i >= 2 else None
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 if i + 14 < n else None
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 if i + 30 < n else None
            records.append({
                "date": d, "item": iname,
                "action": action,
                "pct": pos.percentile_90d, "z": pos.zscore_90d, "th": th,
                "mth": mc["th"], "sent": mc["sentiment"], "cycle": mc["cycle"],
                "mchg30": mc.get("chg30", 0),
                "price": prices[i], "chg3d": round(chg3d, 2) if chg3d is not None else None,
                "no_new_low2": bool(no_new_low2) if no_new_low2 is not None else None,
                "fwd14": round(fwd14, 2) if fwd14 is not None else None,
                "fwd30": round(fwd30, 2) if fwd30 is not None else None,
                "net14": round(fwd14 - COST * 100, 2) if fwd14 is not None else None,
                "net30": round(fwd30 - COST * 100, 2) if fwd30 is not None else None,
                "sources": list(fd.get("deduction_sources", []) or []),
            })
        print(f"== {iname[:40]} days={n} rec={len(records)}", flush=True)
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump({"replay_date": datetime.now().strftime("%Y-%m-%d %H:%M"), "end": end,
                   "records": records}, f, ensure_ascii=False, indent=1)
    print(f"\nsaved: {SAVE} records={len(records)}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", default="")
    ap.add_argument("--end", default="2026-08-05")
    args = ap.parse_args()
    limit = [x.strip() for x in args.limit.split(";") if x.strip()] or None
    replay(limit, end=args.end)
