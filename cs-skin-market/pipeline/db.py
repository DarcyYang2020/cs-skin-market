"""

SQLite database for CS skin market data.

v3: Added good_id column for csQAQ primary key reference.

Tables: items, price_history, market_index, snapshots, positions, backtest_results.

"""


import json
import sqlite3
import time

from datetime import datetime, timedelta


from .config import DB_PATH, DATA_DIR, TZ_BJ


SCHEMA_VERSION = 4  # v58 P1：新增 survive_history / series_snapshot 研究层表


def _now() -> str:

    return datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:

    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")


SUPPLY_GAP_START = "2026-02-01"  # historical known-gap window; no longer used for missing classification after 2026-08-15 backfill
SUPPLY_GAP_END = "2026-04-30"


def supply_depth_missing(raw_value, date_str=None):
    """Return True only when raw in_sale_count is absent (NULL/None).

    2026-08-15: 2026-02-01~04-30 was backfilled from csQAQ period=1095, so
    date-in-gap alone is no longer treated as missing. True zero remains a
    real zero, not missing.
    """
    return raw_value is None


def latest_supply_missing(daily_bars):
    """Latest bar missing-depth flag for engine callers.

    Bars can carry `in_sale_missing` and/or `_in_sale_raw`; fallbacks preserve old behavior
    for callers that only provide numeric in_sale_count (unknown 0 stays non-missing).
    """
    if not daily_bars:
        return True
    bar = daily_bars[-1]
    if getattr(bar, "in_sale_missing", False):
        return True
    raw = getattr(bar, "_in_sale_raw", None)
    if raw is None and not hasattr(bar, "_in_sale_raw"):
        raw = getattr(bar, "in_sale_count", None)
    return supply_depth_missing(raw, getattr(bar, "date", ""))


# 2026-08-06 性能修复：get_conn 每次连接都跑 _init_schema（32 条 DDL），
# 在 WAL 写竞争下每条 execute 可达 ~0.1s，导致分析链（event_risk_coefficient 等）单次连接 ~11s。
# 改为按 DB 路径缓存：同一进程内文件库只初始化一次；:memory: 每连接都是新库，不缓存。
_SCHEMA_INIT_PATHS: set = set()


_BID_OBSERVATIONS_SCHEMA = """CREATE TABLE IF NOT EXISTS bid_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    item_id INTEGER,
    good_id INTEGER NOT NULL,
    item_name TEXT,
    price_rmb REAL,
    in_sale_count INTEGER,
    bid_highest REAL,
    bid_7d_chg REAL,
    bid_30d_chg REAL,
    spread_pct REAL,
    spread_avg REAL,
    quality_note TEXT,
    source TEXT DEFAULT 'weekly',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(date, good_id))"""


