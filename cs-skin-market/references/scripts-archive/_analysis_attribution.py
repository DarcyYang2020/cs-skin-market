# -*- coding: utf-8 -*-
"""B: 信号属性期望归因(簇内切片, 临时分析 2026-08-03)"""
import json
from collections import defaultdict

d = json.load(open('data/item_backtest_latest.json', encoding='utf-8'))
sigs = d['signals']

def net_at(s, h):
    fs = s['fwd_series']; ep = s['entry_price']
    if len(fs) < h or not ep:
        return None
    return (fs[h - 1] / ep - 1) * 100 - 2.0

# 簇
cl1 = [s for s in sigs if '2026-05-2' in s['date']]   # 5/22-26 恐慌簇
cl2 = [s for s in sigs if '2026-06-1' in s['date'] or '2026-06-2' in s['date']]  # 6/15-23 低吸簇

def show(title, ss, h=14):
    f = [x for x in (net_at(s, h) for s in ss) if x is not None]
    if not f:
        return
    n = len(f); wins = [x for x in f if x > 0]
    print(f"  n={n:>2} 胜率={len(wins)/n*100:5.1f}% 均净={sum(f)/n:+7.2f}% 总净={sum(f):+8.1f}%")

print('=' * 90)
print('B1. 簇1(5/22-26恐慌共振,41) 属性切片 — 同一事件内找区分度')
print('=' * 90)
for label, fn in [
    ('pct<10', lambda s: s['pct'] < 10), ('pct 10~25', lambda s: 10 <= s['pct'] <= 25),
    ('z<-2', lambda s: s['z'] < -2), ('z -2~-1.5', lambda s: -2 <= s['z'] < -1.5), ('z>=-1.5', lambda s: s['z'] >= -1.5),
    ('TH<30', lambda s: s['th'] < 30), ('TH 30~45', lambda s: 30 <= s['th'] <= 45),
    ('价格<50', lambda s: s['entry_price'] < 50), ('价格 50~300', lambda s: 50 <= s['entry_price'] < 300), ('价格>=300', lambda s: s['entry_price'] >= 300),
    ('sent>=85', lambda s: s.get('sentiment', 50) >= 85), ('sent<85', lambda s: s.get('sentiment', 50) < 85),
]:
    sub = [s for s in cl1 if fn(s)]
    if sub:
        print(f"{label:<14}", end='')
        show(label, sub)

print('\n' + '=' * 90)
print('B2. 簇2(6/15-23低吸,33) 属性切片')
print('=' * 90)
for label, fn in [
    ('pct<10', lambda s: s['pct'] < 10), ('pct 10~25', lambda s: 10 <= s['pct'] <= 25),
    ('z<-1.5', lambda s: s['z'] < -1.5), ('z>=-1.5', lambda s: s['z'] >= -1.5),
    ('TH<40', lambda s: s['th'] < 40), ('TH 40~55', lambda s: 40 <= s['th'] <= 55), ('TH>=55', lambda s: s['th'] >= 55),
    ('价格<100', lambda s: s['entry_price'] < 100), ('价格>=100', lambda s: s['entry_price'] >= 100),
    ('dd深(dd30<=-25)', lambda s: s.get('dd30', -99) <= -25),
]:
    sub = [s for s in cl2 if fn(s)]
    if sub:
        print(f"{label:<18}", end='')
        show(label, sub)

print('\n' + '=' * 90)
print('B3. 检查可用字段(簇2 dd30 是否存在)')
print('=' * 90)
print('cl2[0] 字段:', sorted(cl2[0].keys()))