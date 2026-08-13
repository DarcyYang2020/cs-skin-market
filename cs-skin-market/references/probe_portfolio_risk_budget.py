import json
import random
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'references'))
import b1_risk_backtest_v2 as b1

REPLAY = BASE / 'data' / 'item_backtest_full_2025.json'
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_portfolio_risk_budget.json'
CAP = 0.8


def load_signals():
    d = json.load(open(REPLAY, encoding='utf-8'))
    out = []
    for s in d['signals']:
        fwd = s.get('fwd_series') or []
        if not fwd:
            continue
        st = b1.classify(s.get('action_label'))
        out.append({
            'date': date.fromisoformat(s['date']),
            'item': s['name'],
            'entry': s['entry_price'],
            'limit': float(s.get('position_limit') or 0.0),
            'fwd': fwd,
            'st': st,
            'prio': b1.PRIORITY.get(st, 1),
            'net14': s.get('net14'),
            'raw': s,
        })
    return out


def load_vol_map(sigs):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    name2id = {n: i for i, n in cur.execute('SELECT id, name FROM items')}
    by_item = defaultdict(list)
    for iid, dt, price in cur.execute('SELECT item_id, date, price_rmb FROM price_history WHERE price_rmb IS NOT NULL'):
        by_item[iid].append((dt, float(price)))
    con.close()
    for iid in by_item:
        by_item[iid].sort()
    vol_map = {}
    for s in sigs:
        iid = name2id.get(s['item'])
        rows = by_item.get(iid, [])
        prior = [(d, p) for d, p in rows if d <= s['raw']['date']][-30:]
        if len(prior) >= 10 and all(p > 0 for d, p in prior):
            rets = [(prior[i][1] / prior[i-1][1] - 1.0) for i in range(1, len(prior))]
            vol_map[(s['item'], s['raw']['date'])] = statistics.stdev(rets)
    vols = [v for v in vol_map.values() if v and v > 0]
    vol_ref = statistics.median(vols) if vols else 0.02
    return vol_map, vol_ref


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def vol_scale_for(s, vol_map, vol_ref):
    v = vol_map.get((s['item'], s['raw']['date']))
    if not v or v <= 0:
        return 1.0
    return clamp(vol_ref / v, 0.4, 1.0)


def regime_mult_for(s):
    r = s['raw']
    sent = r.get('sentiment')
    mc = r.get('market_cycle') or 'unknown'
    mth = r.get('market_th')
    mchg30 = r.get('mkt_chg30')
    mult = 1.0
    if sent is not None and sent >= 75:
        mult = 0.5
    if mc in ('bear', 'distribution'):
        mult = min(mult, 0.5)
    if mth is not None and mchg30 is not None and mth < 45 and mchg30 < 0:
        mult = min(mult, 0.25)
    return mult


def adjusted_sigs(base, mode, vol_map, vol_ref):
    out = []
    for s in base:
        lim = s['limit']
        if mode == 'vol':
            lim = lim * vol_scale_for(s, vol_map, vol_ref)
        elif mode == 'regime':
            lim = lim * regime_mult_for(s)
        elif mode == 'vol_regime':
            lim = lim * vol_scale_for(s, vol_map, vol_ref) * regime_mult_for(s)
        out.append({**s, 'limit': round(lim, 4)})
    return out


def run_mode(base, mode, vol_map, vol_ref, cap=CAP):
    sigs = adjusted_sigs(base, mode, vol_map, vol_ref)
    res = b1.simulate(sigs, cap=cap)
    m = b1.metrics(res)
    m['n_trades'] = res['n_trades']
    m['rejected_cap'] = res['rejected_cap']
    return m


def split_metrics(base, mode, vol_map, vol_ref, cutoff, side, cap=CAP):
    cutoff_date = date.fromisoformat(cutoff)
    if side == 'pre':
        sigs = [s for s in adjusted_sigs(base, mode, vol_map, vol_ref) if s['date'] < cutoff_date]
    else:
        sigs = [s for s in adjusted_sigs(base, mode, vol_map, vol_ref) if s['date'] >= cutoff_date]
    if not sigs:
        return {'total_return_pct': None, 'max_drawdown_pct': None, 'max_position': None, 'n_trades': 0, 'n_signals': 0}
    res = b1.simulate(sigs, cap=cap)
    m = b1.metrics(res)
    m['n_trades'] = res['n_trades']
    m['n_signals'] = len(sigs)
    return m


def permutation_vol(base, vol_map, vol_ref, n=200, seed=20260813):
    rng = random.Random(seed)
    actual_scales = [vol_scale_for(s, vol_map, vol_ref) for s in base]
    shuffled = []
    for _ in range(n):
        scales = actual_scales[:]
        rng.shuffle(scales)
        sigs = []
        for s, sc in zip(base, scales):
            sigs.append({**s, 'limit': round(s['limit'] * sc, 4)})
        res = b1.simulate(sigs, cap=CAP)
        m = b1.metrics(res)
        shuffled.append({'total_return_pct': m['total_return_pct'], 'max_drawdown_pct': m['max_drawdown_pct'], 'calmar': round(m['total_return_pct'] / abs(m['max_drawdown_pct']), 2) if m['max_drawdown_pct'] else 0.0})
    actual = run_mode(base, 'vol', vol_map, vol_ref)
    actual_calmar = round(actual['total_return_pct'] / abs(actual['max_drawdown_pct']), 2) if actual['max_drawdown_pct'] else 0.0
    p_calmar = sum(1 for x in shuffled if x['calmar'] >= actual_calmar) / n
    return {'actual_calmar': actual_calmar, 'actual_total_return_pct': actual['total_return_pct'], 'actual_max_drawdown_pct': actual['max_drawdown_pct'], 'permutation_calmar_mean': round(statistics.mean(x['calmar'] for x in shuffled), 2), 'p_calmar_ge': round(p_calmar, 3), 'n': n}


def main():
    base = load_signals()
    vol_map, vol_ref = load_vol_map(base)
    dates = sorted(s['date'] for s in base)
    cutoff = dates[len(dates) // 2].isoformat()
    pre_n = sum(1 for s in base if s['date'] < date.fromisoformat(cutoff))
    post_n = len(base) - pre_n
    modes = ['baseline', 'vol', 'regime', 'vol_regime']
    out = {'generated': 'stage0', 'signals': len(base), 'vol_ref': round(vol_ref, 6), 'modes': {}, 'splits': {}, 'split': {'cutoff': cutoff, 'pre_n': pre_n, 'post_n': post_n}, 'permutation_vol': {}}
    for mode in modes:
        out['modes'][mode] = run_mode(base, mode, vol_map, vol_ref)
    for mode in modes:
        out['splits'][mode] = {'pre': split_metrics(base, mode, vol_map, vol_ref, cutoff, 'pre'), 'post': split_metrics(base, mode, vol_map, vol_ref, cutoff, 'post')}
    out['permutation_vol'] = permutation_vol(base, vol_map, vol_ref, n=200)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])


if __name__ == '__main__':
    main()
