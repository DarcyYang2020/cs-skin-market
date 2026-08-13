import json
import sqlite3
import statistics
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_cross_1_stage0.json'


def num(v):
    return float(v) if v is not None else None


def spread(ref, other):
    if not ref or not other or ref <= 0:
        return None
    return (other / ref - 1.0) * 100.0


def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {}
    return {
        'n': len(vals),
        'median_pct': round(statistics.median(vals), 2),
        'mean_pct': round(sum(vals) / len(vals), 2),
        'p90_pct': round(sorted(vals)[int(len(vals) * 0.9) - 1], 2) if len(vals) >= 10 else None,
        'gt20_pct': round(100.0 * sum(1 for v in vals if v > 20) / len(vals), 1),
        'negative_pct': round(100.0 * sum(1 for v in vals if v < 0) / len(vals), 1),
    }


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute('SELECT * FROM item_fundamental_snapshot').fetchall()
    # latest price per item for anchor check
    latest_price = {}
    for item_id, price in con.execute('SELECT p.item_id, p.price_rmb FROM price_history p JOIN (SELECT item_id, MAX(date) AS maxd FROM price_history GROUP BY item_id) x ON x.item_id = p.item_id AND x.maxd = p.date'):
        latest_price[item_id] = price
    con.close()

    out_rows = []
    pairs = {
        'buff_sell_vs_yyyp': [],
        'c5_sell_vs_yyyp': [],
        'steam_sell_vs_yyyp': [],
        'buff_buy_vs_yyyp_buy': [],
        'steam_buy_vs_yyyp_buy': [],
        'buff_sell_num_vs_yyyp': [],
        'c5_sell_num_vs_yyyp': [],
        'anchor_vs_price_history': [],
    }
    for r in rows:
        d = dict(r)
        yyyp = num(d.get('yyyp_sell_price'))
        buff = num(d.get('buff_sell_price'))
        c5 = num(d.get('c5_sell_price'))
        steam = num(d.get('steam_sell_price'))
        yyyp_buy = num(d.get('yyyp_buy_price'))
        buff_buy = num(d.get('buff_buy_price'))
        steam_buy = num(d.get('steam_buy_price'))
        ph = latest_price.get(d.get('item_id'))

        vals = {
            'buff_sell_vs_yyyp': spread(yyyp, buff),
            'c5_sell_vs_yyyp': spread(yyyp, c5),
            'steam_sell_vs_yyyp': spread(yyyp, steam),
            'buff_buy_vs_yyyp_buy': spread(yyyp_buy, buff_buy),
            'steam_buy_vs_yyyp_buy': spread(yyyp_buy, steam_buy),
            'buff_sell_num_vs_yyyp': spread(d.get('yyyp_sell_num'), d.get('buff_sell_num')),
            'c5_sell_num_vs_yyyp': spread(d.get('yyyp_sell_num'), d.get('c5_sell_num')),
            'anchor_vs_price_history': spread(ph, yyyp),
        }
        for k, v in vals.items():
            if v is not None:
                pairs[k].append(v)

        row = {
            'item_id': d.get('item_id'),
            'good_id': d.get('good_id'),
            'item_name': d.get('item_name'),
            'yyyp_sell_price': yyyp,
            'buff_sell_price': buff,
            'c5_sell_price': c5,
            'steam_sell_price': steam,
            'yyyp_buy_price': yyyp_buy,
            'buff_buy_price': buff_buy,
            'steam_buy_price': steam_buy,
            'yyyp_sell_num': d.get('yyyp_sell_num'),
            'buff_sell_num': d.get('buff_sell_num'),
            'c5_sell_num': d.get('c5_sell_num'),
            'price_history_last': ph,
        }
        row.update({k: round(v, 2) if v is not None else None for k, v in vals.items()})
        out_rows.append(row)

    out = {
        'generated': 'stage0-readonly',
        'data': {
            'n_fundamental_rows': len(rows),
            'n_with_yyyp': sum(1 for r in out_rows if r['yyyp_sell_price']),
            'n_with_buff': sum(1 for r in out_rows if r['buff_sell_price']),
            'n_with_c5': sum(1 for r in out_rows if r['c5_sell_price']),
            'n_with_steam': sum(1 for r in out_rows if r['steam_sell_price']),
        },
        'spread_summary': {k: stats(v) for k, v in pairs.items()},
        'largest_buff_premium': sorted(out_rows, key=lambda r: r.get('buff_sell_vs_yyyp') if r.get('buff_sell_vs_yyyp') is not None else -999, reverse=True)[:15],
        'largest_buff_discount': sorted(out_rows, key=lambda r: r.get('buff_sell_vs_yyyp') if r.get('buff_sell_vs_yyyp') is not None else 999)[:15],
        'largest_c5_premium': sorted(out_rows, key=lambda r: r.get('c5_sell_vs_yyyp') if r.get('c5_sell_vs_yyyp') is not None else -999, reverse=True)[:15],
        'largest_anchor_mismatch': sorted(out_rows, key=lambda r: abs(r.get('anchor_vs_price_history') or 0), reverse=True)[:15],
        'notes': [
            'CROSS-1 stage0: read-only cross-platform spread inventory from item_fundamental_snapshot (one-day snapshot).',
            'Anchor = yyyp_sell_price; steam is reference-only, not a trading anchor.',
            'No engine parameter, threshold, signal-family, or gate changed.',
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out['data'], ensure_ascii=False, indent=1))
    print(json.dumps(out['spread_summary'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
