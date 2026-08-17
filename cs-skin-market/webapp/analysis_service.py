"""单品分析服务层（2026-08-07 重构）。

从 webapp/main.py 抽出：kline 兜底 / 脏价校验 / 锚价校正 / 大盘上下文 / 快照落库 /
统一分析核心 analyze_fresh()。合并 api_items_search / api_items_analyze /
api_watchlist_analyze 三条约 90% 重复的分析路径；批量扫描 _scan_item 因
「价格校验先行 + 参数子集 + 结果结构不同」暂保留原流程（调用本模块助手函数）。
"""
import asyncio, copy, io, json, logging, statistics, sys, threading, time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.templating import Jinja2Templates
from pipeline import db, collector, collector_csqaq, item_analysis, config as _config, signal_tracking as _sig_tracking
from pipeline.config import TZ_BJ

_log = logging.getLogger("webapp")  # 与 main.py 同通道
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


class AnalysisAbort(Exception):
    """分析中止（用户可见错误文案）。"""

    def __init__(self, msg: str):
        super().__init__(msg)
        self.msg = msg


def _now_str() -> str:
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")


# ============================================================
# 以下函数由 webapp.main 迁入（2026-08-07），行为不变
# ============================================================


# ============================================================
# 采集复用优先（F-3, 2026-08-08）：DB 有新鲜 K 线则不重复采集
# 新鲜度 = 行数>=14 且 最新日期距今 <= max_stale_days
# 单品主动分析要求当天数据（stale==0）；批量/积累场景容忍 3 天
# ============================================================
KLINE_FRESH_SINGLE = 0     # 单品主动分析（search/analyze/watchlist analyze）：当日已采 6h 内复用（B-4），否则强制当天采集
KLINE_FRESH_BATCH = 3      # 批量扫描 / 午间监控轻量刷新
KLINE_FRESH_DISCOVER = 3   # discover 全量/增量扫描
KLINE_FRESH_SINGLE_HOURS = 6  # B-4（2026-08-10）单品主动分析「当日已采 6h 内复用」窗口


def _history_to_bars(rows):
    """price_history 行 -> 90 日 K 线 SimpleNamespace 列表（close/high/low/in_sale_count）。"""
    import types as _types
    bars = []
    for r in rows:
        price = float(r["price_rmb"] or 0)
        _raw_sale = r["in_sale_count"]
        bars.append(_types.SimpleNamespace(
            ts=0, date=r["date"], close=price, high=price, low=price,
            volume=float(r["volume_day"] or 0),
            in_sale_count=int(_raw_sale) if _raw_sale is not None else 0,  # 去量: 在售量为唯一量源（勿用 volume_total）
            tx_amount=0, tx_count=0, survive=0,
            _in_sale_raw=_raw_sale,
            in_sale_missing=db.supply_depth_missing(_raw_sale, r["date"]),
        ))
    return bars


