import json
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_data_reserve_quality.json'


def scalar(con, sql, args=()):
    return con.execute(sql, args).fetchone()[0]


def null_counts(con, table, cols):
    out = {}
    for c in cols:
        out[c] = scalar(con, f'SELECT COUNT(*) FROM {table} WHERE {c} IS NULL')
    return out


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    checks = {}

    checks['table_counts'] = {}
    for t in ('item_fundamental_snapshot', 'bid_history', 'survive_history', 'series_snapshot', 'monitor_rank_snapshot'):
        checks['table_counts'][t] = {
            'rows': scalar(con, f'SELECT COUNT(*) FROM {t}'),
            'distinct_good_id': scalar(con, f'SELECT COUNT(DISTINCT good_id) FROM {t}') if t != 'series_snapshot' else None,
            'date_min': scalar(con, f'SELECT MIN(date) FROM {t}'),
            'date_max': scalar(con, f'SELECT MAX(date) FROM {t}'),
        }

    checks['platform_and_source'] = {}
    for t in ('item_fundamental_snapshot', 'bid_history', 'survive_history', 'series_snapshot'):
        entry = {
            'sources': {str(r['source']): r['c'] for r in con.execute(f'SELECT source, COUNT(*) c FROM {t} GROUP BY source')},
        }
        if t != 'series_snapshot':
            entry['platforms'] = {str(r['platform']): r['c'] for r in con.execute(f'SELECT platform, COUNT(*) c FROM {t} GROUP BY platform')}
        checks['platform_and_source'][t] = entry

    checks['null_counts'] = {
        'item_fundamental_snapshot': null_counts(con, 'item_fundamental_snapshot', ['good_id', 'item_name', 'yyyp_sell_price', 'yyyp_sell_num', 'buff_sell_price', 'buff_sell_num', 'c5_sell_price', 'c5_sell_num', 'statistic']),
        'bid_history': null_counts(con, 'bid_history', ['good_id', 'item_name', 'buy_price_last', 'buy_num_last', 'point_count']),
        'survive_history': null_counts(con, 'survive_history', ['good_id', 'item_name', 'statistic', 'source_created_at']),
        'series_snapshot': null_counts(con, 'series_snapshot', ['series_id', 'series_name', 'amount', 'total_value', 'sell_price_1']),
    }

    checks['invalid_values'] = {
        'bid_negative_buy_price': scalar(con, "SELECT COUNT(*) FROM bid_history WHERE buy_price_last < 0"),
        'bid_negative_buy_num': scalar(con, "SELECT COUNT(*) FROM bid_history WHERE buy_num_last < 0"),
        'bid_low_point_count': scalar(con, "SELECT COUNT(*) FROM bid_history WHERE point_count < 1"),
        'survive_zero_or_negative_statistic': scalar(con, "SELECT COUNT(*) FROM survive_history WHERE statistic IS NOT NULL AND statistic <= 0"),
        'series_negative_total_value': scalar(con, "SELECT COUNT(*) FROM series_snapshot WHERE total_value < 0"),
        'fundamental_negative_yyyp': scalar(con, "SELECT COUNT(*) FROM item_fundamental_snapshot WHERE yyyp_sell_price < 0"),
    }

    checks['orphan_refs'] = {
        'fundamental_item_id_missing': scalar(con, "SELECT COUNT(*) FROM item_fundamental_snapshot f LEFT JOIN items i ON i.id=f.item_id WHERE i.id IS NULL"),
        'bid_item_id_missing': scalar(con, "SELECT COUNT(*) FROM bid_history b LEFT JOIN items i ON i.id=b.item_id WHERE i.id IS NULL"),
        'survive_item_id_missing': scalar(con, "SELECT COUNT(*) FROM survive_history s LEFT JOIN items i ON i.id=s.item_id WHERE i.id IS NULL"),
        'fundamental_good_missing_in_items': scalar(con, "SELECT COUNT(*) FROM item_fundamental_snapshot f LEFT JOIN items i ON i.good_id=f.good_id WHERE i.good_id IS NULL"),
        'bid_good_missing_in_items': scalar(con, "SELECT COUNT(*) FROM bid_history b LEFT JOIN items i ON i.good_id=b.good_id WHERE i.good_id IS NULL"),
        'survive_good_missing_in_items': scalar(con, "SELECT COUNT(*) FROM survive_history s LEFT JOIN items i ON i.good_id=s.good_id WHERE i.good_id IS NULL"),
    }

    checks['date_integrity'] = {
        'future_fundamental': scalar(con, "SELECT COUNT(*) FROM item_fundamental_snapshot WHERE date > date('now')"),
        'future_bid': scalar(con, "SELECT COUNT(*) FROM bid_history WHERE date > date('now')"),
        'future_survive': scalar(con, "SELECT COUNT(*) FROM survive_history WHERE date > date('now')"),
        'survive_date_not_equal_source': scalar(con, "SELECT COUNT(*) FROM survive_history WHERE substr(source_created_at,1,10) <> date"),
    }

    checks['series_inventory'] = {
        'series_count': scalar(con, "SELECT COUNT(DISTINCT series_id) FROM series_snapshot"),
        'series_without_name': scalar(con, "SELECT COUNT(*) FROM series_snapshot WHERE series_name IS NULL OR series_name=''"),
        'series_amount_min': scalar(con, "SELECT MIN(amount) FROM series_snapshot"),
        'series_amount_max': scalar(con, "SELECT MAX(amount) FROM series_snapshot"),
        'series_total_value_sum': scalar(con, "SELECT ROUND(SUM(total_value),2) FROM series_snapshot"),
    }

    out = {
        'generated': 'readonly-quality-audit',
        'checks': checks,
        'notes': [
            'Read-only quality audit for v58 P0/P1 research tables. No data modified.',
            'These tables are research-only and intentionally not FK-bound to items.',
        ],
    }
    con.close()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
