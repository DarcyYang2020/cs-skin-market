# -*- coding: utf-8 -*-
"""诊断：189 信号族分布 + 信号丢失（只读，输出到文件）。"""
import json
from collections import defaultdict, Counter

d = json.load(open('data/_exp_cycle_replay_period_route.json', encoding='utf-8'))
sigs = d.get('signals', [])

lines = []
# 1. 细族分布（signal_type）
st = Counter(s.get('signal_type') or '?' for s in sigs)
lines.append('=== signal_type（细族）分布 ===')
for k, v in st.most_common():
    lines.append(f'  {k}  n={v}')

# 2. action_label 分布（剥离 emoji）
def clean(s):
    return ''.join(c for c in (s or '') if ord(c) < 0x2700)
al = Counter(clean(s.get('action_label') or '?') for s in sigs)
lines.append('\n=== action_label 分布（剥离emoji） ===')
for k, v in al.most_common():
    lines.append(f'  {k}  n={v}')

# 3. 按月信号数
bym = defaultdict(int)
for s in sigs:
    bym[s.get('date', '')[:7]] += 1
lines.append('\n=== 按月信号数（空月=丢失） ===')
for m in sorted(bym):
    lines.append(f'  {m}  {bym[m]}')

# 4. 恐慌族（panic）的时间分布
lines.append('\n=== panic 族信号日期（前20条） ===')
panic = [s for s in sigs if s.get('signal_type', '').startswith('panic')]
for s in sorted(panic, key=lambda x: x.get('date', ''))[:20]:
    lines.append(f"  {s.get('date')}  {clean(s.get('action_label') or '')}")

# 5. 各族的日期范围
lines.append('\n=== 各族日期范围 ===')
bytype = defaultdict(list)
for s in sigs:
    bytype[s.get('signal_type') or '?'].append(s.get('date', ''))
for k, v in bytype.items():
    lines.append(f'  {k}: {min(v)} ~ {max(v)}  (n={len(v)})')

open('data/_exp_diag_family_audit.txt', 'w', encoding='utf-8').write('\n'.join(lines))
print('saved data/_exp_diag_family_audit.txt')
print('\n'.join(lines))
