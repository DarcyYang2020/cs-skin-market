#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LIQ-RATIO-1 P-D-1 因子本体（只读，零引擎改动）。"""
import json
import math
import random
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_liq_ratio_pd1.json'
random.seed(20260815)

def fnum(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None

def quantile_vals(vals, k):
    vals = sorted(vals)
    if not vals:
        return []
    qs = []
    for i in range(1, k):
        idx = min(len(vals) - 1, int(round(i * (len(vals) - 1) / k)))
        qs.append(vals[idx])
    return qs

def group_stats(rows):
    def st(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return {'n': 0, 'win_pct': None, 'avg_pct': None}
        wins = sum(1 for v in vals if v > 0)
        return {
            'n': len(vals),
            'win_pct': round(100.0 * wins / len(vals), 2),
            'avg_pct': round(sum(vals) / len(vals), 3),
        }
    return {
        'n': len(rows),
        'fwd14': st([r.get('fwd14') for r in rows]),
        'fwd30': st([r.get('fwd30') for r in rows]),
    }

def permutation_pval(group_rows, horizon):
    def metric(rows):
        vals = [r.get(horizon) for r in rows if r.get(horizon) is not None]
        return sum(vals) / len(vals) if vals else 0.0
    lo = [r for r in group_rows[0] if r.get(horizon) is not None]
    hi = [r for r in group_rows[-1] if r.get(horizon) is not None]
    if not lo or not hi:
        return None
    observed = metric(hi) - metric(lo)
    pool = [r.get(horizon) for r in group_rows[0] + group_rows[-1] if r.get(horizon) is not None]
    n_hi = len(hi)
    n_pool = len(pool)
    hits = 0
    trials = 300
    for _ in range(trials):
        random.shuffle(pool)
        m_hi = sum(pool[:n_hi]) / n_hi if n_hi else 0.0
        m_lo = sum(pool[n_hi:]) / (n_pool - n_hi) if n_pool - n_hi else 0.0
        if m_hi - m_lo >= observed:
            hits += 1
    return {'observed_diff': round(observed, 3), 'p_greater': round(hits / trials, 4), 'trials': trials}

def monotone(stats):
    vals = [stats[k]['fwd14']['win_pct'] for k in stats if stats[k]['fwd14']['win_pct'] is not None]
    return all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1)) if len(vals) >= 2 else False

