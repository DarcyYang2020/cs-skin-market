# -*- coding: utf-8 -*-
"""market.db 自动备份：SQLite online backup API（避免运行中文件锁），复制到
data/backup/market_YYYYMMDD_HHMMSS.db，并清理保留份数之外的旧备份。

用法:
    python backup_db.py                 # 默认备份 cs-skin-market/data/market.db, 保留 14 份
    python backup_db.py --keep 7
    python backup_db.py --dry-run       # 只打印将执行的动作

配合 Windows 计划任务（每日一次）使用，见 install_tasks.ps1。
"""
import sys, io, os, sqlite3, shutil, argparse
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
DEFAULT_DB = BASE / "data" / "market.db"
BACKUP_DIR = BASE / "data" / "backup"


def backup(db_path, keep=14, dry_run=False):
    db_path = Path(db_path)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"market_{stamp}.db"
    if not db_path.exists():
        raise FileNotFoundError(f"db not found: {db_path}")
    if dry_run:
        print(f"[dry-run] would backup {db_path.name} -> {dest.name} ({db_path.stat().st_size/1024/1024:.1f} MB)")
    else:
        src_conn = sqlite3.connect(str(db_path))
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)   # online backup, 运行中也可安全复制
        finally:
            dst_conn.close()
            src_conn.close()
        print(f"backup ok: {dest.name} ({dest.stat().st_size/1024/1024:.1f} MB)")
    # 清理旧备份（按修改时间保留最近 keep 份）
    backups = sorted(BACKUP_DIR.glob("market_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        if dry_run:
            print(f"[dry-run] would remove old backup: {old.name}")
        else:
            old.unlink(missing_ok=True)
            print(f"removed old backup: {old.name}")
    print(f"backups kept: {min(len(backups), keep)} (max {keep})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--keep", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    backup(args.db, keep=args.keep, dry_run=args.dry_run)