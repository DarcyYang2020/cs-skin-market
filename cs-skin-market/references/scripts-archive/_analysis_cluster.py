# -*- coding: utf-8 -*-
"""C: 信号聚集/独立性分析 (临时分析, 2026-08-03)"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

d = json.load(open('data/item_backtest_latest.json', encoding='utf-8'))
sigs = sorted(d['signals'], key=lambda s: s['date'])

def net_at(s, h):
    fs = s['fwd_series']; ep = s['entry_price']
    if len(fs) < h or not ep:
        return None
    return (fs[h - 1] / ep - 1) * 100 - 2.0

# 1) 3日窗口聚类 -> 独立事件簇
clusters = []
cur = []
prev_date = None
for s in sigs:
    dt = datetime.strptime(s['date'], '%Y-%m-%d')
    if cur and (dt - prev_date).days > 3:
        clusters.append(cur)
        cur = []
    cur.append(s)
    prev_date = dt
if cur:
    clusters.append(cur)

print('=' * 100)
print('C1. 独立事件簇识别 (3日窗口聚类): 74信号 -> 几个独立事件')
print('=' * 100)
for i, cl in enumerate(clusters, 1):
    dates = [s['date'] for s in cl]
    labels = Counter(s['action_label'] for s in cl)
    f14 = [x for x in (net_at(s, 14) for s in cl) if x is not None]
    f30 = [x for x in (net_at(s, 30) for s in cl) if x is not None]
    avg14 = sum(f14) / len(f14) if f14 else float('nan')
    avg30 = sum(f30) / len(f30) if f30 else float('nan')
    w14 = sum(1 for x in f14 if x > 0) / len(f14) * 100 if f14 else float('nan')
    w30 = sum(1 for x in f30 if x > 0) / len(f30) * 100 if f30 else float('nan')
    print(f"簇{i}: {min(dates)} ~ {max(dates)} | {len(cl)} 信号 | {dict(labels)}")
    print(f"    净14d: n={len(f14)} 胜率{w14:.0f}% 均{avg14:+.2f}% | 净30d: n={len(f30)} 胜率{w30:.0f}% 均{avg30:+.2f}%")

# 2) 武器类型分布
print('\n' + '=' * 100)
print('C2. 信号武器类型分布 (重叠采样检查)')
print('=' * 100)
weapon = Counter()
for s in sigs:
    name = s['name']
    w = name.split('|')[0].strip()
    weapon[w] += 1
for w, c in weapon.most_common():
    print(f"{w}: {c}")

# 3) 同品重复采样 (同一物品在同簇内多次触发)
print('\n' + '=' * 100)
print('C3. 同品重复触发 (独立性稀释)')
print('=' * 100)
per_item = Counter(s['name'] for s in sigs)
dup = {k: v for k, v in per_item.items() if v > 1}
print(f"触发>=2次的品数: {len(dup)} / {len(per_item)}")
for k, v in sorted(dup.items(), key=lambda x: -x[1])[:10]:
    print(f"  {v}x  {k}")

# 4) 大盘周期/情绪分布
print('\n' + '=' * 100)
print('C4. 信号发生时大盘周期/情绪分布')
print('=' * 100)
print('market_cycle:', dict(Counter(s.get('market_cycle', '?') for s in sigs)))
print('sentiment档 :', dict(Counter(('极度恐惧' if s.get('sentiment', 50) >= 85 else '恐惧' if s.get('sentiment', 50) >= 70 else '中性' if s.get('sentiment', 50) >= 50 else '贪婪') for s in sigs)))