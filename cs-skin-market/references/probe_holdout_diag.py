# -*- coding: utf-8 -*-
"""holdout 品数据量诊断（2026-08-16，只读）。"""
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

c = sqlite3.connect(os.environ["CS_MODEL_DB"])
c.row_factory = sqlite3.Row
rows = c.execute("SELECT i.id, i.name, MIN(p.date) fd, "
                 "COUNT(CASE WHEN p.price_rmb IS NOT NULL THEN 1 END) n_nonnull "
                 "FROM items i JOIN price_history p ON p.item_id=i.id "
                 "WHERE i.good_id>0 GROUP BY i.id").fetchall()
c.close()
hold = [r for r in rows if r["fd"] > "2025-08-10"]
print("holdout 品数:", len(hold), "| 非空行数分布:")
dist = Counter(min(r["n_nonnull"] // 50 * 50, 300) for r in hold)
for k in sorted(dist):
    print("  %d~%d 行: %d 品" % (k, k + 49, dist[k]))
big = [r for r in hold if r["n_nonnull"] >= 121]
print("≥121 行的 holdout 品:", len(big))
for r in big[:15]:
    print("  ", r["name"][:40], r["fd"], r["n_nonnull"])
