import json
import sqlite3
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / 'data' / 'item_backtest_full_2025.json'
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_supply_confirmation_audit.json'


def is_supply_accum(s):
    return '供给' in (s.get('action_label') or '')


def main():
    replay = json.load(open(REPLAY, encoding='utf-8'))
    sigs = replay['signals']
    con = sqlite3.connect(DB)
    dbcur = con.cursor()
    name2id = {n: i for i, n in dbcur.execute('SELECT id, name FROM items')}
    by_item = defaultdict(list)
    for iid, dt, ins in dbcur.execute('SELECT item_id, date, in_sale_count FROM price_history'):
        by_item[iid].append((dt, ins))
    for iid in by_item:
        by_item[iid].sort()

    def supply_at(iid, date, lookback=30):
        rows = [(d, v) for d, v in by_item[iid] if d <= date][-lookback:]
        curv = None
        for d, v in by_item[iid]:
            if d == date:
                curv = v
        s30 = rows[-1][1] if rows else None
        s7 = rows[-7][1] if len(rows) >= 7 else None
        real_pos = sum(1 for d, v in rows if v is not None and v > 0)
        return curv, s7, s30, real_pos, len(rows)

    all_stats = []
    for s in sigs:
        iid = name2id.get(s['name'])
        if iid is None:
            all_stats.append({'name': s['name'], 'date': s['date'], 'supply_accum': is_supply_accum(s), 'cur': None, 's7': None, 's30': None, 'real_pos': 0, 'lookback_n': 0, 'ratio': None})
            continue
        curv, s7, s30, real_pos, n = supply_at(iid, s['date'])
        ratio = None
        if s7 is not None and s30 not in (None, 0):
            ratio = s7 / s30
        all_stats.append({'name': s['name'], 'date': s['date'], 'supply_accum': is_supply_accum(s), 'cur': curv, 's7': s7, 's30': s30, 'ratio': round(ratio, 4) if ratio is not None else None, 'real_pos': real_pos, 'lookback_n': n})

    supply_rows = [r for r in all_stats if r['supply_accum']]
    def summarize(rows):
        n = len(rows)
        cur_pos = sum(1 for r in rows if r['cur'] is not None and r['cur'] > 0)
        cur_zero = sum(1 for r in rows if r['cur'] == 0)
        cur_null = sum(1 for r in rows if r['cur'] is None)
        real20 = sum(1 for r in rows if r['real_pos'] >= 20)
        ratio_contract = sum(1 for r in rows if r['ratio'] is not None and r['ratio'] <= 0.85)
        ratio_contract_real20 = sum(1 for r in rows if r['ratio'] is not None and r['ratio'] <= 0.85 and r['real_pos'] >= 20)
        return {'n': n, 'cur_positive': cur_pos, 'cur_zero': cur_zero, 'cur_null': cur_null, 'real20_plus': real20, 'ratio_le_085': ratio_contract, 'ratio_le_085_real20': ratio_contract_real20}

    clean_by_month = defaultdict(lambda: [0, 0])
    for r in all_stats:
        m = r['date'][:7]
        clean_by_month[m][0] += 1
        if r['cur'] is not None and r['cur'] > 0:
            clean_by_month[m][1] += 1

    db_audit = {}
    db_audit['price_history'] = dbcur.execute('SELECT MIN(date), MAX(date), COUNT(*), COUNT(DISTINCT item_id) FROM price_history').fetchone()
    db_audit['price_history_insale_null'] = dbcur.execute('SELECT COUNT(*) FROM price_history WHERE in_sale_count IS NULL').fetchone()[0]
    db_audit['price_history_insale_zero'] = dbcur.execute('SELECT COUNT(*) FROM price_history WHERE in_sale_count = 0').fetchone()[0]
    db_audit['snapshots'] = dbcur.execute('SELECT MIN(date), MAX(date), COUNT(*), COUNT(DISTINCT item_id), SUM(CASE WHEN spread_pct IS NOT NULL THEN 1 ELSE 0 END), SUM(CASE WHEN bid_highest IS NOT NULL THEN 1 ELSE 0 END) FROM snapshots').fetchone()
    db_audit['monitor_rank_snapshot'] = dbcur.execute('SELECT MIN(date), MAX(date), COUNT(DISTINCT date), COUNT(DISTINCT item_id), COUNT(*) FROM monitor_rank_snapshot').fetchone()
    con.close()

    out = {
        'generated': 'stage0',
        'all_signals': summarize(all_stats),
        'supply_accum_signals': summarize(supply_rows),
        'clean_positive_by_month': {k: {'n': v[0], 'cur_positive': v[1]} for k, v in sorted(clean_by_month.items())},
        'db_audit': {
            'price_history': {'range': db_audit['price_history'][0:2], 'rows': db_audit['price_history'][2], 'items': db_audit['price_history'][3], 'insale_null': db_audit['price_history_insale_null'], 'insale_zero': db_audit['price_history_insale_zero']},
            'snapshots': {'range': db_audit['snapshots'][0:2], 'rows': db_audit['snapshots'][2], 'items': db_audit['snapshots'][3], 'spread_nonnull': db_audit['snapshots'][4], 'bid_nonnull': db_audit['snapshots'][5]},
            'monitor_rank_snapshot': {'range': db_audit['monitor_rank_snapshot'][0:2], 'dates': db_audit['monitor_rank_snapshot'][2], 'items': db_audit['monitor_rank_snapshot'][3], 'rows': db_audit['monitor_rank_snapshot'][4]},
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])


if __name__ == '__main__':
    main()
