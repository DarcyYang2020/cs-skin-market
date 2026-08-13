import json
import statistics
from pathlib import Path
from datetime import date, timedelta

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / 'data' / 'item_backtest_full_2025.json'
OUT = BASE / 'data' / '_exp_exit_path_rules.json'
COST = 0.02
CAP = 0.8
HOLD = 21
TRAIL = [0.10, 0.15, 0.20, 0.25]


def _is_panic(s):
    return ('恐慌' in (s.get('action_label') or ''))


def exit_for(s, rule, k=None, max_hold=60):
    fwd = s.get('fwd_series') or []
    if not fwd:
        return None
    entry = float(s['entry_price'])
    if rule == 'hold21':
        mh = min(HOLD, len(fwd))
        idx = mh - 1
        px = fwd[idx]
        reason = 'hold21'
    elif rule == 'trail':
        high = entry
        idx = None
        px = None
        reason = 'trail_max'
        for i, cur in enumerate(fwd[:max_hold]):
            high = max(high, cur)
            if cur <= high * (1.0 - k):
                idx = i
                px = cur
                reason = 'trail_hit'
                break
        if idx is None:
            idx = min(len(fwd), max_hold) - 1
            px = fwd[idx]
    elif rule == 'regime':
        kk = 0.25 if _is_panic(s) else 0.15
        mh = 30 if _is_panic(s) else HOLD
        return exit_for(s, 'trail', k=kk, max_hold=mh)
    else:
        raise ValueError(rule)
    net_pct = (px / entry - 1.0 - COST) * 100.0
    return {'idx': idx, 'price': px, 'reason': reason, 'net_pct': net_pct}


def trade_stats(rows):
    vals = [r['net_pct'] for r in rows if r]
    if not vals:
        return {'n': 0}
    vals_sorted = sorted(vals)
    def pct(q):
        k = min(len(vals_sorted) - 1, max(0, int((len(vals_sorted) - 1) * q)))
        return round(vals_sorted[k], 2)
    return {
        'n': len(vals),
        'win_pct': round(100.0 * sum(1 for x in vals if x > 0) / len(vals), 1),
        'avg_pct': round(sum(vals) / len(vals), 2),
        'median_pct': round(statistics.median(vals), 2),
        'p05_pct': pct(0.05),
        'p95_pct': pct(0.95),
    }


def portfolio(sigs, rule, k=None, max_hold=60):
    by_day = {}
    valid_dates = []
    for s in sigs:
        ex = exit_for(s, rule, k=k, max_hold=max_hold)
        if ex is None:
            continue
        by_day.setdefault(s['date'], []).append((s, ex))
        valid_dates.append(date.fromisoformat(s['date']))
    if not valid_dates:
        return None
    first = min(valid_dates)
    last = max(date.fromisoformat(s['date']) for s in sigs) + timedelta(days=70)
    day = first
    active = []
    realized = 0.0
    total_invested = 0.0
    peak = 1.0
    max_dd = 0.0
    while day <= last:
        for a in active:
            a['idx'] += 1
        for s, ex in sorted(by_day.get(day.isoformat(), []), key=lambda x: -x[0].get('position_limit', 0)):
            lim = float(s.get('position_limit') or 0)
            if CAP is not None and total_invested + lim > CAP + 1e-9:
                continue
            active.append({'s': s, 'ex': ex, 'idx': 0, 'limit': lim})
            total_invested += lim
        unreal = 0.0
        for a in active:
            kk = a['idx']
            fwd = a['s'].get('fwd_series') or []
            if kk <= 0 or kk > len(fwd):
                continue
            px = fwd[min(kk - 1, len(fwd) - 1)]
            unreal += a['limit'] * (px / float(a['s']['entry_price']) - 1.0)
        for a in list(active):
            if a['idx'] >= a['ex']['idx'] + 1:
                pnl = a['limit'] * (a['ex']['price'] / float(a['s']['entry_price']) - 1.0 - COST)
                realized += pnl
                total_invested -= a['limit']
                active.remove(a)
        eq = 1.0 + realized + unreal
        peak = max(peak, eq)
        max_dd = min(max_dd, (eq / peak - 1.0) * 100.0)
        day += timedelta(days=1)
    total = (eq - 1.0) * 100.0
    calmar = (total / abs(max_dd)) if max_dd < 0 else 0.0
    return {
        'total_return_pct': round(total, 2),
        'max_drawdown_pct': round(max_dd, 2),
        'calmar': round(calmar, 2),
    }


def main():
    replay = json.load(open(REPLAY, encoding='utf-8'))
    sigs = replay['signals']
    rules = [('hold21', None, 60)]
    for k in TRAIL:
        rules.append(('trail', k, 60))
    rules.append(('regime', None, 60))
    out = {'generated': 'stage0', 'signals': len(sigs), 'rules': []}
    for rule, k, mh in rules:
        rows = [exit_for(s, rule, k=k, max_hold=mh) for s in sigs]
        key = rule if k is None else f'{rule}_{k}'
        out['rules'].append({'rule': key, 'trades': trade_stats(rows), 'portfolio': portfolio(sigs, rule, k=k, max_hold=mh)})
    out['baseline_meta'] = {'replay': replay.get('aggregate'), 'hold21_cost': COST, 'cap': CAP}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])


if __name__ == '__main__':
    main()