def main():
    uri = f'file:{DB}?mode=ro'
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row

    series = defaultdict(list)
    for r in con.execute('SELECT item_id, date, price_rmb, in_sale_count FROM price_history ORDER BY item_id, date'):
        series[r['item_id']].append(r)

    rows = []
    for r in con.execute('SELECT item_id, date, buy_num_last FROM bid_history ORDER BY item_id, date'):
        iid = r['item_id']
        d = r['date']
        arr = series.get(iid)
        if not arr:
            continue
        idx = next((j for j, x in enumerate(arr) if x['date'] == d), None)
        if idx is None:
            continue
        price = fnum(arr[idx]['price_rmb'])
        in_sale = arr[idx]['in_sale_count']
        if price is None or price <= 0 or in_sale is None or in_sale <= 0:
            continue
        floor = 200 if price < 10000 else 100
        if in_sale < floor:
            continue
        buy_num = fnum(r['buy_num_last'])
        if buy_num is None or buy_num < 3:
            continue
        fwd14 = (fnum(arr[idx + 14]['price_rmb']) / price - 1) * 100 if idx + 14 < len(arr) else None
        fwd30 = (fnum(arr[idx + 30]['price_rmb']) / price - 1) * 100 if idx + 30 < len(arr) else None
        rows.append({
            'item_id': iid, 'date': d, 'idx': idx, 'price': price,
            'in_sale': in_sale, 'floor': floor, 'buy_num': buy_num,
            'ratio': buy_num / in_sale, 'fwd14': fwd14, 'fwd30': fwd30,
        })
    con.close()

    ratio_all = sorted(r['ratio'] for r in rows)
    p99 = ratio_all[min(len(ratio_all) - 1, int(round(0.99 * (len(ratio_all) - 1))))] if ratio_all else 0.0
    for r in rows:
        r['ratio_w'] = min(r['ratio'], p99)

    by_item = defaultdict(list)
    for r in rows:
        by_item[r['item_id']].append(r)
    for iid, arr in by_item.items():
        arr.sort(key=lambda x: x['idx'])
        for j, r in enumerate(arr):
            if j >= 7:
                r['ratio_chg'] = r['ratio_w'] - arr[j - 7]['ratio_w']
            else:
                r['ratio_chg'] = None
        last_kept = None
        for r in arr:
            r['keep'] = (last_kept is None) or (r['idx'] - last_kept >= 30)
            if r['keep']:
                last_kept = r['idx']

    kept = [r for r in rows if r['keep']]

    # cross-sectional
    cs = {}
    if kept:
        qq = quantile_vals([r['ratio_w'] for r in kept], 3)
        groups = {'Q1_low': [], 'Q2_mid': [], 'Q3_high': []}
        for r in kept:
            if r['ratio_w'] <= qq[0]:
                groups['Q1_low'].append(r)
            elif r['ratio_w'] <= qq[1]:
                groups['Q2_mid'].append(r)
            else:
                groups['Q3_high'].append(r)
        cs = {
            'quantile_cutoffs': [round(x, 5) for x in qq],
            'groups': {k: group_stats(v) for k, v in groups.items()},
            'monotone_win14': monotone({k: group_stats(v) for k, v in groups.items()}),
            'permutation_fwd14': permutation_pval([groups['Q1_low'], groups['Q2_mid'], groups['Q3_high']], 'fwd14'),
            'permutation_fwd30': permutation_pval([groups['Q1_low'], groups['Q2_mid'], groups['Q3_high']], 'fwd30'),
        }

    # time-series
    ts_rows = [r for r in kept if r.get('ratio_chg') is not None]
    ts = {}
    if ts_rows:
        qq = quantile_vals([r['ratio_chg'] for r in ts_rows], 3)
        groups = {'T1_falling': [], 'T2_flat': [], 'T3_rising': []}
        for r in ts_rows:
            if r['ratio_chg'] <= qq[0]:
                groups['T1_falling'].append(r)
            elif r['ratio_chg'] <= qq[1]:
                groups['T2_flat'].append(r)
            else:
                groups['T3_rising'].append(r)
        stats_map = {k: group_stats(v) for k, v in groups.items()}
        ts = {
            'quantile_cutoffs': [round(x, 5) for x in qq],
            'groups': stats_map,
            'monotone_win14': monotone(stats_map),
            'permutation_fwd14': permutation_pval([groups['T1_falling'], groups['T2_flat'], groups['T3_rising']], 'fwd14'),
            'permutation_fwd30': permutation_pval([groups['T1_falling'], groups['T2_flat'], groups['T3_rising']], 'fwd30'),
        }

    rw = sorted(r['ratio_w'] for r in kept)
    out = {
        'probe': 'LIQ-RATIO-1 P-D-1 factor body',
        'pre_registered': {
            'level_factor': 'buy_num_last / same-day in_sale_count',
            'ts_factor': 'ratio_w change vs 7 rows prior',
            'winsorize': 'p99',
            'base_floor': 'in_sale >= 200 (price<10000) else 100; buy_num_last >= 3',
            'fwd': 'same item price_history +14/+30 rows (replay-aligned)',
            'decluster_spacing': '>=30 rows per item',
            'threshold': 'win >=8pp OR avg >=3pp AND monotone',
            'permutation_trials': 300,
        },
        'sample': {
            'eligible_before_decluster': len(rows),
            'p99_winsor': round(p99, 5),
            'kept_declustered': len(kept),
            'ts_kept_with_change': len(ts_rows),
            'ratio_w_summary': {
                'min': round(rw[0], 5), 'median': round(statistics.median(rw), 5),
                'p75': round(rw[min(len(rw) - 1, int(round(0.75 * (len(rw) - 1))))], 5),
                'max': round(rw[-1], 5),
            } if rw else {},
        },
        'cross_sectional': cs,
        'time_series': ts,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=1))

if __name__ == '__main__':
    main()