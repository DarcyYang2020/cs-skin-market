# -*- coding: utf-8 -*-
import sqlite3, collections
conn = sqlite3.connect('data/market.db')
cur = conn.cursor()
n_items = cur.execute("SELECT COUNT(DISTINCT item_id) FROM price_history WHERE date BETWEEN '2026-02-03' AND '2026-03-17'").fetchone()[0]
n_rows = cur.execute("SELECT COUNT(*) FROM price_history WHERE date BETWEEN '2026-02-03' AND '2026-03-17'").fetchone()[0]
print(f'2/3-3/17 区间: {n_items} 品 / {n_rows} 行')
pts = cur.execute("SELECT item_id, COUNT(*), MIN(date), MAX(date) FROM price_history WHERE date BETWEEN '2026-02-03' AND '2026-03-17' GROUP BY item_id").fetchall()
c = collections.Counter(p[1] for p in pts)
print('点数分布:', dict(sorted(c.items())))
print('--- 覆盖>=30天的品 ---')
for p in sorted([x for x in pts if x[1] >= 30], key=lambda x: -x[1])[:8]:
    print(f'  item_id={p[0]} 点数={p[1]} {p[2]}~{p[3]}')
print('--- 大盘指数 2/1~3/20 ---')
for r in cur.execute("SELECT date, value, change_7d FROM market_index WHERE date BETWEEN '2026-02-01' AND '2026-03-20' ORDER BY date"):
    print(f'  {r[0]} {r[1]:.2f} chg7={r[2]}')
conn.close()