def db_kline_fresh(good_id, name, max_stale_days=KLINE_FRESH_BATCH, max_stale_hours=0):
    """DB 新鲜 K 线判定：定位 items 行 -> 近 90 日价格 -> 行数>=14 且最新日期距今<=max_stale_days。

    max_stale_hours（B-4, 2026-08-10）：当日数据（stale==0）时按最近采集时间再限窗口，
    超过则视为不新鲜（单品主动分析 6h 双轨，限流预算与新鲜度折中）。
    返回 dict(bars, stale, last_date, item_id, db_name, yyyp_id) 或 None。纯读不采集。"""
    conn = db.get_conn()
    try:
        row = None
        if name:
            row = conn.execute("SELECT id, name, yyyp_id FROM items WHERE name=?", (name,)).fetchone()
        if row is None and good_id:
            row = conn.execute("SELECT id, name, yyyp_id FROM items WHERE good_id=?", (good_id,)).fetchone()
        if row is None:
            return None
        rows = db.get_item_history(conn, row["id"], limit=90)
        if not rows or len(rows) < 14:
            return None
        rows = sorted(rows, key=lambda r: r["date"])
        last_date = rows[-1]["date"]
        stale = (datetime.now(TZ_BJ).date() - datetime.strptime(last_date, "%Y-%m-%d").date()).days
        if stale > max_stale_days:
            return None
        # B-4（2026-08-10）：当日数据 + 最近采集不超过 max_stale_hours 小时才复用
        if max_stale_hours > 0 and stale == 0:
            try:
                _ct = (rows[-1]["created_at"] or "").strip()
            except Exception:
                _ct = ""
            if _ct:
                try:
                    # created_at 为 SQLite localtime naive 字符串；本机时区=Asia/Shanghai，用 naive now 对齐
                    _age_h = (datetime.now() - datetime.strptime(_ct, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600.0
                except ValueError:
                    _age_h = float("inf")
                if _age_h > max_stale_hours:
                    _log.info(f"db_kline_fresh {row['name']}: 当日已采但超 {max_stale_hours}h（{_age_h:.1f}h）→ 重新采集")
                    return None
        # F-3.18（2026-08-10）采集时间带出：缓存复用路径需告知用户数据新鲜度（模板提示条）
        _collected_at = ""
        try:
            for _r in reversed(rows):
                _c = ((_r["created_at"] if "created_at" in _r.keys() else "") or "").strip()
                if _c:
                    _collected_at = _c
                    break
        except Exception:
            _collected_at = ""
        return {"bars": _history_to_bars(rows), "stale": stale, "last_date": last_date,
                "item_id": row["id"], "db_name": row["name"], "yyyp_id": row["yyyp_id"] or "",
                "collected_at": _collected_at}
    except Exception as _e:
        _log.warning(f"db_kline_fresh failed: {_e}")
        return None
    finally:
        conn.close()


def item_from_db(fresh, good_id):
    """用 DB 新鲜数据构造 ItemData（from_db=True），供分析路径复用，避免重复采集。"""
    from pipeline.collector_csqaq import ItemData
    bars = fresh["bars"]
    last = next((k for k in reversed(bars) if getattr(k, "close", 0) or 0), None)
    last_sale = 0
    for k in reversed(bars):
        if getattr(k, "in_sale_count", 0) or 0:
            last_sale = k.in_sale_count
            break
    it = ItemData()
    it.good_id = good_id
    it.name = fresh["db_name"]
    it.price_rmb = float(last.close) if last else 0.0
    it.sell_num_yyyp = last_sale
    it.in_sale_count = last_sale
    it.yyyp_id = fresh["yyyp_id"]
    it.kline_90d = bars
    it.order_book = None  # 求购为数据储备阶段，DB 复用不采集（分析可选参数）
    it.from_db = True
    it.stale_days = fresh["stale"]
    it.collected_at = fresh.get("collected_at") or ""
    return it


async def resolve_item(good_id, name, max_stale_days=KLINE_FRESH_BATCH, force_refresh=False, max_stale_hours=0):
    """复用优先入口：DB 新鲜则返回 DB ItemData（不采集）；否则走 csQAQ 采集。
    force_refresh=True 时跳过 DB 复用，强制联网采集最新数据（批量扫描「强制联网刷新」入口）。
    max_stale_hours（B-4, 2026-08-10）透传 db_kline_fresh：当日已采超窗口视为不新鲜。
    返回 ItemData（可能 from_db=True）或 None。"""
    if not force_refresh:
        fresh = db_kline_fresh(good_id, name, max_stale_days, max_stale_hours)
        if fresh:
            _log.info(f"采集复用 DB {fresh['db_name']}: stale={fresh['stale']}d bars={len(fresh['bars'])}")
            return item_from_db(fresh, good_id)
    else:
        _log.info(f"强制联网刷新 {name} (good_id={good_id})")
    return await collector_csqaq.fetch_item_detail(good_id)


def kline_db_fallback(good_id, name):
    """csQAQ 图表采集失败时，用数据库缓存的90日K线兜底。Returns (bars, stale_days, last_date) or (None, None, "")."""
    conn = db.get_conn()
    try:
        row = db.find_item(conn, name) if name else None
        if row is None and good_id:
            row = conn.execute("SELECT id FROM items WHERE good_id=?", (good_id,)).fetchone()
        if row is None:
            return None, None, ""
        rows = db.get_item_history(conn, row["id"], limit=90)
        if not rows:
            return None, None, ""
        rows = sorted(rows, key=lambda r: r["date"])
        last_date = rows[-1]["date"]
        stale = (datetime.now(TZ_BJ).date() - datetime.strptime(last_date, "%Y-%m-%d").date()).days
        if stale > 14 or len(rows) < 14:
            return None, None, ""
        return _history_to_bars(rows), stale, last_date
    except Exception as _e:
        _log.warning(f"db kline fallback failed: {_e}")
        return None, None, ""
    finally:
        conn.close()


def _log_caliber_event(kind, label, detail):
    """F-4（2026-08-10）口径漂移审计日志：锚校正/脏价拦截事件写 data/caliber_override_log.jsonl。

    纯留痕，不改任何分析/落库行为；供供给特征口径漂移核查与 8 节审计 SOP 旁证。
    """
    try:
        import json as _json
        from datetime import datetime as _dt
        from pathlib import Path as _P3
        _fp = _P3(__file__).resolve().parent.parent / "data" / "caliber_override_log.jsonl"
        _line = _json.dumps({
            "ts": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind, "label": label, "detail": detail,
        }, ensure_ascii=False)
        with _fp.open("a", encoding="utf-8") as _f:
            _f.write(_line + "\n")
    except Exception:
        pass


def kline_price_sane(daily_bars, item_id, anchor_price=None, conn=None):
    """K线价格合理性校验，防 csQAQ 偶发串品/脏价覆盖历史。

    规则：新采集最新价 vs DB 该品最近历史价 偏差>25%，且新序列内存在单日跳变>30%，
    判为疑似脏数据（如 2026-08-01 水灵 595 vs 真实 424）。
    规则2（2026-08-04 增强）：anchor_price（悠悠锚）存在时，最新 close vs 锚价偏差>20%
    判脏——拦截「整条序列整体口径偏移」型脏价（如死寂空间 chart 883 vs 悠悠 614，
    序列内无大跳变但整体偏离，规则1漏检）。
    Returns (ok: bool, msg: str)；ok=False 时调用方统一以悠悠锚价为准校正最新价（anchor>0），
    无锚价可用时才跳过落库（保留 DB 旧数据）。
    """
    if not daily_bars or len(daily_bars) < 3:
        return True, ""
    closes = [b.close for b in daily_bars if getattr(b, "close", 0) and b.close > 0]
    if len(closes) < 3:
        return True, ""
    # F-3.17 (2026-08-09)：在售量 sanity —— chart 在售量全 0 但 DB 该品有非 0 在售量，
    # 判采集异常（不落库覆盖 DB 在售量；分析侧由 analyze_fresh supply 兜底用 DB 在售量）
    if all(not (getattr(b, "in_sale_count", 0) or 0) for b in daily_bars):
        try:
            _close_conn_s = conn is None
            _conn_s = conn or db.get_conn()
            try:
                _srow = _conn_s.execute(
                    "SELECT COUNT(*) AS n FROM price_history WHERE item_id=? AND in_sale_count>0",
                    (item_id,)).fetchone()
                if _srow and _srow["n"] > 0:
                    _msg2 = "chart 在售量全 0，DB 存在非 0 在售量（采集异常，不覆盖）"
                    _log_caliber_event("sale_zero", str(item_id), _msg2)
                    return False, _msg2
            finally:
                if _close_conn_s:
                    _conn_s.close()
        except Exception:
            pass
    new_last = closes[-1]
    if anchor_price and anchor_price > 0 and new_last > 0:
        dev_anchor = abs(new_last / anchor_price - 1)
        if dev_anchor > 0.20:
            _msg3 = "最新价¥%.2f vs 悠悠锚¥%.2f 偏差%.0f%%" % (new_last, anchor_price, dev_anchor * 100)
            _log_caliber_event("anchor_mismatch", str(item_id), _msg3)
            return False, _msg3
    max_jump = 0.0
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            max_jump = max(max_jump, abs(closes[i] / closes[i - 1] - 1))
    db_last = 0
    last_date = getattr(daily_bars[-1], "date", "") or "9999-99-99"
    try:
        _close_conn = conn is None
        _conn = conn or db.get_conn()
        try:
            row = _conn.execute(
                "SELECT price_rmb FROM price_history WHERE item_id=? AND date < ? ORDER BY date DESC LIMIT 1",
                (item_id, last_date),
            ).fetchone()
            if row:
                db_last = row["price_rmb"] or 0
        finally:
            if _close_conn:
                _conn.close()
    except Exception:
        return True, ""
    if db_last <= 0 or new_last <= 0:
        return True, ""
    dev = abs(new_last / db_last - 1)
    if dev > 0.25 and max_jump > 0.30:
        _msg4 = "最新价¥%.2f vs DB ¥%.2f 偏差%.0f%%，序列内跳变%.0f%%" % (new_last, db_last, dev * 100, max_jump * 100)
        _log_caliber_event("jump_suspect", str(item_id), _msg4)
        return False, _msg4
    return True, ""


def anchor_override(daily_bars, anchor_price, label=""):
    """新规则（2026-08-04）：chart 最新价与悠悠锚价偏差>20% 时，统一以悠悠锚价为准。

    以「近7日历史水平（去掉最新 bar 后的中位数）」为参考判定口径：
    - 历史水平与锚价偏差>20% → 整条序列按 (锚价/参考水平) 缩放到悠悠锚口径（整体口径偏移型脏价）；
    - 仅最新价偏差>20%（历史正常） → 仅把最新 bar 校正为锚价（尾部跳变）；
    最新 bar 未含当日时追加一根当日锚价 bar。校正后继续分析/落库（顺带修复被污染的 DB 历史）。
    anchor_price<=0 时不校正，原样返回。
    """
    if not daily_bars or not anchor_price or anchor_price <= 0:
        return daily_bars
    closes = [b.close for b in daily_bars if getattr(b, "close", 0) and b.close > 0]
    if len(closes) < 3:
        return daily_bars
    last_close = closes[-1]
    hist = sorted(closes[-8:-1])  # 近7日历史（去掉最新 bar）
    ref = hist[len(hist) // 2]
    dev_last = abs(last_close / anchor_price - 1)
    dev_ref = abs(ref / anchor_price - 1)
    if dev_last <= 0.20 and dev_ref <= 0.20:
        return daily_bars
    if dev_ref > 0.20:
        factor = anchor_price / ref
        mode = "序列整体缩放"
        out = []
        for b in daily_bars:
            nb = copy.copy(b)
            if getattr(nb, "close", 0) or 0:
                nb.close = round(nb.close * factor, 2)
            if getattr(nb, "high", 0) or 0:
                nb.high = round(nb.high * factor, 2)
            if getattr(nb, "low", 0) or 0:
                nb.low = round(nb.low * factor, 2)
            out.append(nb)
    else:
        factor = anchor_price / last_close
        mode = "仅最新价校正"
        out = list(daily_bars)
    out[-1].close = anchor_price
    _log.warning(f"anchor override {label}: 最新价¥{last_close:.2f} 近7日水平¥{ref:.2f} vs 悠悠锚¥{anchor_price:.2f}（偏差{dev_ref * 100:.0f}%），{mode}统一以悠悠锚价为准")
    _log_caliber_event("anchor_override", label, "最新¥%.2f 近7日¥%.2f 锚¥%.2f 偏差%.0f%% %s" % (last_close, ref, anchor_price, dev_ref * 100, mode))
    today = _today_str()
    if (getattr(out[-1], "date", "") or "") < today:
        nb = copy.copy(out[-1])
        nb.date = today
        nb.close = anchor_price
        nb.high = max((getattr(nb, "high", 0) or 0), anchor_price)
        nb.low = min((getattr(nb, "low", 0) or 0) or anchor_price, anchor_price)
        nb.volume = 0
        nb.tx_count = 0
        out.append(nb)
    return out


# 2026-08-12 性能优化：大盘上下文整体 5min 进程内缓存（含 sentiment 拉取结果）。
# 大盘上下文为低频变化量，批量扫描/报告弹窗/大盘页高频调用时共享同一快照，
# 消除冷缓存时段的重复 DB 读与重复联网情绪拉取（csQAQ /current_data）。
_MARKET_SNAP_TTL = 300.0
_market_snap_cache = {"ts": 0.0, "data": None}
_market_snap_lock = threading.Lock()


def bust_market_snapshot_cache():
    """大盘手动刷新后立即失效快照缓存（2026-08-12，性能层）。"""
    with _market_snap_lock:
        _market_snap_cache["ts"] = 0.0
        _market_snap_cache["data"] = None


def market_snapshot():
    """Market context from stored index history (pct/z/cycle/th/chg7/chg30/sentiment).

    指数统计复用 pipeline.market_context.market_index_stats（与监控 _market_ctx_from_db 同源）；
    情绪保持在线口径 compute_sentiment_score（10min 缓存），监控路径用 DB 口径。
    2026-08-12 起整体结果带 5min 进程内缓存（bust_market_snapshot_cache 手动失效）。
    """
    now = time.time()
    _c = _market_snap_cache
    if _c["data"] is not None and (now - _c["ts"]) < _MARKET_SNAP_TTL:
        return _c["data"]
    with _market_snap_lock:
        if _c["data"] is not None and (time.time() - _c["ts"]) < _MARKET_SNAP_TTL:
            return _c["data"]
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT date, value FROM market_index ORDER BY date ASC"
            ).fetchall()
            market_history = [(r["date"], float(r["value"])) for r in rows] if rows else []
        finally:
            conn.close()
        from pipeline.market_context import market_index_stats
        stats = market_index_stats(market_history)
        try:
            from pipeline.market_macro import compute_sentiment_score
            sentiment = float(compute_sentiment_score() or 50)
        except Exception:
            sentiment = 50.0
        result = {
            "history": market_history,
            "pct": stats["pct"], "z": stats["z"], "cycle": stats["cycle"],
            "th": stats["th"], "chg7": stats["chg7"], "chg30": stats["chg30"],
            "drop21": stats["drop21"], "chg180": stats.get("chg180", 0),
            "sentiment": sentiment,
        }
        _c["data"] = result
        _c["ts"] = time.time()
    return result


def _bid_history_for(item_id):
    """C 族（2026-08-16）：单品求购历史（[(date, buy_price_last)] 升序），供二波承接判定。
    数据=market.db bid_history 3 年回填；任何异常返回 None（展示/触发层不阻断分析）。"""
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date, buy_price_last FROM bid_history WHERE item_id=? AND buy_price_last IS NOT NULL "
            "ORDER BY date", (item_id,)).fetchall()
        conn.close()
        return [(r["date"], r["buy_price_last"]) for r in rows]
    except Exception:
        return None


def recent_buy_dates(conn, item_id, days=7):
    """Snapshot buy-signal dates within the last N days (for 7-day signal clustering).

    v2-T11（2026-08-16 优先级感知去重）：返回 "YYYY-MM-DD|P"（P=族优先级，item_analysis.dedup_prio_for_label
    单一事实源）；旧行 action_label 为空 → 返回裸日期（保守拦一切）。
    """
    from pipeline.item_analysis import dedup_prio_for_label
    cutoff = (datetime.now(TZ_BJ) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT date, action_label FROM snapshots WHERE item_id=? AND action IN ('buy','oversold_buy') AND date >= ? ORDER BY date DESC",
        (item_id, cutoff),
    ).fetchall()
    out = []
    for r in rows:
        d = r["date"][:10]
        label = r["action_label"] or ""
        out.append("%s|%d" % (d, dedup_prio_for_label(label)) if label else d)
    return out


def save_item_snapshot(conn, item_id, analysis, price_rmb, today=None, order_book=None):
    """Render + upsert today report into snapshots; records fusion action for 7-day buy dedup.

    order_book: 可选，求购(order_book)原始字段，持久化供后续版本迭代验证求购因子（决策零改动）。
    """
    def _bid_vals(ob):
        if not isinstance(ob, dict):
            return (None, None, None, None, None)
        return (ob.get("highest_buy"), ob.get("bid_7d_chg"), ob.get("bid_30d_chg"),
                ob.get("spread_pct"), ob.get("spread_avg"))
    if today is None:
        today = _now_str()
    report_html = templates.get_template("partials/analysis.html").render(build_analysis_ctx(analysis))
    score = analysis.value.score
    grade = analysis.value.grade
    action = ""
    action_label = ""
    if isinstance(getattr(analysis, "fusion_decision", None), dict):
        action = analysis.fusion_decision.get("action", "")
        action_label = analysis.fusion_decision.get("action_label", "") or ""
    summary_json = json.dumps({
        "valuation_tier": getattr(analysis.position, "valuation_tier", "") if hasattr(analysis, "position") else "",
        "percentile_90d": getattr(analysis.position, "percentile_90d", 50) if hasattr(analysis, "position") else 50,
        "cycle_phase": getattr(analysis.cycle, "phase", "") if hasattr(analysis, "cycle") else "",
        "fusion_action": action,
        "score": score, "grade": grade,
        "proximity": (analysis.fusion_decision or {}).get("proximity")
                     if isinstance(getattr(analysis, "fusion_decision", None), dict) else None,
    }, ensure_ascii=False)
    existing = conn.execute(
        "SELECT id FROM snapshots WHERE item_id=? AND date=?", (item_id, today)
    ).fetchone()
    # score_volume 为 DB 兼容字段：去量后恒 0（ValueScore 无成交量维度，勿再引用）
    if existing:
        conn.execute(
            "UPDATE snapshots SET report_html=?, total_score=?, grade=?, price_rmb=?, score_scarcity=?, score_volume=?, score_market=?, score_liquidity=?, recommendation=?, action=?, action_label=?, bid_highest=?, bid_7d_chg=?, bid_30d_chg=?, spread_pct=?, spread_avg=? WHERE id=?",
            (report_html, score, grade, price_rmb,
             analysis.value.scarcity if hasattr(analysis.value, "scarcity") else 0,
             analysis.value.volume if hasattr(analysis.value, "volume") else 0,
             analysis.value.market_sentiment if hasattr(analysis.value, "market_sentiment") else 0,
             analysis.value.liquidity if hasattr(analysis.value, "liquidity") else 0,
             summary_json, action, action_label, *_bid_vals(order_book), existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO snapshots (item_id, date, report_html, total_score, grade, price_rmb, score_scarcity, score_volume, score_market, score_liquidity, recommendation, action, action_label, bid_highest, bid_7d_chg, bid_30d_chg, spread_pct, spread_avg) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, today, report_html, score, grade, price_rmb,
             analysis.value.scarcity if hasattr(analysis.value, "scarcity") else 0,
             analysis.value.volume if hasattr(analysis.value, "volume") else 0,
             analysis.value.market_sentiment if hasattr(analysis.value, "market_sentiment") else 0,
             analysis.value.liquidity if hasattr(analysis.value, "liquidity") else 0,
             summary_json, action, action_label, *_bid_vals(order_book)),
        )
    conn.commit()


def save_analysis_result(analysis, kline_stale_days=None, kline_stale_date="", collected_at=""):
    """渲染简洁报告并 upsert 到 analysis_results（单品分析/批量扫描共用，按 name 覆盖老数据）。"""
    try:
        grade = analysis.value.grade
        th = analysis.trend_health or {}
        trend_dir = th.get("direction", "")
        trend_score = th.get("score", 0)
        # 2026-08-12 口径修复：快照渲染复用 build_analysis_ctx 同款展示层注入
        # （期望徽章/regime 分层/决策链 trace/供给语义），discover 弹窗与 6h 缓存命中报告与重建口径一致。
        fd = _fd_display(analysis.fusion_decision, analysis)
        supply = _supply_display(getattr(analysis, "supply_analysis", None), getattr(analysis, "position", None))
        report_html = templates.get_template("partials/analysis.html").render({
            "name": analysis.name,
            "price_rmb": analysis.price_rmb,
            "supply_analysis": supply,
            "position": analysis.position,
            "aux": analysis.aux,
            "cycle": analysis.cycle,
            "liquidity": analysis.liquidity,
            "probability": analysis.probability,
            "value": analysis.value,
            "whale": analysis.whale,
            "data_quality": analysis.data_quality,
            "trend_health": analysis.trend_health,
            "fusion_decision": fd,
            "error": None,
            "kline_stale_days": kline_stale_days,
            "kline_stale_date": kline_stale_date,
            "price_zones": analysis.price_zones,
            "buy_distance": analysis.buy_distance,
            "analysis_time": _now_str(),
            "collected_at": collected_at or "",
        })
        conn_save = db.get_conn()
        try:
            conn_save.execute("""
                INSERT OR REPLACE INTO analysis_results (name, price_rmb, grade, trend_dir, trend_score, report_html, created_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))
            """, (analysis.name, analysis.price_rmb, grade, trend_dir, trend_score, report_html))
            conn_save.commit()
        finally:
            conn_save.close()
    except Exception as _e:
        _log.warning(f"Failed to save analysis result: {_e}")


# ============================================================
# 统一分析核心（2026-08-07 重构：三条路径共用）
# ============================================================

async def analyze_fresh(item, good_id, exact_name, *, db_item_id=None, apply_anchor=True,
                        hard_error_no_kline=False,
                        allow_single_price=False,
                        auto_watchlist=False):
    """单品分析统一核心：大盘上下文 + K线兜底/锚价校正 + 引擎分析 + 落库 + 快照 + 报告。

    参数：
      item            fetch_item_detail 返回的详情对象（含 kline_90d/order_book/price_rmb 等）
      good_id         csQAQ good id
      exact_name      清洗后的规范名
      db_item_id      已有 DB 行 id（watchlist 路径；None 时用 upsert 后的 pid）
      apply_anchor    是否应用锚价校正（search/analyze=True；watchlist 沿用历史行为=False）
      hard_error_no_kline  K 线获取失败时抛 AnalysisAbort（search 路径；其他路径降级用锚价单点）
      allow_single_price K 线为空时降级用单点锚价分析（watchlist 历史行为；search/analyze 传空保持原样）
      auto_watchlist   分析后是否自动加入自选（2026-08-09 F-3.16：默认=False，只允许用户主动加入；扫描/分析一律不自动加入，入口为 /api/watchlist/add）
    返回 bundle dict；失败抛 AnalysisAbort（msg 为用户可见文案）。
    """
    idx = await asyncio.to_thread(collector.fetch_market_index)
    if idx is None or idx.value == 0:
        idx = collector.MarketIndex(value=0, change_7d=0, mood="neutral")

    price_rmb = item.price_rmb
    volume_total = item.volume_total
    if volume_total == 0 and hasattr(item, 'in_sale_count') and item.in_sale_count:
        volume_total = item.in_sale_count

    daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
    kline_stale_days = None
    kline_stale_date = ""
    price_history = [k.close for k in daily_bars if k.close > 0] if daily_bars else []
    if not daily_bars or not price_history:
        _db_bars, _stale, _stale_date = kline_db_fallback(good_id, exact_name)
        if _db_bars:
            daily_bars = _db_bars
            price_history = [k.close for k in daily_bars if k.close > 0]
            kline_stale_days, kline_stale_date = _stale, _stale_date
            _log.warning(f"kline DB fallback for {exact_name} stale={_stale}d")
        elif hard_error_no_kline:
            raise AnalysisAbort("K线数据获取失败，请稍后重试（csQAQ 图表采集偶发为空，已自动重试仍失败）")
    if apply_anchor:
        daily_bars = anchor_override(daily_bars, price_rmb, label=exact_name)
        price_history = [k.close for k in daily_bars if k.close > 0] if daily_bars else []
    supply_history = [k.in_sale_count for k in daily_bars] if daily_bars else []
    supply_depth_missing = db.latest_supply_missing(daily_bars)

    ms = market_snapshot()
    market_history = ms["history"]

    conn_p = db.get_conn()
    try:
        pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id, yyyp_id=item.yyyp_id,
                             in_watchlist=(1 if auto_watchlist else None))
        conn_p.commit()
    finally:
        conn_p.close()
    use_id = db_item_id or pid

    conn_r = db.get_conn()
    # F-3.17 (2026-08-09)：实时采集 chart 在售量偶发全 0/缺失 -> 用 DB 在售量按日期补全，
    # 避免供给分析退化导致决策降级（单品分析=筑底观察 vs discover=供给收缩吸筹 的分歧根因）
    if daily_bars and (not supply_history or all(not s for s in supply_history)):
        try:
            _conn_sup = db.get_conn()
            try:
                _db_sup = {r['date']: (r['in_sale_count'] or 0) for r in _conn_sup.execute(
                    'SELECT date, in_sale_count FROM price_history WHERE item_id=? AND in_sale_count>0',
                    (use_id,))}
            finally:
                _conn_sup.close()
            if _db_sup:
                supply_history = [
                    (getattr(_k, 'in_sale_count', 0) or 0) or _db_sup.get(getattr(_k, 'date', ''), 0)
                    for _k in daily_bars
                ]
                _log.warning(f'supply DB backfill for {exact_name} (chart in_sale 缺失)')
        except Exception:
            _log.warning("cs-skin-market/webapp/analysis_service.py unexpected error near line 586", exc_info=True)

    conn_r = db.get_conn()
    try:
        recent_buys = recent_buy_dates(conn_r, use_id, days=30)
    finally:
        conn_r.close()

    analysis = item_analysis.run_item_analysis(
        name=exact_name,
        prices=price_history if price_history else ([price_rmb] if allow_single_price else []),
        supply_hist=supply_history if supply_history else None,
        supply_depth_missing=supply_depth_missing,
        order_book=item.order_book,
        index_change_7d=idx.change_7d,
        market_history=market_history,
        market_pct_90d=ms["pct"],
        market_zscore=ms["z"],
        market_cycle=ms["cycle"],
        market_th_score=ms["th"],
        market_30d_change=ms["chg30"],
        market_drop21=ms.get("drop21", 0),
        market_180d_change=ms.get("chg180", 0),
        bid_history=_bid_history_for(use_id),
        recent_buy_dates=recent_buys,
        signal_date=_today_str(),
        price_anchor=price_rmb,
        survive_count=getattr(item, "survive_count", 0),
    )
    # 报告价格锚定悠悠有品 DOM 价（chart fallback 价只补 K 线不参与定价）
    if price_rmb and price_rmb > 0:
        analysis.price_rmb = price_rmb
    # 去量 (2026-08-07): 不再抓取悠悠成交量，volume_day 置 0（不伪造模拟量）
    analysis.volume_day = 0
    analysis.volume_total = volume_total

    # 脏价校验：chart 最新 close vs 悠悠锚偏差>20% 时不落库（保留 DB 旧数据，防整体口径偏移脏价）
    _sane, _sane_msg = kline_price_sane(daily_bars, use_id, anchor_price=price_rmb)
    if not _sane:
        _log.warning(f"analyze kline skip {exact_name}: {_sane_msg}")
        daily_bars = None
    if daily_bars:
        try:
            conn_k = db.get_conn()
            try:
                db.save_price_history_batch(conn_k, use_id, daily_bars,
                                             collect_time=getattr(item, "collected_at", "") or "")
                conn_k.commit()
            finally:
                conn_k.close()
        except Exception as _pe:
            _log.warning("kline persist failed: " + str(_pe))
    try:
        conn_s = db.get_conn()
        try:
            save_item_snapshot(conn_s, use_id, analysis, price_rmb, order_book=getattr(item, "order_book", None))
        finally:
            conn_s.close()
    except Exception as _se:
        _log.warning(f"save snapshot failed {exact_name}: {_se}")
    _collected_at = getattr(item, "collected_at", "") or ""
    save_analysis_result(analysis, kline_stale_days, kline_stale_date, _collected_at)

    # 生产实盘信号跟踪 (2026-08-07 C 通道实盘化): buy 信号当日记录, 14/30 交易日后按真实价格回填
    try:
        _fd = getattr(analysis, "fusion_decision", None) or {}
        if isinstance(_fd, dict) and _fd.get("action") in ("buy", "oversold_buy"):
            _entry = daily_bars[-1].close if daily_bars and getattr(daily_bars[-1], "close", 0) > 0 else (price_rmb or 0)
            conn_t = db.get_conn()
            try:
                _sig_tracking.record_buy_signal(
                    conn_t, item_id=use_id, item_name=exact_name,
                    signal_date=_today_str(), action=_fd.get("action", "buy"),
                    action_label=_fd.get("action_label", "") or "",
                    entry_price=_entry, position_limit=_fd.get("position_limit") or 0.10,
                    source="analyze",
                    features=_sig_tracking.build_features(
                        analysis, bars=daily_bars,
                        order_book=getattr(item, "order_book", None) or None,
                        market=ms if isinstance(ms, dict) else None))
            finally:
                conn_t.close()
    except Exception as _te:
        _log.warning(f"signal tracking record failed {exact_name}: {_te}")


    # F-3.7 持仓上下文（展示层）：报告页在「持仓浮亏」时展示补仓/止损双建议（纯展示，不改引擎）
    _holding_ctx = None
    try:
        conn_h = db.get_conn()
        try:
            _hr = conn_h.execute(
                "SELECT holding, avg_cost, quantity FROM items WHERE id=?", (use_id,)).fetchone()
            if _hr and _hr["holding"] and (_hr["avg_cost"] or 0) > 0:
                _holding_ctx = {"holding": 1, "avg_cost": float(_hr["avg_cost"] or 0),
                                "qty": int(_hr["quantity"] or 1), "item_id": int(use_id or 0)}
        finally:
            conn_h.close()
    except Exception:
        _holding_ctx = None

    return {
        "analysis": analysis,
        "holding_ctx": _holding_ctx,
        "market_30d_change": ms.get("chg30"),
        "market_th": ms["th"],
        "sentiment": ms.get("sentiment", 50.0),
        "pid": pid,
        "daily_bars": daily_bars,
        "kline_stale_days": kline_stale_days,
        "kline_stale_date": kline_stale_date,
        "price_rmb": price_rmb,
        "volume_total": volume_total,
        "collected_at": _collected_at,
    }


