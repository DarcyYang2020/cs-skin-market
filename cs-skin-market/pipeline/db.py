"""
SQLite database for CS skin market data.
v3: Added good_id column for csQAQ primary key reference.
Tables: items, price_history, market_index, snapshots, positions, backtest_results.
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import DB_PATH, DATA_DIR

TZ_BJ = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        good_id INTEGER DEFAULT 0,
        name TEXT NOT NULL,
        in_watchlist INTEGER DEFAULT 0,
        steam_name TEXT,
        weapon TEXT,
        skin TEXT,
        wear TEXT,
        rarity TEXT,
        source TEXT,
        is_discontinued INTEGER DEFAULT 0,
        discontinued_years REAL DEFAULT 0,
        stat_trak INTEGER DEFAULT 0,
        souvenir INTEGER DEFAULT 0,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')))""")
    # Migrate: add good_id if missing
    try:
        conn.execute("ALTER TABLE items ADD COLUMN good_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists

    conn.execute("""CREATE TABLE IF NOT EXISTS market_index (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL UNIQUE,
        value REAL,
        change_7d REAL,
        mood TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")

    conn.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        date TEXT NOT NULL,
        price_rmb REAL,
        volume_day INTEGER,
        volume_total INTEGER,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_price_history_item_date ON price_history(item_id, date)")
    conn.execute("""CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        date TEXT NOT NULL,
        score_scarcity REAL,
        score_volume REAL,
        score_market REAL,
        score_liquidity REAL DEFAULT 0,
        total_score REAL,
        grade TEXT,
        recommendation TEXT,
        price_rmb REAL,
        report_md TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_item_date ON snapshots(item_id, date)")
    conn.execute("""CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        buy_date TEXT NOT NULL,
        buy_price REAL NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        notes TEXT,
        closed INTEGER DEFAULT 0,
        close_date TEXT,
        close_price REAL,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_item ON positions(item_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS backtest_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy TEXT NOT NULL,
        item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        initial_capital REAL NOT NULL,
        final_value REAL,
        total_return_pct REAL,
        annualized_return_pct REAL,
        max_drawdown_pct REAL,
        sharpe_ratio REAL,
        win_rate_pct REAL,
        total_trades INTEGER DEFAULT 0,
        winning_trades INTEGER DEFAULT 0,
        metrics_json TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")


def upsert_item(conn, name, steam_name="", weapon="", skin="", wear="",
                rarity="", source="", is_discontinued=0, discontinued_years=0,
                stat_trak=0, souvenir=0, notes="", in_watchlist=0, good_id=0) -> int:
    cur = conn.execute("SELECT id, in_watchlist FROM items WHERE name = ?", (name,))
    row = cur.fetchone()
    now = _now()
    if row:
        conn.execute("""UPDATE items SET steam_name=?,weapon=?,skin=?,wear=?,rarity=?,
                     source=?,is_discontinued=?,discontinued_years=?,stat_trak=?,
                     souvenir=?,notes=?,in_watchlist=?,good_id=?,updated_at=? WHERE id=?""",
                     (steam_name, weapon, skin, wear, rarity, source, is_discontinued,
                      discontinued_years, stat_trak, souvenir, notes, in_watchlist, good_id, now, row["id"]))
        return row["id"]
    cur = conn.execute("""INSERT INTO items (name,steam_name,weapon,skin,wear,rarity,
                       source,is_discontinued,discontinued_years,stat_trak,souvenir,notes,in_watchlist,good_id,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (name, steam_name, weapon, skin, wear, rarity, source, is_discontinued,
                        discontinued_years, stat_trak, souvenir, notes, in_watchlist, good_id, now, now))
    return cur.lastrowid


def save_price(conn, item_id, price_rmb, volume_day=0, volume_total=0):
    conn.execute("INSERT OR REPLACE INTO price_history (item_id,date,price_rmb,volume_day,volume_total) VALUES (?,?,?,?,?)",
                 (item_id, _today(), price_rmb, volume_day, volume_total))


def save_market_index(conn, value, change_7d, mood=""):
    conn.execute("INSERT OR REPLACE INTO market_index (date,value,change_7d,mood) VALUES (?,?,?,?)",
                 (_today(), value, change_7d, mood))


def save_snapshot(conn, item_id, score_scarcity, score_volume, score_market, score_liquidity=0, total_score=0, grade="", recommendation="", price_rmb=0, report_md="") -> int:
    cur = conn.execute("""INSERT INTO snapshots (item_id,date,score_scarcity,score_volume,score_market,score_liquidity,total_score,grade,recommendation,price_rmb,report_md)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (item_id, _now(), score_scarcity, score_volume, score_market, score_liquidity, total_score, grade, recommendation, price_rmb, report_md))
    return cur.lastrowid


def upsert_snapshot(conn, item_id, price_rmb=0, total_score=0, grade="", report_md="", report_html=""):
    conn.execute("DELETE FROM snapshots WHERE item_id=?", (item_id,))
    cur = conn.execute(
        "INSERT INTO snapshots (item_id,date,score_scarcity,score_volume,score_market,score_liquidity,total_score,grade,recommendation,price_rmb,report_md,report_html) VALUES (?,?,0,0,0,0,?,?,?,?,?,?)",
        (item_id, _now(), total_score, grade, "", price_rmb, report_md, report_html))
    return cur.lastrowid


def get_latest_market_index(conn):
    return conn.execute("SELECT * FROM market_index ORDER BY date DESC LIMIT 1").fetchone()


def get_market_index_history(conn, limit=90):
    rows = conn.execute(
        "SELECT date, value FROM market_index ORDER BY date ASC LIMIT ?", (limit,)
    ).fetchall()
    return [(r["date"], r["value"]) for r in rows]


def get_item_history(conn, item_id, limit=90):
    return conn.execute("SELECT * FROM price_history WHERE item_id=? ORDER BY date DESC LIMIT ?", (item_id, limit)).fetchall()


def get_item_snapshots(conn, item_id, limit=30):
    return conn.execute("SELECT * FROM snapshots WHERE item_id=? ORDER BY date DESC LIMIT ?", (item_id, limit)).fetchall()


def list_items(conn):
    return conn.execute("SELECT * FROM items ORDER BY updated_at DESC").fetchall()


def find_item(conn, name):
    return conn.execute("SELECT * FROM items WHERE name=?", (name,)).fetchone()


# ---- P2: Position CRUD ----

def add_position(conn, item_id, buy_date, buy_price, quantity=1, notes=""):
    cur = conn.execute("INSERT INTO positions (item_id,buy_date,buy_price,quantity,notes) VALUES (?,?,?,?,?)",
                       (item_id, buy_date, buy_price, quantity, notes))
    return cur.lastrowid


def close_position(conn, position_id, close_price, close_date=None):
    close_date = close_date or _today()
    conn.execute("UPDATE positions SET closed=1, close_date=?, close_price=? WHERE id=?", (close_date, close_price, position_id))


def get_open_positions(conn):
    return conn.execute("SELECT * FROM positions WHERE closed=0 ORDER BY buy_date ASC").fetchall()


def get_all_positions(conn):
    return conn.execute("""SELECT p.*, i.name FROM positions p
        LEFT JOIN items i ON p.item_id = i.id ORDER BY p.buy_date DESC""").fetchall()


def get_position_pnl(conn, position_id):
    row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    if not row:
        return {}
    item = conn.execute("SELECT name FROM items WHERE id=?", (row["item_id"],)).fetchone()
    return {
        "id": row["id"], "item_name": item["name"] if item else "?",
        "buy_price": row["buy_price"], "quantity": row["quantity"],
        "close_price": row["close_price"], "closed": bool(row["closed"]),
        "buy_date": row["buy_date"], "close_date": row["close_date"],
    }


# ---- Backtest ----

def save_backtest(conn, strategy, item_id, start_date, end_date, initial_capital,
                  final_value, total_return_pct, annualized_return_pct,
                  max_drawdown_pct, sharpe_ratio, win_rate_pct,
                  total_trades, winning_trades, metrics_json=""):
    cur = conn.execute("""INSERT INTO backtest_results (strategy,item_id,start_date,end_date,initial_capital,
        final_value,total_return_pct,annualized_return_pct,max_drawdown_pct,sharpe_ratio,
        win_rate_pct,total_trades,winning_trades,metrics_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (strategy, item_id, start_date, end_date, initial_capital, final_value,
         total_return_pct, annualized_return_pct, max_drawdown_pct, sharpe_ratio,
         win_rate_pct, total_trades, winning_trades, metrics_json))
    return cur.lastrowid


def get_backtest_by_item(conn, item_id, limit=5):
    return conn.execute("""SELECT * FROM backtest_results WHERE item_id=?
        ORDER BY created_at DESC LIMIT ?""", (item_id, limit)).fetchall()




# ---- Settings key-value store ----

def set_setting(conn, key, value):
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now','localtime'))",
        (key, value))

def get_setting(conn, key, default=""):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


# ---- Watchlist CRUD ----

def watchlist_list(conn):
    return conn.execute(
        "SELECT * FROM items WHERE in_watchlist=1 ORDER BY name"
    ).fetchall()

def watchlist_add(conn, name) -> int:
    item_id = upsert_item(conn, name, in_watchlist=1)
    return item_id

def watchlist_update(conn, name, **kwargs):
    item = find_item(conn, name)
    if not item:
        return
    valid = {"rarity", "source", "is_discontinued", "discontinued_years", "notes",
             "stat_trak", "souvenir", "holding", "avg_cost", "quantity", "good_id"}
    for k, v in kwargs.items():
        if k in valid and v is not None:
            conn.execute(f"UPDATE items SET {k}=?, updated_at=datetime('now','localtime') WHERE id=?",
                         (v, item["id"]))

def watchlist_remove(conn, name):
    conn.execute("UPDATE items SET in_watchlist=0 WHERE name=?", (name,))

def get_watchlist_holdings_total(conn):
    row = conn.execute(
        "SELECT SUM(holding) as total FROM items WHERE in_watchlist=1"
    ).fetchone()
    return (row["total"] or 0) if row else 0


# ---- Snapshot helpers ----

def get_latest_snapshot_report(conn, item_id):
    return conn.execute(
        "SELECT * FROM snapshots WHERE item_id=? ORDER BY date DESC LIMIT 1",
        (item_id,)
    ).fetchone()


# ---- Cleanup ----

def cleanup_old_data(conn, retention_days=90):
    from datetime import timedelta
    cutoff = (datetime.now(TZ_BJ) - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    conn.execute("DELETE FROM price_history WHERE date < ?", (cutoff,))
    conn.execute("DELETE FROM market_index WHERE date < ?", (cutoff,))
    conn.execute("DELETE FROM snapshots WHERE date < ?", (cutoff,))
    # Clean old debug files (7 days)
    cutoff_debug = (datetime.now(TZ_BJ) - timedelta(days=7)).strftime("%Y-%m-%d")
    import glob, os
    for f in glob.glob(str(DATA_DIR / "_debug_*")):
        if os.path.getmtime(f) < (datetime.now(TZ_BJ) - timedelta(days=7)).timestamp():
            os.remove(f)
    conn.execute("VACUUM")
