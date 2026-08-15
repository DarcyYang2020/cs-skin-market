# -*- coding: utf-8 -*-
"""P2 参数×事件敏感性体检（2026-08-15）：逐族算「全样本 vs 剔除事件影响」的漂移量。

黑天鹅参数污染治理 P2：
- 对每个细族，报 全样本 / 事件影响 / 干净 三组的 n、win14、avg14、win30、avg30；
- 漂移 = 干净组 vs 全样本（win pp、avg pp）；
- 分类：事件依赖（干净 n=0，参数完全由事件样本确定）；稳（干净 n≥15 且漂移小）；
  中度（0<干净 n<15，或漂移明显）。
- 只标注不调参。产物 data/_exp_event_sensitivity_p2.json。
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


def _stats(sigs):
    n = len(sigs)
    def f(field):
        v = [s[field] for s in sigs if isinstance(s.get(field), (int, float))]
        if not v:
            return None, None
        w = 100.0 * sum(1 for x in v if x > 0) / len(v)
        a = sum(v) / len(v)
        return round(w, 1), round(a, 2)
    w14, a14 = f('fwd14')
    w30, a30 = f('fwd30')
    return n, w14, a14, w30, a30


def analyze(baseline_name, sigs):
    fams = {}
    for s in sigs:
        fam = classify(s.get('action_label') or '')
        impacted = historical_event_impact(s['date'], horizon_days=30)
        d = fams.setdefault(fam, {'full': [], 'clean': [], 'impacted': []})
        d['full'].append(s)
        (d['impacted'] if impacted else d['clean']).append(s)
    out = {}
    for fam, d in sorted(fams.items()):
        fn, fw14, fa14, fw30, fa30 = _stats(d['full'])
        cn, cw14, ca14, cw30, ca30 = _stats(d['clean'])
        inn, iw14, ia14, iw30, ia30 = _stats(d['impacted'])
        drift_w14 = round((cw14 - fw14), 1) if cw14 is not None else None
        drift_a14 = round((ca14 - fa14), 2) if ca14 is not None else None
        if cn == 0:
            grade = '事件依赖'
        elif cn >= 15 and abs(drift_w14 or 0) <= 5 and abs(drift_a14 or 0) <= 3:
            grade = '稳'
        else:
            grade = '中度'
        out[fam] = {
            'grade': grade,
            'full': {'n': fn, 'win14': fw14, 'avg14': fa14, 'win30': fw30, 'avg30': fa30},
            'impacted': {'n': inn, 'win14': iw14, 'avg14': ia14, 'win30': iw30, 'avg30': ia30},
            'clean': {'n': cn, 'win14': cw14, 'avg14': ca14, 'win30': cw30, 'avg30': ca30},
            'drift_clean_vs_full': {'win14_pp': drift_w14, 'avg14_pp': drift_a14},
        }
    return out


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
    report['per_baseline'][name] = analyze(name, d['signals'])

out = BASE / 'data' / '_exp_event_sensitivity_p2.json'
with io.open(out, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
print('written:', out)

# 控制台摘要（以 CYCLE_186 为主口径）
print("\n=== CYCLE_186 逐族漂移（主口径）===")
for fam, v in report['per_baseline']['CYCLE_186'].items():
    fu, cl, dr = v['full'], v['clean'], v['drift_clean_vs_full']
    print(f"  [{v['grade']:4s}] {fam:16s} 全n={fu['n']:3d} win14={fu['win14']} avg14={fu['avg14']} | "
          f"干净n={cl['n']:3d} win14={cl['win14']} avg14={cl['avg14']} | 漂移 win={dr['win14_pp']}pp avg={dr['avg14_pp']}pp")
