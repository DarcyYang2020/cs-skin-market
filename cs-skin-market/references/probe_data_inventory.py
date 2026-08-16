# -*- coding: utf-8 -*-
"""数据资产盘点：replay DB 与 market.db 的表与 bid_history 覆盖（第一性原理探索前置）。"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for label, path in (("replay", ROOT / "data" / "replay_cycle_win.db"),
                    ("market", ROOT / "data" / "market.db")):
    print("=== %s: %s ===" % (label, path))
    if not path.exists():
        print("  (不存在)")
        continue
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print("  tables:", tabs)
    for t in ("bid_history", "price_history", "items", "market_index"):
        if t in tabs:
            n = c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            print("  %s n=%d" % (t, n))
    if "bid_history" in tabs:
        cols = [r[1] for r in c.execute("PRAGMA table_info(bid_history)")]
        print("  bid_history cols:", cols)
        r = c.execute("SELECT MIN(date), MAX(date) FROM bid_history").fetchone()
        print("  bid_history 日期范围:", r[0], "~", r[1])
        r2 = c.execute("SELECT COUNT(DISTINCT item_id) FROM bid_history").fetchone()[0]
        print("  bid_history 覆盖品数:", r2)
    if "price_history" in tabs:
        r = c.execute("SELECT MIN(date), MAX(date), COUNT(DISTINCT item_id) FROM price_history").fetchone()
        print("  price_history:", r[0], "~", r[1], "品数", r[2])
    c.close()
