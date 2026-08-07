# -*- coding: utf-8 -*-
"""生产实盘信号跟踪（2026-08-07，C 通道实盘化）。

记录生产 buy 信号（单品分析 / 搜索 / 自选 / 批量扫描），14/30 交易日后按 price_history
真实价格回填收益，使 J-2 C 通道从「370 信号回放近似」升级为「实盘信号验证」。

口径与回放一致：entry = 信号日 chart close；fwd14 = 信号日后第 14 个交易日 close 的涨跌幅；
net = fwd - 2%（双边成本，同 run_item_backtest.py）。表结构见 db.py signal_tracking。
"""
import logging

from . import db

_LOG = logging.getLogger(__name__)

COST_PCT = 2.0  # 双边成本 2%（与回放 net 口径一致）
_BUY_ACTIONS = ("buy", "oversold_buy")


def ensure_schema(conn):
    """建表（独立于 db.get_conn 调用，测试/工具可用内存 DB）。"""
    conn.execute("""CREATE TABLE IF NOT EXISTS signal_tracking (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        item_name TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        action TEXT NOT NULL,
        action_label TEXT NOT NULL,
        entry_price REAL NOT NULL,
        position_limit REAL DEFAULT 0.10,
        source TEXT NOT NULL DEFAULT 'analyze',
        fwd14 REAL,
        fwd30 REAL,
        net14 REAL,
        net30 REAL,
        checked14_at TEXT,
        checked30_at TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE (item_id, signal_date, action_label))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_tracking_date ON signal_tracking(signal_date)")
    conn.commit()


def record_buy_signal(conn, *, item_id, item_name, signal_date, action, action_label,
                      entry_price, position_limit=0.10, source="analyze"):
    """记录一条生产 buy 信号（去重：同 item + 同日 + 同族只记一次）。返回 True 新插入 / False 重复。"""
    if action not in _BUY_ACTIONS:
        return False
    if not item_id or not entry_price or entry_price <= 0:
        return False
    exists = conn.execute(
        "SELECT 1 FROM signal_tracking WHERE item_id=? AND signal_date=? AND action_label=?",
        (item_id, signal_date, action_label)).fetchone()
    if exists:
        return False
    conn.execute(
        "INSERT INTO signal_tracking "
        "(item_id, item_name, signal_date, action, action_label, entry_price, position_limit, source) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (item_id, item_name, signal_date, action, action_label,
         round(float(entry_price), 4), float(position_limit or 0.10), source))
    conn.commit()
    return True


def _fwd_returns(conn, item_id, signal_date, entry_price):
    """信号日后第 14/30 个交易日收益（%）。返回 (fwd14, fwd30)；不足 30 天时 fwd30=None。"""
    rows = conn.execute(
        "SELECT price_rmb FROM price_history WHERE item_id=? AND date > ? AND price_rmb > 0 ORDER BY date",
        (item_id, signal_date)).fetchall()
    prices = [r["price_rmb"] for r in rows]
    if not prices or not entry_price or entry_price <= 0:
        return None, None
    fwd14 = None
    fwd30 = None
    if len(prices) >= 14:
        fwd14 = (prices[13] / entry_price - 1) * 100.0
    if len(prices) >= 30:
        fwd30 = (prices[29] / entry_price - 1) * 100.0
    return fwd14, fwd30


def backfill_signal_tracking(conn):
    """回填已到期信号的真实收益（14/30 交易日后）。返回回填条数。"""
    rows = conn.execute(
        "SELECT id, item_id, signal_date, entry_price FROM signal_tracking "
        "WHERE fwd14 IS NULL OR fwd30 IS NULL").fetchall()
    updated = 0
    for r in rows:
        f14, f30 = _fwd_returns(conn, r["item_id"], r["signal_date"], r["entry_price"])
        if f14 is None and f30 is None:
            continue
        set14 = f14 is not None
        set30 = f30 is not None
        conn.execute(
            "UPDATE signal_tracking SET "
            "fwd14=CASE WHEN ? THEN ? ELSE fwd14 END, "
            "net14=CASE WHEN ? THEN ? ELSE net14 END, "
            "checked14_at=CASE WHEN ? THEN datetime('now','localtime') ELSE checked14_at END, "
            "fwd30=CASE WHEN ? THEN ? ELSE fwd30 END, "
            "net30=CASE WHEN ? THEN ? ELSE net30 END, "
            "checked30_at=CASE WHEN ? THEN datetime('now','localtime') ELSE checked30_at END "
            "WHERE id=?",
            (set14, round(f14, 2) if f14 is not None else None,
             set14, round(f14 - COST_PCT, 2) if f14 is not None else None,
             set14,
             set30, round(f30, 2) if f30 is not None else None,
             set30, round(f30 - COST_PCT, 2) if f30 is not None else None,
             set30, r["id"]))
        updated += 1
    conn.commit()
    return updated


def tracking_summary(conn):
    """实盘跟踪统计（供 J-2 C 通道生产口径展示）。"""
    total = conn.execute("SELECT COUNT(*) n FROM signal_tracking").fetchone()["n"] or 0
    n14 = conn.execute("SELECT COUNT(*) n FROM signal_tracking WHERE fwd14 IS NOT NULL").fetchone()["n"] or 0
    n30 = conn.execute("SELECT COUNT(*) n FROM signal_tracking WHERE fwd30 IS NOT NULL").fetchone()["n"] or 0
    def _stats(field):
        row = conn.execute(
            "SELECT COUNT(*) n, AVG({0}) avg FROM signal_tracking WHERE {0} IS NOT NULL".format(field)).fetchone()
        n = row["n"] or 0
        if n == 0:
            return {"n": 0, "win": None, "avg": None}
        win = conn.execute(
            "SELECT COUNT(*) n FROM signal_tracking WHERE {0} > 0".format(field)).fetchone()["n"] or 0
        return {"n": n, "win": round(100.0 * win / n, 1), "avg": round(row["avg"], 2) if row["avg"] is not None else None}
    earliest_open = conn.execute(
        "SELECT MIN(signal_date) d FROM signal_tracking WHERE fwd14 IS NULL").fetchone()["d"]
    latest = conn.execute("SELECT MAX(signal_date) d FROM signal_tracking").fetchone()["d"]
    return {
        "n_total": total,
        "n_filled14": n14,
        "n_filled30": n30,
        "net14": _stats("net14"),
        "net30": _stats("net30"),
        "earliest_open": earliest_open,
        "latest": latest,
        "note": "生产实盘信号跟踪：buy 信号当日记录，14/30 交易日后按 price_history 真实价格回填（net 扣 2% 双边成本，与回放口径一致）",
    }


def run_backfill_once():
    """每日任务入口：回填 + 返回统计摘要。"""
    conn = db.get_conn()
    try:
        updated = backfill_signal_tracking(conn)
        summary = tracking_summary(conn)
        return {"updated": updated, "summary": summary}
    finally:
        conn.close()