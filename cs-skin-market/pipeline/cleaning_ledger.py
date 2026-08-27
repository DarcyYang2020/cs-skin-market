# -*- coding: utf-8 -*-
"""D3 清洗台账（2026-08-27）：规则配置化触警留痕。

规则阈值单一事实源 = pipeline.config.CLEANING_RULES（禁止在调用处硬编码）。
触警时 append 一行 JSON 到 data/cleaning_ledger.jsonl（键 = ts/rule/item/value/action/detail）；
每日健康检查读本台账当日计数（run_health_monitor 集成）。
"""
import json
import os
from datetime import datetime

from .config import DATA_DIR, TZ_BJ

LEDGER_PATH = os.path.join(str(DATA_DIR), "cleaning_ledger.jsonl")


def append(rule, item=None, value=None, action=None, detail="", ts=None):
    """追加一条清洗触警记录，返回完整记录 dict（含 ts）。"""
    rec = {
        "ts": ts or datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "rule": rule,
        "item": item,
        "value": value,
        "action": action,
        "detail": detail,
    }
    try:
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


def read_since(date_str):
    """读取 ts >= date_str（含）以来的触警记录列表（损坏行跳过）。"""
    out = []
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if (r.get("ts") or "")[:10] >= date_str:
                    out.append(r)
    except FileNotFoundError:
        pass
    return out


def count_since(date_str):
    """某日期以来的触警条数（供健康检查计数）。"""
    return len(read_since(date_str))
