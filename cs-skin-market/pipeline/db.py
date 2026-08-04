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

    conn = sqlite3.connect(str(DB_PATH), timeout=10)

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

    # Migrate: add yyyp_id if missing
    try:
        conn.execute("ALTER TABLE items ADD COLUMN yyyp_id TEXT DEFAULT ''")
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
        in_sale_count INTEGER,

        created_at TEXT DEFAULT (datetime('now','localtime')),

        UNIQUE(item_id, date))""")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_price_history_item_date ON price_history(item_id, date)")


    # 迁移：price_history 增加 in_sale_count 列（幂等，兼容旧库）
    try:
        _cols = [r[1] for r in conn.execute("PRAGMA table_info(price_history)").fetchall()]
        if "in_sale_count" not in _cols:
            conn.execute("ALTER TABLE price_history ADD COLUMN in_sale_count INTEGER")
    except sqlite3.OperationalError:
        pass  # 列已存在/锁定冲突时跳过


    # 迁移：price_history (item_id,date) 唯一化——清重复行(保留最新) + 唯一索引(幂等)

    try:

        _has_uq = conn.execute(

            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_price_history_item_date'"

        ).fetchone()

        if not _has_uq:

            conn.execute(

                "DELETE FROM price_history WHERE id NOT IN "

                "(SELECT MAX(id) FROM price_history GROUP BY item_id, date)"

            )

            conn.execute(

                "CREATE UNIQUE INDEX IF NOT EXISTS uq_price_history_item_date ON price_history(item_id, date)"

            )

            conn.commit()

    except sqlite3.OperationalError:

        pass  # 并发/锁冲突时跳过，下轮启动再迁移

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
        report_html TEXT DEFAULT '',

        created_at TEXT DEFAULT (datetime('now','localtime')))""")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_item_date ON snapshots(item_id, date)")

    # Migrate: add report_html if missing
    try:
        conn.execute("ALTER TABLE snapshots ADD COLUMN report_html TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists

    # Migrate: add action (fusion decision) for 7-day signal clustering
    try:
        conn.execute("ALTER TABLE snapshots ADD COLUMN action TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists

    conn.execute("""CREATE TABLE IF NOT EXISTS macro_history (
        date TEXT PRIMARY KEY,
        greedy_index REAL,
        card_price REAL,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")


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
    # 执行记录(P0-2, 2026-08-04): 按建议执行 + 14/30天自动复盘
    conn.execute("""CREATE TABLE IF NOT EXISTS executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        action TEXT NOT NULL,
        advice_date TEXT NOT NULL,
        advice_signal TEXT,
        exec_price REAL NOT NULL,
        qty INTEGER NOT NULL DEFAULT 1,
        settle_14 REAL,
        settle_30 REAL,
        pnl_14 REAL,
        pnl_30 REAL,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_date ON executions(advice_date)")

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
                stat_trak=0, souvenir=0, notes="", in_watchlist=0, good_id=0, yyyp_id="") -> int:
    cur = conn.execute("SELECT id, in_watchlist FROM items WHERE name = ?", (name,))
    row = cur.fetchone()
    now = _now()
    if row:
        conn.execute("""UPDATE items SET steam_name=?,weapon=?,skin=?,wear=?,rarity=?,
                     source=?,is_discontinued=?,discontinued_years=?,stat_trak=?,
                     souvenir=?,notes=?,in_watchlist=?,good_id=?,yyyp_id=?,updated_at=? WHERE id=?""",
                     (steam_name, weapon, skin, wear, rarity, source, is_discontinued,
                      discontinued_years, stat_trak, souvenir, notes, in_watchlist, good_id, yyyp_id, now, row["id"]))
        return row["id"]
    cur = conn.execute("""INSERT INTO items (name,steam_name,weapon,skin,wear,rarity,
                       source,is_discontinued,discontinued_years,stat_trak,souvenir,notes,in_watchlist,good_id,yyyp_id,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (name, steam_name, weapon, skin, wear, rarity, source, is_discontinued,
                        discontinued_years, stat_trak, souvenir, notes, in_watchlist, good_id, yyyp_id, now, now))
    return cur.lastrowid








def save_price_history_batch(conn, item_id, daily_bars):
    """Save 90-day K-line data (Bar objects) to price_history table.
    daily_bars: list of Bar objects with .date, .close, .volume, .in_sale_count, .survive
    """
    for bar in daily_bars:
        if not bar.date or not bar.close or bar.close <= 0:
            continue
        vol_day = int(bar.volume) if bar.volume else 0
        vol_total = int(bar.survive) if bar.survive else 0
        in_sale = int(bar.in_sale_count) if getattr(bar, "in_sale_count", 0) else 0
        conn.execute(
            "INSERT OR REPLACE INTO price_history (item_id, date, price_rmb, volume_day, volume_total, in_sale_count) VALUES (?,?,?,?,?,?)",
            (item_id, bar.date, round(bar.close, 2), vol_day, vol_total, in_sale)
        )









def save_macro_snapshots(conn, rows):
    """Bulk upsert daily macro snapshots.

    rows: iterable of (date, greedy_index, card_price) tuples; each point carries
    its own date so the full history from the API can be backfilled at once.
    """
    conn.executemany(
        "INSERT OR REPLACE INTO macro_history (date, greedy_index, card_price) VALUES (?,?,?)",
        [tuple(r) for r in rows],
    )



def get_greedy_history(conn, start=None):
    """Return [(date, greedy_index)] ascending; empty until daily collection accumulates."""
    if start:
        rows = conn.execute(
            "SELECT date, greedy_index AS value FROM macro_history WHERE date >= ? AND greedy_index IS NOT NULL ORDER BY date",
            (start,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT date, greedy_index AS value FROM macro_history WHERE greedy_index IS NOT NULL ORDER BY date"
        ).fetchall()
    return [(r["date"], float(r["value"])) for r in rows]
























def get_item_history(conn, item_id, limit=90):

    return conn.execute("SELECT * FROM price_history WHERE item_id=? ORDER BY date DESC LIMIT ?", (item_id, limit)).fetchall()















def find_item(conn, name):

    return conn.execute("SELECT * FROM items WHERE name=?", (name,)).fetchone()





# ---- P2: Position CRUD ----


























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








def set_setting(conn, key, value):

    conn.execute(

        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now','localtime'))",

        (key, value))



def get_setting(conn, key, default=""):

    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()

    return row["value"] if row else default





# ---- Watchlist CRUD ----





def watchlist_list_with_snapshots(conn):
    """Optimized: single JOIN query instead of N+1 per-item queries."""
    return conn.execute("""
        SELECT i.*, s.price_rmb AS latest_price, s.grade AS latest_grade, s.recommendation AS latest_summary
        FROM items i
        LEFT JOIN snapshots s ON s.item_id = i.id
            AND s.date = (SELECT MAX(date) FROM snapshots WHERE item_id = i.id)
        WHERE i.in_watchlist = 1
        ORDER BY i.id DESC
    """).fetchall()






def watchlist_add(conn, name, holding=0, avg_cost=0.0, quantity=0) -> int:
    # 保留已有 good_id/yyyp_id：upsert_item 默认 good_id=0 会覆盖清空，导致后续分析需重新搜索
    existing = conn.execute("SELECT id, good_id, yyyp_id FROM items WHERE name = ?", (name,)).fetchone()
    keep_good_id = existing["good_id"] if existing else 0
    keep_yyyp_id = existing["yyyp_id"] if existing else ""
    item_id = upsert_item(conn, name, in_watchlist=1, good_id=keep_good_id, yyyp_id=keep_yyyp_id)
    if holding:
        conn.execute("UPDATE items SET holding=?, avg_cost=?, quantity=? WHERE id=?", (holding, avg_cost, quantity, item_id))
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






def get_latest_snapshot_report(conn, item_id):

    return conn.execute(

        "SELECT * FROM snapshots WHERE item_id=? ORDER BY date DESC LIMIT 1",

        (item_id,)

    ).fetchone()





# ---- Executions (P0-2, 2026-08-04) ----


def add_execution(conn, item_id, name, action, advice_date, exec_price, qty=1, advice_signal=""):
    """新增执行记录（按建议执行：建仓/补仓/减仓/清仓）。"""
    cur = conn.execute(
        "INSERT INTO executions (item_id, name, action, advice_date, advice_signal, exec_price, qty) "
        "VALUES (?,?,?,?,?,?,?)",
        (item_id, name, action, advice_date, advice_signal, exec_price, qty))
    conn.commit()
    return cur.lastrowid


def list_executions(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM executions ORDER BY id DESC")]


def delete_execution(conn, eid):
    conn.execute("DELETE FROM executions WHERE id=?", (eid,))
    conn.commit()


def settle_execution(conn, eid, settle_14=None, settle_30=None, pnl_14=None, pnl_30=None):
    """回填复盘结果（settle 价格 + 净收益率%，扣 2% 双边成本）。"""
    conn.execute("UPDATE executions SET settle_14=?, settle_30=?, pnl_14=?, pnl_30=? WHERE id=?",
                 (settle_14, settle_30, pnl_14, pnl_30, eid))
    conn.commit()


def closing_price_on(conn, item_id, date_str):
    """≤ date_str 的最近收盘价（用于复盘结算）；无任何历史返回 None。"""
    row = conn.execute(
        "SELECT price_rmb FROM price_history WHERE item_id=? AND date<=? ORDER BY date DESC LIMIT 1",
        (item_id, date_str)).fetchone()
    if row and row["price_rmb"]:
        return row["price_rmb"]
    row = conn.execute("SELECT price_rmb FROM price_history WHERE item_id=? ORDER BY date DESC LIMIT 1",
                       (item_id,)).fetchone()
    return row["price_rmb"] if row else None


# ---- Cleanup ----




