# -*- coding: utf-8 -*-
"""只读：对比生产库与回放库 market_index 的范围/重叠值一致性。"""
import sqlite3

for tag, dbp in (("PROD", "data/market.db"), ("REPLAY", "data/replay_cycle_win.db")):
    c = sqlite3.connect(dbp)
    c.row_factory = sqlite3.Row
    n, d0, d1 = c.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM market_index").fetchone()
    print("%s market_index: n=%s %s ~ %s" % (tag, n, d0, d1))
    if tag == "PROD":
        prod = {r["date"]: r["value"] for r in c.execute("SELECT date, value FROM market_index")}
        cols = [r[1] for r in c.execute("PRAGMA table_info(market_index)")]
        print("  prod columns:", cols)
    else:
        rep = {r["date"]: r["value"] for r in c.execute("SELECT date, value FROM market_index")}
        cols = [r[1] for r in c.execute("PRAGMA table_info(market_index)")]
        print("  replay columns:", cols)
    c.close()

common = sorted(set(prod) & set(rep))
print("overlap days:", len(common))
if common:
    diffs = [(d, prod[d], rep[d]) for d in common if abs(float(prod[d]) - float(rep[d])) > 1e-6]
    print("value-mismatch days:", len(diffs), diffs[:5])
    print("sample match:", common[0], prod[common[0]], rep[common[0]], "|", common[-1], prod[common[-1]], rep[common[-1]])
only_rep = sorted(set(rep) - set(prod))
only_prod = sorted(set(prod) - set(rep))
print("only in replay:", len(only_rep), only_rep[:3], "...", only_rep[-3:] if only_rep else "")
print("only in prod:", len(only_prod), only_prod[:3], "...", only_prod[-3:] if only_prod else "")
