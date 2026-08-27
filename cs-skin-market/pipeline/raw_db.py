# -*- coding: utf-8 -*-
"""D7 原始层 raw.db（2026-08-27）：高价值数据 append-only 独立层。

订单簿 / 成交 / 存世量原始值落 raw.db（仅 INSERT 追加，不可变原始留痕）；
加工层 market.db 仍为权威。本层仅作不可变原始留痕 + 未来重建源。
git 不跟踪（*.db 已在 .gitignore）；备份 = 双副本（随每日 backup_db 走同一策略）。
"""
import os
import sqlite3

from .config import DATA_DIR

RAW_DB_PATH = os.path.join(str(DATA_DIR), "raw.db")

_SCHEMA = {
    "raw_order_book": """
        CREATE TABLE IF NOT EXISTS raw_order_book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            date TEXT NOT NULL,
            good_id INTEGER NOT NULL,
            item_name TEXT,
            lowest_sell REAL,
            highest_buy REAL,
            sell_count INTEGER,
            buy_count INTEGER,
            source TEXT DEFAULT 'csqaq_direct',
            platform INTEGER DEFAULT 2
        )""",
    "raw_trade": """
        CREATE TABLE IF NOT EXISTS raw_trade (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            date TEXT NOT NULL,
            good_id INTEGER NOT NULL,
            item_name TEXT,
            turnover_number INTEGER,
            turnover_avg_price REAL,
            source TEXT DEFAULT 'csqaq_direct',
            platform INTEGER DEFAULT 2
        )""",
    "raw_survive": """
        CREATE TABLE IF NOT EXISTS raw_survive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            date TEXT NOT NULL,
            good_id INTEGER NOT NULL,
            item_name TEXT,
            statistic INTEGER,
            source TEXT DEFAULT 'csqaq_direct',
            platform INTEGER DEFAULT 2
        )""",
}


def get_raw_conn():
    """打开 raw.db 并幂等建表（append-only 层，无任何变更路径）。"""
    conn = sqlite3.connect(RAW_DB_PATH, timeout=10)
    for ddl in _SCHEMA.values():
        conn.execute(ddl)
    conn.commit()
    return conn


def append_raw(conn, table, fields):
    """append-only 写入：仅 INSERT 追加，不存在变更/删除路径。"""
    if table not in _SCHEMA:
        raise ValueError(f"raw 表不存在: {table}")
    cols = list(fields.keys())
    conn.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [fields[c] for c in cols])
    return fields
