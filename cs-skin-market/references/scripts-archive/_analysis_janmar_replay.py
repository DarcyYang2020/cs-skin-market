# -*- coding: utf-8 -*-
"""2026-01/23~03/17 小牛段单品回放 (临时分析, 2026-08-03)"""
import sys, json
from collections import Counter, defaultdict
sys.path.insert(0, '.')
from pipeline import item_analysis as ia
from pipeline import db
from pipeline.backtest_common import patch_sentiment, build_market_context
import run_item_backtest as rib

START, END, WARMUP = '2026-02-03', '2026-03-17', 15
market_ctx = build_market_context('2025-11-02')
print(f'market_ctx 覆盖: {len(market_ctx)} 天')

conn = db.get_conn()
items = [r for r in conn.execute("SELECT id, name FROM items ORDER BY id").fetchall()]

all_sigs = []
near = []
item_stats = []
for item_id, name in items:
    dates, prices, in_sale = rib.load_item_series(item_id)
    if len(prices) < WARMUP + 1:
        continue
    n = len(prices)
    first_ok = None
    for i in range(WARMUP, n):
        d = dates[i]
        if d < START or d > END:
            continue
        if d not in market_ctx:
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
        except Exception as exc:
            continue
        fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
        action = fd.get("action", "")
        if first_ok is None and action in ("buy", "oversold_buy", "watch"):
            first_ok = d
        f14 = (prices[i + 14] / prices[i] - 1) * 100 - 2 if i + 14 < n else None
        f30 = (prices[i + 30] / prices[i] - 1) * 100 - 2 if i + 30 < n else None
        th = res.trend_health or {}
        rec = {
            "date": d, "name": name, "action": action,
            "label": fd.get("action_label", action),
            "pct": round(getattr(res.position, "percentile_90d", None), 1),
            "z": round(getattr(res.position, "zscore_90d", None), 2),
            "th": th.get("score"),
            "price": round(prices[i], 2), "net14": f14, "net30": f30,
        }
        all_sigs.append(rec)
        if action in ("buy", "oversold_buy", "watch"):
            near.append(rec)
    # 每品区间涨幅 (首尾)
    sub = [(dates[j], prices[j]) for j in range(n) if START <= dates[j] <= END]
    if sub:
        item_stats.append((name, sub[0][1], sub[-1][1], (sub[-1][1] / sub[0][1] - 1) * 100))

print(f'\n回放完成: 参与品数 {len(item_stats)}, 总记录 {len(all_sigs)}')
print('\n=== 1) action 分布 ===')
print(dict(Counter(s['action'] for s in all_sigs)))
print('\n=== 2) buy/oversold/watch 信号 ===')
for s in sorted(near, key=lambda x: x['date'])[:30]:
    print(f"  {s['date']} {s['name'][:22]:<24} {s['action']:<8} pct={s['pct']} z={s['z']} th={s['th']} net14={s['net14']} net30={s['net30']}")
print(f'  ... 共 {len(near)} 条')

print('\n=== 3) 单品区间涨幅分布 (2/3 ~ 3/17) ===')
gains = sorted([(x[3], x[0]) for x in item_stats], reverse=True)
import statistics
gs = [g for g, _ in gains]
print(f'  平均 {statistics.mean(gs):+.1f}% | 中位 {statistics.median(gs):+.1f}% | 最大 {max(gs):+.1f}% | 最小 {min(gs):+.1f}% | 上涨占比 {sum(1 for g in gs if g > 0) / len(gs) * 100:.0f}%')
print('  涨幅前10:')
for g, nm in gains[:10]:
    print(f'    {g:+.1f}%  {nm}')
print('  涨幅后10:')
for g, nm in gains[-10:]:
    print(f'    {g:+.1f}%  {nm}')

print('\n=== 4) 大盘对照 (market_index) ===')
mv = dict((r[0], r[1]) for r in conn.execute("SELECT date, value FROM market_index WHERE date BETWEEN '2026-02-03' AND '2026-03-17'"))
print(f'  大盘 2/3={mv.get("2026-02-03")} -> 3/17={mv.get("2026-03-17")} = {(mv.get("2026-03-17",0)/mv.get("2026-02-03",1)-1)*100:+.1f}%')
conn.close()