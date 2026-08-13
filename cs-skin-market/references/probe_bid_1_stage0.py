import json
import sqlite3
import statistics
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_bid_1_stage0.json'


def d(s):
    return date.fromisoformat(s)


def pct_change(cur, prev):
    if cur is None or prev is None or float(prev) <= 0:
        return None
    return (float(cur) / float(prev) - 1.0) * 100.0


def avg(vals):
    return round(sum(vals) / len(vals), 2) if vals else None


def median(vals):
    return round(statistics.median(vals), 2) if vals else None


def future_return(sorted_dates, price_map, base_date, days):
    target = base_date + timedelta(days=days)
    idx = bisect_left(sorted_dates, target)
    for d in sorted_dates[idx:idx + 4]:
        delta = (d - base_date).days
        if delta < days:
            continue
        if delta > days + 3:
            break
        cur = price_map.get(base_date)
        fut = price_map.get(d)
        if cur and fut and float(cur) > 0:
            return (float(fut) / float(cur) - 1.0) * 100.0
    return None


def trailing_change(series, base_date, window):
    vals = [(k, v) for k, v in series.items() if k <= base_date]
    if not vals:
        return None
    vals.sort(key=lambda x: x[0])
    if len(vals) < window + 1:
        return None
    return pct_change(vals[-1][1], vals[-1 - window][1])


def avg_trailing(series, base_date, window):
    vals = [(k, v) for k, v in series.items() if k <= base_date]
    if not vals:
        return None
    vals.sort(key=lambda x: x[0])
    take = vals[-window:]
    nums = [float(v) for _, v in take if v is not None]
    return sum(nums) / len(nums) if nums else None


def bid_label(chg):
    if chg is None:
        return 'no_data'
    if chg > 0:
        return 'cooperate'
    if chg < -3:
        return 'diverge'
    return 'neutral'


def outcome_stats(rows):
    out = {}
    for horizon in (14, 30):
        key = f'fwd{horizon}'
        vals = [r[key] for r in rows if r.get(key) is not None]
        wins = [v for v in vals if v > 0]
        out[f'n{horizon}'] = len(vals)
        out[f'win{horizon}_pct'] = round(100.0 * len(wins) / len(vals), 1) if vals else None
        out[f'avg{horizon}_pct'] = avg(vals)
        out[f'med{horizon}_pct'] = median(vals)
    return out


def load_data(con):
    items = {r[0]: r[1] for r in con.execute('SELECT id, name FROM items')}
    price_rows = defaultdict(lambda: defaultdict(dict))
    dates_by_item = defaultdict(list)
    for item_id, dt, price, ins in con.execute('SELECT item_id, date, price_rmb, in_sale_count FROM price_history ORDER BY date'):
        day = d(dt)
        price_rows[item_id][day] = {'price': price, 'in_sale': ins}
        if day not in dates_by_item[item_id]:
            dates_by_item[item_id].append(day)
    for item_id in dates_by_item:
        dates_by_item[item_id].sort()
    market_dates = []
    market_map = {}
    for dt, value in con.execute('SELECT date, value FROM market_index ORDER BY date'):
        day = d(dt)
        if day not in market_map:
            market_dates.append(day)
        market_map[day] = value
    bids = con.execute('SELECT item_id, good_id, item_name, date, buy_price_last, buy_num_last, point_count FROM bid_history ORDER BY date, item_id').fetchall()
    return items, price_rows, dates_by_item, bids, market_dates, market_map


