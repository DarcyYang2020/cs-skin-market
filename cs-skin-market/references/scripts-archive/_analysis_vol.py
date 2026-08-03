# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect('data/market.db')
cur = conn.cursor()
rows = cur.execute("SELECT substr(date,1,7) AS ym, COUNT(*) FROM price_history WHERE volume_day IS NOT NULL AND volume_day > 0 GROUP BY ym ORDER BY ym").fetchall()
print('有量行按月分布:')
for r in rows:
    print(f'  {r[0]}: {r[1]} 行')
n = cur.execute('SELECT COUNT(DISTINCT item_id) FROM price_history WHERE volume_day IS NOT NULL AND volume_day > 0').fetchone()[0]
print(f'有量的品数: {n} / 94')
recent = cur.execute("SELECT COUNT(*) FROM price_history WHERE date >= '2026-07-28' AND volume_day > 0").fetchone()[0]
tot_recent = cur.execute("SELECT COUNT(*) FROM price_history WHERE date >= '2026-07-28'").fetchone()[0]
print(f'最近7天: 有量 {recent} / {tot_recent}')
conn.close()