_SOURCE_LABELS = {
    # 守卫/过滤
    "market_weak_filter": "大盘走弱·禁买", "greedy_no_buy": "情绪贪婪·禁买",
    "survive_too_low": "存世量过低", "halfway_downgrade": "半山腰·观望",
    "buy_cluster_dedup": "7日去重·等待回调", "falling_knife_filter": "飞刀未止跌",
    "micro_th_weak": "短期动能弱", "bid_support_weak": "求购承接弱",
    "market_distribution_filter": "大盘出货期", "item_z_gate": "Z偏高·等待更优入场",
    "consecutive_buy": "连买抑制", "supply_expansion_filter": "供给扩张·禁买",
    "event_risk_filter": "事件风险·观望",
    # 信号族命中/升级
    "panic_resonance_upgrade": "命中·恐慌共振族", "deep_value_stable_market": "命中·深值企稳族",
    "panic_easing_deep_bottom": "命中·恐慌退潮族", "supply_contraction_accumulation": "命中·供给收缩吸筹族",
    "oversold_buy_exception": "命中·超跌反弹例外", "deep_dip_exemption": "深度回调低吸豁免",
    "cycle_accumulation_needs_market_drop": "周期吸筹需大盘深跌",
    # 周期修正
    "cycle_distribution_downgrade": "周期出货·减仓", "cycle_accumulation_upgrade": "周期吸筹·升级",
    "cycle_accumulation_boost": "周期吸筹·加成", "cycle_markup_boost": "周期拉升·加成",
    "cycle_distribution": "周期出货·降级", "cycle_consolidation": "周期洗盘·观望",
    "market_relative_strength_upgrade": "相对强势·升级",
    # 趋势健康上限/折扣
    "oversold_rebound_cap": "TH超跌反弹上限", "steepness_bottom_cap": "TH底部陡度上限",
    "steepness_reversal_cap": "TH反转陡度上限", "flat_strong_cap": "TH强势平台上限",
    "flat_improving_cap": "TH平台修复上限", "distribution_cycle": "TH出货周期扣分",
    "high_consolidation": "TH高位整理扣分", "consolidation_phase": "TH洗盘期扣分",
    "whale_pooling": "TH庄家吸筹扣分", "position_locked": "TH庄家锁仓扣分",
    # 其他
    "th_boost": "情绪/结构修正", "liquidity_filter": "流动性过滤", "bid_boost": "求购承接增强",
}


