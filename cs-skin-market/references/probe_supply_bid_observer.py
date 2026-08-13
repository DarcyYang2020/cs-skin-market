import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_supply_bid_observer.json'


def load_series(con):
    price_rows = defaultdict(list)
    for item_id, dt, price, ins in con.execute('SELECT item_id, date, price_rmb, in_sale_count FROM price_history ORDER BY date'):
        price_rows[item_id].append((dt, price, ins))
    names = {r[0]: r[1] for r in con.execute('SELECT id, name FROM items')}
    snaps = con.execute('SELECT item_id, date, bid_7d_chg, spread_pct FROM snapshots ORDER BY date, id').fetchall()
    return names, price_rows, snaps


def supply_metrics(rows, date):
    prior = [(dt, p, ins) for dt, p, ins in rows if dt <= date]
    if not prior:
        return None
    last30 = prior[-30:]
    last7 = prior[-7:]
    vals30 = [(ins or 0) for _, _, ins in last30]
    vals7 = [(ins or 0) for _, _, ins in last7]
    s30 = sum(vals30) / len(vals30) if vals30 else 0.0
    s7 = sum(vals7) / len(vals7) if vals7 else 0.0
    ratio = (s7 / s30) if s30 > 0 else None
    real_pos = sum(1 for v in vals30 if v > 0)
    cont = 0
    for _, _, ins in reversed(last30):
        if ins is not None and ins > 0:
            cont += 1
        else:
            break
    if len(prior) >= 8 and prior[-1][1] and prior[-8][1]:
        chg7 = (prior[-1][1] / prior[-8][1] - 1) * 100
    else:
        chg7 = None
    return {
        's7': round(s7, 2),
        's30': round(s30, 2),
        'ratio': round(ratio, 4) if ratio is not None else None,
        'real_pos_30': real_pos,
        'consecutive_positive_days': cont,
        'chg7': round(chg7, 2) if chg7 is not None else None,
        'supply_contract': s30 > 0 and s7 > 0 and ratio is not None and ratio <= 0.85,
        'price_stable': chg7 is not None and abs(chg7) <= 3.0,
    }


def bid_label(bid7, spread):
    if bid7 is None:
        return 'no_data'
    if bid7 > 0:
        return 'cooperate'
    if bid7 < -3:
        return 'diverge'
    return 'neutral'


def main():
    con = sqlite3.connect(DB)
    names, price_rows, snaps = load_series(con)
    con.close()

    rows_out = []
    latest_by_item = {}
    for item_id, dt, bid7, spread in snaps:
        base = supply_metrics(price_rows.get(item_id, []), dt)
        if base is None:
            continue
        label = bid_label(bid7, spread)
        candidate = base['supply_contract'] and base['price_stable']
        row = {
            'item_id': item_id,
            'name': names.get(item_id),
            'date': dt,
            **base,
            'bid_7d_chg': bid7,
            'spread_pct': spread,
            'bid_label': label,
            'candidate': candidate,
        }
        rows_out.append(row)
        latest_by_item[item_id] = row

    candidates = [r for r in rows_out if r['candidate']]
    bid_nonnull = [r for r in rows_out if r['bid_7d_chg'] is not None]
    spreads = [r['spread_pct'] for r in rows_out if r['spread_pct'] is not None]
    latest_candidates = {}
    for r in candidates:
        if r['item_id'] not in latest_candidates or r['date'] > latest_candidates[r['item_id']]['date']:
            latest_candidates[r['item_id']] = r
    monthly = defaultdict(Counter)
    for r in candidates:
        monthly[r['date'][:7]][r['bid_label']] += 1

    out = {
        'generated': 'stage0',
        'summary': {
            'n_snapshots_evaluated': len(rows_out),
            'n_bid_nonnull': len(bid_nonnull),
            'n_spread_nonnull': len(spreads),
            'spread_median_pct': round(statistics.median(spreads), 2) if spreads else None,
            'spread_p90_pct': round(sorted(spreads)[int(len(spreads) * 0.9) - 1], 2) if spreads else None,
            'n_supply_contract_price_stable_candidates': len(candidates),
            'n_candidate_unique_items': len(latest_candidates),
            'candidate_bid_labels': dict(Counter(r['bid_label'] for r in candidates)),
        },
        'monthly_candidates': {k: dict(v) for k, v in sorted(monthly.items())},
        'candidates': sorted(candidates, key=lambda r: (r['date'], r['name'] or '')),
        'candidate_latest_unique': sorted(latest_candidates.values(), key=lambda r: (r['date'], r['name'] or '')),
        'latest_by_item': sorted(latest_by_item.values(), key=lambda r: (r['name'] or '', r['date'])),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])


if __name__ == '__main__':
    main()
