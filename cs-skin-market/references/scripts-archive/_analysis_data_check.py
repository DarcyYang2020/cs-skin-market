# -*- coding: utf-8 -*-
"""D: 数据完整性巡检 (临时分析, 2026-08-03)"""
import sqlite3, json, os
from datetime import datetime, timedelta

conn = sqlite3.connect('data/market.db')
cur = conn.cursor()
today = datetime.now().strftime('%Y-%m-%d')

print('=' * 80)
print('D1. price_history 覆盖')
print('=' * 80)
n_items = cur.execute('SELECT COUNT(DISTINCT item_id) FROM price_history').fetchone()[0]
n_rows = cur.execute('SELECT COUNT(*) FROM price_history').fetchone()[0]
date_range = cur.execute('SELECT MIN(date), MAX(date) FROM price_history').fetchone()
print(f"有历史的品数: {n_items} | 总行数: {n_rows} | 日期范围: {date_range[0]} ~ {date_range[1]}")
# 每品数据点数分布
pts = cur.execute('SELECT item_id, COUNT(*), MIN(date), MAX(date) FROM price_history GROUP BY item_id').fetchall()
short = [p for p in pts if p[1] < 40]
print(f"点数<40的品: {len(short)}")
for p in short[:10]:
    print(f"  item_id={p[0]} 点数={p[1]} {p[2]}~{p[3]}")
# 最近日期覆盖（今天缺多少品）
last_global = max(p[3] for p in pts) if pts else None
print(f"最新数据日: {last_global}")

print('\n' + '=' * 80)
print('D2. macro_history 贪婪指数缺失')
print('=' * 80)
rows = cur.execute('SELECT date, greedy_index, card_price FROM macro_history ORDER BY date DESC LIMIT 15').fetchall()
for r in rows:
    mark = '  <-- greedy缺失' if r[1] is None else ''
    print(f"  {r[0]}  greedy={r[1]}  card={r[2]}{mark}")
n_greedy_missing = cur.execute('SELECT COUNT(*) FROM macro_history WHERE greedy_index IS NULL').fetchone()[0]
print(f"greedy 缺失总天数: {n_greedy_missing}")

print('\n' + '=' * 80)
print('D3. snapshots 报告新鲜度')
print('=' * 80)
snaps = cur.execute('SELECT COUNT(*), MAX(date) FROM snapshots').fetchone()
print(f"snapshots 总数: {snaps[0]} | 最新: {snaps[1]}")
old = cur.execute("SELECT COUNT(*) FROM snapshots WHERE date < ?", ((datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d'),)).fetchone()[0]
print(f"超过14天未更新的报告: {old}")

print('\n' + '=' * 80)
print('D4. 成交量回填缺口 (price_history volume_day)')
print('=' * 80)
tot = cur.execute('SELECT COUNT(*) FROM price_history').fetchone()[0]
no_vol = cur.execute('SELECT COUNT(*) FROM price_history WHERE volume_day IS NULL OR volume_day = 0').fetchone()[0]
print(f"总行数 {tot} | volume_day 缺失/为0: {no_vol} ({no_vol/tot*100:.1f}%)")

print('\n' + '=' * 80)
print('D5. items 自选/持仓')
print('=' * 80)
for r in cur.execute('SELECT in_watchlist, holding, COUNT(*) FROM items GROUP BY in_watchlist, holding'):
    print(f"  in_watchlist={r[0]} holding={r[1]}: {r[2]} 品")
conn.close()

print('\n' + '=' * 80)
print('D6. 缓存文件时效')
print('=' * 80)
for f in ['data/batch_scan_latest.json', 'data/discover_latest.json', 'data/item_backtest_latest.json', 'data/portfolio_backtest_latest.json']:
    if os.path.exists(f):
        t = datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M')
        print(f"  {f}: {t}")