_EXP_REGIME_CACHE = {"mtime": 0.0, "data": None}


def _load_expectancy_by_regime():
    """只读加载 B-1 状态分层聚合产物（data/_exp_expectancy_by_regime.json），mtime 缓存。

    产物由 references/expectancy_by_regime.py 生成（五时期×族 n/win14/avg14/win30/avg30，net 已扣 2%）；
    文件缺失/解析失败返回 None，展示层静默降级为仅全局徽章。纯展示口径，不参与引擎决策。
    """
    _p = Path(__file__).resolve().parent.parent / "data" / "_exp_expectancy_by_regime.json"
    try:
        _mtime = _p.stat().st_mtime
    except OSError:
        return None
    if _EXP_REGIME_CACHE["mtime"] == _mtime:
        return _EXP_REGIME_CACHE["data"]
    try:
        with io.open(_p, "r", encoding="utf-8") as _f:
            _data = json.load(_f)
    except Exception:
        _EXP_REGIME_CACHE.update(mtime=_mtime, data=None)
        return None
    _EXP_REGIME_CACHE.update(mtime=_mtime, data=_data)
    return _data



_COST_SHADOW_CACHE = {"mtime": 0.0, "data": None}


def _load_cost_shadow():
    """Load the 3% cost shadow artifact (display-only; production 2% cost unchanged)."""
    _p = Path(__file__).resolve().parent.parent / "data" / "_exp_cost_shadow_3pct.json"
    try:
        _mtime = _p.stat().st_mtime
    except OSError:
        return None
    if _COST_SHADOW_CACHE["mtime"] == _mtime:
        return _COST_SHADOW_CACHE["data"]
    try:
        with io.open(_p, "r", encoding="utf-8") as _f:
            _data = json.load(_f)
    except Exception:
        _COST_SHADOW_CACHE.update(mtime=_mtime, data=None)
        return None
    _COST_SHADOW_CACHE.update(mtime=_mtime, data=_data)
    return _data


_BENCHMARK_VIEW_CACHE = {"mtime": 0.0, "data": None}


def _load_benchmark_view():
    """只读加载 data/benchmark_compare.json（组合风险调整后收益双基线展示），mtime 缓存。"""
    _p = Path(__file__).resolve().parent.parent / "data" / "benchmark_compare.json"
    try:
        _mtime = _p.stat().st_mtime
    except OSError:
        return None
    if _BENCHMARK_VIEW_CACHE["mtime"] == _mtime:
        return _BENCHMARK_VIEW_CACHE["data"]
    try:
        with io.open(_p, "r", encoding="utf-8") as _f:
            _data = json.load(_f)
    except Exception:
        _BENCHMARK_VIEW_CACHE.update(mtime=_mtime, data=None)
        return None
    _BENCHMARK_VIEW_CACHE.update(mtime=_mtime, data=_data)
    return _data


