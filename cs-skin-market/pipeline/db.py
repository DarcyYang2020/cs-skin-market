"""

SQLite database for CS skin market data.

v3: Added good_id column for csQAQ primary key reference.

Tables: items, price_history, market_index, snapshots, positions, backtest_results.

"""



import sqlite3

from datetime import datetime, timezone, timedelta



from .config import DB_PATH, DATA_DIR



TZ_BJ = timezone(timedelta(hours=8))





def _now() -> str:

    return datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")





def _today() -> str:

    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")





# 2026-08-06 性能修复：get_conn 每次连接都跑 _init_schema（32 条 DDL），
# 在 WAL 写竞争下每条 execute 可达 ~0.1s，导致分析链（event_risk_coefficient 等）单次连接 ~11s。
# 改为按 DB 路径缓存：同一进程内文件库只初始化一次；:memory: 每连接都是新库，不缓存。
_SCHEMA_INIT_PATHS: set = set()


def get_conn() -> sqlite3.Connection:

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH), timeout=10)

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("PRAGMA foreign_keys=ON")

    key = str(DB_PATH)

    if key not in _SCHEMA_INIT_PATHS:
        _init_schema(conn)
        _SCHEMA_INIT_PATHS.add(key)

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
        holding INTEGER DEFAULT 0,
        avg_cost REAL DEFAULT 0,
        quantity INTEGER DEFAULT 0,
        total_bought REAL DEFAULT 0,

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

    # Migrate: add holding/avg_cost/quantity if missing (??????? webapp ??????
    # 2026-08-05 ??? schema?????/????????)
    for _col, _defn in (("holding", "INTEGER DEFAULT 0"),
                        ("avg_cost", "REAL DEFAULT 0"),
                        ("quantity", "INTEGER DEFAULT 0")):
        try:
            conn.execute("ALTER TABLE items ADD COLUMN %s %s" % (_col, _defn))
        except sqlite3.OperationalError:
            pass  # column already exists

    # Migrate: add total_bought (累计买入金额, 2026-08-05) if missing
    # 语义: 只增不减的累计买入成本(不含卖出); 历史持仓按 avg_cost*quantity 回填(幂等, 只补 0/NULL)
    try:
        conn.execute("ALTER TABLE items ADD COLUMN total_bought REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("UPDATE items SET total_bought = ROUND(avg_cost * quantity, 2) "
                     "WHERE holding = 1 AND quantity > 0 AND (total_bought IS NULL OR total_bought = 0)")
    except sqlite3.OperationalError:
        pass  # ??????????????????????



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
        advice_price REAL,
        exec_price REAL NOT NULL,
        qty INTEGER NOT NULL DEFAULT 1,
        settle_14 REAL,
        settle_30 REAL,
        pnl_14 REAL,
        pnl_30 REAL,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_date ON executions(advice_date)")
    # 滑点统计(2026-08-06): 旧库惰性补 advice_price 列
    _exec_cols = [r[1] for r in conn.execute("PRAGMA table_info(executions)").fetchall()]  # 索引访问兼容无 row_factory 连接
    if "advice_price" not in _exec_cols:
        conn.execute("ALTER TABLE executions ADD COLUMN advice_price REAL")

    # 全市场快照(2026-08-04): 每日 get_page_list 拉全市场价格/在售数快照, 样本扩容
    conn.execute("""CREATE TABLE IF NOT EXISTS market_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        good_id INTEGER NOT NULL,
        name TEXT,
        exterior_localized_name TEXT,
        rarity_localized_name TEXT,
        yyyp_sell_price REAL,
        yyyp_sell_num INTEGER,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(date, good_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_market_snapshot_date ON market_snapshot(date)")

    # 大户集中度日常快照(2026-08-04): /monitor monitor/rank 每日采集顶头大户持有量排行, 筹码分布方向
    conn.execute("""CREATE TABLE IF NOT EXISTS monitor_rank_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        good_id INTEGER NOT NULL,
        rank INTEGER NOT NULL,          -- Top N 序号 1..50
        steam_name TEXT,
        steam_id TEXT,
        num INTEGER,                    -- 持有量
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(date, item_id, rank))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monitor_snapshot_date ON monitor_rank_snapshot(date)")

    # 数据源健康监控 (A1, 2026-08-05): 健康检查结果按日 upsert, 供 Web 展示/告警
    conn.execute("""CREATE TABLE IF NOT EXISTS health_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (status IN ('pass','warn','fail')),
        checks_json TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")

    # 生产实盘信号跟踪（2026-08-07 C 通道实盘化）: buy 信号记录 -> 14/30 交易日后按真实价格回填
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

    # 2026-08-07 修复: _init_schema 全部 DDL 统一提交（此前 236 行迁移块 commit 之后的建表依赖调用方 commit，只读路径会回滚）
    conn.commit()





def upsert_item(conn, name, steam_name="", weapon="", skin="", wear="",
                rarity="", source="", is_discontinued=0, discontinued_years=0,
                stat_trak=0, souvenir=0, notes="", in_watchlist=0, good_id=0, yyyp_id="") -> int:
    # 2026-08-06 复发修复：按精确 name 匹配会漏掉仅差半角/全角空格的变体（USP消音版 vs USP 消音版，
    # 同 good_id 重复条目两次被 health 检出：id=162 已删、id=209 再犯）。
    # 统一在唯一入口归一匹配：命中则复用原行并保留规范名，分析/搜索/自选三条路径一并覆盖。
    cur = conn.execute(
        "SELECT id, in_watchlist FROM items "
        "WHERE REPLACE(REPLACE(name,' ',''),'\u3000','') = ?",
        (name.replace(" ", "").replace("\u3000", ""),))
    row = cur.fetchone()
    if row is None:
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


def add_execution(conn, item_id, name, action, advice_date, exec_price, qty=1, advice_signal="", advice_price=None):
    """新增执行记录（按建议执行：建仓/补仓/减仓/清仓）。"""
    cur = conn.execute(
        "INSERT INTO executions (item_id, name, action, advice_date, advice_signal, advice_price, exec_price, qty) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (item_id, name, action, advice_date, advice_signal, advice_price, exec_price, qty))
    conn.commit()
    return cur.lastrowid


def list_executions(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM executions ORDER BY id DESC")]


def apply_execution_to_position(conn, item_id, action, exec_price, qty):
    """执行记录同步持仓（2026-08-05）：buy/add 加权摊薄均价+累计买入；reduce/sell 减数量。

    纯数据层：不改任何信号/引擎。与 watchlist 编辑口径一致。
    - buy/add: 数量+=qty, 均价=(旧均价*旧数量+成交价*qty)/新数量, total_bought+=成交价*qty, holding=1
    - reduce/sell: 数量-=qty(不为负), 均价/总买入不变; 清仓后 holding=0
    """
    if item_id <= 0 or qty <= 0:
        return None
    row = conn.execute(
        "SELECT holding, avg_cost, quantity, total_bought FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return None
    avg_cost = float(row["avg_cost"] or 0)
    quantity = int(row["quantity"] or 0)
    total_bought = float(row["total_bought"] or 0)
    if action in ("buy", "add"):
        new_qty = quantity + qty
        new_avg = round((avg_cost * quantity + exec_price * qty) / new_qty, 2) if new_qty > 0 else round(exec_price, 2)
        new_total = round(total_bought + exec_price * qty, 2)
        conn.execute("UPDATE items SET holding=1, avg_cost=?, quantity=?, total_bought=?, "
                     "updated_at=datetime('now','localtime') WHERE id=?",
                     (new_avg, new_qty, new_total, item_id))
        ret = {"holding": 1, "quantity": new_qty, "avg_cost": new_avg, "total_bought": new_total}
    elif action in ("reduce", "sell"):
        new_qty = max(0, quantity - qty)
        conn.execute("UPDATE items SET quantity=?, holding=?, "
                     "updated_at=datetime('now','localtime') WHERE id=?",
                     (new_qty, 1 if new_qty > 0 else 0, item_id))
        ret = {"holding": 1 if new_qty > 0 else 0, "quantity": new_qty,
               "avg_cost": avg_cost, "total_bought": total_bought}
    else:
        return None
    conn.commit()
    return ret


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



def save_market_snapshot(conn, date, rows):
    """全市场快照落库（2026-08-04，样本扩容数据积累）。
    rows: list of dict {good_id, name, exterior_localized_name, rarity_localized_name,
                        yyyp_sell_price, yyyp_sell_num}
    同 (date, good_id) 幂等覆盖，重复运行安全。
    """
    conn.executemany(
        """INSERT OR REPLACE INTO market_snapshot
           (date, good_id, name, exterior_localized_name, rarity_localized_name,
            yyyp_sell_price, yyyp_sell_num)
           VALUES (?,?,?,?,?,?,?)""",
        [(date, r["good_id"], r.get("name"), r.get("exterior_localized_name"),
          r.get("rarity_localized_name"), r.get("yyyp_sell_price"), r.get("yyyp_sell_num"))
         for r in rows if r.get("good_id")])
    conn.commit()




def save_monitor_rank_snapshot(conn, date, item_id, good_id, rows):
    """大户集中度快照落库(2026-08-04, P1 数据积累)。
    rows: list of dict {steam_name, steam_id, num} (持有量降序, 已裁剪 Top N)。
    同 (date, good_id, rank) 幂等覆盖, 重复运行安全。
    """
    # 快照语义：先删该 (date, item_id) 全部旧行再插入，避免 Top 数量变少时旧行残留（按 item_id 不按 good_id，防重复品误删）
    conn.execute("DELETE FROM monitor_rank_snapshot WHERE date=? AND item_id=?", (date, item_id))
    conn.executemany(
        """INSERT INTO monitor_rank_snapshot
           (date, item_id, good_id, rank, steam_name, steam_id, num)
           VALUES (?,?,?,?,?,?,?)""",
        [(date, item_id, good_id, i + 1, r.get("steam_name"), r.get("steam_id"), r.get("num"))
         for i, r in enumerate(rows) if r.get("num")])
    conn.commit()
def save_health_check(conn, check_date, status, checks_json):
    """健康检查结果 upsert（A1, 2026-08-05）：按日期每天一条，重复运行覆盖。

    status ∈ pass/warn/fail；checks_json 为检查明细 JSON 字符串
    （[{name, level, detail}]，level ∈ PASS/FAIL）。
    """
    conn.execute(
        """INSERT INTO health_checks (date, status, checks_json)
           VALUES (?,?,?)
           ON CONFLICT(date) DO UPDATE SET
               status=excluded.status,
               checks_json=excluded.checks_json,
               created_at=datetime('now','localtime')""",
        (check_date, status, checks_json))
    conn.commit()


def backfill_price_missing(conn, item_id, rows):
    """仅补缺失日期的历史价格（simple/chartAll 回填用）。

    与 save_price_history_batch 的 INSERT OR REPLACE 不同：不覆盖已有行，
    保护已有 volume_day / in_sale_count（历史回填只写价格）。
    rows: list of (date, price_rmb)
    """
    conn.executemany(
        "INSERT OR IGNORE INTO price_history (item_id, date, price_rmb) VALUES (?,?,?)",
        [(item_id, d, round(float(p), 2)) for d, p in rows if d and p])
    conn.commit()


def item_history_start(conn, item_id):
    """返回单品 price_history 最早日期（无数据返回 None）。"""
    row = conn.execute("SELECT MIN(date) AS d FROM price_history WHERE item_id=?", (item_id,)).fetchone()
    return row["d"] if row and row["d"] else None


# ---- Cleanup ----




