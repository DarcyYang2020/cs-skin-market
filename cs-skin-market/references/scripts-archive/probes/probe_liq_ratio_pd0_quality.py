#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LIQ-RATIO-1 P-D-0 数据质量闸门（只读，零引擎改动）。

预注册口径（2026-08-14 外审钉死）：
  因子 = buy_num / in_sale_count（bid_history 同日 buy_num_*，price_history 同日 in_sale_count）。
  本探针只回答「数据能不能支撑 P-D-1」，不计算因子分组绩效。
输出: data/_exp_liq_ratio_pd0_quality.json
"""
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_liq_ratio_pd0_quality.json'


def scalar(con, sql, args=()):
    return con.execute(sql, args).fetchone()[0]


def pct_jump(cur, prev):
    if cur is None or prev is None or float(prev) <= 0:
        return None
    return (float(cur) / float(prev) - 1.0) * 100.0


def summary(vals):
    vals = [float(v) for v in vals if v is not None]
    if not vals:
        return {}
    vals_sorted = sorted(vals)
    q = lambda p: vals_sorted[min(len(vals_sorted) - 1, int(round(p * (len(vals_sorted) - 1))))]
    return {
        'n': len(vals),
        'min': round(vals_sorted[0], 3),
        'p25': round(q(0.25), 3),
        'median': round(statistics.median(vals_sorted), 3),
        'p75': round(q(0.75), 3),
        'p95': round(q(0.95), 3),
        'max': round(vals_sorted[-1], 3),
    }


def main():
    uri = f'file:{DB}?mode=ro'
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    out = {
        'probe': 'LIQ-RATIO-1 P-D-0 data quality gate',
        'pre_registered_factor': 'buy_num_last / same-day in_sale_count',
        'read_only': True,
    }

    # 1. 规模与覆盖
    out['coverage'] = {
        'rows': scalar(con, 'SELECT COUNT(*) FROM bid_history'),
        'distinct_good_id': scalar(con, 'SELECT COUNT(DISTINCT good_id) FROM bid_history'),
        'distinct_item_id': scalar(con, 'SELECT COUNT(DISTINCT item_id) FROM bid_history'),
        'item_id_null': scalar(con, 'SELECT COUNT(*) FROM bid_history WHERE item_id IS NULL'),
        'date_min': scalar(con, 'SELECT MIN(date) FROM bid_history'),
        'date_max': scalar(con, 'SELECT MAX(date) FROM bid_history'),
        'unique_dates': scalar(con, 'SELECT COUNT(DISTINCT date) FROM bid_history'),
    }

    # 2. buy_num 缺失率 / 非法值
    out['buy_num_quality'] = {
        'buy_num_last_null': scalar(con, 'SELECT SUM(buy_num_last IS NULL) FROM bid_history'),
        'buy_num_last_zero': scalar(con, 'SELECT SUM(buy_num_last=0) FROM bid_history'),
        'buy_num_last_negative': scalar(con, 'SELECT SUM(buy_num_last<0) FROM bid_history'),
        'buy_num_mean_null': scalar(con, 'SELECT SUM(buy_num_mean IS NULL) FROM bid_history'),
        'buy_num_mean_zero': scalar(con, 'SELECT SUM(buy_num_mean=0) FROM bid_history'),
        'point_count_min': scalar(con, 'SELECT MIN(point_count) FROM bid_history'),
        'point_count_avg': round(scalar(con, 'SELECT AVG(point_count) FROM bid_history'), 3),
        'point_count_max': scalar(con, 'SELECT MAX(point_count) FROM bid_history'),
    }

    # 3. 同日 price_history.in_sale_count join 覆盖（因子分母）
    join_rows = con.execute('''
        SELECT b.item_id, b.date, b.buy_num_last, p.in_sale_count
        FROM bid_history b
        LEFT JOIN price_history p ON p.item_id=b.item_id AND p.date=b.date
    ''').fetchall()
    total = len(join_rows)
    have_sale = sum(1 for r in join_rows if r['in_sale_count'] is not None)
    positive_sale = sum(1 for r in join_rows if (r['in_sale_count'] or 0) > 0)
    out['same_day_in_sale'] = {
        'bid_rows': total,
        'in_sale_joined': have_sale,
        'in_sale_join_rate_pct': round(100.0 * have_sale / total, 2) if total else None,
        'in_sale_positive_rows': positive_sale,
        'in_sale_positive_rate_pct': round(100.0 * positive_sale / total, 2) if total else None,
    }

    # 4. 逐品日间跳变分布（buy_num_last 快照级稳定性）
    per_item = defaultdict(list)
    for r in con.execute('SELECT item_id, date, buy_num_last FROM bid_history ORDER BY item_id, date'):
        per_item[r['item_id']].append((r['date'], r['buy_num_last']))
    jumps = []
    max_jumps = []
    for iid, series in per_item.items():
        for prev, cur in zip(series, series[1:]):
            j = pct_jump(cur[1], prev[1])
            if j is not None:
                jumps.append(j)
                max_jumps.append((abs(j), iid, prev[0], cur[0], prev[1], cur[1]))
    out['day_over_day_jump_pct'] = summary(jumps)
    top = sorted(max_jumps, reverse=True)[:10]
    out['largest_jumps'] = [
        {'item_id': iid, 'from_date': a, 'to_date': b, 'from_buy_num': float(x), 'to_buy_num': float(y), 'pct': round(p, 2)}
        for p, iid, a, b, x, y in top
    ]

    # 5. 可计算因子的行（buy_num_last>0 且 in_sale_count>0 且同日）
    calc = sum(1 for r in join_rows if (r['buy_num_last'] or 0) > 0 and (r['in_sale_count'] or 0) > 0)
    ratios = []
    for r in join_rows:
        bn = r['buy_num_last']
        sc = r['in_sale_count']
        if bn and sc and float(bn) > 0 and float(sc) > 0:
            ratios.append(float(bn) / float(sc))
    out['factor_ready'] = {
        'calc_rows': calc,
        'calc_rate_pct': round(100.0 * calc / total, 2) if total else None,
        'ratio_summary': summary(ratios),
        'ratio_gt_1_pct': round(100.0 * sum(1 for v in ratios if v > 1) / len(ratios), 2) if ratios else None,
    }

    con.close()
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()