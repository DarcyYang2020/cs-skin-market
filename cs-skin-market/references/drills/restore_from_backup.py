# -*- coding: utf-8 -*-
"""D4 恢复演练脚本（2026-08-27）：从 .bak 恢复 SQLite 到目标路径并校验。

校验 = 备份文件 PRAGMA integrity_check + 恢复后目标库 integrity_check（幂等）。
用法: python references/drills/restore_from_backup.py <bak_path> <target_db>
"""
import os
import shutil
import sqlite3
import sys


def _integrity(db_path):
    conn = sqlite3.connect(db_path)
    try:
        r = conn.execute("PRAGMA integrity_check").fetchone()
        detail = r[0] if r else ""
        return {"ok": detail == "ok", "detail": detail}
    finally:
        conn.close()


def restore(bak_path, target_db):
    """恢复备份到目标库，返回 {ok, integrity, restored_from, target}。"""
    if not os.path.exists(bak_path):
        return {"ok": False, "error": f"备份不存在: {bak_path}"}
    pre = _integrity(bak_path)
    if not pre["ok"]:
        return {"ok": False, "error": "备份文件损坏", "integrity": pre}
    if os.path.exists(target_db):
        shutil.copy2(target_db, target_db + ".pre-restore")
    shutil.copy2(bak_path, target_db)
    post = _integrity(target_db)
    return {"ok": post["ok"], "integrity": post,
            "restored_from": bak_path, "target": target_db}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python restore_from_backup.py <bak_path> <target_db>")
        sys.exit(2)
    res = restore(sys.argv[1], sys.argv[2])
    print("恢复成功" if res.get("ok") else "恢复失败", res.get("integrity", res.get("error")))
    sys.exit(0 if res.get("ok") else 2)
