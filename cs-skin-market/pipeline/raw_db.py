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
    # W7-2 蓄水池（2026-08-27，decision-log EY+EZ，契约 references/w7-2-collect-contract-2026-08-27.md）：
    # steamdt.com 市场级数据（独立第三方站，GET 零鉴权），每日 1 行/多行 append-only。
    # 幂等 = UNIQUE(date) / UNIQUE(date,level,block_name)；合规积累 3-6 月后再评（W7-1 v1c 届时复用）。
    "raw_steamdt_market": """
        CREATE TABLE IF NOT EXISTS raw_steamdt_market (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            date TEXT NOT NULL UNIQUE,
            broad_market_index REAL,
            diff_yesterday REAL,
            diff_yesterday_ratio REAL,
            add_num INTEGER,
            add_valuation REAL,
            trade_num INTEGER,
            turnover REAL,
            add_num_ratio REAL,
            add_amount_ratio REAL,
            trade_volume_ratio REAL,
            trade_amount_ratio REAL,
            survive_num INTEGER,
            holders_num INTEGER,
            online_count INTEGER,
            month_avg_online INTEGER,
            update_time TEXT,
            source TEXT DEFAULT 'steamdt'
        )""",
    "raw_steamdt_blocks": """
        CREATE TABLE IF NOT EXISTS raw_steamdt_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            date TEXT NOT NULL,
            level TEXT NOT NULL,
            block_name TEXT NOT NULL,
            index_value REAL,
            rise_fall_rate REAL,
            rise_fall_diff REAL,
            source TEXT DEFAULT 'steamdt',
            UNIQUE(date, level, block_name)
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
