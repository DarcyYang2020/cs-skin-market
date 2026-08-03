# -*- coding: utf-8 -*-
"""A: 信号类型 x 最优持有期分析 (临时分析, 2026-08-03) - fwd_series为价格序列"""
import json
from math import sqrt

d = json.load(open('data/item_backtest_latest.json', encoding='utf-8'))
sigs = d['signals']

def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt((p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (centre - half, centre + half)

groups = {}
for s in sigs:
    label = s['action_label']
    if '\u6050\u614c\u5171\u632f' in label:
        g = '\u6050\u614c\u5171\u632f'
    elif '\u4f4e\u5438' in label:
        g = '\u6df1\u5ea6\u56de\u8c03\u4f4e\u5438'
    else:
        g = '\u5176\u4ed6'
    groups.setdefault(g, []).append(s)

COST = 2.0
HOLDS = [7, 14, 21, 30, 45]

def net_at(s, h):
    fs = s['fwd_series']
    ep = s['entry_price']
    if len(fs) < h or not ep:
        return None
    return (fs[h - 1] / ep - 1) * 100 - COST

print('=' * 92)
print('信号类型 x 持有期: 净收益口径 (未来价格/入场价-1)*100 - 2%成本')
print('=' * 92)
for g, ss in groups.items():
    print(f'\n【{g}】 共 {len(ss)} 信号')
    print(f"{'持有期':<6}{'n':>4}{'胜率':>8}{'均净%':>9}{'总净%':>10}{'盈亏比':>9}{'95%CI(低,高)':>16}")
    for h in HOLDS:
        f = [x for x in (net_at(s, h) for s in ss) if x is not None]
        if not f:
            print(f"{h:>4}天  {0:>4}  数据不足")
            continue
        n = len(f)
        wins = [x for x in f if x > 0]
        losses = [x for x in f if x <= 0]
        wr = len(wins) / n * 100
        avg = sum(f) / n
        tot = sum(f)
        pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float('inf')
        lo, hi = wilson(len(wins), n)
        print(f"{h:>4}天  {n:>4}{wr:>7.1f}%{avg:>9.2f}{tot:>10.1f}{pf:>9.2f}  ({lo*100:.0f}%, {hi*100:.0f}%)")

print('\n' + '=' * 92)
print('各类型最优持有期(按均净期望) vs 当前统一21天')
print('=' * 92)
for g, ss in groups.items():
    best = None
    for h in HOLDS:
        f = [x for x in (net_at(s, h) for s in ss) if x is not None]
        if not f:
            continue
        avg = sum(f) / len(f)
        if best is None or avg > best[1]:
            best = (h, avg)
    f21 = [x for x in (net_at(s, 21) for s in ss) if x is not None]
    avg21 = sum(f21) / len(f21) if f21 else float('nan')
    print(f"{g:<10} 最优持有 {best[0]}天 (均净{best[1]:+.2f}%) | 当前21天 (均净{avg21:+.2f}%)")

# 额外: 检查信号日期分布(独立性参考)
print('\n' + '=' * 92)
print('信号日期分布(按周)')
print('=' * 92)
from collections import Counter
weeks = Counter()
for s in sigs:
    date = s['date']
    y, m, dd = date.split('-')
    week = f"{y}-{m}-W{(int(dd)-1)//7+1}"
    weeks[week] += 1
for w in sorted(weeks):
    print(f"{w}: {weeks[w]}")