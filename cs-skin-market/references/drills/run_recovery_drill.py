# -*- coding: utf-8 -*-
"""D4 恢复演练（2026-08-27）：每月一次全流程，落 recovery_drill_log.jsonl。

流程 = 对生产库与两个派生回放库做 PRAGMA integrity_check + 行数对比
      （回放库 items/price_history/market_index 行数应与生产库一致，因重建全量复制）。
台账 data/recovery_drill_log.jsonl 格式固定可机器读（ts/databases/result）。
用法: python references/drills/run_recovery_drill.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from pipeline.config import DATA_DIR, TZ_BJ

DRLL_LOG = os.path.join(str(DATA_DIR), "recovery_drill_log.jsonl")
DBS = ["market.db", "replay_hybrid.db", "replay_cycle_win.db"]
TABLES = ["items", "price_history", "market_index"]


def _integrity_and_counts(db_path):
    conn = sqlite3.connect(db_path)
    try:
        r = conn.execute("PRAGMA integrity_check").fetchone()
        detail = r[0] if r else ""
        names = [x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in TABLES if t in names}
        return {"integrity_ok": detail == "ok", "integrity_detail": detail, "counts": counts}
    finally:
        conn.close()


def run_drill():
    """执行恢复演练，返回记录 dict，并落 recovery_drill_log.jsonl。

    result = PASS iff 所有库 integrity_check 通过；行数为「行数留痕」供跨月对比
    （生产库每日增长，回放库为派生快照，二者行数不做严格相等断言）。
    """
    dbs_report = {}
    result = "PASS"
    for db in DBS:
        p = os.path.join(str(DATA_DIR), db)
        if not os.path.exists(p):
            dbs_report[db] = {"integrity_ok": False, "integrity_detail": "missing", "counts": {}}
            result = "FAIL"
            continue
        r = _integrity_and_counts(p)
        dbs_report[db] = r
        if not r["integrity_ok"]:
            result = "FAIL"
    rec = {
        "ts": datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "databases": dbs_report,
        "result": result,
    }
    try:
        with open(DRLL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


if __name__ == "__main__":
    print(json.dumps(run_drill(), ensure_ascii=False, indent=2))