def _period_fire_note(bucket):
    """当前时期可买类型（**暂不上线**，2026-08-18 用户裁定下架）：
    早期版本把时期级静态历史均值（如 S3 base 14d 78%）当作「现在进场胜率」展示，
    40 天阴跌期内每天都显示同一数字，误导用户接飞刀——时期级均值 ≠ 时点进场期望。
    须先厘清「进入时期第 N 天的剩余反弹期望/衰减」语义后再上。保留本函数+测试供未来重上。"""
    try:
        from pipeline.item_analysis import PERIOD_ROUTE_BAN
        _plain = {"panic_resonance": "恐慌黄金坑抄底", "panic_easing": "恐慌后止跌反弹",
                  "deep_value": "深值回调买", "supply_accum": "供给收缩吸筹",
                  "rise_accum": "强势品买涨", "base": "低位低估品"}
        _active = {
            "P恐慌深跌": ("panic_resonance", "panic_easing", "base"),
            "S1牛市上行": ("base", "supply_accum"),
            "S2牛市回调": ("base", "deep_value", "supply_accum"),
            "S3弱市阴跌": ("base",),
            "S4弱市反弹": ("base", "rise_accum"),
        }
        _evid = {("S3弱市阴跌", "base"): "此时期历史 14d 78%",
                 ("S2牛市回调", "deep_value"): "此时期历史 30d 68%"}
        _active_text = "、".join(
            (_plain.get(k, k) + ("（%s）" % _evid[(bucket, k)] if (bucket, k) in _evid else ""))
            for k in _active.get(bucket, ("base",)))
        _banned = [k for k, ps in PERIOD_ROUTE_BAN.items() if bucket in ps]
        _detail = []
        if bucket in ("S3弱市阴跌", "S4弱市反弹"):
            _detail.append("大盘\u201c空仓区\u201d是别去抄指数的意思；上面的类型是这个时期历史仍赚钱的精选腿，所以还开着")
        if _banned:
            _detail.append("已禁用：" + "、".join(_plain.get(k, k) for k in _banned) + "——此时期历史 0~17% 胜率，接刀/吸筹失效")
        _detail.append("长持候选未启用（组合验证不过，仅观察）")
        return {"active": _active_text, "detail": "；".join(_detail)}
    except Exception:
        return {"active": "", "detail": ""}


def market_expectancy_card():
    """当前市场状态 × 信号族期望（外部常驻卡片，2026-08-12 从单品报告抽离）。

    市场级信息，与具体品无关：同族品、同一时期所有报告显示相同，故从单品报告
    决策条移出，改为仪表盘常驻卡片统一展示。

    纯展示：状态桶 = market_context.state_bucket（大盘五时期，chg180×chg30，2026-08-16 定稿，
    与单品报告同口径；贪婪禁入为 batch_scan.market_regime 覆盖层，不进入本卡分层）；
    当前桶分层 = B-1 产物 _exp_expectancy_by_regime.json（五时期×族 n/win14/avg30，net 已扣 2%）；
    全局 = config.ITEM_EXPECTANCY_STATS（HIST-FULL 基线）。产物缺失静默降级。
    """
    ms = market_snapshot()
    try:
        from pipeline.market_context import state_bucket as _sb
        bucket = _sb(ms.get("chg180"), ms.get("chg30"))
    except Exception:
        bucket = ""
    _rb = (_load_expectancy_by_regime() or {}).get("regimes") or {}
    _bdata = _rb.get(bucket) or {}
    _bfam = _bdata.get("family") or {}
    _btotal = _bdata.get("total") or {}
    _shadow = _load_cost_shadow() or {}
    _sfam = _shadow.get("families") or {}
    _bench = _load_benchmark_view() or {}
    _risk_view = None
    _risk_view_clean = None

    def _risk(x):
        _ann = x.get("annualized_pct")
        _dd = x.get("max_drawdown_pct")
        _calmar = round(_ann / abs(_dd), 2) if _ann is not None and _dd not in (None, 0) else None
        return {
            "total_return_pct": x.get("total_return_pct"),
            "max_drawdown_pct": _dd,
            "annualized_pct": _ann,
            "calmar": _calmar,
        }

    def _build_risk(bench_blob):
        _active_win = ((bench_blob or {}).get("windows") or {}).get("active") or {}
        if not _active_win:
            return None
        return {
            "range": _active_win.get("range"),
            "strategy": _risk(_active_win.get("strategy") or {}),
            "pool_buy_hold": _risk(_active_win.get("pool_buy_hold") or {}),
            "market_index": _risk(_active_win.get("market_index") or {}),
        }

    _baselines = _bench.get("baselines") or {}
    _risk_view = _build_risk(_baselines.get("HIST-FULL") or _bench)
    _risk_view_clean = _build_risk(_baselines.get("CLEAN-CUR"))
    families = []
    for _key, _label in (("panic", "恐慌族"), ("deep_value", "深值企稳"), ("accumulate", "吸筹族")):
        _g = _config.ITEM_EXPECTANCY_STATS.get(_key) or {}
        _c = _config.ITEM_EXPECTANCY_STATS_CLEAN_CUR.get(_key) or {}
        _f = _bfam.get(_key) or {}
        _n = _f.get("n") or 0
        _s = _sfam.get(_key) or {}
        families.append({
            "key": _key, "label": _label,
            "n": _n,
            "win14": _f.get("win14"), "avg30": _f.get("avg30"),
            # 2026-08-16：五时期下某些桶×族 30d 样本为 0（如 S3×deep_value n30=0），
            # 统计缺失视同 insufficient（不展示，防模板对 None 格式化）
            "insufficient": _n < 5 or _f.get("win14") is None or _f.get("avg30") is None,
            "global_n": _g.get("n"), "global_win14": _g.get("win14"),
            "global_avg30": _g.get("avg30"),
            "global_win14_3pct": _s.get("win14_3pct"),
            "global_avg14_3pct": _s.get("avg14_3pct"),
            "global_win30_3pct": _s.get("win30_3pct"),
            "global_avg30_3pct": _s.get("avg30_3pct"),
            "clean_n": _c.get("n"),
            "clean_win14": _c.get("win14"),
            "clean_avg30": _c.get("avg30"),
        })
    return {
        "bucket": bucket,
        "fire_note": _period_fire_note(bucket),
        "families": families,
        "bucket_total": _btotal.get("n14") or _btotal.get("n") or 0,
        "bucket_win14": _btotal.get("win14"),
        "bucket_avg30": _btotal.get("avg30"),
        "cost_shadow_available": bool(_shadow),
        "cost_base_pct": _shadow.get("cost_base_pct"),
        "cost_shadow_pct": _shadow.get("cost_shadow_pct"),
        "cost_shadow_overall": _shadow.get("overall") or {},
        "risk_view": _risk_view,
        "risk_view_clean": _risk_view_clean,
        "baseline_hist": (_config.BASELINE_LEDGER or {}).get("HIST-FULL") or {},
        "baseline_clean": (_config.BASELINE_LEDGER or {}).get("CLEAN-CUR") or {},
    }


def _spread_trap_note(name):
    """O4（2026-08-15）：Δspread 走阔陷阱指纹软标注——只读提示，不改变决策。

    口径与 A2-2 资产一致：信号日 5 日价差走阔 > +8.9pp = 强陷阱指纹
    （effect −11.53pp、p=0.0、去簇 16；负期望占比 69.2% 差 0.8pp 未过 70% 门槛 → 候选）。
    数据：market.db bid_history.buy_price_last（3 年直连回填）+ price_history.price_rmb。
    任何异常返回 None（展示层绝不阻断分析）。
    """
    try:
        from pipeline import db as _db
        conn = _db.get_conn()
        r = conn.execute("SELECT id, good_id FROM items WHERE name=? AND good_id>0", (name,)).fetchone()
        if not r:
            conn.close()
            return None
        iid, gid = r["id"], r["good_id"]
        bids = conn.execute(
            "SELECT date, buy_price_last FROM bid_history WHERE good_id=? AND buy_price_last IS NOT NULL "
            "ORDER BY date DESC LIMIT 6", (gid,)).fetchall()
        if len(bids) < 2:
            conn.close()
            return None
        d_now, b_now = bids[0]["date"], bids[0]["buy_price_last"]
        d_prev, b_prev = bids[1]["date"], bids[1]["buy_price_last"]
        p_now = conn.execute(
            "SELECT price_rmb FROM price_history WHERE item_id=? AND date<=? AND price_rmb IS NOT NULL "
            "ORDER BY date DESC LIMIT 1", (iid, d_now)).fetchone()
        p_prev = conn.execute(
            "SELECT price_rmb FROM price_history WHERE item_id=? AND date<=? AND price_rmb IS NOT NULL "
            "ORDER BY date DESC LIMIT 1", (iid, d_prev)).fetchone()
        conn.close()
        if not p_now or not p_prev or p_now["price_rmb"] <= 0 or p_prev["price_rmb"] <= 0:
            return None
        sp_now = (p_now["price_rmb"] - b_now) / p_now["price_rmb"] * 100
        sp_prev = (p_prev["price_rmb"] - b_prev) / p_prev["price_rmb"] * 100
        chg = sp_now - sp_prev
        if chg <= 8.9:
            return None
        return (f"陷阱指纹候选（仅研究标注，不改变决策）：5 日价差走阔 +{chg:.1f}pp（>8.9pp）——"
                f"A2-2 大样本验证的强陷阱指纹（effect −11.53pp、p=0.0），当前为候选闸门、未接入 buy 拦截。")
    except Exception:
        return None