def main():
    con = sqlite3.connect(DB)
    items, price_rows, dates_by_item, bids, market_dates, market_map = load_data(con)
    con.close()

    spread_vals = []
    point_counts = Counter()
    rows = []
    for item_id, good_id, item_name, dt, buy_price, buy_num, point_count in bids:
        day = d(dt)
        pr = price_rows.get(item_id, {}).get(day, {})
        price = pr.get('price')
        in_sale = pr.get('in_sale')
        point_counts[point_count] += 1

        spread = None
        if price and buy_price and float(price) > 0 and float(buy_price) > 0:
            spread = (float(price) - float(buy_price)) / float(price) * 100.0
            spread_vals.append(spread)

        bid_cover = None
        if in_sale and buy_num is not None and float(in_sale) > 0:
            bid_cover = float(buy_num) / float(in_sale)

        bid_price_series = {}
        bid_num_series = {}
        bid_price_series[day] = buy_price
        bid_num_series[day] = buy_num

        # trailing features are computed from the full series in a second pass below
        rows.append({
            'item_id': item_id,
            'good_id': good_id,
            'item_name': item_name,
            'date': dt,
            'day': day,
            'price': price,
            'in_sale': in_sale,
            'buy_price_last': buy_price,
            'buy_num_last': buy_num,
            'point_count': point_count,
            'spread_pct': round(spread, 2) if spread is not None else None,
            'bid_cover': round(bid_cover, 4) if bid_cover is not None else None,
        })

    # build full bid series by item
    bid_price_by_item = defaultdict(dict)
    bid_num_by_item = defaultdict(dict)
    for r in rows:
        bid_price_by_item[r['item_id']][r['day']] = r['buy_price_last']
        bid_num_by_item[r['item_id']][r['day']] = r['buy_num_last']
    in_sale_by_item = defaultdict(dict)
    price_by_item = defaultdict(dict)
    for item_id, mp in price_rows.items():
        for day, v in mp.items():
            in_sale_by_item[item_id][day] = v['in_sale']
            price_by_item[item_id][day] = v['price']

    for r in rows:
        item_id = r['item_id']
        day = r['day']
        r['bid_price_chg7'] = round(trailing_change(bid_price_by_item[item_id], day, 7), 2) if trailing_change(bid_price_by_item[item_id], day, 7) is not None else None
        r['bid_num_chg7'] = round(trailing_change(bid_num_by_item[item_id], day, 7), 2) if trailing_change(bid_num_by_item[item_id], day, 7) is not None else None
        s7 = avg_trailing(in_sale_by_item[item_id], day, 7)
        s30 = avg_trailing(in_sale_by_item[item_id], day, 30)
        r['in_sale_ratio7_30'] = round(s7 / s30, 4) if s7 and s30 else None
        r['supply_contract'] = bool(r['in_sale_ratio7_30'] is not None and r['in_sale_ratio7_30'] <= 0.85)
        price_chg7 = trailing_change(price_by_item[item_id], day, 7)
        r['price_chg7'] = round(price_chg7, 2) if price_chg7 is not None else None
        r['price_stable'] = bool(price_chg7 is not None and abs(price_chg7) <= 3.0)
        r['bid_label'] = bid_label(r['bid_num_chg7'])
        r['fwd14'] = future_return(dates_by_item[item_id], price_by_item[item_id], day, 14)
        r['fwd30'] = future_return(dates_by_item[item_id], price_by_item[item_id], day, 30)
        r['market_fwd14'] = future_return(market_dates, market_map, day, 14)
        r['market_fwd30'] = future_return(market_dates, market_map, day, 30)

    candidates = [r for r in rows if r['supply_contract'] and r['price_stable']]
    cooperate_supply = [r for r in candidates if r['bid_label'] == 'cooperate']
    supply_noncoop = [r for r in candidates if r['bid_label'] in ('neutral', 'diverge')]
    all_label_groups = {}
    for label in ('cooperate', 'neutral', 'diverge', 'no_data'):
        all_label_groups[label] = [r for r in rows if r['bid_label'] == label]

    # quintile of bid_num_chg7 among non-null
    chg_rows = [r for r in rows if r['bid_num_chg7'] is not None]
    chg_rows_sorted = sorted(chg_rows, key=lambda r: r['bid_num_chg7'])
    quintiles = {}
    if chg_rows_sorted:
        n = len(chg_rows_sorted)
        for q in range(5):
            lo = int(round(n * q / 5))
            hi = int(round(n * (q + 1) / 5))
            quintiles[f'q{q+1}'] = chg_rows_sorted[lo:hi]

    out = {
        'generated': 'stage0-readonly',
        'data': {
            'bid_rows': len(rows),
            'unique_goods': len(set(r['good_id'] for r in rows)),
            'unique_items': len(set(r['item_id'] for r in rows)),
            'date_min': min(r['date'] for r in rows),
            'date_max': max(r['date'] for r in rows),
            'point_count_distribution': dict(sorted(point_counts.items())),
            'spread_median_pct': median(spread_vals),
            'spread_p90_pct': round(sorted(spread_vals)[int(len(spread_vals) * 0.9) - 1], 2) if spread_vals else None,
            'spread_gt2_pct': round(100.0 * sum(1 for v in spread_vals if v > 2) / len(spread_vals), 1) if spread_vals else None,
            'n_fwd14': sum(1 for r in rows if r['fwd14'] is not None),
            'n_fwd30': sum(1 for r in rows if r['fwd30'] is not None),
            'n_market_fwd14': sum(1 for r in rows if r['market_fwd14'] is not None),
            'n_market_fwd30': sum(1 for r in rows if r['market_fwd30'] is not None),
            'n_supply_contract_price_stable_candidates': len(candidates),
            'candidate_unique_items': len(set(r['item_id'] for r in candidates)),
        },
        'outcomes': {
            'market_index_baseline': outcome_stats([{'fwd14': r['market_fwd14'], 'fwd30': r['market_fwd30']} for r in rows if r['market_fwd14'] is not None or r['market_fwd30'] is not None]),
            'all': outcome_stats(rows),
            'bid_cooperate': outcome_stats(all_label_groups['cooperate']),
            'bid_neutral': outcome_stats(all_label_groups['neutral']),
            'bid_diverge': outcome_stats(all_label_groups['diverge']),
            'bid_no_data': outcome_stats(all_label_groups['no_data']),
            'supply_contract_price_stable': outcome_stats(candidates),
            'supply_contract_price_stable_bid_cooperate': outcome_stats(cooperate_supply),
            'supply_contract_price_stable_bid_noncoop': outcome_stats(supply_noncoop),
        },
        'quintiles_by_bid_num_chg7': {k: outcome_stats(v) for k, v in quintiles.items()},
        'bid_label_distribution': {k: len(v) for k, v in all_label_groups.items()},
        'candidate_items': sorted([{'item_id': r['item_id'], 'good_id': r['good_id'], 'item_name': r['item_name'], 'date': r['date'], 'bid_label': r['bid_label'], 'bid_num_chg7': r['bid_num_chg7'], 'spread_pct': r['spread_pct'], 'fwd14': r['fwd14'], 'fwd30': r['fwd30']} for r in candidates], key=lambda x: (x['date'], x['item_name'] or '')),
        'notes': [
            'BID-1 stage0: read-only feasibility using bid_history joined to price_history.',
            'bid_num_chg7>0 = cooperate; < -3 = diverge; otherwise neutral.',
            'supply_contract = avg in_sale 7d / avg in_sale 30d <= 0.85; price_stable = |chg7| <= 3%.',
            'No engine parameter, threshold, signal-family, or gate changed. No formal A2 decision at this stage.',
        ],
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out['data'], ensure_ascii=False, indent=1))
    print(json.dumps(out['outcomes'], ensure_ascii=False, indent=1))
    print(json.dumps(out['quintiles_by_bid_num_chg7'], ensure_ascii=False, indent=1))
    print('bid_label_distribution', out['bid_label_distribution'])
    print('candidate_items', len(out['candidate_items']))


if __name__ == '__main__':
    main()
