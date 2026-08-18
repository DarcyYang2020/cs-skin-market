# -*- coding: utf-8 -*-
"""P1 事件影响重标注（2026-08-15）：用修正后的 EVENT_CALENDAR 对三个回放产物全信号标注。

黑天鹅参数污染治理 P1（见 decision-log 黑天鹅参数污染条目）：
- 修正后日历：纪念品炼金 2026-05-22 / 黄盾 2025-07-16 / 五合一 2025-10-24 /
  终端机手套 2026-03-12 / 2025 双 Major。
- 对 HIST-FULL 317 / CLEAN-CUR 230 / cycle 186 全信号调 historical_event_impact()，
  按细族报「事件影响占比 + 剔除事件影响后的 win/avg」。
- 只标注不调参；恐慌族专项入档（89.5% 胜率 = 单事件指纹）。
"""
import io, json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from pipeline.market_macro import historical_event_impact


def classify(al):
    if '恐慌共振' in al: return 'panic_resonance'
    if '恐慌退潮' in al: return 'panic_easing'
    if '深值' in al: return 'deep_value'
    if '供给收缩' in al: return 'supply_accum'
    if '深度回调' in al: return 'deep_dip'
    if '分批建仓' in al: return 'base'
    return 'other'


def stats(sigs):
    out = {}
    for s in sigs:
        fam = classify(s.get('action_label') or '')
        impacted = historical_event_impact(s['date'], horizon_days=30)
        bucket = 'panic' if fam.startswith('panic') else fam
        d = out.setdefault(bucket, {'n': 0, 'impacted': 0, 'events': {}, 'clean': {'n': 0, 'w14': 0, 's14': 0, 'w30': 0, 's30': 0}})
        d['n'] += 1
        if impacted:
            d['impacted'] += 1
            for ev in impacted:
                d['events'][ev] = d['events'].get(ev, 0) + 1
        else:
            c = d['clean']
            c['n'] += 1
            if isinstance(s.get('fwd14'), (int, float)):
                c['s14'] += s['fwd14']; c['w14'] += 1 if s['fwd14'] > 0 else 0
            if isinstance(s.get('fwd30'), (int, float)):
                c['s30'] += s['fwd30']; c['w30'] += 1 if s['fwd30'] > 0 else 0
    res = {}
    for k, d in out.items():
        c = d['clean']
        res[k] = {
            'n': d['n'],
            'impacted_n': d['impacted'],
            'impacted_pct': round(100.0 * d['impacted'] / d['n'], 1) if d['n'] else 0,
            'events': d['events'],
            'clean_n': c['n'],
            'clean_win14': round(100.0 * c['w14'] / c['n'], 1) if c['n'] else None,
            'clean_avg14': round(c['s14'] / c['n'], 2) if c['n'] else None,
            'clean_win30': round(100.0 * c['w30'] / c['n'], 1) if c['n'] else None,
            'clean_avg30': round(c['s30'] / c['n'], 2) if c['n'] else None,
        }
    return res


def load(p):
    with io.open(p, encoding='utf-8') as f:
        return json.load(f)


products = {
    'HIST-FULL_317': BASE / 'data' / 'item_backtest_full_2025.json',
    'CLEAN-CUR_230': BASE / 'data' / '_exp_v2t9_win_replay.json',
    'CYCLE_186': BASE / 'data' / '_exp_cycle_replay_2026.json',
}

report = {'generated': '2026-08-15', 'per_baseline': {}}
for name, p in products.items():
    d = load(p)
    sigs = d['signals']
    report['per_baseline'][name] = {'total': len(sigs), 'families': stats(sigs)}

out = BASE / 'data' / '_exp_event_impact_p1.json'
with io.open(out, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
print('written:', out)

# 控制台摘要
for name, r in report['per_baseline'].items():
    print(f"\n=== {name} (n={r['total']}) ===")
    for fam, v in r['families'].items():
        print(f"  {fam:16s} n={v['n']:3d} 受影响={v['impacted_pct']:5.1f}% 事件={v['events']} "
              f"干净: n={v['clean_n']} win14={v['clean_win14']} avg14={v['clean_avg14']} win30={v['clean_win30']}")
