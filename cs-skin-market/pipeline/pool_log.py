# -*- coding: utf-8 -*-
"""池维护台账（F-3.2, 2026-08-08）——260 品完整链路留痕，一行一条 JSON。

- type=daily:    每日采集收尾（pool_size/active_pool/pruned/kline_ok/new_items/health）
- type=prune:    prune_inactive 淘汰执行（marked/阈值）
- type=discover: discover 扩池扫描完成（candidates/ok/error/skipped/pool_size_now）

台账文件: data/pool_maintenance_log.jsonl（追加写，无清理——历史可追溯）
"""
import json
import os
from datetime import datetime, timedelta, timezone

TZ_BJ = timezone(timedelta(hours=8))
POOL_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "pool_maintenance_log.jsonl",
)


def append_pool_log(entry: dict) -> None:
    """追加一行台账；写入失败静默（不中断采集主流程）。"""
    entry.setdefault("ts", datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S"))
    try:
        with open(POOL_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
