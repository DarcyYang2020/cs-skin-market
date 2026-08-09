"""单品分析服务层（2026-08-07 重构）。

从 webapp/main.py 抽出：kline 兜底 / 脏价校验 / 锚价校正 / 大盘上下文 / 快照落库 /
统一分析核心 analyze_fresh()。合并 api_items_search / api_items_analyze /
api_watchlist_analyze 三条约 90% 重复的分析路径；批量扫描 _scan_item 因
「价格校验先行 + 参数子集 + 结果结构不同」暂保留原流程（调用本模块助手函数）。
"""
import asyncio, copy, json, logging, sys
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
KLINE_FRESH_SINGLE = 0     # 单品主动分析（search/analyze/watchlist analyze）
KLINE_FRESH_BATCH = 3      # 批量扫描 / 午间监控轻量刷新
KLINE_FRESH_DISCOVER = 3   # discover 全量/增量扫描


def _history_to_bars(rows):
    """price_history 行 -> 90 日 K 线 SimpleNamespace 列表（close/high/low/in_sale_count）。"""
    import types as _types
    bars = []
    for r in rows:
        price = float(r["price_rmb"] or 0)
        bars.append(_types.SimpleNamespace(
            ts=0, date=r["date"], close=price, high=price, low=price,
            volume=float(r["volume_day"] or 0),
            in_sale_count=int(r["in_sale_count"] or 0),  # 去量: 在售量为唯一量源（勿用 volume_total）
            tx_amount=0, tx_count=0, survive=0,
        ))
    return bars


def db_kline_fresh(good_id, name, max_stale_days=KLINE_FRESH_BATCH):
    """DB 新鲜 K 线判定：定位 items 行 -> 近 90 日价格 -> 行数>=14 且最新日期距今<=max_stale_days。
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
        return {"bars": _history_to_bars(rows), "stale": stale, "last_date": last_date,
                "item_id": row["id"], "db_name": row["name"], "yyyp_id": row["yyyp_id"] or ""}
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
    return it


async def resolve_item(good_id, name, max_stale_days=KLINE_FRESH_BATCH):
    """复用优先入口：DB 新鲜则返回 DB ItemData（不采集）；否则走 csQAQ 采集。
    返回 ItemData（可能 from_db=True）或 None。"""
    fresh = db_kline_fresh(good_id, name, max_stale_days)
    if fresh:
        _log.info(f"采集复用 DB {fresh['db_name']}: stale={fresh['stale']}d bars={len(fresh['bars'])}")
        return item_from_db(fresh, good_id)
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
    new_last = closes[-1]
    if anchor_price and anchor_price > 0 and new_last > 0:
        dev_anchor = abs(new_last / anchor_price - 1)
        if dev_anchor > 0.20:
            return False, "最新价¥%.2f vs 悠悠锚¥%.2f 偏差%.0f%%" % (new_last, anchor_price, dev_anchor * 100)
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
        return False, "最新价¥%.2f vs DB ¥%.2f 偏差%.0f%%，序列内跳变%.0f%%" % (new_last, db_last, dev * 100, max_jump * 100)
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


def market_snapshot():
    """Market context from stored index history (pct/z/cycle/th/chg7/chg30/sentiment).

    指数统计复用 pipeline.market_context.market_index_stats（与监控 _market_ctx_from_db 同源）；
    情绪保持在线口径 compute_sentiment_score（10min 缓存），监控路径用 DB 口径。
    """
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
    return {
        "history": market_history,
        "pct": stats["pct"], "z": stats["z"], "cycle": stats["cycle"],
        "th": stats["th"], "chg7": stats["chg7"], "chg30": stats["chg30"],
        "drop21": stats["drop21"],
        "sentiment": sentiment,
    }


def recent_buy_dates(conn, item_id, days=7):
    """Snapshot buy-signal dates within the last N days (for 7-day signal clustering)."""
    cutoff = (datetime.now(TZ_BJ) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT date FROM snapshots WHERE item_id=? AND action IN ('buy','oversold_buy') AND date >= ? ORDER BY date DESC",
        (item_id, cutoff),
    ).fetchall()
    return [r["date"][:10] for r in rows]


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
    if isinstance(getattr(analysis, "fusion_decision", None), dict):
        action = analysis.fusion_decision.get("action", "")
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
            "UPDATE snapshots SET report_html=?, total_score=?, grade=?, price_rmb=?, score_scarcity=?, score_volume=?, score_market=?, score_liquidity=?, recommendation=?, action=?, bid_highest=?, bid_7d_chg=?, bid_30d_chg=?, spread_pct=?, spread_avg=? WHERE id=?",
            (report_html, score, grade, price_rmb,
             analysis.value.scarcity if hasattr(analysis.value, "scarcity") else 0,
             analysis.value.volume if hasattr(analysis.value, "volume") else 0,
             analysis.value.market_sentiment if hasattr(analysis.value, "market_sentiment") else 0,
             analysis.value.liquidity if hasattr(analysis.value, "liquidity") else 0,
             summary_json, action, *_bid_vals(order_book), existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO snapshots (item_id, date, report_html, total_score, grade, price_rmb, score_scarcity, score_volume, score_market, score_liquidity, recommendation, action, bid_highest, bid_7d_chg, bid_30d_chg, spread_pct, spread_avg) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, today, report_html, score, grade, price_rmb,
             analysis.value.scarcity if hasattr(analysis.value, "scarcity") else 0,
             analysis.value.volume if hasattr(analysis.value, "volume") else 0,
             analysis.value.market_sentiment if hasattr(analysis.value, "market_sentiment") else 0,
             analysis.value.liquidity if hasattr(analysis.value, "liquidity") else 0,
             summary_json, action, *_bid_vals(order_book)),
        )
    conn.commit()


def save_analysis_result(analysis, kline_stale_days=None, kline_stale_date=""):
    """渲染简洁报告并 upsert 到 analysis_results（单品分析/批量扫描共用，按 name 覆盖老数据）。"""
    try:
        grade = analysis.value.grade
        th = analysis.trend_health or {}
        trend_dir = th.get("direction", "")
        trend_score = th.get("score", 0)
        report_html = templates.get_template("partials/analysis.html").render({
            "name": analysis.name,
            "price_rmb": analysis.price_rmb,
            "supply_analysis": analysis.supply_analysis,
            "position": analysis.position,
            "aux": analysis.aux,
            "cycle": analysis.cycle,
            "liquidity": analysis.liquidity,
            "probability": analysis.probability,
            "value": analysis.value,
            "whale": analysis.whale,
            "data_quality": analysis.data_quality,
            "trend_health": analysis.trend_health,
            "fusion_decision": analysis.fusion_decision,
            "error": None,
            "kline_stale_days": kline_stale_days,
            "kline_stale_date": kline_stale_date,
            "price_zones": analysis.price_zones,
            "buy_distance": analysis.buy_distance,
            "analysis_time": _now_str(),
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
                        auto_watchlist=True):
    """单品分析统一核心：大盘上下文 + K线兜底/锚价校正 + 引擎分析 + 落库 + 快照 + 报告。

    参数：
      item            fetch_item_detail 返回的详情对象（含 kline_90d/order_book/price_rmb 等）
      good_id         csQAQ good id
      exact_name      清洗后的规范名
      db_item_id      已有 DB 行 id（watchlist 路径；None 时用 upsert 后的 pid）
      apply_anchor    是否应用锚价校正（search/analyze=True；watchlist 沿用历史行为=False）
      hard_error_no_kline  K 线获取失败时抛 AnalysisAbort（search 路径；其他路径降级用锚价单点）
      allow_single_price K 线为空时降级用单点锚价分析（watchlist 历史行为；search/analyze 传空保持原样）
      auto_watchlist   分析后是否自动加入自选（2026-08-09 方案A：search/单品分析=True；查看报告=False，不污染关注列表）
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
    try:
        recent_buys = recent_buy_dates(conn_r, use_id)
    finally:
        conn_r.close()

    analysis = item_analysis.run_item_analysis(
        name=exact_name,
        prices=price_history if price_history else ([price_rmb] if allow_single_price else []),
        supply_hist=supply_history if supply_history else None,
        order_book=item.order_book,
        index_change_7d=idx.change_7d,
        market_history=market_history,
        market_pct_90d=ms["pct"],
        market_zscore=ms["z"],
        market_cycle=ms["cycle"],
        market_th_score=ms["th"],
        market_30d_change=ms["chg30"],
        market_drop21=ms.get("drop21", 0),
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
                db.save_price_history_batch(conn_k, use_id, daily_bars)
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
    save_analysis_result(analysis, kline_stale_days, kline_stale_date)

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
                    source="analyze")
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
                                "qty": int(_hr["quantity"] or 1)}
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