def _family_card_note(action_label):
    """第一批（2026-08-16）：族特征卡接入单品报告（研究提示区，纯展示）。

    从 data/family_feature_cards.json 取该信号所属族的历史特征（14/30/60d 胜率/期望），
    让报告「用族的历史说话」；卡缺失/异常静默返回 None，不改变任何决策。缓存按 mtime 失效。
    """
    global _CARD_CACHE
    try:
        import json as _json
        from pathlib import Path as _P
        _path = _P(__file__).resolve().parent.parent / "data" / "family_feature_cards.json"
        _mtime = _path.stat().st_mtime if _path.exists() else None
        if not _mtime:
            return None
        if _CARD_CACHE.get("mtime") != _mtime:
            with open(_path, encoding="utf-8") as _f:
                _CARD_CACHE = {"mtime": _mtime, "data": _json.load(_f)}
        _cards = (_CARD_CACHE.get("data") or {}).get("families") or {}
        from pipeline.signal_tracking import family_key_for_label as _fk
        _card = _cards.get(_fk(action_label))
        if not _card:
            return None
        _h14 = _card.get("horizons", {}).get("14") or {}
        _h30 = _card.get("horizons", {}).get("30") or {}
        _h60 = _card.get("horizons", {}).get("60") or {}
        if _h14.get("n", 0) < 5:
            return None
        _fmt = lambda h: "%s%%/期望%s%%" % (h.get("win"), h.get("avg"))  # noqa: E731
        _base = (f"族历史特征（3 年回放 n={_card.get('n')}）：14d 胜率/期望 {_fmt(_h14)}、"
                 f"30d {_fmt(_h30)}、60d {_fmt(_h60)}")
        # M3（2026-08-16）：当前大盘五时期族分层历史（替代原 bull/nonbull 牛熊拆分）
        try:
            from pipeline.market_context import state_bucket as _sb
            _ms = market_snapshot()
            _p = _sb(_ms.get("chg180"), _ms.get("chg30"))
            _layer = (_card.get("period") or {}).get(_p) or {}
            _l14 = _layer.get("net14") or {}
            _l30 = _layer.get("net30") or {}
            if _l14.get("n", 0) >= 5:
                _base += (f"；当前时期（{_p}）族历史："
                          f"14d {_fmt(_l14)}、30d {_fmt(_l30)}")
        except Exception:
            pass
        return _base + "——仅展示族历史，不改变当前决策。"
    except Exception:
        return None


_CARD_CACHE = {}


def _uniqueness_lines(dates, prices, supply, market_hist):
    """独特性状态行（2026-08-17，纯计算，纯展示）：全部预注册独特性形式命中检测。

    输入：dates/prices/supply = 单品 K 线（升序，≥90 点）；market_hist = [(date, value), ...] 大盘。
    形式（证据引用）：RS30>10（P4 60d +39.8/180d +117.6）、F1 逆市走强（P13 60d +47.9）、
    F2 逆市抗跌（60d +38.7）、F3 低相关独立（60d +18.4，最正常市）、F4 领先见底（60d +16.0）、
    F5 平静期异动（60d +30.0）、F6 供给锁仓（60d +15.6）。
    全部标「假设验证」——结构证据来自回放探针，族未落地（rs/ct 默认关），不改变当前决策。
    """
    try:
        n = len(prices)
        if n < 90 or len(market_hist) < 62:
            return []
        cur = prices[-1]
        if cur <= 0:
            return []
        mdates = [d for d, _ in market_hist]
        mvals = [float(v) for _, v in market_hist]
        if mvals[-1] <= 0 or mvals[-31] <= 0:
            return []
        mkt30 = (mvals[-1] / mvals[-31] - 1) * 100
        mkt7 = (mvals[-1] / mvals[-8] - 1) * 100 if len(mvals) >= 8 and mvals[-8] > 0 else None
        mrets = [(mvals[i] / mvals[i - 1] - 1) for i in range(len(mvals) - 20, len(mvals)) if mvals[i - 1] > 0]
        mvol20 = (sum((r - sum(mrets) / len(mrets)) ** 2 for r in mrets) / len(mrets)) ** 0.5 if mrets else None
        mlo = min(range(len(mvals) - 60, len(mvals)), key=lambda j: mvals[j])
        mkt_low_ago = len(mvals) - 1 - mlo

        item30 = (cur / prices[-31] - 1) * 100 if prices[-31] > 0 else None
        item7 = (cur / prices[-8] - 1) * 100 if prices[-8] > 0 else None
        w = prices[-90:]
        pct90 = sum(1 for p in w if p <= cur) / 90 * 100
        ilo = min(range(n - 60, n), key=lambda j: prices[j])
        item_low_ago = n - 1 - ilo
        sc30 = None
        sup = [s for s in supply[-30:] if s is not None]
        sup7 = [s for s in supply[-7:] if s is not None]
        if len(sup) == 30 and len(sup7) == 7 and sum(sup) > 0:
            sc30 = (sum(sup7) / 7 / (sum(sup) / 30) - 1) * 100
        # corr60：日期对齐的 60 日收益相关
        dset = {d: v for d, v in market_hist}
        pairs = []
        for i in range(max(1, n - 60), n):
            if dates[i] in dset and dates[i - 1] in dset and prices[i - 1] > 0:
                ir = prices[i] / prices[i - 1] - 1
                j = mdates.index(dates[i])
                k = mdates.index(dates[i - 1])
                if j > k and mvals[k] > 0:
                    pairs.append((ir, mvals[j] / mvals[k] - 1))
        corr60 = None
        if len(pairs) >= 30:
            ia_ = [a for a, _ in pairs]
            ib_ = [b for _, b in pairs]
            if __import__("statistics").pstdev(ia_) > 0 and __import__("statistics").pstdev(ib_) > 0:
                corr60 = __import__("statistics").correlation(ia_, ib_)

        lines = []
        rs30 = (item30 - mkt30) if item30 is not None else None
        if rs30 is not None and rs30 > 10:
            lines.append("独特性[假设验证]：相对强度（RS30 %+.0fpp，跑赢大盘）→ 建议：观察独立强势是否延续，"
                         "小仓 pilot 候选——历史同类 60 天平均 +40%%" % rs30)
        if corr60 is not None and corr60 < 0.2 and item30 is not None and abs(item30) > 8:
            lines.append("独特性[假设验证]：低相关独立（60 天相关 %.2f）→ 建议：按它自身结构判断，"
                         "别套大盘结论——历史同类 60 天平均 +18%%" % corr60)
        if mvol20 is not None and mvol20 <= 0.008 and item7 is not None and abs(item7) >= 8:
            lines.append("独特性[假设验证]：大盘平静期异动（单品 7 天 %+.0f%%）→ 建议：先查它自己的事件/资金面，"
                         "再决定是否跟随——历史同类 60 天平均 +30%%" % item7)
        if mkt30 < 0 and item30 is not None and item30 > 5:
            lines.append("独特性[假设验证]：逆市走强（大盘 30 天 %+.0f%% 它却 %+.0f%%）→ 建议：独立资金运作迹象，"
                         "可小仓跟踪独立行情——历史同类 60 天平均 +60%%（半数样本来自事件窗，注意）"
                         % (mkt30, item30))
        if mkt30 < -5 and item30 is not None and abs(item30) <= 3:
            lines.append("独特性[假设验证]：逆市抗跌（大盘 30 天 %+.0f%% 它横盘 %+.0f%%）→ 建议：承接强，"
                         "先观察会不会补跌，不追——历史同类 60 天平均 +39%%" % (mkt30, item30))
        if mkt_low_ago <= 14 and item_low_ago >= mkt_low_ago + 7:
            lines.append("独特性[假设验证]：领先见底（比大盘早 %d 天止跌）→ 建议：先行指标候选，"
                         "观察它是否带动同类——历史同类 60 天平均 +16%%" % (item_low_ago - mkt_low_ago))
        if pct90 > 70 and sc30 is not None and sc30 <= -10 and item7 is not None and item7 >= -2:
            lines.append("独特性[假设验证]：供给锁仓（高位 + 7 日供给收缩 %.0f%%）→ 建议：警惕庄家锁仓诱多，"
                         "勿追涨——历史同类 60 天平均 +16%%" % sc30)
        return lines
    except Exception:
        return []


