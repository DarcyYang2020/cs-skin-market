import json
import sqlite3
import statistics
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / 'data' / 'item_backtest_full_2025.json'
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_cost_liquidity_ladder.json'
COSTS = [1.0, 2.0, 3.0, 5.0]


def family_of(s):
    lab = s.get('action_label') or ''
    if '恐慌' in lab:
        return 'panic'
    if '深值' in lab:
        return 'deep_value'
    if '供给' in lab:
        return 'supply_accum'
    return 'base_dip'


def agg(vals, cost):
    net = [x - cost for x in vals]
    if not net:
        return {'n': 0}
    return {
        'n': len(net),
        'win_pct': round(100.0 * sum(1 for x in net if x > 0) / len(net), 1),
        'avg_pct': round(sum(net) / len(net), 2),
        'median_pct': round(statistics.median(net), 2),
    }


def main():
    replay = json.load(open(REPLAY, encoding='utf-8'))
    sigs = replay['signals']
    con = sqlite3.connect(DB)
    cur = con.cursor()
    name2id = {n: i for i, n in cur.execute('SELECT id, name FROM items')}
    by_item = {}
    for iid, dt, ins in cur.execute('SELECT item_id, date, in_sale_count FROM price_history'):
        by_item.setdefault(iid, {})[dt] = ins
    rows = []
    for s in sigs:
        iid = name2id.get(s['name'])
        cur_supply = None
        if iid:
            cur_supply = by_item.get(iid, {}).get(s['date'])
        bucket = 'missing'
        if cur_supply is None:
            bucket = 'null'
        elif cur_supply == 0:
            bucket = 'zero'
        elif cur_supply < 50:
            bucket = '1_49'
        elif cur_supply < 200:
            bucket = '50_199'
        else:
            bucket = '200_plus'
        rows.append({
            'family': family_of(s),
            'bucket': bucket,
            'supply': cur_supply,
            'fwd14': s.get('fwd14'),
            'fwd30': s.get('fwd30'),
        })
    buckets = ['all', 'null', 'zero', '1_49', '50_199', '200_plus']
    families = ['all', 'panic', 'deep_value', 'supply_accum', 'base_dip']
    out = {'generated': 'stage0', 'cost_ladder': [], 'signal_counts': {'total': len(rows)}}
    for c in COSTS:
        entry = {'cost_pct': c, 'by_family': {}, 'by_supply_bucket': {}}
        for fam in families:
            vals = [r['fwd14'] for r in rows if r['fwd14'] is not None and (fam == 'all' or r['family'] == fam)]
            entry['by_family'][fam] = agg(vals, c)
        for b in buckets:
            vals = [r['fwd14'] for r in rows if r['fwd14'] is not None and (b == 'all' or r['bucket'] == b)]
            entry['by_supply_bucket'][b] = agg(vals, c)
        out['cost_ladder'].append(entry)
    supply_counts = {}
    for b in buckets:
        supply_counts[b] = sum(1 for r in rows if b == 'all' or r['bucket'] == b)
    out['supply_bucket_counts'] = supply_counts
    spread_vals = [r[0] for r in cur.execute('SELECT spread_pct FROM snapshots WHERE spread_pct IS NOT NULL')]
    spread_vals.sort()
    def q(p):
        if not spread_vals: return None
        k = min(len(spread_vals)-1, max(0, int((len(spread_vals)-1)*p)))
        return round(spread_vals[k], 3)
    out['spread_snapshot'] = {
        'n': len(spread_vals),
        'median_pct': q(0.5),
        'p75_pct': q(0.75),
        'p90_pct': q(0.90),
        'share_over_2pct': round(100.0 * sum(1 for x in spread_vals if x > 2) / len(spread_vals), 1) if spread_vals else None,
    }
    out['executions_count'] = cur.execute('SELECT COUNT(*) FROM executions').fetchone()[0]
    con.close()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])


if __name__ == '__main__':
    main()