def _migrate_bid_observations_fk(conn):
    """One-time migration away from item_id ON DELETE CASCADE.

    items.id is not stable across pool reindex/delete operations.  A cascade
    foreign key would silently wipe accumulated bid/spread research samples,
    which is the same failure mode previously hit by signal_tracking.
    """
    try:
        fks = conn.execute("PRAGMA foreign_key_list(bid_observations)").fetchall()
    except sqlite3.OperationalError:
        return
    has_cascade = any(r[3] == "item_id" and str(r[6] or "").upper() == "CASCADE" for r in fks)
    if not has_cascade:
        return
    old_cols = [r[1] for r in conn.execute("PRAGMA table_info(bid_observations)").fetchall()]
    desired = ["date", "item_id", "good_id", "item_name", "price_rmb", "in_sale_count",
               "bid_highest", "bid_7d_chg", "bid_30d_chg", "spread_pct", "spread_avg",
               "quality_note", "source", "created_at"]
    copy_cols = [c for c in desired if c in old_cols]
    col_list = ", ".join(copy_cols)
    conn.execute("SAVEPOINT bid_obs_migrate")
    try:
        conn.execute("DROP INDEX IF EXISTS idx_bid_observations_date")
        conn.execute("ALTER TABLE bid_observations RENAME TO bid_observations_old_fk")
        conn.execute(_BID_OBSERVATIONS_SCHEMA)
        conn.execute(f"INSERT INTO bid_observations ({col_list}) SELECT {col_list} FROM bid_observations_old_fk")
        conn.execute("DROP TABLE bid_observations_old_fk")
        conn.execute("RELEASE bid_obs_migrate")
    except Exception:
        conn.execute("ROLLBACK TO bid_obs_migrate")
        conn.execute("RELEASE bid_obs_migrate")


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

        weapon TEXT,

        skin TEXT,

        wear TEXT,

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

    # Migrate: add holding/avg_cost/quantity if missing
    for _col, _defn in (("holding", "INTEGER DEFAULT 0"),
                        ("avg_cost", "REAL DEFAULT 0"),
                        ("quantity", "INTEGER DEFAULT 0")):
        try:
            conn.execute("ALTER TABLE items ADD COLUMN %s %s" % (_col, _defn))
        except sqlite3.OperationalError:
            pass  # column already exists

    # Migrate: add total_bought (cumulative buy cost, 2026-08-05) if missing
    try:
        conn.execute("ALTER TABLE items ADD COLUMN total_bought REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("UPDATE items SET total_bought = ROUND(avg_cost * quantity, 2) "
                     "WHERE holding = 1 AND quantity > 0 AND (total_bought IS NULL OR total_bought = 0)")
    except sqlite3.OperationalError:
        pass  # concurrent lock / missing column

    # 2026-08-09 data cleanup: items.steam_name/rarity always empty, never consumed (analysis uses fresh item_meta); drop columns
    for _drop_col in ("steam_name", "rarity"):
        try:
            _cols_now = [r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()]
            if _drop_col in _cols_now:
                conn.execute("ALTER TABLE items DROP COLUMN " + _drop_col)
        except sqlite3.OperationalError:
            pass  # column missing / lock conflict

    # 2026-08-09 data cleanup: settings dead keys (pre-devolume volume caches uu_vol_*/stdt_vol_* + unread cached_*)
    # settings table created later; new DB has no table yet -> guard
    try:
        conn.execute("DELETE FROM settings WHERE key LIKE 'uu_vol_%' OR key LIKE 'stdt_vol_%' "
                     "OR key IN ('cached_index_analysis', 'cached_sectors', 'cached_sub_indices')")
    except sqlite3.OperationalError:
        pass  # fresh DB: settings table not created yet

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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(date)")

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

    # 去重优先级感知（2026-08-16 v2-T11）：快照持久化 action_label，供 7 日去重按族优先级过滤
    try:
        conn.execute("ALTER TABLE snapshots ADD COLUMN action_label TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists

    # Migrate: 求购(bid/order_book)字段持久化（2026-08-08 数据储备，供后续版本迭代验证求购因子；决策零改动）
    for _bid_col in ("bid_highest REAL", "bid_7d_chg REAL", "bid_30d_chg REAL",
                     "spread_pct REAL", "spread_avg REAL"):
        try:
            conn.execute("ALTER TABLE snapshots ADD COLUMN " + _bid_col)
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.execute("""CREATE TABLE IF NOT EXISTS macro_history (
        date TEXT PRIMARY KEY,
        greedy_index REAL,
        card_price REAL,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")


    # H-2（2026-08-10）：positions 表为历史遗留（仅建表无读写，库内 1 行），保留不删以免 schema 变更风险
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
        prev_holding INTEGER,
        prev_quantity INTEGER,
        prev_avg_cost REAL,
        prev_total_bought REAL,
        source TEXT DEFAULT 'manual',   -- D-3（2026-08-10）执行来源: manual / push:{push_id}，供推送→执行归因
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_date ON executions(advice_date)")
    # 滑点统计(2026-08-06): 旧库惰性补 advice_price 列
    _exec_cols = [r[1] for r in conn.execute("PRAGMA table_info(executions)").fetchall()]  # 索引访问兼容无 row_factory 连接
    if "source" not in _exec_cols:
        conn.execute("ALTER TABLE executions ADD COLUMN source TEXT DEFAULT 'manual'")  # D-3（2026-08-10）推送→执行归因
    if "advice_price" not in _exec_cols:
        conn.execute("ALTER TABLE executions ADD COLUMN advice_price REAL")

    # 2026-08-09 执行记录编辑/回滚: 每条记录存操作前持仓快照(prev_*), 删除/编辑后从此状态分段重放
    for _pc in ("prev_holding INTEGER", "prev_quantity INTEGER", "prev_avg_cost REAL", "prev_total_bought REAL"):
        try:
            conn.execute("ALTER TABLE executions ADD COLUMN " + _pc)
        except sqlite3.OperationalError:
            pass  # column already exists
    # 旧记录回填 prev: 按 (item_id, id) 降序从当前持仓逆向重放（2026-08-09 前无快照）
    # 逆向保证 prev 与物品实际持仓一致，兼容「手动设置持仓后再记账」的存量数据
    try:
        _old_items = conn.execute(
            "SELECT DISTINCT item_id FROM executions WHERE prev_quantity IS NULL AND item_id > 0").fetchall()
        for _it in _old_items:
            _iid = _it[0]
            _row = conn.execute(
                "SELECT holding, avg_cost, quantity, total_bought FROM items WHERE id=?", (_iid,)).fetchone()
            if not _row:
                continue
            _h, _q, _a, _t = (int(_row["holding"] or 0), int(_row["quantity"] or 0),
                              float(_row["avg_cost"] or 0), float(_row["total_bought"] or 0))
            _olds = conn.execute(
                "SELECT id, action, exec_price, qty FROM executions "
                "WHERE item_id=? AND prev_quantity IS NULL ORDER BY id DESC", (_iid,)).fetchall()
            for _r in _olds:
                _qty = int(_r["qty"] or 0)
                _price = float(_r["exec_price"] or 0)
                if _r["action"] in ("buy", "add"):
                    _q = max(0, _q - _qty)
                    _t = max(0.0, _t - _price * _qty)
                    _a = round(_t / _q, 2) if _q > 0 else 0.0
                    _h = 1 if _q > 0 else 0
                elif _r["action"] in ("reduce", "sell"):
                    _q = _q + _qty
                    _h = 1 if _q > 0 else 0
                conn.execute("UPDATE executions SET prev_holding=?, prev_quantity=?, prev_avg_cost=?, prev_total_bought=? WHERE id=?",
                             (_h, _q, _a, _t, _r["id"]))
    except sqlite3.OperationalError:
        pass  # 新库无旧记录/并发锁冲突

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
    # 2026-08-13 B-2: 三张表的唯一约束已自带前缀索引，删除冗余普通索引以降低写入与存储开销。
    for _redundant_idx in ("idx_price_history_item_date", "idx_market_snapshot_date", "idx_monitor_snapshot_date"):
        try:
            conn.execute(f"DROP INDEX IF EXISTS {_redundant_idx}")
        except sqlite3.OperationalError:
            pass

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
        engine_version TEXT,
        fwd14 REAL,
        fwd30 REAL,
        net14 REAL,
        net30 REAL,
        checked14_at TEXT,
        checked30_at TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE (item_id, signal_date, action_label))""")
    # Migrate: add engine_version if missing (Phase 0 版本化: 记录信号时的引擎参数版本)
    try:
        conn.execute("ALTER TABLE signal_tracking ADD COLUMN engine_version TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    # 第一批（2026-08-16）：特征快照列（与 pipeline/signal_tracking.py FEATURE_COLUMNS 同源，幂等补列）
    for _col, _typ in (("family", "TEXT"), ("pct", "REAL"), ("z", "REAL"), ("sc30", "REAL"),
                       ("s7_ratio", "REAL"), ("bid_price", "REAL"), ("spread_pct", "REAL"),
                       ("sentiment", "REAL"), ("market_th", "REAL"), ("mkt_chg180", "REAL")):
        try:
            conn.execute("ALTER TABLE signal_tracking ADD COLUMN %s %s" % (_col, _typ))
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_tracking_date ON signal_tracking(signal_date)")
    # 2026-08-13 B-5: separate read-only bid observation accumulator (weekly manual/scheduled probe).
    # Does not feed snapshots or the engine; keeps bid/spread samples bounded independently.
    # No FK/cascade on item_id: items.id can change, so preserve good_id/item_name instead.
    conn.execute(_BID_OBSERVATIONS_SCHEMA)
    _migrate_bid_observations_fk(conn)
    for _bid_obs_col in ("price_rmb REAL", "in_sale_count INTEGER", "quality_note TEXT"):
        try:
            conn.execute("ALTER TABLE bid_observations ADD COLUMN " + _bid_obs_col)
        except sqlite3.OperationalError:
            pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bid_observations_date ON bid_observations(date)")

    # v58 P0（2026-08-13）：直连 API 数据储备，研究层独立表。
    # 不设 item_id 外键/级联，避免 items 重排时历史研究样本被误删；good_id 作为稳定键。
    conn.execute("""CREATE TABLE IF NOT EXISTS item_fundamental_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        item_id INTEGER,
        good_id INTEGER NOT NULL,
        item_name TEXT,
        source TEXT NOT NULL DEFAULT 'csqaq_direct',
        platform INTEGER NOT NULL DEFAULT 2,
        yyyp_sell_price REAL,
        yyyp_sell_num INTEGER,
        yyyp_buy_price REAL,
        yyyp_buy_num INTEGER,
        buff_sell_price REAL,
        buff_sell_num INTEGER,
        buff_buy_price REAL,
        buff_buy_num INTEGER,
        c5_sell_price REAL,
        c5_sell_num INTEGER,
        steam_sell_price REAL,
        steam_buy_price REAL,
        turnover_number INTEGER,
        turnover_avg_price REAL,
        sell_price_rate_1 REAL,
        sell_price_rate_7 REAL,
        sell_price_rate_15 REAL,
        sell_price_rate_30 REAL,
        sell_price_rate_90 REAL,
        sell_price_rate_180 REAL,
        sell_price_rate_365 REAL,
        rank_num INTEGER,
        statistic INTEGER,
        rarity_localized_name TEXT,
        type_localized_name TEXT,
        exterior_localized_name TEXT,
        quality_localized_name TEXT,
        min_float REAL,
        max_float REAL,
        extra_json TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(date, good_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_fundamental_date ON item_fundamental_snapshot(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_fundamental_good ON item_fundamental_snapshot(good_id)")

    conn.execute("""CREATE TABLE IF NOT EXISTS bid_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        item_id INTEGER,
        good_id INTEGER NOT NULL,
        item_name TEXT,
        source TEXT NOT NULL DEFAULT 'csqaq_direct',
        platform INTEGER NOT NULL DEFAULT 2,
        buy_price_last REAL,
        buy_price_min REAL,
        buy_price_max REAL,
        buy_price_mean REAL,
        buy_num_last REAL,
        buy_num_min REAL,
        buy_num_max REAL,
        buy_num_mean REAL,
        point_count INTEGER,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(date, good_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bid_history_date ON bid_history(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bid_history_good ON bid_history(good_id)")

    # v58 P1（2026-08-13）：存世量历史 / 系列面板，研究层独立表。
    # 同样不设 item_id 外键/级联；good_id / series_id 为稳定键。
    conn.execute("""CREATE TABLE IF NOT EXISTS survive_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        item_id INTEGER,
        good_id INTEGER NOT NULL,
        item_name TEXT,
        source TEXT NOT NULL DEFAULT 'csqaq_direct',
        platform INTEGER NOT NULL DEFAULT 2,
        statistic INTEGER,
        source_created_at TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(date, good_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_survive_history_date ON survive_history(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_survive_history_good ON survive_history(good_id)")

    conn.execute("""CREATE TABLE IF NOT EXISTS series_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        series_id INTEGER NOT NULL,
        series_key INTEGER,
        series_name TEXT,
        source TEXT NOT NULL DEFAULT 'csqaq_direct',
        amount REAL,
        total_value REAL,
        sell_price_1 REAL,
        sell_price_7 REAL,
        sell_price_15 REAL,
        sell_price_30 REAL,
        sell_price_90 REAL,
        sell_price_180 REAL,
        recently_data_json TEXT,
        extra_json TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(date, series_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_series_snapshot_date ON series_snapshot(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_series_snapshot_series ON series_snapshot(series_id)")

    # ???????????/???????? name ???2026-08-09 P1.2 ????????????? /api/analysis/results 500?
    conn.execute("""CREATE TABLE IF NOT EXISTS analysis_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price_rmb REAL,
        grade TEXT,
        trend_dir TEXT,
        trend_score REAL,
        report_html TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")

    # M1 监控模式 (2026-08-08): 每日自选品异动事件归档(纯提醒层, 只读引擎输出)
    conn.execute("""CREATE TABLE IF NOT EXISTS monitor_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        item_id INTEGER,
        item_name TEXT,
        event_type TEXT NOT NULL,   -- near_buy/stop_loss/decision_flip/supply_shift/price_spike/market_state/exec_due/new_buy_signal
        level TEXT NOT NULL,        -- info/warn/danger
        detail TEXT NOT NULL,
        dedup_key TEXT NOT NULL UNIQUE,   -- date|item_id|event_type (大盘状态事件 item_id 为空)
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monitor_events_date ON monitor_events(date)")

    # 废弃: backtest_results 仅旧组合回测写入(run_portfolio_backtest.py 已归档 scripts-archive), 引擎不再消费; 表结构保留兼容历史库
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
    # ---- Phase 4: schema 版本化 ----
    # schema_version 表记录当前 schema 版本；当前无存量迁移，版本落后时直接升到 SCHEMA_VERSION。
    # 既有 CREATE IF NOT EXISTS / ALTER try-except 保持幂等，不在此重构，避免破坏旧库。
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        version INTEGER NOT NULL,
        applied_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("INSERT OR REPLACE INTO schema_version (id, version, applied_at) "
                 "VALUES (1, ?, datetime('now','localtime'))", (SCHEMA_VERSION,))
    conn.commit()


def upsert_item(conn, name, weapon="", skin="", wear="",
                source="", is_discontinued=0, discontinued_years=0,
                stat_trak=0, souvenir=0, notes="", in_watchlist=None, good_id=0, yyyp_id="") -> int:
    # 2026-08-06 复发修复：按精确 name 匹配会漏掉仅差半角/全角空格的变体（USP消音版 vs USP 消音版，
    # 同 good_id 重复条目两次被 health 检出：id=162 已删、id=209 再犯）。
    # 统一在唯一入口归一匹配：命中则复用原行并保留规范名，分析/搜索/自选三条路径一并覆盖。
    # 2026-08-09 方案A：in_watchlist=None（默认）不改变关注状态——新建=0、已存在=保留原值；
    # 显式传 1/0 才设置/取消关注，分析、扫描类路径传 None 避免误加/误删自选。
    cur = conn.execute(
        "SELECT id, in_watchlist FROM items "
        "WHERE REPLACE(REPLACE(name,' ',''),'\u3000','') = ?",
        (name.replace(" ", "").replace("\u3000", ""),))
    row = cur.fetchone()
    if row is None:
        cur = conn.execute("SELECT id, in_watchlist FROM items WHERE name = ?", (name,))
        row = cur.fetchone()
    wl = in_watchlist if in_watchlist is not None else (int(row["in_watchlist"] or 0) if row else 0)
    now = _now()
    if row:
        conn.execute("""UPDATE items SET weapon=?,skin=?,wear=?,
                     source=?,is_discontinued=?,discontinued_years=?,stat_trak=?,
                     souvenir=?,notes=?,in_watchlist=?,good_id=?,yyyp_id=?,updated_at=? WHERE id=?""",
                     (weapon, skin, wear, source, is_discontinued,
                      discontinued_years, stat_trak, souvenir, notes, wl, good_id, yyyp_id, now, row["id"]))
        return row["id"]
    cur = conn.execute("""INSERT INTO items (name,weapon,skin,wear,
                       source,is_discontinued,discontinued_years,stat_trak,souvenir,notes,in_watchlist,good_id,yyyp_id,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (name, weapon, skin, wear, source, is_discontinued,
                        discontinued_years, stat_trak, souvenir, notes, wl, good_id, yyyp_id, now, now))
    return cur.lastrowid


def save_price_history_batch(conn, item_id, daily_bars, mode="incremental", collect_time=""):
    """Save 90-day K-line data (Bar objects) to price_history table.
    daily_bars: list of Bar objects with .date, .close, .volume, .in_sale_count, .survive

    mode（2026-08-10 B-1 增量写，防串品污染历史）:
      incremental（默认）: 只写「date > 库内 max(date)」的新行 + 当日最新行更新；
        历史行不可被覆盖——单次坏 chart 只污染当日行；变更记 data/price_history_write_log.jsonl。
      force: 原全窗口 INSERT OR REPLACE 语义（审计回填/串品修复专用，须人工确认后调用）。
    返回 (n_insert, n_update)。
    """
    if mode not in ("incremental", "force"):
        raise ValueError(f"save_price_history_batch mode 非法: {mode!r}")
    n_ins = n_upd = 0
    log = []
    today = datetime.now(TZ_BJ).date().isoformat()

    def _vals(bar):
        return (item_id, bar.date, round(bar.close, 2),
                int(bar.volume) if bar.volume else 0,
                int(bar.survive) if bar.survive else 0,
                int(bar.in_sale_count) if getattr(bar, "in_sale_count", 0) else 0)

    if mode == "force":
        for bar in daily_bars:
            if not bar.date or not bar.close or bar.close <= 0:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO price_history (item_id, date, price_rmb, volume_day, volume_total, in_sale_count) VALUES (?,?,?,?,?,?)",
                _vals(bar))
            n_ins += 1
            log.append(("insert", bar.date, round(bar.close, 2)))
        _append_price_write_log(item_id, mode, n_ins, n_upd, log)
        return n_ins, n_upd

    r = conn.execute("SELECT MAX(date) m FROM price_history WHERE item_id=?", (item_id,)).fetchone()
    max_date = r[0] if r and r[0] else ""
    for bar in daily_bars:
        if not bar.date or not bar.close or bar.close <= 0:
            continue
        if bar.date > max_date:
            conn.execute(
                "INSERT OR REPLACE INTO price_history (item_id, date, price_rmb, volume_day, volume_total, in_sale_count) VALUES (?,?,?,?,?,?)",
                _vals(bar))
            n_ins += 1
            log.append(("insert", bar.date, round(bar.close, 2)))
        elif bar.date == today and bar.date == max_date:
            # 当日最新行更新（晚间重采/当日修正）：仅改 price/in_sale，保留 volume；
            # collect_time 传入时同步刷新 created_at（F-3.19，2026-08-11）
            if collect_time:
                conn.execute(
                    "UPDATE price_history SET price_rmb=?, in_sale_count=?, created_at=? WHERE item_id=? AND date=?",
                    (round(bar.close, 2), int(bar.in_sale_count) if getattr(bar, "in_sale_count", 0) else 0,
                     collect_time, item_id, bar.date))
            else:
                conn.execute(
                    "UPDATE price_history SET price_rmb=?, in_sale_count=? WHERE item_id=? AND date=?",
                    (round(bar.close, 2), int(bar.in_sale_count) if getattr(bar, "in_sale_count", 0) else 0,
                     item_id, bar.date))
            n_upd += 1
            log.append(("update", bar.date, round(bar.close, 2)))
        # 其余历史行跳过：防单次坏 chart 整段覆盖落库（2026-08-08/09 串品事故根因）
    if log:
        _append_price_write_log(item_id, mode, n_ins, n_upd, log)
    return n_ins, n_upd


def _append_price_write_log(item_id, mode, n_ins, n_upd, log):
    """B-1 变更日志（2026-08-10）：记录增量写/强制写事件，供审计回溯。"""
    try:
        p = DATA_DIR / "price_history_write_log.jsonl"
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(TZ_BJ).isoformat(timespec="seconds"),
                "item_id": item_id, "mode": mode,
                "n_insert": n_ins, "n_update": n_upd,
                "detail": [{"op": o, "date": d, "price": pr} for o, d, pr in log],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


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


def save_monitor_events(conn, date, events):
    """M1 监控事件批量落库（dedup_key 冲突忽略，当日重跑不重复）。

    events: list of dict(item_id, item_name, event_type, level, detail, dedup_key)
    """
    if not events:
        return 0
    _cur = conn.executemany(
        "INSERT OR IGNORE INTO monitor_events (date, item_id, item_name, event_type, level, detail, dedup_key) "
        "VALUES (?,?,?,?,?,?,?)",
        [(date, e.get("item_id"), e.get("item_name"), e["event_type"], e["level"], e["detail"], e["dedup_key"])
         for e in events],
    )
    return _cur.rowcount if hasattr(_cur, "rowcount") else len(events)


def list_monitor_events(conn, days=7):
    """近 N 天监控事件，日期倒序。"""
    cutoff = (datetime.now(TZ_BJ) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT date, item_id, item_name, event_type, level, detail, dedup_key FROM monitor_events "
        "WHERE date >= ? ORDER BY date DESC, id DESC", (cutoff,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        dk = d.pop("dedup_key") or ""
        d["slot"] = dk.split("::", 1)[0] if dk.startswith(("noon::", "night::")) else "night"
        out.append(d)
    return out


def get_item_history(conn, item_id, limit=90):

    return conn.execute("SELECT * FROM price_history WHERE item_id=? ORDER BY date DESC LIMIT ?", (item_id, limit)).fetchall()


def find_item(conn, name):

    return conn.execute("SELECT * FROM items WHERE name=?", (name,)).fetchone()


# ---- P2: Position CRUD ----


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
        SELECT i.*, s.price_rmb AS latest_price, s.grade AS latest_grade, s.recommendation AS latest_summary,
               s.created_at AS snapshot_created_at
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


def _apply_exec(holding, quantity, avg_cost, total_bought, action, exec_price, qty):
    """按单条执行记录重放持仓状态（纯函数；新增/编辑/删除重放共用）。

    返回 (holding, quantity, avg_cost, total_bought)。
    - buy/add: 数量+=qty, 均价=(旧均价*旧数量+成交价*qty)/新数量, total_bought+=成交价*qty, holding=1
    - reduce/sell: 数量-=qty(不为负), 均价/总买入不变; 清仓后 holding=0
    """
    holding = int(holding or 0)
    quantity = int(quantity or 0)
    avg_cost = float(avg_cost or 0)
    total_bought = float(total_bought or 0)
    qty = max(0, int(qty or 0))
    if qty <= 0 or exec_price is None or float(exec_price or 0) <= 0:
        return (holding, quantity, avg_cost, total_bought)
    exec_price = float(exec_price)
    if action in ("buy", "add"):
        new_qty = quantity + qty
        new_avg = round((avg_cost * quantity + exec_price * qty) / new_qty, 2) if new_qty > 0 else round(exec_price, 2)
        new_total = round(total_bought + exec_price * qty, 2)
        return (1, new_qty, new_avg, new_total)
    if action in ("reduce", "sell"):
        new_qty = max(0, quantity - qty)
        return (1 if new_qty > 0 else 0, new_qty, avg_cost, total_bought)
    return (holding, quantity, avg_cost, total_bought)


def _write_position(conn, item_id, state):
    """将重放后的持仓状态写回 items（state=(holding, quantity, avg_cost, total_bought)）。"""
    conn.execute("UPDATE items SET holding=?, avg_cost=?, quantity=?, total_bought=?, "
                 "updated_at=datetime('now','localtime') WHERE id=?",
                 (state[0], state[2], state[1], state[3], item_id))
    conn.commit()
    return {"holding": state[0], "quantity": state[1], "avg_cost": state[2], "total_bought": state[3]}


def _replay_after(conn, item_id, start_id, base_state):
    """分段重放：从 base_state（start_id 操作前的快照）开始，重放该品 id > start_id 的记录。

    重放中同步刷新后续记录的 prev 快照，保证链条一致；最终状态写回 items。
    """
    state = tuple(base_state)
    rows = conn.execute(
        "SELECT id, action, exec_price, qty FROM executions "
        "WHERE item_id=? AND id>? ORDER BY id", (item_id, start_id)).fetchall()
    for r in rows:
        conn.execute("UPDATE executions SET prev_holding=?, prev_quantity=?, prev_avg_cost=?, prev_total_bought=? WHERE id=?",
                     (state[0], state[1], state[2], state[3], r["id"]))
        state = _apply_exec(*state, r["action"], float(r["exec_price"] or 0), int(r["qty"] or 0))
    return _write_position(conn, item_id, state)


def _rebuild_item(conn, item_id):
    """兜底重建：prev 快照缺失时从零重放该品全部执行记录（2026-08-09 前旧记录迁移回填失败时使用）。"""
    state = (0, 0, 0.0, 0.0)
    rows = conn.execute(
        "SELECT id, action, exec_price, qty FROM executions WHERE item_id=? ORDER BY id", (item_id,)).fetchall()
    for r in rows:
        conn.execute("UPDATE executions SET prev_holding=?, prev_quantity=?, prev_avg_cost=?, prev_total_bought=? WHERE id=?",
                     (state[0], state[1], state[2], state[3], r["id"]))
        state = _apply_exec(*state, r["action"], float(r["exec_price"] or 0), int(r["qty"] or 0))
    return _write_position(conn, item_id, state)


def add_execution(conn, item_id, name, action, advice_date, exec_price, qty=1, advice_signal="", advice_price=None, source="manual"):
    """新增执行记录（按建议执行：建仓/补仓/减仓/清仓）。

    2026-08-09: 记录操作前持仓快照(prev_*)，删除/编辑该条时可从此状态分段重放回滚持仓/资产。
    """
    prev = (0, 0, 0.0, 0.0)
    if item_id > 0:
        row = conn.execute(
            "SELECT holding, avg_cost, quantity, total_bought FROM items WHERE id=?", (item_id,)).fetchone()
        if row:
            prev = (int(row["holding"] or 0), int(row["quantity"] or 0),
                    float(row["avg_cost"] or 0), float(row["total_bought"] or 0))
    cur = conn.execute(
        "INSERT INTO executions (item_id, name, action, advice_date, advice_signal, advice_price, exec_price, qty, "
        "prev_holding, prev_quantity, prev_avg_cost, prev_total_bought, source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (item_id, name, action, advice_date, advice_signal, advice_price, exec_price, qty,
         prev[0], prev[1], prev[2], prev[3], source))
    conn.commit()
    return cur.lastrowid


def list_executions(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM executions ORDER BY id DESC")]


def sold_qty_recent(conn, item_id, days=30):
    """近 N 天累计卖出件数（sell/reduce，按 advice_date）——供止损矩阵识别「已执行止损」（F-3.14）。

    纯数据层：不改任何信号/引擎；口径与 realized_pnl_total 一致（只看卖单）。
    """
    cutoff = (datetime.now(TZ_BJ) - timedelta(days=days)).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(qty), 0) AS n FROM executions "
        "WHERE item_id=? AND action IN ('sell','reduce') AND advice_date >= ?",
        (item_id, cutoff)).fetchone()
    return int(row["n"] or 0)


def realized_pnl_total(conn):
    """累计已实现盈亏（2026-08-09）：sell/reduce 实际卖出 = (成交价 - 操作前持仓成本) x 数量。

    与 exec 表「该笔盈亏」列同口径；在请求时直接从 executions 重算，
    编辑/删除执行记录后天然幂等，无需额外同步。
    """
    total = 0.0
    for r in conn.execute(
            "SELECT exec_price, qty, prev_avg_cost FROM executions "
            "WHERE action IN ('sell','reduce') AND prev_avg_cost IS NOT NULL"):
        if r["exec_price"] and r["qty"] and r["prev_avg_cost"] is not None:
            total += (float(r["exec_price"]) - float(r["prev_avg_cost"])) * int(r["qty"])
    return round(total, 2)


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
    state = _apply_exec(row["holding"], row["quantity"], row["avg_cost"], row["total_bought"],
                        action, exec_price, qty)
    return _write_position(conn, item_id, state)


def _exec_prev_state(row):
    """从 executions 行提取 prev 快照；快照缺失(旧数据)返回 None。"""
    if row["prev_quantity"] is None:
        return None
    return (int(row["prev_holding"] or 0), int(row["prev_quantity"] or 0),
            float(row["prev_avg_cost"] or 0), float(row["prev_total_bought"] or 0))


def delete_execution(conn, eid):
    """删除执行记录（2026-08-09）：同步回滚持仓/资产——从该条操作前快照分段重放其后记录。"""
    row = conn.execute(
        "SELECT item_id, prev_holding, prev_quantity, prev_avg_cost, prev_total_bought FROM executions WHERE id=?",
        (eid,)).fetchone()
    if not row:
        return None
    conn.execute("DELETE FROM executions WHERE id=?", (eid,))
    conn.commit()
    item_id = int(row["item_id"] or 0)
    if item_id <= 0:
        return {"warning": "该记录未关联系统物品，仅删除记录，未同步持仓"}
    base = _exec_prev_state(row)
    if base is None:
        return _rebuild_item(conn, item_id)
    return _replay_after(conn, item_id, eid, base)


def update_execution(conn, eid, action, advice_date, exec_price, qty, advice_signal="", advice_price=None):
    """编辑执行记录（2026-08-09）：更新字段后从该条 prev 快照分段重放后续记录，同步持仓/资产。

    编辑会清空已结算的 14/30 复盘（日期/价格/数量变化后原结算失效，等待重新到期结算）。
    """
    row = conn.execute(
        "SELECT item_id, prev_holding, prev_quantity, prev_avg_cost, prev_total_bought FROM executions WHERE id=?",
        (eid,)).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE executions SET action=?, advice_date=?, advice_signal=?, advice_price=?, exec_price=?, qty=?, "
        "settle_14=NULL, settle_30=NULL, pnl_14=NULL, pnl_30=NULL WHERE id=?",
        (action, advice_date, advice_signal, advice_price, exec_price, qty, eid))
    conn.commit()
    item_id = int(row["item_id"] or 0)
    if item_id <= 0:
        return {"warning": "该记录未关联系统物品，仅更新记录，未同步持仓"}
    base = _exec_prev_state(row)
    if base is None:
        return _rebuild_item(conn, item_id)
    # 先应用本条更新后的新效果，再分段重放其后记录（删除路径 base 已是操作前状态，无需这一步）
    new_state = _apply_exec(*base, action, exec_price, qty)
    return _replay_after(conn, item_id, eid, new_state)


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


def save_item_fundamental_snapshot(conn, date, row):
    """P0 研究层：活跃品基本面快照（info/good 直连字段子集）。

    row 以 good_id 为稳定键，同 (date, good_id) 幂等覆盖；不写 items/price_history，
    不接引擎。extra_json 保留未建模字段，便于后续研究。
    """
    conn.execute(
        """INSERT OR REPLACE INTO item_fundamental_snapshot
           (date, item_id, good_id, item_name, source, platform,
            yyyp_sell_price, yyyp_sell_num, yyyp_buy_price, yyyp_buy_num,
            buff_sell_price, buff_sell_num, buff_buy_price, buff_buy_num,
            c5_sell_price, c5_sell_num, steam_sell_price, steam_buy_price,
            turnover_number, turnover_avg_price,
            sell_price_rate_1, sell_price_rate_7, sell_price_rate_15,
            sell_price_rate_30, sell_price_rate_90, sell_price_rate_180,
            sell_price_rate_365, rank_num, statistic,
            rarity_localized_name, type_localized_name, exterior_localized_name,
            quality_localized_name, min_float, max_float, extra_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (date, row.get("item_id"), row.get("good_id"), row.get("item_name"),
         row.get("source", "csqaq_direct"), row.get("platform", 2),
         row.get("yyyp_sell_price"), row.get("yyyp_sell_num"),
         row.get("yyyp_buy_price"), row.get("yyyp_buy_num"),
         row.get("buff_sell_price"), row.get("buff_sell_num"),
         row.get("buff_buy_price"), row.get("buff_buy_num"),
         row.get("c5_sell_price"), row.get("c5_sell_num"),
         row.get("steam_sell_price"), row.get("steam_buy_price"),
         row.get("turnover_number"), row.get("turnover_avg_price"),
         row.get("sell_price_rate_1"), row.get("sell_price_rate_7"),
         row.get("sell_price_rate_15"), row.get("sell_price_rate_30"),
         row.get("sell_price_rate_90"), row.get("sell_price_rate_180"),
         row.get("sell_price_rate_365"), row.get("rank_num"), row.get("statistic"),
         row.get("rarity_localized_name"), row.get("type_localized_name"),
         row.get("exterior_localized_name"), row.get("quality_localized_name"),
         row.get("min_float"), row.get("max_float"), row.get("extra_json")))


def save_bid_history(conn, date, row):
    """P0 研究层：悠悠求购价/求购量 10 分钟点按日聚合落库。

    只落 platform=2 的日聚合，不落原始 10 分钟点；同 (date, good_id) 幂等覆盖。
    """
    conn.execute(
        """INSERT OR REPLACE INTO bid_history
           (date, item_id, good_id, item_name, source, platform,
            buy_price_last, buy_price_min, buy_price_max, buy_price_mean,
            buy_num_last, buy_num_min, buy_num_max, buy_num_mean, point_count)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (date, row.get("item_id"), row.get("good_id"), row.get("item_name"),
         row.get("source", "csqaq_direct"), row.get("platform", 2),
         row.get("buy_price_last"), row.get("buy_price_min"), row.get("buy_price_max"),
         row.get("buy_price_mean"), row.get("buy_num_last"), row.get("buy_num_min"),
         row.get("buy_num_max"), row.get("buy_num_mean"), row.get("point_count")))

def save_survive_history(conn, date, row):
    """P1 研究层：单品存世量历史点（info/good/statistic 直连）。

    同 (date, good_id) 幂等覆盖；source_created_at 保留接口原始时间戳，不接引擎。
    """
    conn.execute(
        """INSERT OR REPLACE INTO survive_history
           (date, item_id, good_id, item_name, source, platform,
            statistic, source_created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (date, row.get("item_id"), row.get("good_id"), row.get("item_name"),
         row.get("source", "csqaq_direct"), row.get("platform", 2),
         row.get("statistic"), row.get("source_created_at")))


def save_series_snapshot(conn, date, row):
    """P1 研究层：系列/板块面板快照（info/get_series_list 直连）。

    同 (date, series_id) 幂等覆盖；recently_data_json / extra_json 保留未建模字段。
    """
    conn.execute(
        """INSERT OR REPLACE INTO series_snapshot
           (date, series_id, series_key, series_name, source,
            amount, total_value,
            sell_price_1, sell_price_7, sell_price_15, sell_price_30,
            sell_price_90, sell_price_180,
            recently_data_json, extra_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (date, row.get("series_id"), row.get("series_key"), row.get("series_name"),
         row.get("source", "csqaq_direct"), row.get("amount"), row.get("total_value"),
         row.get("sell_price_1"), row.get("sell_price_7"), row.get("sell_price_15"),
         row.get("sell_price_30"), row.get("sell_price_90"), row.get("sell_price_180"),
         row.get("recently_data_json"), row.get("extra_json")))


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


# 数据保留策略（2026-08-09 落地，2026-08-16 大盘五时期更新，口径见 references/data-layer.md）：
#   price_history / snapshots / monitor_events / market_snapshot 保留 365 天；
#   market_index 保留 1095 天（3 年）——五时期长周期轴 chg180 需 180 天回看 + 周期完整性
#     （2026-08-16 一次性回填至 2023-11-17 起，见 references/backfill_market_index_3y.py）；
#   scan_progress_*.json / discover_progress_*.json 等进度文件 7 天；scan_*.md 旧报告 90 天；
#   runtime jsonl 日志（price_history_write_log/caliber_override_log/signal_tracking_reconcile/csqaq_chart_probe）365 天；
#   monitor_rank_snapshot 为研究型数据积累（大户集中度），不清理。
# 调用点：批量扫描收尾（webapp/main.py）与每日任务收尾（run_daily_collect.py）。
# 纯运维动作，不触碰引擎参数；单表失败隔离，不影响其他表。
_RETENTION_TABLE_DAYS = {
    "price_history": 365,
    "snapshots": 365,   # date 为 YYYY-MM-DD HH:MM:SS，按日期部分比较
    "market_index": 1095,
    "monitor_events": 365,
    "market_snapshot": 365,   # 2026-08-13：全市场周度快照保留 365 天，控制研究型面板增长预算
}
_PROGRESS_FILE_GLOBS = ("scan_progress_*.json", "discover_progress_*.json")
_PROGRESS_FILE_DAYS = 7
_SCAN_MD_DAYS = 90
_RUNTIME_LOG_NAMES = (
    "price_history_write_log.jsonl",
    "caliber_override_log.jsonl",
    "signal_tracking_reconcile.jsonl",
    "csqaq_chart_probe.jsonl",
)
_RUNTIME_LOG_DAYS = 365


def run_retention_cleanup(conn=None, vacuum: bool = True) -> dict:
    """数据保留清理：删除超期历史行 + 过期进度/报告文件，可选 VACUUM。

    Returns {deleted: {table: n}, files: n, vacuum: bool}；任何异常按项隔离。
    """
    stats = {"deleted": {}, "files": 0, "vacuum": False}
    _conn = conn or get_conn()
    try:
        for _table, _days in _RETENTION_TABLE_DAYS.items():
            try:
                _cutoff = (datetime.now(TZ_BJ) - timedelta(days=_days)).strftime("%Y-%m-%d")
                # snapshots.date 含时间部分，统一截断到日期比较（其余表纯日期不受影响）
                _cur = _conn.execute(
                    f"DELETE FROM {_table} WHERE date < ?", (_cutoff,))
                _n = getattr(_cur, "rowcount", 0)
                if _n:
                    stats["deleted"][_table] = _n
            except Exception:
                pass
        _conn.commit()
    finally:
        if conn is None:
            _conn.close()
    _cutoff_ts = time.time() - _PROGRESS_FILE_DAYS * 86400
    for _glob in _PROGRESS_FILE_GLOBS:
        for _f in DATA_DIR.glob(_glob):
            try:
                if _f.stat().st_mtime < _cutoff_ts:
                    _f.unlink()
                    stats["files"] += 1
            except Exception:
                pass
    try:
        _md_cutoff_ts = time.time() - _SCAN_MD_DAYS * 86400
        for _f in DATA_DIR.glob("scan_*.md"):
            if _f.stat().st_mtime < _md_cutoff_ts:
                _f.unlink()
                stats["files"] += 1
    except Exception:
        pass
    try:
        _log_cutoff_ts = time.time() - _RUNTIME_LOG_DAYS * 86400
        for _name in _RUNTIME_LOG_NAMES:
            _f = DATA_DIR / _name
            if _f.exists() and _f.stat().st_mtime < _log_cutoff_ts:
                _f.unlink()
                stats["files"] += 1
    except Exception:
        pass
    if vacuum:
        try:
            _vc = get_conn()
            try:
                _vc.execute("VACUUM")
            finally:
                _vc.close()
            stats["vacuum"] = True
        except Exception:
            pass
    return stats