def _expectancy_badge(action_label):
    """决策条回测徽章（纯展示层）：按 ITEM_EXPECTANCY_STATS 口径匹配（含「恐慌」→panic / 含「深值」→deep_value / 其余→accumulate）。"""
    if not action_label:
        return None
    key = "panic" if "恐慌" in action_label else ("deep_value" if "深值" in action_label else "accumulate")
    st = _config.ITEM_EXPECTANCY_STATS.get(key)
    if not st:
        return None
    return {
        "label": st.get("label", key),
        "n": st.get("n"),
        "events": st.get("events"),
        "win14": st.get("win14"),
        "avg14": st.get("avg14"),
        "win30": st.get("win30"),
        "avg30": st.get("avg30"),
        "ci14_lo": st.get("ci14_lo"),
        "ci14_hi": st.get("ci14_hi"),
    }


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


def build_analysis_ctx(analysis, kline_stale_days=None, kline_stale_date="",
                       holding_ctx=None, market_30d_change=None, market_th=None, sentiment=50.0):
    """三条分析路径共用的模板上下文（与原 api_items_search/analyze 输出一致）。

    展示层增强（不参与决策，参数冻结不受影响）：
    - fusion_decision.expectancy：决策条回测徽章（族 14d 胜率 / 30d 期望）
    - supply_analysis：高位供给收缩语义统一（锁仓诱多嫌疑）
    """
    # F-3.7 持仓浮亏双路径（纯展示层，回测 data/stop_loss_backtest.json）：有持仓时复用批量扫描同一套建议口径
    holding_advice = None
    if holding_ctx and holding_ctx.get("holding"):
        try:
            from pipeline.batch_scan import _portfolio_advice
            holding_advice = _portfolio_advice(
                True, float(holding_ctx.get("avg_cost") or 0), int(holding_ctx.get("qty") or 1),
                analysis.price_rmb or 0, analysis,
                market_th=market_th, sentiment_score=sentiment,
                market_30d_change=market_30d_change, total_assets=0.0)
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
    fd = dict(analysis.fusion_decision or {})
    fd["expectancy"] = _expectancy_badge(fd.get("action_label"))
    _src_labels = [_SOURCE_LABELS.get(str(s), str(s)) for s in (fd.get("deduction_sources") or [])]
    fd["trace"] = {
        "zone": fd.get("zone_label", ""),
        "bucket": fd.get("state_bucket", ""),
        "sources": _src_labels,
    }
    supply = _supply_display(getattr(analysis, "supply_analysis", None), getattr(analysis, "position", None))
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
        "analysis_time": datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M"),
    }
