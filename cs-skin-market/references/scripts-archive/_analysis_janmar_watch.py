# -*- coding: utf-8 -*-
"""补充: 2月小牛段 watch 信号分析 (临时, 2026-08-03)"""
import sys, json
from collections import Counter, defaultdict
sys.path.insert(0, '.')
from pipeline import item_analysis as ia
from pipeline import db
from pipeline.backtest_common import patch_sentiment, build_market_context
import run_item_backtest as rib

START, END, WARMUP = '2026-02-03', '2026-03-17', 15
market_ctx = build_market_context('2025-11-02')
conn = db.get_conn()
items = conn.execute("SELECT id, name FROM items ORDER BY id").fetchall()

all_sigs = []
for item_id, name in items:
    dates, prices, in_sale = rib.load_item_series(item_id)
    if len(prices) < WARMUP + 1:
        continue
    n = len(prices)
    for i in range(WARMUP, n):
        d = dates[i]
        if d < START or d > END or d not in market_ctx:
            continue
        mc = market_ctx[d]
        patch_sentiment(mc["sentiment"])
        prefix = prices[:i + 1]
        try:
            res = ia.run_item_analysis(
                name=name, prices=prefix, volumes=[0] * len(prefix),
                supply_hist=in_sale[:i + 1], market_history=None,
                market_pct_90d=mc["pct"], market_cycle=mc["cycle"],
                market_zscore=mc["z"], market_th_score=mc["th"],
                market_30d_change=mc.get("chg30", 0), market_drop21=mc.get("drop21", 0),
                recent_buy_dates=[], signal_date=d,
            )
        except Exception:
            continue
        fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
        action = fd.get("action", "")
        if action not in ("watch", "buy", "oversold_buy"):
            continue
        f30 = (prices[i + 30] / prices[i] - 1) * 100 - 2 if i + 30 < n else None
        f14 = (prices[i + 14] / prices[i] - 1) * 100 - 2 if i + 14 < n else None
        th = res.trend_health or {}
        all_sigs.append({
            "date": d, "action": action, "label": fd.get("action_label", action),
            "pct": getattr(res.position, "percentile_90d", None),
            "z": getattr(res.position, "zscore_90d", None),
            "th": th.get("score"), "mkt_th": mc["th"], "mkt_chg7": mc.get("chg7"),
            "net14": f14, "net30": f30,
        })
conn.close()

print(f'watch/buy 总记录: {len(all_sigs)}')
print('\n=== 按日汇总 (watch 数, 平均 net14/net30) ===')
by_date = defaultdict(list)
for s in all_sigs:
    by_date[s['date']].append(s)
for d in sorted(by_date):
    ss = by_date[d]
    n14 = [s['net14'] for s in ss if s['net14'] is not None]
    n30 = [s['net30'] for s in ss if s['net30'] is not None]
    print(f"  {d}  n={len(ss):>3}  avg14={sum(n14)/len(n14):+7.1f}% (n={len(n14)})  avg30={sum(n30)/len(n30):+7.1f}% (n={len(n30)})")

print('\n=== watch 且 net30>=50% 的信号共性 (pct/z/th/大盘th) ===')
good = [s for s in all_sigs if s['net30'] is not None and s['net30'] >= 50]
print(f'数量: {len(good)}')
def q(vals, p):
    sv = sorted(vals)
    return sv[int(len(sv)*p)]
for k in ['pct', 'z', 'th', 'mkt_th']:
    vals = [s[k] for s in good if s[k] is not None]
    print(f'  {k}: 中位={q(vals,0.5):.2f}  P25={q(vals,0.25):.2f}  P75={q(vals,0.75):.2f}')
print('  日期分布:', dict(Counter(s["date"] for s in good)))
print('  label 分布:', dict(Counter(s["label"] for s in good)))