def _uniqueness_note(name):
    """独特性状态行 DB 包装（任何异常返回 []，展示层绝不阻断分析）。"""
    try:
        from pipeline import db as _db
        conn = _db.get_conn()
        try:
            r = conn.execute("SELECT id FROM items WHERE name=? AND good_id>0", (name,)).fetchone()
            if not r:
                return []
            rows = conn.execute(
                "SELECT date, price_rmb, in_sale_count FROM price_history "
                "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (r["id"],)).fetchall()
        finally:
            conn.close()
        if len(rows) < 90:
            return []
        ms = market_snapshot()
        hist = ms.get("history") or []
        if len(hist) < 62:
            return []
        return _uniqueness_lines([x["date"] for x in rows], [float(x["price_rmb"]) for x in rows],
                                 [x["in_sale_count"] for x in rows], hist)
    except Exception:
        return []


def _f_pullback_note(name):
    """F 判别风险提示层（2026-08-16 落地批次，纯展示）：阴跌/派发后 3 日急拉（chg3d≥8%）。

    承接×拉阳双因子（探针2c：14d 差 15.2pp/30d 差 20.8pp 达标）：
    承接(求购抗跌≥0)+拉大(≥15%) = 真反转候选标注；否则 = 反抽嫌疑（当前窗口此类结构正在失败）。
    任何异常返回 None，绝不改变决策。
    """
    try:
        from pipeline import db as _db
        conn = _db.get_conn()
        r = conn.execute("SELECT id, good_id FROM items WHERE name=? AND good_id>0", (name,)).fetchone()
        if not r:
            conn.close()
            return None
        iid, gid = r["id"], r["good_id"]
        rows = conn.execute(
            "SELECT date, price_rmb, in_sale_count FROM price_history "
            "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date DESC LIMIT 90", (iid,)).fetchall()
        bids = conn.execute(
            "SELECT date, buy_price_last FROM bid_history WHERE good_id=? AND buy_price_last IS NOT NULL "
            "ORDER BY date DESC LIMIT 8", (gid,)).fetchall()
        conn.close()
        if len(rows) < 25 or len(bids) < 2:
            return None
        rows = list(reversed(rows))  # 升序
        prices = [x["price_rmb"] for x in rows]
        ins = [x["in_sale_count"] for x in rows]
        n = len(prices)
        # 阴跌前置：前 20 日（不含近 3 日）价跌 ≤-5%
        if n < 24 or prices[n - 4] <= 0:
            return None
        pre = prices[n - 4] / prices[n - 24] - 1
        if pre > -0.05:
            return None
        # 派发：30 日供给扩张
        ok30 = all(x is not None for x in ins[-30:])
        ok30a = all(x is not None for x in ins[-60:-30]) if n >= 60 else False
        if not (ok30 and ok30a):
            return None
        s30 = sum(ins[-30:]) / 30
        s30a = sum(ins[-60:-30]) / 30
        if s30a <= 0 or s30 / s30a - 1 <= 0:
            return None
        # 急拉
        chg3 = prices[-1] / prices[-4] - 1
        if chg3 < 0.08:
            return None
        # 承接：3 日求购跌幅 vs 价格跌幅
        bnow = bids[0]["buy_price_last"]
        bpk = None
        for b in bids[1:]:
            if b["date"] <= rows[-4]["date"]:
                bpk = b["buy_price_last"]
                break
        sup = None
        if bpk and bpk > 0:
            sup = (bnow / bpk - 1) * 100 - chg3 * 100
        big = chg3 >= 0.15
        if sup is not None and sup >= 0 and big:
            return ("F 判别·真反转候选（研究标注）：阴跌派发后急拉且承接(求购抗跌+%.1fpp)+拉阳大(3日+%.0f%%)——"
                    "历史 14d/30d 胜率显著高于反抽型；仅标注，不改变决策。" % (sup, chg3 * 100))
        return ("F 判别·反抽嫌疑（风险提示）：阴跌派发后 3 日急拉 +%.0f%%，承接/拉阳双因子未同时达标——"
                "当前市场窗口此类结构 30d 胜率仅约 30%%（历史 49%%），谨慎追涨；仅提示，不改变决策。" % (chg3 * 100))
    except Exception:
        return None


def _fd_display(fd, analysis=None):
    """融合决策展示层注入（决策链 trace）。纯展示，不改引擎输出。

    2026-08-12：期望徽章（全局族 + B-1 regime 分层）已从单品报告抽离为外部常驻卡片
    market_expectancy_card()（市场级信息，同族品重复无意义）；本函数仅保留单品特有的 trace 注入，
    build_analysis_ctx 与 save_analysis_result 共用，保证快照/重建口径一致。
    """
    fd = dict(fd or {})
    _src_labels = [_SOURCE_LABELS.get(str(s), str(s)) for s in (fd.get("deduction_sources") or [])]
    _caveats = []
    _action_label = str(fd.get("action_label") or "")
    if "恐慌" in _action_label:
        _caveats.append(
            "恐慌族口径风险：回放用价格近似情绪，生产用真实贪婪指数；"
            "real/approx 尺度未对齐（spearman 0.092、real 偏高 +16.76、sent≥75 一致率 45.8%），外推置信度低。"
        )
    _rm = getattr(analysis, "research_metrics", None) or {}
    if ("吸筹" in _action_label or "supply_contraction_accumulation" in (fd.get("deduction_sources") or [])):
        if _rm.get("supply_contract"):
            _state = _rm.get("price_state")
            _s7 = _rm.get("s7")
            _s30 = _rm.get("s30")
            _chg7 = _rm.get("chg7")
            _num = ""
            if _s7 is not None and _s30 is not None and _chg7 is not None:
                _num = f"（s7={_s7:.0f}，s30={_s30:.0f}，chg7={_chg7:+.1f}%）"
            if _state == "up":
                _caveats.append(
                    "供给收缩三态=价涨量缩·真吸筹，理论上偏正面；研究截面 win14 28.9% / 均值 -4.83%"
                    f"{_num}。仅观察标注，不改变现有决策。"
                )
            elif _state == "down":
                _caveats.append(
                    "供给收缩三态=价跌量缩·下跌惜售，研究截面 win14 38.5% / 均值 +3.05%"
                    f"{_num}。相对最好但仍为观察层，不接 buy。"
                )
            elif _state == "flat":
                _caveats.append(
                    "供给收缩三态=价平量缩·挂单撤走（现引擎按吸筹处理）；研究截面 win14 22.2% / 均值 -5.67%"
                    f"{_num}。仅标注，不改变现有 buy 口径。"
                )
            else:
                _caveats.append("供给收缩三态标注数据不足，保持现有结论，不调整动作。")
        else:
            _caveats.append(
                "供给收缩三态：当前未满足 s7≤s30×0.85 的严格收缩口径，仍按现有动作展示，不改变结论。"
            )
    # O4（2026-08-15）：Δspread 走阔陷阱指纹软标注——buy 信号时提示，不改决策
    if (fd.get("action") == "buy") and getattr(analysis, "name", None):
        _trap = _spread_trap_note(analysis.name)
        if _trap:
            _caveats.append(_trap)
    # 第一批（2026-08-16）：族特征卡软标注——buy 信号时展示所属族的历史特征，不改决策
    if fd.get("action") == "buy":
        _fc = _family_card_note(fd.get("action_label") or "")
        if _fc:
            _caveats.append(_fc)
    # F 判别风险提示层（2026-08-16 落地批次）：阴跌派发后急拉的反抽/真反转标注（任何动作均提示）
    if getattr(analysis, "name", None):
        _fn = _f_pullback_note(analysis.name)
        if _fn:
            _caveats.append(_fn)
    # 大盘语境行（2026-08-17 模块 A，纯引擎无关）：当前时期+大盘动作+该时期大盘自身前视证据
    try:
        from pipeline.market_signal import market_signal as _ms
        _msig = _ms()
        if _msig.get("ok") and _msig.get("period") != "unknown":
            _fwd = _msig.get("period_forward") or {}
            _caveats.append(
                "大盘语境：当前 {}——{}（该时期大盘自身前视 14d {}、30d {}，3 年回放证据，非预测）".format(
                    _msig["period"], _msig.get("action_note", ""),
                    _fwd.get("fwd14", "n/a"), _fwd.get("fwd30", "n/a"))
            )
    except Exception:
        pass
    # 独特性状态行（2026-08-17 查漏补缺，纯展示）：全部预注册形式命中标注（假设验证，不改变决策）
    if getattr(analysis, "name", None):
        _caveats.extend(_uniqueness_note(analysis.name))
    fd["trace"] = {
        "zone": fd.get("zone_label", ""),
        "bucket": fd.get("state_bucket", ""),
        "sources": _src_labels,
    }
    fd["research_caveats"] = _caveats
    return fd

def _position_pct(position):
    if isinstance(position, dict):
        return position.get("percentile_90d")
    if position is not None and hasattr(position, "percentile_90d"):
        return position.percentile_90d
    return None


def _supply_display(supply_dict, position):
    """供给语义统一（纯展示层）：低位/中位收缩=吸筹；高位（分位>70%）收缩=锁仓诱多嫌疑，与庄家口径一致。"""
    if not isinstance(supply_dict, dict):
        return supply_dict
    out = dict(supply_dict)
    pct = _position_pct(position)
    if out.get("supply_risk") == "hoarding" and pct is not None and pct > 70:
        out["supply_risk"] = "trap"
        out["supply_risk_label"] = "📦 高位收缩·锁仓诱多嫌疑"
        out["supply_risk_note"] = "供给收缩但价格处高位（分位>70%），更可能是庄家锁仓诱多：禁止追涨，持仓注意减仓"
    return out


# ============================================================
#  贴纸庄盘指纹（2026-08-12 展示层，只读 S-1 深历史研究快照）
#  依据 references/first-principles-manipulation.md：贴纸天然适合坐庄，
#  尖顶崩塌后长期不复原（144 品：峰后 90d 中位剩 31.9%）；本块仅展示
#  「已被爆炒过/正在回落」的事实，不产生任何决策信号（H1 回测验证中）。
# ============================================================
_STICKER_DEEP_CACHE = {"mtime": 0.0, "data": {}}


def _load_sticker_deep():
    """只读加载贴纸深历史研究快照（data/_exp_sticker_deep_full.jsonl，S-1 产物）。
    带 mtime 缓存：S-1 回填进行中，文件变化时自动重载。"""
    _p = Path(__file__).resolve().parent.parent / "data" / "_exp_sticker_deep_full.jsonl"
    try:
        _mtime = _p.stat().st_mtime
    except OSError:
        return {}
    if _STICKER_DEEP_CACHE["mtime"] == _mtime:
        return _STICKER_DEEP_CACHE["data"]
    _data = {}
    try:
        with io.open(_p, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _o = json.loads(_line)
                except Exception:
                    continue
                _pts = [(d, v) for d, v in _o.get("points", [])
                        if isinstance(v, (int, float)) and v > 0]
                if len(_pts) >= 60:
                    _data[_o.get("name", "")] = _pts
    except OSError:
        return {}
    _STICKER_DEEP_CACHE.update(mtime=_mtime, data=_data)
    return _data


def sticker_whale_fingerprint(name):
    """贴纸庄盘指纹（展示层，只读）：max_gain / 全样本分位 / 尖顶形态 / 距峰值回撤。
    非贴纸或无深历史返回 None；本函数不参与任何引擎决策。"""
    if not name or not name.startswith("印花 |"):
        return None
    _series = _load_sticker_deep().get(name)
    if not _series:
        return None
    _prices = [v for _, v in _series]
    _lo, _hi = min(_prices), max(_prices)
    if _lo <= 0 or _hi <= 0:
        return None
    _i_hi = _prices.index(_hi)
    _after3 = _prices[_i_hi + 1:_i_hi + 4]
    _after14 = _prices[_i_hi + 1:_i_hi + 15]
    _max_gain = _hi / _lo - 1
    _gains = []
    _batch_gains = None
    _batch = name.split("|")[-1].strip() if "|" in name else None
    for _bn, _pts in _load_sticker_deep().items():
        _lo2 = min(v for _, v in _pts)
        _hi2 = max(v for _, v in _pts)
        if _lo2 > 0 and _hi2 > 0:
            _gains.append(_hi2 / _lo2 - 1)
            if _batch and _bn.split("|")[-1].strip() == _batch:
                _batch_gains = _batch_gains or []
                _batch_gains.append(_hi2 / _lo2 - 1)
    _rank = (sum(1 for g in _gains if g >= _max_gain) / len(_gains) * 100) if _gains else None
    return {
        "max_gain": _max_gain,
        "gain_rank_pct": _rank,
        "dd3": (min(_after3) / _hi - 1) * 100 if len(_after3) >= 3 else None,
        "dd14": (min(_after14) / _hi - 1) * 100 if _after14 else None,
        "dd_now": (_prices[-1] / _hi - 1) * 100,
        "vs_start": (_prices[-1] / _prices[0] - 1) * 100,
        "peak_date": _series[_i_hi][0],
        "issue_price": _prices[0],
        "n": len(_gains),
        "batch": _batch,
        "batch_median": statistics.median(_batch_gains) if _batch_gains else None,
        "batch_max": max(_batch_gains) if _batch_gains else None,
        "batch_n": len(_batch_gains) if _batch_gains else 0,
    }


def render_sticker_whale_block(fp):
    """庄盘指纹 HTML fragment（模板变量与静态报告注入共用；纯展示层零决策）。"""
    if not fp:
        return ""

    def _fmt(x, signed=False, suffix=""):
        if x is None:
            return "--"
        return ("%+.0f%%" if signed else "%.0f%%") % x + suffix

    _warn = ""
    if fp.get("dd_now") is not None and fp["dd_now"] < -70:
        _warn = ('<div style="margin-top:6px;font-size:11px;color:var(--yellow);">'
                 '⚠️ 距历史峰值已回落 &gt;70%%：若已历经过一轮爆炒，非 Major 前置期勿按枪皮逻辑抄底'
                 '（尖顶崩塌预测 H1 回测验证中，未进决策）。</div>')
    _rank = fp.get("gain_rank_pct")
    _rank_txt = ("（%d 品中前 %.0f%%）" % (fp.get("n") or 0, _rank)) if _rank is not None else "（样本不足）"
    _batch_line = ""
    if fp.get("batch_n"):
        _bm = fp.get("batch_median") or 0
        _ratio = fp.get("max_gain") / _bm if _bm else None
        _tag = "（个别品巨幅 = 选品坐庄特征）" if _ratio and _ratio >= 3 else "（同届普涨，非庄盘特征）"
        _batch_line = ('同届分化（%s，%d 品）：中位 %+.0f%%%% / 最大 %+.0f%%%%；该品 = 中位 ×%.1f%s<br>'
                       % (fp.get("batch") or "—", fp.get("batch_n"), _bm * 100,
                          (fp.get("batch_max") or 0) * 100, _ratio or 0, _tag))
        _batch_line = _batch_line.replace("%", "%%")
    return (
        '<details style="margin-top:10px;font-size:12px;color:var(--text-secondary);">'
        '<summary style="cursor:pointer;font-weight:700;color:var(--text-primary);font-size:14px;">'
        '📛 庄盘指纹（贴纸专项 · 深历史）</summary>'
        '<div style="margin-top:6px;line-height:1.9;padding:8px 10px;background:rgba(100,116,139,0.08);border-radius:8px;">'
        '历史脉冲：区间最高涨幅 <b>%+.0f%%</b>%s<br>'
        '尖顶形态：峰后 3d %s / 14d %s<br>'
        '距历史峰值（%s）：现价 = 峰值的 %s（回落 %s）<br>'
        '现价 vs 深历史起点（2025-01 ≈ 发行价）：%s<br>'
        + _batch_line +
        _warn +
        '</div></details>'
    ) % (
        fp["max_gain"] * 100, _rank_txt,
        _fmt(fp.get("dd3"), signed=True), _fmt(fp.get("dd14"), signed=True),
        fp.get("peak_date", "—"),
        _fmt((1 + fp.get("dd_now", 0) / 100) * 100), _fmt(fp.get("dd_now"), signed=True),
        _fmt(fp.get("vs_start"), signed=True),
    )


def build_analysis_ctx(analysis, kline_stale_days=None, kline_stale_date="",
                       holding_ctx=None, market_30d_change=None, market_th=None, sentiment=50.0,
                       collected_at=""):
    """三条分析路径共用的模板上下文（与原 api_items_search/analyze 输出一致）。

    展示层增强（不参与决策，参数冻结不受影响）：
    - fusion_decision.trace：决策链 trace（2026-08-12 起期望徽章已抽离为 market_expectancy_card）
    - supply_analysis：高位供给收缩语义统一（锁仓诱多嫌疑）
    """
    # F-3.7 持仓浮亏双路径（纯展示层，回测 data/stop_loss_backtest.json）：有持仓时复用批量扫描同一套建议口径
    holding_advice = None
    if holding_ctx and holding_ctx.get("holding"):
        try:
            from pipeline.batch_scan import _portfolio_advice
            _sold_recent = 0
            _iid = holding_ctx.get("item_id")
            if _iid:
                try:
                    _conn_s = db.get_conn()
                    try:
                        _sold_recent = db.sold_qty_recent(_conn_s, int(_iid))
                    finally:
                        _conn_s.close()
                except Exception:
                    _sold_recent = 0
            holding_advice = _portfolio_advice(
                True, float(holding_ctx.get("avg_cost") or 0), int(holding_ctx.get("qty") or 1),
                analysis.price_rmb or 0, analysis,
                market_th=market_th, sentiment_score=sentiment,
                market_30d_change=market_30d_change, total_assets=0.0, sold_recent=_sold_recent)
        except Exception as _he:
            _log.warning(f"holding advice failed {analysis.name}: {_he}")
    # F-3.13 (2026-08-09) 持仓品「建议动作」以持仓风控矩阵为准（止损/补仓/止盈优先于入场信号），
    # 与下方持仓建议卡片口径一致；仅展示层，不改引擎 fusion_decision。
    holding_action = None
    if holding_advice:
        _sp2 = holding_advice.get("stop_plan") or {}
        _sa2 = _sp2.get("sell_action")
        _ha = holding_advice.get("action") or ""
        _cur = analysis.price_rmb or 0
        if _sa2 in ("sell", "reduce"):
            holding_action = {
                "action": "sell" if _sa2 == "sell" else "reduce",
                "label": "清仓/止损" if _sa2 == "sell" else "减仓止损",
                "signal": "止损评估·" + str(_sp2.get("state") or ""),
                "price": _cur, "qty": int(_sp2.get("sell_qty") or 0),
            }
        elif _ha == "可分批补仓":
            _adds2 = holding_advice.get("add_positions") or []
            holding_action = {
                "action": "add", "label": "补仓", "signal": _ha,
                "price": float(_adds2[0]["price"]) if _adds2 else _cur,
                "qty": int(_adds2[0]["qty"]) if _adds2 else 0,
            }
        elif _ha in ("建议止盈减仓", "大幅盈利，部分止盈"):
            holding_action = {
                "action": "reduce", "label": "减仓止盈", "signal": _ha,
                "price": _cur, "qty": int(holding_advice.get("reduce_qty") or 0),
            }
        else:
            holding_action = {"action": "hold", "label": "观望", "signal": _ha,
                              "price": _cur, "qty": 0}
    fd = _fd_display(analysis.fusion_decision, analysis)
    supply = _supply_display(getattr(analysis, "supply_analysis", None), getattr(analysis, "position", None))
    # F-3.16：仅用户主动加入自选——报告页按 in_watchlist 状态展示「加入自选」按钮
    _in_wl = False
    try:
        _conn_wl = db.get_conn()
        try:
            _rw_wl = _conn_wl.execute("SELECT in_watchlist FROM items WHERE name=?", (analysis.name,)).fetchone()
            _in_wl = bool(_rw_wl and _rw_wl["in_watchlist"])
        finally:
            _conn_wl.close()
    except Exception:
        pass
    return {
        "name": analysis.name,
        "price_rmb": analysis.price_rmb,
        "supply_analysis": supply,
        "position": analysis.position,
        "aux": analysis.aux,
        "cycle": analysis.cycle,
        "liquidity": analysis.liquidity,
        "probability": analysis.probability,
        "value": analysis.value,
        "whale": analysis.whale,
        "data_quality": analysis.data_quality,
        "trend_health": analysis.trend_health,
        "fusion_decision": fd,
        "error": None,
        "kline_stale_days": kline_stale_days,
        "kline_stale_date": kline_stale_date,
        "price_zones": analysis.price_zones,
        "holding_advice": holding_advice,
        "holding_action": holding_action,
        "is_holding": bool(holding_ctx and holding_ctx.get("holding")),
        "analysis_time": datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M"),
        "in_watchlist": _in_wl,
        "collected_at": collected_at or "",
        "sticker_whale_html": render_sticker_whale_block(sticker_whale_fingerprint(analysis.name)),
    }
