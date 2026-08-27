# -*- coding: utf-8 -*-
"""D4 派生层重建（2026-08-27）：从生产库 market.db 重建两个回放库（幂等）。

- 源：data/market.db（只读，不修改）
- 目标：data/replay_hybrid.db、data/replay_cycle_win.db
- 复制表：items / price_history / market_index（DDL + 索引 + 数据全量复制）
- 幂等：每次重建前清空目标库三表；重建后 append provenance（血缘台账）。
用法: python references/drills/rebuild_derived.py [--no-backup]
"""
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from pipeline import provenance
from pipeline.config import DATA_DIR, TZ_BJ

SRC = os.path.join(str(DATA_DIR), "market.db")
DBS = ["replay_hybrid.db", "replay_cycle_win.db"]
TABLES = ["items", "price_history", "market_index"]


def rebuild(backup_old=True):
    """从生产库重建两个回放库，返回 {dbname: {table: count}}。"""
    src = sqlite3.connect(SRC)
    src.row_factory = sqlite3.Row
    report = {}
    for dbname in DBS:
        dst_path = os.path.join(str(DATA_DIR), dbname)
        if backup_old and os.path.exists(dst_path) and os.path.getsize(dst_path) > 0:
            bk_dir = os.path.join(str(DATA_DIR), "_ops_recovery_latest")
            os.makedirs(bk_dir, exist_ok=True)
            shutil.copy2(dst_path, os.path.join(bk_dir, f"{dbname}.pre-rebuild"))
        dst = sqlite3.connect(dst_path)
        for t in TABLES:
            dst.execute(f"DROP TABLE IF EXISTS {t}")
        dst.commit()
        for r in src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name IN "
            "('items','price_history','market_index')"
        ):
            dst.execute(r["sql"])
        for r in src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name IN "
            "('items','price_history','market_index') AND sql IS NOT NULL"
        ):
            try:
                dst.execute(r["sql"])
            except Exception:
                pass
        dst.commit()
        dst.execute("ATTACH DATABASE ? AS src", (SRC,))
        for t in TABLES:
            cols = [r["name"] for r in src.execute(f"PRAGMA table_info({t})")]
            dst.execute(f"INSERT INTO {t} ({','.join(cols)}) SELECT {','.join(cols)} FROM src.{t}")
        dst.commit()
        counts = {t: dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        dst.close()
        report[dbname] = counts
    src.close()
    provenance.append("references/drills/rebuild_derived.py",
                      inputs=[SRC], params={"tables": TABLES, "dbs": DBS},
                      version=datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S"))
    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="重建派生回放库（幂等）")
    ap.add_argument("--no-backup", action="store_true", help="覆盖前不备份旧库")
    args = ap.parse_args()
    print(json.dumps(rebuild(backup_old=not args.no_backup), ensure_ascii=False, indent=2))
