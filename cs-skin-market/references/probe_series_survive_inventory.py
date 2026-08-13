import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_series_survive_inventory.json'


def d(s):
    return date.fromisoformat(s)


def pct(cur, prev):
    if not prev or prev <= 0:
        return None
    return (cur / prev - 1.0) * 100.0


def nearest_on_or_before(sorted_dates, target, tol_days=3):
    # dates sorted ascending; find latest <= target, then check gap
    cand = None
    for x in sorted_dates:
        if x <= target:
            cand = x
        else:
            break
    if cand is None or (target - cand).days > tol_days:
        return None
    return cand


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # series snapshot inventory
    series = [dict(r) for r in con.execute("SELECT * FROM series_snapshot WHERE date=(SELECT MAX(date) FROM series_snapshot)")]
    horizons = ('sell_price_1', 'sell_price_7', 'sell_price_15', 'sell_price_30', 'sell_price_90', 'sell_price_180')
    series_out = {
        'n': len(series),
        'breadth': {},
        'top_amount': sorted(series, key=lambda r: r.get('amount') or 0, reverse=True)[:10],
        'top_total_value': sorted(series, key=lambda r: r.get('total_value') or 0, reverse=True)[:10],
        'movers': {},
    }
    for h in horizons:
        vals = [r.get(h) for r in series if r.get(h) is not None]
        series_out['breadth'][h] = {
            'positive': sum(1 for v in vals if v > 0),
            'negative': sum(1 for v in vals if v < 0),
            'median': round(statistics.median(vals), 2) if vals else None,
        }
        series_out['movers'][h] = {
            'top': sorted(series, key=lambda r: r.get(h) if r.get(h) is not None else -999, reverse=True)[:5],
            'bottom': sorted(series, key=lambda r: r.get(h) if r.get(h) is not None else 999)[:5],
        }
    # trim mover rows
    for h in horizons:
        for side in ('top', 'bottom'):
            series_out['movers'][h][side] = [{k: r.get(k) for k in ('series_id', 'series_name', 'amount', 'total_value', h)} for r in series_out['movers'][h][side]]

    # survive history inventory
    by_good = defaultdict(dict)
    for r in con.execute("SELECT good_id, item_id, item_name, date, statistic FROM survive_history ORDER BY date"):
        by_good[r['good_id']][d(r['date'])] = r['statistic']
        by_good[r['good_id']]['_meta'] = {'item_id': r['item_id'], 'item_name': r['item_name']}

    survive_rows = []
    for good_id, mp in by_good.items():
        meta = mp.pop('_meta', {})
        dates = sorted(mp.keys())
        latest = dates[-1]
        cur = mp[latest]
        changes = {}
        for label, days in (('7d', 7), ('30d', 30), ('90d', 90), ('180d', 180)):
            target = latest - timedelta(days=days)
            prev_date = nearest_on_or_before(dates, target)
            prev = mp.get(prev_date) if prev_date else None
            changes[label] = round(pct(cur, prev), 2) if prev is not None else None
        survive_rows.append({
            'good_id': good_id,
            'item_id': meta.get('item_id'),
            'item_name': meta.get('item_name'),
            'date_min': str(dates[0]),
            'date_max': str(latest),
            'n_days': len(dates),
            'latest_statistic': cur,
            **changes,
        })

    event_cols = ('7d', '30d', '90d', '180d')
    survive_out = {
        'n_goods': len(survive_rows),
        'changes': {},
        'top_increases': {},
        'top_decreases': {},
    }
    for col in event_cols:
        vals = [r[col] for r in survive_rows if r[col] is not None]
        survive_out['changes'][col] = {
            'n': len(vals),
            'median_pct': round(statistics.median(vals), 2) if vals else None,
            'positive': sum(1 for v in vals if v > 0),
            'negative': sum(1 for v in vals if v < 0),
            'gt5_pct': sum(1 for v in vals if v > 5),
            'lt_minus5_pct': sum(1 for v in vals if v < -5),
        }
        survive_out['top_increases'][col] = sorted([r for r in survive_rows if r[col] is not None], key=lambda r: r[col], reverse=True)[:10]
        survive_out['top_decreases'][col] = sorted([r for r in survive_rows if r[col] is not None], key=lambda r: r[col])[:10]

    out = {
        'generated': 'readonly-inventory',
        'series_snapshot': series_out,
        'survive_history': survive_out,
        'notes': [
            'Read-only inventory from series_snapshot and survive_history. No engine change.',
            'survive_history statistic is supply count, not in_sale_count; do not mix with engine supply metric.',
        ],
    }
    con.close()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out['series_snapshot']['breadth'], ensure_ascii=False, indent=1))
    print(json.dumps(out['survive_history']['changes'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
