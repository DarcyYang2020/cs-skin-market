# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect('data/market.db')
cur = conn.cursor()
for t in ['price_history', 'market_index', 'macro_history', 'snapshots']:
    try:
        r = cur.execute(f"SELECT MIN(date), MAX(date), COUNT(*) FROM {t}").fetchone()
        print(f'{t}: {r[0]} ~ {r[1]} ({r[2]} 行)')
    except Exception as e:
        print(f'{t}: ERROR {e}')
print('\n--- 大盘 1/15~2/5 ---')
for r in cur.execute("SELECT date, value, mood FROM market_index WHERE date BETWEEN '2026-01-15' AND '2026-02-05' ORDER BY date"):
    print(f'  {r[0]} {r[1]:.2f} {r[2]}')
print('\n--- macro_history 1/15~2/5 ---')
for r in cur.execute("SELECT date, greedy_index FROM macro_history WHERE date BETWEEN '2026-01-15' AND '2026-02-05' ORDER BY date"):
    print(f'  {r[0]} greedy={r[1]}')
conn.close()