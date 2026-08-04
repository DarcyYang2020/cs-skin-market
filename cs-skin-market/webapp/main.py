"""CS-Market Web App - FastAPI application."""

import sys, io, asyncio, json, re, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logging
from pipeline import config, db, collector, valuation, index_analysis, item_analysis
from pipeline import collector_csqaq, collector_youpin

_web_log = logging.getLogger("webapp")

# In-memory analysis cache
_analysis_cache = {}

def _cached_analysis(item_id, compute_fn):
    import time as _time
    now = _time.time()
    entry = _analysis_cache.get(item_id)
    if entry and (now - entry[0]) < 1800:
        return entry[1]
    result = compute_fn()
    _analysis_cache[item_id] = (now, result)
    return result

app = FastAPI(title="CS-Market")
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
TZ_BJ = timezone(timedelta(hours=8))


def _ae(msg: str) -> str:
    """Wrap error message in styled HTML."""
    return f"""<div class="card" style="border-color: rgba(239,68,68,0.5);">
<div class="card-header"><span class="card-title">&#9888;&#65039; 错误</span></div>
<p style="color: var(--red);">{msg}</p>
</div>"""

def _now_str() -> str:
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")

def _today_str() -> str:
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")


def _db_kline_fallback(good_id, name):
    """csQAQ 图表采集失败时，用数据库缓存的90日K线兜底。Returns (bars, stale_days, last_date) or (None, None, "")."""
    import types as _types
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
        bars = []
        for r in rows:
            price = float(r["price_rmb"] or 0)
            bars.append(_types.SimpleNamespace(
                ts=0, date=r["date"], close=price, high=price, low=price,
                volume=float(r["volume_day"] or 0),
                in_sale_count=int(r["volume_total"] or 0),
                tx_amount=0, tx_count=0, survive=0,
            ))
        return bars, stale, last_date
    except Exception as _e:
        _web_log.warning(f"db kline fallback failed: {_e}")
        return None, None, ""
    finally:
        conn.close()


async def _resolve_good_id(query):
    """定位 good_id：DB 已知（分析过的品秒回）→ Playwright 搜索兜底。Returns (good_id, page_title)."""
    try:
        conn = db.get_conn()
        try:
            row = db.find_item(conn, query)
            if row and row["good_id"]:
                return row["good_id"], row["name"]
        finally:
            conn.close()
    except Exception:
        pass
    return await collector_csqaq.search_good_id(query)


def _cached_youpin_volume(good_id):
    """悠悠成交量缓存（settings 表）。Returns (vol, vol_map, fresh)。

    fresh 表示是否为当天抓取；即使过期也返回最近一次历史 map，供软过期回退。
    """
    if not good_id:
        return 0, {}, False
    conn = db.get_conn()
    try:
        raw = db.get_setting(conn, f"uu_vol_{good_id}")
        if not raw:
            return 0, {}, False
        data = json.loads(raw)
        vol = float(data.get("vol") or 0)
        vol_map = data.get("map") or {}
        fresh = data.get("date") == _today_str()
        return vol, vol_map, fresh
    except Exception:
        pass
    finally:
        conn.close()
    return 0, {}, False


def _save_youpin_volume(good_id, vol, vol_map):
    """滚动累积：新 7 天真实量并入历史 map，不丢旧日期（攒够 20+ 天量能项才激活）。"""
    if not good_id:
        return
    conn = db.get_conn()
    try:
        merged = dict(vol_map or {})
        old_raw = db.get_setting(conn, f"uu_vol_{good_id}")
        if old_raw:
            try:
                old_map = (json.loads(old_raw).get("map") or {})
                for _d, _v in old_map.items():
                    merged.setdefault(_d, _v)
            except Exception:
                pass
        db.set_setting(conn, f"uu_vol_{good_id}", json.dumps({"date": _today_str(), "vol": vol, "map": merged}))
        conn.commit()
    except Exception as _e:
        _web_log.warning(f"youpin cache save failed: {_e}")
    finally:
        conn.close()


def _apply_volume_map(daily_bars, vol_map):
    """用悠悠逐日成交量回填 daily_bars（按 bar.date 匹配）。

    未覆盖日期清 0：避免旧采样假量混入长窗口量能判断（真实量天数以非 0 计）。
    """
    if not daily_bars or not vol_map:
        return
    for bar in daily_bars:
        v = vol_map.get(getattr(bar, "date", ""))
        bar.volume = int(v) if v and v > 0 else 0


def _kline_price_sane(daily_bars, item_id, anchor_price=None):
    """K线价格合理性校验，防 csQAQ 偶发串品/脏价覆盖历史。

    规则：新采集最新价 vs DB 该品最近历史价 偏差>25%，且新序列内存在单日跳变>30%，
    判为疑似脏数据（如 2026-08-01 水灵 595 vs 真实 424）。
    规则2（2026-08-04 增强）：anchor_price（悠悠锚）存在时，最新 close vs 锚价偏差>20%
    判脏——拦截「整条序列整体口径偏移」型脏价（如死寂空间 chart 883 vs 悠悠 614，
    序列内无大跳变但整体偏离，规则1漏检）。
    Returns (ok: bool, msg: str)；ok=False 时调用方应跳过落库，保留 DB 旧数据。
    """
    if not daily_bars or len(daily_bars) < 3:
        return True, ""
    closes = [b.close for b in daily_bars if getattr(b, "close", 0) and b.close > 0]
    if len(closes) < 3:
        return True, ""
    new_last = closes[-1]
    # 锚定校验：chart 最新价 vs 悠悠锚价（价格锚定同口径，偏差>20% 视为整体口径偏移脏价；不依赖 DB 历史）
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
        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT price_rmb FROM price_history WHERE item_id=? AND date < ? ORDER BY date DESC LIMIT 1",
                (item_id, last_date),
            ).fetchone()
            if row:
                db_last = row["price_rmb"] or 0
        finally:
            conn.close()
    except Exception:
        return True, ""
    if db_last <= 0 or new_last <= 0:
        return True, ""
    dev = abs(new_last / db_last - 1)
    if dev > 0.25 and max_jump > 0.30:
        return False, "最新价¥%.2f vs DB ¥%.2f 偏差%.0f%%，序列内跳变%.0f%%" % (new_last, db_last, dev * 100, max_jump * 100)
    return True, ""


async def _fetch_volume_cached(good_id, item):
    """单品成交量：当日缓存 → 悠悠有品逐日成交量(近7天真实成交) → info/good turnover_number 兜底。

    Returns:
        (today_vol, {date: vol})；today_vol 用于当日成交量，vol_map 用于回填全部 K 线 bar。
    """
    vol, vol_map, fresh = _cached_youpin_volume(good_id)
    if fresh:
        # 当天已有缓存：直接复用（当日 0 成交时用 turnover_number 兜底当日量）
        if vol > 0:
            return vol, vol_map
        turnover = getattr(item, "turnover_number", 0) or 0
        return (turnover if turnover > 0 else 0), vol_map
    # 非当天：先保留历史缓存，再尝试抓取最新悠悠数据
    cached_map = vol_map
    template_id = getattr(item, "yyyp_id", "") or ""
    if template_id:
        try:
            vol_map = await collector_youpin.fetch_youpin_volume(template_id)
        except Exception as _e:
            _web_log.warning(f"youpin volume failed: {_e}")
            vol_map = {}
        if vol_map:
            vol = float(vol_map.get(_today_str(), 0) or 0)
            _save_youpin_volume(good_id, vol, vol_map)
            return vol, vol_map
        # 抓取失败（token 过期/网络）：软过期回退——历史 map 照常回填，当日量 turnover 兜底
        if cached_map:
            turnover = getattr(item, "turnover_number", 0) or 0
            return (turnover if turnover > 0 else 0), cached_map
        _web_log.warning(f"youpin volume 无缓存且抓取失败: {template_id}")
    turnover = getattr(item, "turnover_number", 0) or 0
    if turnover > 0:
        return turnover, {}
    return 0, {}


def _market_snapshot():
    """Market context from stored index history (pct/z/cycle/th/chg7/chg30/sentiment)."""
    conn = db.get_conn()
    market_history = []
    market_pct = 50
    market_z = 0.0
    market_cycle = "unknown"
    market_th = 50
    market_7d_change = 0.0
    market_30d_change = 0.0
    market_21d_change = 0.0
    try:
        rows = conn.execute(
            "SELECT date, value FROM market_index ORDER BY date ASC"
        ).fetchall()
        market_history = [(r["date"], float(r["value"])) for r in rows] if rows else []
        values = [v for _, v in market_history if v > 0]
        if len(values) >= 30:
            current_m = values[-1]
            from pipeline.index_analysis import analyze_index
            _ires = analyze_index(market_history[-90:])
            _ipos = _ires.get("position", {}) if isinstance(_ires, dict) else {}
            market_pct = _ipos.get("percentile_90d", 50)
            market_z = _ipos.get("zscore_90d", 0)
            m7 = values[-7] if len(values) >= 7 else values[0]
            m30 = values[-30] if len(values) >= 30 else values[0]
            market_7d_change = round((current_m - m7) / m7 * 100, 1) if m7 > 0 else 0
            market_30d_change = round((current_m - m30) / m30 * 100, 1) if m30 > 0 else 0
            m21 = values[-21] if len(values) >= 21 else values[0]
            market_21d_change = round((current_m - m21) / m21 * 100, 1) if m21 > 0 else 0
            from pipeline.market_th import derive_market_cycle, compute_market_trend_health
            market_cycle = derive_market_cycle(values, len(values) - 1)
            try:
                _window = values[-90:]
                _mth = compute_market_trend_health(_window, volumes=None)
                market_th = _mth.corrected_score if hasattr(_mth, "corrected_score") else _mth.score
            except Exception:
                market_th = max(0, min(100, 50 + market_30d_change * 3))
    finally:
        conn.close()
    try:
        from pipeline.market_macro import compute_sentiment_score
        sentiment = float(compute_sentiment_score() or 50)
    except Exception:
        sentiment = 50.0
    return {
        "history": market_history,
        "pct": market_pct, "z": market_z, "cycle": market_cycle,
        "th": market_th, "chg7": market_7d_change, "chg30": market_30d_change,
        "drop21": market_21d_change,
        "sentiment": sentiment,
    }


def _recent_buy_dates(conn, item_id, days=7):
    """Snapshot buy-signal dates within the last N days (for 7-day signal clustering)."""
    cutoff = (datetime.now(TZ_BJ) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT date FROM snapshots WHERE item_id=? AND action IN ('buy','oversold_buy') AND date >= ? ORDER BY date DESC",
        (item_id, cutoff),
    ).fetchall()
    return [r["date"][:10] for r in rows]


def _save_item_snapshot(conn, item_id, analysis, price_rmb, today=None):
    """Render + upsert today report into snapshots; records fusion action for 7-day buy dedup."""
    if today is None:
        today = _now_str()
    report_html = templates.get_template("partials/analysis.html").render({
        "name": analysis.name,
        "price_rmb": analysis.price_rmb,
        "volume_day": analysis.volume_day,
        "volume_total": analysis.volume_total,
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
        "oob_price": "",
        "oob_grade": "",
        "price_zones": analysis.price_zones,
        "buy_distance": analysis.buy_distance,
        "analysis_time": _now_str(),
    })
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
    }, ensure_ascii=False)
    existing = conn.execute(
        "SELECT id FROM snapshots WHERE item_id=? AND date=?", (item_id, today)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE snapshots SET report_html=?, total_score=?, grade=?, price_rmb=?, score_scarcity=?, score_volume=?, score_market=?, score_liquidity=?, recommendation=?, action=? WHERE id=?",
            (report_html, score, grade, price_rmb,
             analysis.value.scarcity if hasattr(analysis.value, "scarcity") else 0,
             analysis.value.volume if hasattr(analysis.value, "volume") else 0,
             analysis.value.market_sentiment if hasattr(analysis.value, "market_sentiment") else 0,
             analysis.value.liquidity if hasattr(analysis.value, "liquidity") else 0,
             summary_json, action, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO snapshots (item_id, date, report_html, total_score, grade, price_rmb, score_scarcity, score_volume, score_market, score_liquidity, recommendation, action) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, today, report_html, score, grade, price_rmb,
             analysis.value.scarcity if hasattr(analysis.value, "scarcity") else 0,
             analysis.value.volume if hasattr(analysis.value, "volume") else 0,
             analysis.value.market_sentiment if hasattr(analysis.value, "market_sentiment") else 0,
             analysis.value.liquidity if hasattr(analysis.value, "liquidity") else 0,
             summary_json, action),
        )
    conn.commit()


def _save_analysis_result(analysis, kline_stale_days=None, kline_stale_date="", oob_price="", oob_grade=""):
    """渲染简洁报告并 upsert 到 analysis_results（单品分析/批量扫描共用，按 name 覆盖老数据）。"""
    try:
        grade = analysis.value.grade
        th = analysis.trend_health or {}
        trend_dir = th.get("trend_direction", "")
        trend_score = th.get("score", 0)
        report_html = templates.get_template("partials/analysis.html").render({
            "name": analysis.name,
            "price_rmb": analysis.price_rmb,
            "volume_day": analysis.volume_day,
            "volume_total": analysis.volume_total,
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
            "oob_price": oob_price,
            "oob_grade": oob_grade,
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
        _web_log.warning(f"Failed to save analysis result: {_e}")


def _verify_item_name(query: str, item_name: str) -> bool:
    """Check if the returned item name is related to the query."""
    if not item_name:
        return False
    WEAR_CONDITIONS = ["崭新出厂", "略有磨损", "久经沙场", "破损不堪", "战痕累累"]
    q_wear = None
    r_wear = None
    for wc in WEAR_CONDITIONS:
        if wc in query:
            q_wear = wc
        if wc in item_name:
            r_wear = wc
    if q_wear and r_wear and q_wear != r_wear:
        return False
    q = query.lower().replace(" | ", " ").replace("|", " ").strip("()")
    n = item_name.lower().replace(" | ", " ").replace("|", " ").strip("()")
    if q == n:
        return True
    if q in n or n in q:
        return True
    q_parts = set(q.split())
    n_parts = set(n.split())
    ascii_q = {w for w in q_parts if any(c.isascii() and c.isalpha() for c in w)}
    ascii_n = {w for w in n_parts if any(c.isascii() and c.isalpha() for c in w)}
    if ascii_q and ascii_n and ascii_q & ascii_n:
        return True
    chinese_q = set(c for c in q if "\u4e00" <= c <= "\u9fff")
    chinese_n = set(c for c in n if "\u4e00" <= c <= "\u9fff")
    if chinese_q and chinese_n:
        overlap = chinese_q & chinese_n
        if len(overlap) >= max(1, len(chinese_q) // 2):
            return True
    return False


def _clean_csqaq_name(raw_name: str) -> str:
    """Clean csQAQ page title to extract just the item name."""
    if not raw_name:
        return raw_name
    # Remove price lines (start with ¥)
    lines = raw_name.split("\n")
    WEAR_WORDS = ["崭新出厂", "略有磨损", "久经沙场", "破损不堪", "战痕累累"]
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("¥") or line.startswith("￥"):
            continue
        if re.match(r'^[\d.]+%$', line):
            continue
        if line.startswith("上涨") or line.startswith("下跌"):
            continue
        stripped = line.strip()
        if stripped in WEAR_WORDS:
            continue
        if len(stripped) < 5 and any(w in stripped for w in WEAR_WORDS):
            continue
        cleaned.append(line)
    real_names = [l for l in cleaned if '|' in l or '★' in l]
    if real_names:
        import re as _re2
        name = real_names[0]
        # Remove StatTrak™ label in any bracket variant
        name = _re2.sub(r'[（(]\s*StatTrak(™|\(TM\)|)?\s*[）)]', '', name)
        name = _re2.sub(r'StatTrak™|StatTrak\(TM\)|StatTrak', '', name)
        # Clean up empty parentheses
        name = name.replace('（）', '').replace('()', '')
        name = name.replace('  ', ' ').strip()
        return name
    if cleaned:
        return max(cleaned, key=len)
    return raw_name

# ---- Favicon ----
@app.get("/favicon.ico")
async def favicon():
    return HTMLResponse("", status_code=204)


# ---- DB migration ----
def _migrate_db():
    conn = db.get_conn()
    try:
        for col, defn in [
            ("holding", "INTEGER DEFAULT 0"),
            ("avg_cost", "REAL DEFAULT 0"),
            ("quantity", "INTEGER DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE items ADD COLUMN {col} {defn}")
            except Exception:
                pass
        try:
            conn.execute("ALTER TABLE snapshots ADD COLUMN report_html TEXT DEFAULT ''")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()

_migrate_db()


# ---- Dashboard context ----
def _dashboard_context():
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT value, change_7d, mood, date FROM market_index ORDER BY date DESC LIMIT 1"
        ).fetchone()
        mi = None
        last_update = "N/A"
        if row:
            from pipeline.collector import MarketIndex
            mi = MarketIndex(value=row["value"], change_7d=row["change_7d"], mood=row["mood"])
            last_update = row["date"]
        chart_rows = conn.execute(
            "SELECT date, value FROM market_index ORDER BY date ASC"
        ).fetchall()
        chart_data = [(r["date"], float(r["value"])) for r in chart_rows] if chart_rows else []
        return mi, last_update, chart_data
    finally:
        conn.close()


# ---- Dashboard page ----
@app.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    mi, last_update, chart_data = _dashboard_context()
    # Index analysis
    analysis_data = index_analysis.analyze_index_full(chart_data) if chart_data else None
    response = templates.TemplateResponse(request, "dashboard.html", {
        "active_page": "dashboard",
        "index": mi,
        "last_update": last_update,
        "chart_data": chart_data,
        "analysis": analysis_data,
    })
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


# ---- Search page ----
@app.get("/search", response_class=HTMLResponse)
async def page_search(request: Request, q: str = Query(default="")):
    conn = db.get_conn()
    results = []
    try:
        rows = conn.execute(
            "SELECT id, name, price_rmb, grade, trend_dir, trend_score, report_html, created_at FROM analysis_results ORDER BY created_at DESC"
        ).fetchall()
        results = [dict(r) for r in rows]
    finally:
        conn.close()
    response = templates.TemplateResponse(request, "search.html", {
        "active_page": "search",
        "query": q,
        "items": [],
        "analysis_results": results,
    })
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


async def _analysis_results_partial(request: Request):
    conn = db.get_conn()
    results = []
    try:
        rows = conn.execute(
            "SELECT id, name, price_rmb, grade, trend_dir, trend_score, report_html, created_at FROM analysis_results ORDER BY created_at DESC"
        ).fetchall()
        results = [dict(r) for r in rows]
    finally:
        conn.close()
    return templates.TemplateResponse(request, "partials/analysis_results.html", {"analysis_results": results})
# ---- Analysis Results API ----
@app.delete("/api/analysis/{result_id}")
async def api_analysis_delete(request: Request, result_id: int):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM analysis_results WHERE id = ?", (result_id,))
        conn.commit()
    finally:
        conn.close()
    return await _analysis_results_partial(request)

@app.post("/api/analysis/clear")
async def api_analysis_clear(request: Request):
    conn = db.get_conn()
    try:
        conn.execute("DELETE FROM analysis_results")
        conn.commit()
    finally:
        conn.close()
    return await _analysis_results_partial(request)

@app.get("/api/analysis/results")
async def api_analysis_results(request: Request):
    return await _analysis_results_partial(request)


# ---- Watchlist page ----
@app.get("/watchlist", response_class=HTMLResponse)
async def page_watchlist(request: Request):
    conn = db.get_conn()
    try:
        items_raw = db.watchlist_list_with_snapshots(conn)
        total_assets = float(db.get_setting(conn, "total_assets", 0) or 0)
        all_items = [dict(r) for r in items_raw]

        # ---- filters from URL params (keep state across pagination) ----
        wf = request.query_params.get("filter", "all")
        if wf not in ("all", "holding", "unheld"):
            wf = "all"
        wq = (request.query_params.get("q", "") or "").strip().lower()
        ws = request.query_params.get("sort", "newest")
        filtered = all_items
        if wf == "holding":
            filtered = [i for i in filtered if i.get("holding")]
        elif wf == "unheld":
            filtered = [i for i in filtered if not i.get("holding")]
        if wq:
            filtered = [i for i in filtered if wq in (i.get("name") or "").lower()]
        if ws == "name":
            filtered.sort(key=lambda i: (i.get("name") or "").lower())
        elif ws == "price_desc":
            filtered.sort(key=lambda i: i.get("latest_price") or 0, reverse=True)
        elif ws == "price_asc":
            filtered.sort(key=lambda i: i.get("latest_price") or 0)
        elif ws == "grade":
            _gorder = {"S": 0, "A": 1, "B": 2, "C": 3, "Z": 4}
            filtered.sort(key=lambda i: _gorder.get(i.get("latest_grade") or "Z", 4))

        # ---- per-item pnl + portfolio totals (holding items only) ----
        for item in all_items:
            item["pnl_pct"] = None
            if item.get("holding") and item.get("avg_cost", 0) > 0 and item.get("latest_price"):
                item["pnl_pct"] = (item["latest_price"] - item["avg_cost"]) / item["avg_cost"] * 100
        total_buy_cost = sum((i.get("avg_cost") or 0) * (i.get("quantity") or 0) for i in all_items if i.get("holding"))
        total_market = sum((i.get("latest_price") or 0) * (i.get("quantity") or 0) for i in all_items if i.get("holding"))
        total_pnl = total_market - total_buy_cost
        total_pnl_pct = (total_pnl / total_buy_cost * 100) if total_buy_cost > 0 else 0
        position_ratio = (total_buy_cost / total_assets * 100) if total_assets > 0 else 0

        # ---- pagination on filtered list ----
        PAGE_SIZE = 10
        total_items = len(filtered)
        total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        page = min(page, total_pages)
        items = filtered[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

        # Load trend health + parse latest_summary for each item
        import json as _json
        for item in items:
            th_raw = db.get_setting(conn, f"th_{item['id']}", "")
            try:
                item["trend_health"] = _json.loads(th_raw) if th_raw else None
            except Exception:
                item["trend_health"] = None
            summary_raw = item.get("latest_summary")
            if summary_raw:
                try:
                    item["analysis_summary"] = _json.loads(summary_raw)
                except Exception:
                    item["analysis_summary"] = None
            else:
                item["analysis_summary"] = None
        return templates.TemplateResponse(request, "watchlist.html", {
            "active_page": "watchlist",
            "items": items,
            "total_assets": total_assets,
            "total_buy_cost": total_buy_cost,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "position_ratio": position_ratio,
            "pagination": {"page": page, "total_pages": total_pages, "total_items": total_items},
            "wl_filter": wf,
            "wl_q": wq,
            "wl_sort": ws,
            "all_items_json": json.dumps(
                [{"id": i["id"], "name": i["name"], "holding": bool(i.get("holding"))} for i in all_items],
                ensure_ascii=False),
        })
    finally:
        conn.close()

# ---- Market refresh ----
@app.post("/api/market/refresh")
async def api_market_refresh(request: Request):
    try:
        idx = collector.fetch_market_index()
        if idx is None:
            return HTMLResponse(_ae("获取大盘数据失败"))
        conn = db.get_conn()
        try:
            today = _today_str()
            existing = conn.execute("SELECT id FROM market_index WHERE date = ?", (today,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE market_index SET value=?, change_7d=?, mood=? WHERE date=?",
                    (idx.value, idx.change_7d, idx.mood, today)
                )
            else:
                conn.execute(
                    "INSERT INTO market_index (date, value, change_7d, mood) VALUES (?,?,?,?)",
                    (today, idx.value, idx.change_7d, idx.mood)
                )
            conn.commit()
        finally:
            conn.close()
        mi, last_update, chart_data = _dashboard_context()
        analysis_data = index_analysis.analyze_index_full(chart_data) if chart_data else None
        return templates.TemplateResponse(request, "partials/dashboard_refresh.html", {
            "index": mi,
            "last_update": last_update,
            "chart_data": chart_data,
            "analysis": analysis_data,
        })
    except Exception as e:
        return HTMLResponse(_ae(f"刷新失败: {str(e)[:200]}"))


# ---- Item search ----
@app.post("/api/items/search")
async def api_items_search(request: Request, query: str = Form(...)):
    """Search + analyze in one step. Returns analysis result directly."""
    if not query or len(query.strip()) < 2:
        return HTMLResponse('<div class="card"><div class="empty-state" style="text-align:center;padding:40px;color:var(--text-muted);">请输入至少2个字符</div></div>')

    try:
        # Step 1: Search good_id (API 优先，毫秒级)
        good_id, page_title = await _resolve_good_id(query)
        if good_id == 0:
            return HTMLResponse('<div class="card"><div class="empty-state" style="text-align:center;padding:40px;color:var(--text-muted);">未找到相关饰品，请尝试简化关键词</div></div>')

        # Step 2: Fetch detail
        item = await collector_csqaq.fetch_item_detail(good_id)
        if item is None:
            return HTMLResponse('<div class="card"><div class="empty-state" style="text-align:center;padding:40px;color:var(--text-muted);">获取详情失败，请重试</div></div>')

        exact_name = _clean_csqaq_name(item.name or page_title or query)
        if not _verify_item_name(query, exact_name):
            return HTMLResponse('<div class="card"><div class="empty-state" style="text-align:center;padding:40px;color:var(--text-muted);">搜索结果与查询不匹配，请尝试更精确的关键词</div></div>')

        # Step 3: Run full analysis (same as /api/items/analyze)
        idx = collector.fetch_market_index()
        if idx is None or idx.value == 0:
            idx = collector.MarketIndex(value=0, change_7d=0, mood="neutral")

        
        price_rmb = item.price_rmb
        volume_total = item.volume_total  # max in_sale from num_data (supply, not volume)
        if volume_total == 0 and hasattr(item, 'in_sale_count') and item.in_sale_count:
            volume_total = item.in_sale_count

        daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
        # Fetch real daily volume from youpin (csqaq K-line has no volume data)
        vol_today, vol_map = await _fetch_volume_cached(good_id, item)
        _apply_volume_map(daily_bars, vol_map)

        volume_day = vol_today if vol_today > 0 else max(1, volume_total // 20)
        if vol_today > 0 and daily_bars and len(daily_bars) > 0:
            daily_bars[-1].volume = vol_today

        price_history = [k.close for k in daily_bars if k.close > 0] if daily_bars else []
        kline_stale_days = None
        kline_stale_date = ""
        if not price_history:
            _db_bars, _stale, _stale_date = _db_kline_fallback(good_id, exact_name)
            if _db_bars:
                daily_bars = _db_bars
                price_history = [k.close for k in daily_bars if k.close > 0]
                kline_stale_days, kline_stale_date = _stale, _stale_date
                _web_log.warning(f"search kline DB fallback for {exact_name} stale={_stale}d")
            else:
                return HTMLResponse(_ae("K线数据获取失败，请稍后重试（csQAQ 图表采集偶发为空，已自动重试仍失败）"))
        volume_history = [k.volume for k in daily_bars] if daily_bars else []
        supply_history = [k.in_sale_count for k in daily_bars] if daily_bars else []

        # Build market context
        ms = _market_snapshot()
        market_history = ms["history"]

        # Upsert item first: needed for recent buy dates + snapshot report
        conn_p = db.get_conn()
        try:
            pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id, yyyp_id=item.yyyp_id, in_watchlist=1)
            conn_p.commit()
        finally:
            conn_p.close()
        conn_r = db.get_conn()
        try:
            recent_buys = _recent_buy_dates(conn_r, pid)
        finally:
            conn_r.close()

        analysis = item_analysis.run_item_analysis(
            name=exact_name,
            prices=price_history,
            volumes=volume_history if volume_history else None,
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
        )
        # 报告价格锚定悠悠有品 DOM 价（chart fallback 价只补 K 线不参与定价）
        if price_rmb and price_rmb > 0:
            analysis.price_rmb = price_rmb
        analysis.volume_day = volume_day
        analysis.volume_total = volume_total
        if hasattr(analysis, 'aux') and analysis.aux:
            analysis.aux.turnover_rate = round(volume_day / volume_total * 100, 3) if volume_total > 0 else 0
            analysis.aux.mean_volume_7d = volume_day
    

        # 脏价校验：chart 最新 close vs 悠悠锚偏差>20% 时不落库（保留 DB 旧数据，防整体口径偏移脏价）
        _sane, _sane_msg = _kline_price_sane(daily_bars, pid, anchor_price=price_rmb)
        if not _sane:
            _web_log.warning(f"search kline skip {exact_name}: {_sane_msg}")
            daily_bars = None
        # Persist 90-day kline data (pid already upserted above)
        conn_p = db.get_conn()
        try:
            if daily_bars:
                db.save_price_history_batch(conn_p, pid, daily_bars)
            conn_p.commit()
        except Exception as _pe:
            _web_log.warning("kline persist failed: " + str(_pe))
        finally:
            conn_p.close()
        # Record snapshot so reports + 7-day buy dedup stay in sync
        conn_s = db.get_conn()
        try:
            _save_item_snapshot(conn_s, pid, analysis, price_rmb)
        finally:
            conn_s.close()
        # Save to analysis_results (同步至单品报告)
        _save_analysis_result(analysis, kline_stale_days, kline_stale_date)

        # Save to analysis_results table
        _save_analysis_result(analysis, kline_stale_days, kline_stale_date)

        ctx = {
            "name": analysis.name,
            "price_rmb": analysis.price_rmb,
            "volume_day": analysis.volume_day,
            "volume_total": analysis.volume_total,
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
            "error": None,"oob_price":"","oob_grade":"",
            "kline_stale_days": kline_stale_days,
            "kline_stale_date": kline_stale_date,
            "price_zones": analysis.price_zones,
            "buy_distance": analysis.buy_distance,
            "analysis_time": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        return templates.TemplateResponse(request, "partials/analysis.html", ctx)

    except Exception as e:
        import traceback
        _web_log.error(f"Search error: {e}\    n{traceback.format_exc()}")
        return HTMLResponse(_ae(f"分析失败: {str(e)[:300]}"))

# ---- Item analyze ----
@app.get("/api/items/analyze")
async def api_items_analyze(
    request: Request,
    name: str = Query(...),
    rarity: str = Query(default="restricted"),
    source: str = Query(default="case"),
    discontinued_years: float = Query(default=0),
):
    """Run comprehensive single-item analysis using item_analysis engine."""
    is_discontinued = discontinued_years > 0

    try:
        idx = collector.fetch_market_index()
        if idx is None or idx.value == 0:
            idx = collector.MarketIndex(value=0, change_7d=0, mood="neutral")

        good_id, page_title = await _resolve_good_id(name)
        if good_id == 0:
            return HTMLResponse(_ae("未找到物品: " + name))

        
        item = await collector_csqaq.fetch_item_detail(good_id)
        if item is None:
            return HTMLResponse(_ae(f"获取详情失败: good_id={good_id}"))
        exact_name = _clean_csqaq_name(item.name or page_title or name)

        if not _verify_item_name(name, exact_name):
            _web_log.warning(f"Item name '{exact_name}' does not match query '{name}', trying alternative search")
            simple_q = name.replace("(", "").replace(")", "").strip()
            if simple_q and simple_q != name:
                gid2, _ = await collector_csqaq.search_good_id(simple_q)
                if gid2 and gid2 != good_id:
                    item2 = await collector_csqaq.fetch_item_detail(gid2)
                    if item2 and item2.name:
                        exact_name2 = item2.name
                        if _verify_item_name(name, exact_name2):
                            good_id, item = gid2, item2
                            exact_name = exact_name2
                            _web_log.info(f"Switched to good_id={gid2}, name={exact_name}")

        price_rmb = item.price_rmb
        volume_total = item.volume_total
        if volume_total == 0 and hasattr(item, 'in_sale_count') and item.in_sale_count:
            volume_total = item.in_sale_count

        daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
        # Fetch real daily volume from youpin (csqaq K-line has no volume data)
        vol_today, vol_map = await _fetch_volume_cached(good_id, item)
        _apply_volume_map(daily_bars, vol_map)

        volume_day = vol_today if vol_today > 0 else max(1, volume_total // 20)
        if vol_today > 0 and daily_bars and len(daily_bars) > 0:
            daily_bars[-1].volume = vol_today

        price_history = [k.close for k in daily_bars if k.close > 0] if daily_bars else []
        kline_stale_days = None
        kline_stale_date = ""
        if not price_history:
            _db_bars, _stale, _stale_date = _db_kline_fallback(good_id, exact_name)
            if _db_bars:
                daily_bars = _db_bars
                price_history = [k.close for k in daily_bars if k.close > 0]
                kline_stale_days, kline_stale_date = _stale, _stale_date
                _web_log.warning(f"analyze kline DB fallback for {exact_name} stale={_stale}d")
        volume_history = [k.volume for k in daily_bars] if daily_bars else []
        supply_history = [k.in_sale_count for k in daily_bars] if daily_bars else []

        # Build market context
        ms = _market_snapshot()
        market_history = ms["history"]

        # Upsert item first: needed for recent buy dates + snapshot report
        conn_p = db.get_conn()
        try:
            pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id, yyyp_id=item.yyyp_id, in_watchlist=1)
            conn_p.commit()
        finally:
            conn_p.close()
        conn_r = db.get_conn()
        try:
            recent_buys = _recent_buy_dates(conn_r, pid)
        finally:
            conn_r.close()

        analysis = item_analysis.run_item_analysis(
            name=exact_name,
            prices=price_history,
            volumes=volume_history if volume_history else None,
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
        )
        # 报告价格锚定悠悠有品 DOM 价（chart fallback 价只补 K 线不参与定价）
        if price_rmb and price_rmb > 0:
            analysis.price_rmb = price_rmb
        analysis.volume_day = volume_day
        analysis.volume_total = volume_total
        if hasattr(analysis, 'aux') and analysis.aux:
            analysis.aux.turnover_rate = round(volume_day / volume_total * 100, 3) if volume_total > 0 else 0
            analysis.aux.mean_volume_7d = volume_day

        # 脏价校验：chart 最新 close vs 悠悠锚偏差>20% 时不落库（保留 DB 旧数据，防整体口径偏移脏价）
        _sane, _sane_msg = _kline_price_sane(daily_bars, pid, anchor_price=price_rmb)
        if not _sane:
            _web_log.warning(f"analyze kline skip {exact_name}: {_sane_msg}")
            daily_bars = None
        # Persist 90-day kline data (pid already upserted above)
        conn_p = db.get_conn()
        try:
            if daily_bars:
                db.save_price_history_batch(conn_p, pid, daily_bars)
            conn_p.commit()
        except Exception as _pe:
            _web_log.warning("kline persist failed: " + str(_pe))
        finally:
            conn_p.close()
        # Record snapshot so reports + 7-day buy dedup stay in sync
        conn_s = db.get_conn()
        try:
            _save_item_snapshot(conn_s, pid, analysis, price_rmb)
        finally:
            conn_s.close()


        ctx = {
            "name": analysis.name,
            "price_rmb": analysis.price_rmb,
            "volume_day": analysis.volume_day,
            "volume_total": analysis.volume_total,
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
            "error": None,"oob_price":"","oob_grade":"",
            "kline_stale_days": kline_stale_days,
            "kline_stale_date": kline_stale_date,
            "price_zones": analysis.price_zones,
            "buy_distance": analysis.buy_distance,
            "analysis_time": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        return templates.TemplateResponse(request, "partials/analysis.html", ctx)

    except Exception as e:
        try:
            with open("analysis_error.log", "a", encoding="utf-8") as f:
                f.write(f"\    n=== ERROR ===\n{traceback.format_exc()}\n=== END ===\n")
        except Exception:
            pass
        return HTMLResponse(_ae(f"分析失败: {str(e)[:300]}"))


# ---- Watchlist add ----
@app.post("/api/watchlist/add")
async def api_watchlist_add(request: Request):
    form = await request.form()
    name = form.get("name", "").strip()
    if not name:
        return HTMLResponse("Name is required", status_code=400)
    holding = int(form.get("holding", 0))
    avg_cost = float(form.get("avg_cost", 0))
    quantity = int(form.get("quantity", 0))
    conn = db.get_conn()
    try:
        db.watchlist_add(conn, name, holding=holding, avg_cost=avg_cost, quantity=quantity)
        conn.commit()
        return HTMLResponse("OK")
    except Exception as e:
        return HTMLResponse(str(e), status_code=500)
    finally:
        conn.close()


# ---- Watchlist edit ----
@app.put("/api/watchlist/{item_id}")
async def api_watchlist_edit(request: Request, item_id: int):
    form = await request.form()
    holding = int(form.get("holding", 0))
    avg_cost = float(form.get("avg_cost", 0))
    quantity = int(form.get("quantity", 0))
    conn = db.get_conn()
    try:
        item = conn.execute("SELECT name FROM items WHERE id=?", (item_id,)).fetchone()
        if not item:
            return HTMLResponse("Item not found", status_code=404)
        db.watchlist_update(conn, item[0], holding=holding, avg_cost=avg_cost, quantity=quantity)
        conn.commit()
        return HTMLResponse("OK")
    except Exception as e:
        return HTMLResponse(str(e), status_code=500)
    finally:
        conn.close()


# ---- Watchlist delete ----
@app.delete("/api/watchlist/{item_id}")
async def api_watchlist_delete(item_id: int):
    conn = db.get_conn()
    try:
        item = conn.execute("SELECT name FROM items WHERE id=?", (item_id,)).fetchone()
        if item:
            db.watchlist_remove(conn, item[0])
        conn.commit()
        return HTMLResponse("")
    except Exception as e:
        return HTMLResponse(str(e), status_code=500)
    finally:
        conn.close()


# ---- Watchlist analyze ----
@app.get("/api/watchlist/{item_id}/analyze")
async def api_watchlist_analyze(request: Request, item_id: int):
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT name, rarity, source, is_discontinued, discontinued_years FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return HTMLResponse(_ae("物品不存在"))
        name = row["name"]
    finally:
        conn.close()

    try:
        idx = collector.fetch_market_index()
        if idx is None or idx.value == 0:
            idx = collector.MarketIndex(value=0, change_7d=0, mood="neutral")

        good_id, page_title = await _resolve_good_id(name)
        if good_id == 0:
            return HTMLResponse(_ae(f"未找到: {name}"))

        item = await collector_csqaq.fetch_item_detail(good_id)
        if item is None:
            return HTMLResponse(_ae(f"详情获取失败"))

        exact_name = _clean_csqaq_name(item.name or page_title or name)
        # 回写 good_id/yyyp_id，避免 watchlist 品下次分析重新搜索（csqaq 搜索易风控）
        conn_w = db.get_conn()
        try:
            conn_w.execute("UPDATE items SET good_id=?, yyyp_id=?, name=?, updated_at=datetime('now','localtime') WHERE id=?", (good_id, item.yyyp_id, exact_name, item_id))
            conn_w.commit()
        except Exception as _we:
            _web_log.warning(f"watchlist good_id writeback failed: {_we}")
        finally:
            conn_w.close()
        price_rmb = item.price_rmb
        volume_total = item.volume_total
        if volume_total == 0 and hasattr(item, 'in_sale_count') and item.in_sale_count:
            volume_total = item.in_sale_count

        daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
        kline_stale_days = None
        kline_stale_date = ""
        if not daily_bars:
            _db_bars, _stale, _stale_date = _db_kline_fallback(good_id, exact_name)
            if _db_bars:
                daily_bars = _db_bars
                kline_stale_days, kline_stale_date = _stale, _stale_date
                _web_log.warning(f"watchlist kline DB fallback for {exact_name} stale={_stale}d")
        supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []
        prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else []
        # Fetch real daily volume from youpin (csqaq K-line has no volume data)
        vol_today, vol_map = await _fetch_volume_cached(good_id, item)
        _apply_volume_map(daily_bars, vol_map)
        volume_day = vol_today if vol_today > 0 else max(1, volume_total // 20)
        if vol_today > 0 and daily_bars and len(daily_bars) > 0:
            daily_bars[-1].volume = vol_today
        volumes = [k.volume for k in daily_bars] if daily_bars else []

        # Build market context from stored index history
        ms = _market_snapshot()
        market_history = ms["history"]
        conn_r = db.get_conn()
        try:
            recent_buys = _recent_buy_dates(conn_r, item_id)
        finally:
            conn_r.close()

        analysis = item_analysis.run_item_analysis(
            name=exact_name,
            prices=prices if prices else [price_rmb],
            volumes=volumes if volumes else None,
            supply_hist=supply_hist if supply_hist else None,
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
        )
        # 报告价格锚定悠悠有品 DOM 价（chart fallback 价只补 K 线不参与定价）
        if price_rmb and price_rmb > 0:
            analysis.price_rmb = price_rmb
        analysis.volume_day = volume_day
        analysis.volume_total = volume_total
        if hasattr(analysis, 'aux') and analysis.aux:
            analysis.aux.turnover_rate = round(volume_day / volume_total * 100, 3) if volume_total > 0 else 0
            analysis.aux.mean_volume_7d = volume_day

        # 脏价校验：chart 最新 close vs 悠悠锚偏差>20% 时不落库（保留 DB 旧数据，防整体口径偏移脏价）
        _sane, _sane_msg = _kline_price_sane(daily_bars, item_id, anchor_price=price_rmb)
        if not _sane:
            _web_log.warning(f"watchlist kline skip {exact_name}: {_sane_msg}")
            daily_bars = None
        # Persist 90-day kline data
        if daily_bars:
            try:
                conn_p = db.get_conn()
                db.save_price_history_batch(conn_p, item_id, daily_bars)
                conn_p.commit()
                conn_p.close()
            except Exception as _pe:
                _web_log.warning("kline persist failed: " + str(_pe))


        grade = analysis.value.grade
        score = analysis.value.score
        th = analysis.trend_health or {}

        # Save report to snapshots for "report" button
        conn_save = db.get_conn()
        try:
            _save_item_snapshot(conn_save, item_id, analysis, price_rmb)
        except Exception as _se:
            import traceback as _tb
            with open("snapshot_error.log", "a", encoding="utf-8") as _ef:
                _ef.write(f"\n=== SNAPSHOT ERROR {str(item_id)} ===\n{_tb.format_exc()}\n=== END ===\n")
            _web_log.warning(f"Failed to save snapshot: {_se}")
        finally:
            conn_save.close()
        # Save to analysis_results (同步至单品报告)
        _save_analysis_result(analysis, kline_stale_days, kline_stale_date)


        ctx = {
            "name": analysis.name,
            "price_rmb": analysis.price_rmb,
            "volume_day": analysis.volume_day,
            "volume_total": analysis.volume_total,
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
            "error": None,"oob_price":"","oob_grade":"",
            "kline_stale_days": kline_stale_days,
            "kline_stale_date": kline_stale_date,
            "price_zones": analysis.price_zones,
            "buy_distance": analysis.buy_distance,
        }
        return templates.TemplateResponse(request, "partials/analysis.html", ctx)

    except Exception as e:
        try:
            with open("analysis_error.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== WL ERROR ===\n{traceback.format_exc()}\n=== END ===\n")
        except Exception:
            pass
        return HTMLResponse(_ae(f"分析失败: {str(e)[:300]}"))


# ---- Watchlist report ----
@app.get("/api/watchlist/{item_id}/report")
async def api_watchlist_report(request: Request, item_id: int):
    conn = db.get_conn()
    try:
        row = db.get_latest_snapshot_report(conn, item_id)
        if not row or not (row["report_html"] or row["report_md"]):
            return HTMLResponse(
                '<div class="card" style="border-color: rgba(245,158,11,0.5);">'
                '<div class="card-header"><span class="card-title">⚠️ 暂无报告</span></div>'
                '<p style="color: var(--text-secondary);">该物品尚未生成分析报告，请先点击「分析」按钮。</p>'
                '</div>'
            )
        if row["report_html"]:
            return HTMLResponse(row["report_html"])
        report_html = _render_report_html(row["report_md"], row["date"], row["grade"], row["total_score"] or 0)
        return HTMLResponse(report_html)
    finally:
        conn.close()


# ---- Discover report (existing report, no re-analysis) ----
@app.get("/api/discover/report")
async def api_discover_report(request: Request, name: str = Query(...)):
    """Return saved report by item name without re-running analysis."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT report_html FROM analysis_results WHERE name=? ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row and row["report_html"]:
            return HTMLResponse(row["report_html"])
        item = conn.execute("SELECT id FROM items WHERE name=?", (name,)).fetchone()
        if item:
            snap = conn.execute(
                "SELECT report_html, report_md, date, grade, total_score FROM snapshots WHERE item_id=? ORDER BY date DESC LIMIT 1",
                (item["id"],),
            ).fetchone()
            if snap and (snap["report_html"] or snap["report_md"]):
                if snap["report_html"]:
                    return HTMLResponse(snap["report_html"])
                return HTMLResponse(_render_report_html(snap["report_md"], snap["date"], snap["grade"], snap["total_score"] or 0))
        return HTMLResponse(
            '<div class="card" style="border-color: rgba(245,158,11,0.5);">'
            '<div class="card-header"><span class="card-title">⚠️ 暂无报告</span></div>'
            '<p style="color: var(--text-secondary);">该饰品尚未生成报告，请先执行「开始扫描」或单品分析。</p>'
            '</div>'
        )
    finally:
        conn.close()


def _render_report_html(report_md, date, grade, total_score):
    """Render markdown report to styled HTML matching analysis template."""
    import re as _re
    lines = report_md.split("\n")
    html_parts = []
    in_table = False

    html_parts.append('<div class="card" style="border-color: rgba(59,130,246,0.5);">')
    html_parts.append('<div class="card-header" style="background: rgba(59,130,246,0.08);">')
    html_parts.append('<span class="card-title">📊 分析报告</span>')
    grade_lower = grade.lower() if grade else "unknown"
    html_parts.append(f'<span class="badge badge-{grade_lower}">{grade}</span>')
    html_parts.append(f'<span style="font-size: 12px; color: var(--text-muted); margin-left: 8px;">日期: {date} | 评分: {total_score}</span>')
    html_parts.append('</div>')
    html_parts.append('<div style="padding: 16px; max-height: 70vh; overflow-y: auto; font-size: 13px; line-height: 1.6; color: var(--text-primary);">')

    def _fmt_bold(text):
        return _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_table:
                html_parts.append('</table>')
                in_table = False
            continue

        if stripped.startswith("---"):
            continue

        if stripped.startswith("# ") and not stripped.startswith("## "):
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped[2:])
            html_parts.append(f'<h2 style="font-size: 18px; font-weight: 700; margin: 16px 0 8px; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 4px;">{text}</h2>')

        elif stripped.startswith("## "):
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped[3:])
            html_parts.append(f'<h3 style="font-size: 15px; font-weight: 600; margin: 14px 0 6px; color: var(--text-primary); padding: 4px 8px; background: rgba(59,130,246,0.05); border-radius: 4px;">{text}</h3>')

        elif stripped.startswith("|"):
            if not in_table:
                html_parts.append('<table style="width:100%; border-collapse: collapse; margin: 8px 0; font-size: 12px;">')
                in_table = True
            cells = stripped.split("|")
            cells = [c for c in cells if c.strip()]
            is_header = all(c.strip().replace("-","").replace(":","") == "" for c in cells)
            if is_header:
                continue
            tag = "th" if not in_table else "td"
            row_html = "<tr>" + "".join(
                f'<td style="padding: 4px 8px; border-bottom: 1px solid var(--border);">{_fmt_bold(c.strip())}</td>'
                for c in cells
            ) + "</tr>"
            html_parts.append(row_html)

        elif stripped.startswith("- "):
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped[2:])
            html_parts.append(f'<div style="margin: 4px 0 4px 16px; display: flex; gap: 6px;"><span style="color: var(--accent);">•</span><span>{text}</span></div>')

        elif stripped.startswith("> "):
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped[2:])
            html_parts.append(f'<div style="margin: 8px 0; padding: 8px 12px; background: rgba(245,158,11,0.1); border-left: 3px solid #f59e0b; font-size: 12px; border-radius: 0 4px 4px 0;">{text}</div>')

        else:
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped)
            html_parts.append(f'<div style="margin: 4px 0;">{text}</div>')

    if in_table:
        html_parts.append('</table>')
    html_parts.append("</div>")
    html_parts.append("</div>")
    return "\n".join(html_parts)

# ---- Watchlist assets ----
@app.post("/api/watchlist/assets")
async def api_watchlist_set_assets(request: Request, amount: float = Form(...)):
    conn = db.get_conn()
    try:
        db.set_setting(conn, "total_assets", amount)
        return HTMLResponse(f'<div class="flash-msg flash-success">✅ 总资产已设置为 ¥{amount:,.2f}</div>')
    finally:
        conn.close()









# ---- Batch Scan Selected ----

# ---- Batch Scan Progress ----
_scan_progress: dict = {}

def _item_report_link(name):
    """批量扫描结果中可点击的名称链接：弹窗查看已存报告（不重新分析）。"""
    esc = str(name).replace("'", "\\'").replace('"', "&quot;")
    return ('<a href="javascript:void(0)" onclick="showItemReport(\'' + esc + '\')" '
            'style="color:var(--accent);text-decoration:none;cursor:pointer;font-weight:600;">' + str(name) + '</a>')

async def _scan_item(row, idx, ms, market_th_score, sentiment_score):
    """批量扫描单个物品（可并发调用，共享 Playwright 浏览器多 page）。"""
    import json as _json
    from pipeline.batch_scan import _portfolio_advice, summarize_buy_distance
    from pipeline import collector_csqaq, item_analysis, collector
    item_id, name, holding, avg_cost, qty = row["id"], row["name"], row["holding"] or 0, row["avg_cost"] or 0, row["quantity"] or 0
    try:
        good_id, _ = await _resolve_good_id(name)
        if good_id == 0:
            return dict(name=name, holding=holding, error="未找到")
        item = await collector_csqaq.fetch_item_detail(good_id)
        if item is None:
            return dict(name=name, holding=holding, error="详情获取失败")
        exact_name = item.name or name
        daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
        if not daily_bars:
            _db_bars, _stale, _stale_date = _db_kline_fallback(good_id, exact_name)
            if _db_bars:
                daily_bars = _db_bars
        prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else [item.price_rmb]
        vol_today, vol_map = await _fetch_volume_cached(good_id, item)
        _apply_volume_map(daily_bars, vol_map)
        volumes = [k.volume for k in daily_bars] if daily_bars else []
        supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []
        volume_day = vol_today if vol_today > 0 else max(1, (item.volume_total or 0) // 20)
        conn_r = db.get_conn()
        try:
            recent_buys = _recent_buy_dates(conn_r, item_id)
        finally:
            conn_r.close()
        analysis = item_analysis.run_item_analysis(
            name=exact_name, prices=prices, volumes=volumes or None,
            supply_hist=supply_hist or None, order_book=item.order_book,
            index_change_7d=getattr(idx, "change_7d", 0),
            market_cycle=ms["cycle"],
            market_th_score=ms["th"],
            market_30d_change=ms["chg30"],
            market_drop21=ms.get("drop21", 0),
            recent_buy_dates=recent_buys,
            signal_date=_today_str(),
            price_anchor=item.price_rmb,
        )
        # 报告价格锚定悠悠有品 DOM 价（chart fallback 价只补 K 线不参与定价）
        if getattr(item, "price_rmb", 0) and item.price_rmb > 0:
            analysis.price_rmb = item.price_rmb
        analysis.volume_day = volume_day
        analysis.volume_total = item.volume_total or 0
        # 价格合理性校验：csQAQ 偶发串品/脏价，脏数据不落库（保留 DB 旧数据）
        _sane, _sane_msg = _kline_price_sane(daily_bars, item_id, anchor_price=getattr(item, "price_rmb", 0) or 0)
        if not _sane:
            _web_log.warning(f"batch scan skip {exact_name}: {_sane_msg}")
            return dict(name=exact_name, holding=holding, error="价格校验未通过，保留旧数据")
        pa = _portfolio_advice(holding, avg_cost, qty, item.price_rmb, analysis, market_th=market_th_score, sentiment_score=sentiment_score)
        _fd_lim = (getattr(analysis, "fusion_decision", {}) or {}).get("position_limit", 0) or 0
        result = dict(
            name=exact_name, holding=holding, avg_cost=avg_cost, qty=qty,
            price_rmb=item.price_rmb, grade=analysis.value.grade, score=analysis.value.score,
            position_limit=float(_fd_lim),
            portfolio_advice=pa,
            buy_distance=summarize_buy_distance(getattr(analysis, "buy_distance", None) or {}),
            valuation_tier=getattr(analysis.position, "valuation_tier", "") if hasattr(analysis, "position") else "",
            percentile_90d=getattr(analysis.position, "percentile_90d", 50) if hasattr(analysis, "position") else 50,
            error=None,
        )
        # Save to analysis_results (同步至单品报告)
        _save_analysis_result(analysis)
        # Persist
        conn_p = db.get_conn()
        try:
            pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id, yyyp_id=item.yyyp_id, in_watchlist=1)
            db.save_price_history_batch(conn_p, pid, daily_bars)
            conn_p.commit()
        finally:
            conn_p.close()
        # Snapshot + summary
        conn_s = db.get_conn()
        try:
            _save_item_snapshot(conn_s, item_id, analysis, item.price_rmb)
            db.set_setting(conn_s, f"th_{pid}", _json.dumps(analysis.trend_health, ensure_ascii=False) if analysis.trend_health else "")
            conn_s.commit()
        except Exception as _se:
            import traceback as _tb
            with open("snapshot_error.log", "a", encoding="utf-8") as _ef:
                _ef.write("\n=== BATCH ERROR " + str(item_id) + " ===\n" + _tb.format_exc() + "\n=== END ===\n")
            _web_log.warning(f"Batch save error: {_se}")
        finally:
            conn_s.close()
        return result
    except Exception as e:
        _web_log.error(f"batch scan item failed: {name}: {e}")
        return dict(name=name, holding=holding, error=str(e)[:100])


async def _run_batch_scan_task(scan_id: str, rows: list):
    """批量扫描：并发 2 路共享浏览器采集（提速），结果排序 + 结构化缓存。"""
    import json as _json
    from pathlib import Path as _P
    from pipeline.batch_scan import build_scan_html, sort_results
    from pipeline import collector
    idx = collector.fetch_market_index()
    if idx is None or idx.value == 0:
        idx = type("obj", (object,), {"value": 0, "change_7d": 0})()
    # Compute market TH + sentiment once for resonance-aware portfolio advice
    ms = _market_snapshot()
    market_th_score = ms["th"]
    sentiment_score = ms["sentiment"]
    total = len(rows)
    _scan_progress[scan_id]["total"] = total
    _scan_progress[scan_id]["name"] = "准备扫描..."
    sem = asyncio.Semaphore(2)  # 并发 2 路：共享浏览器多 page，提速且降低风控风险
    done = 0

    async def _one(row):
        nonlocal done
        async with sem:
            res = await _scan_item(row, idx, ms, market_th_score, sentiment_score)
            done += 1
            _scan_progress[scan_id]["current"] = done
            if res:
                _scan_progress[scan_id]["name"] = res.get("name", "")
            return res

    raw_results = await asyncio.gather(*(_one(r) for r in rows))
    results = [r for r in raw_results if r is not None]
    results = sort_results(results)

    now_str = __import__("datetime").datetime.now().strftime("%H:%M:%S")
    final_html = build_scan_html(
        results, total,
        {"th": market_th_score, "sentiment": sentiment_score, "cycle": ms["cycle"],
         "index": getattr(idx, "value", 0)},
        now_str=now_str,
        name_link=_item_report_link,
    )
    _scan_progress[scan_id]["html"] = final_html
    _scan_progress[scan_id]["done"] = True
    # Persist to disk
    try:
        _cache_path = _P(__file__).resolve().parent.parent / "data" / "batch_scan_latest.json"
        _cache_path.write_text(_json.dumps({
            "time": __import__("datetime").datetime.now().isoformat(),
            "html": final_html,
            "results": results,
            "market_th": market_th_score,
        }, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass
@app.get("/api/watchlist/batch-scan-latest")
async def api_batch_scan_latest():
    """Return the latest cached batch scan result."""
    import json as _J
    from pathlib import Path as _P
    cache_path = _P(__file__).resolve().parent.parent / "data" / "batch_scan_latest.json"
    if not cache_path.exists():
        return {"found": False}
    try:
        data = _J.loads(cache_path.read_text(encoding="utf-8"))
        return {"found": True, "time": data["time"], "html": data.get("html", ""),
                "results": data.get("results", []), "market_th": data.get("market_th")}
    except Exception:
        return {"found": False}

@app.post("/api/watchlist/batch-scan-latest/clear")
async def api_batch_scan_latest_clear():
    """Clear cached batch scan result."""
    from pathlib import Path as _P
    cache_path = _P(__file__).resolve().parent.parent / "data" / "batch_scan_latest.json"
    try:
        cache_path.unlink(missing_ok=True)
    except Exception:
        pass
    return {"ok": True}

@app.post("/api/watchlist/batch-scan-selected")
async def api_watchlist_batch_scan_selected(request: Request):
    body = await request.json()
    ids = body.get("ids", [])
    if not ids:
        return HTMLResponse('<div class="card" style="padding:20px;">\u8bf7\u9009\u62e9\u7269\u54c1</div>')
    conn = db.get_conn()
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute("SELECT id, name, holding, avg_cost, quantity FROM items WHERE id IN (" + placeholders + ")", ids).fetchall()
    finally:
        conn.close()
    if not rows:
        return HTMLResponse('<div class="card" style="padding:20px;">\u672a\u627e\u5230\u7269\u54c1</div>')
    import uuid
    scan_id = uuid.uuid4().hex[:8]
    _scan_progress[scan_id] = {"current": 0, "total": len(rows), "name": "", "done": False, "html": ""}
    asyncio.create_task(_run_batch_scan_task(scan_id, rows))
    html = '<div class="card" id="scan-progress-{sid}" data-scanid="{sid}"><div class="card-header"><span class="card-title">\u626b\u63cf\u8fdb\u5ea6</span></div><div class="card-body" id="scan-status-{sid}"><p style="text-align:center;padding:20px;">\u6b63\u5728\u51c6\u5907\u626b\u63cf... <span class="spinner"></span></p></div></div>'.format(sid=scan_id)
    return HTMLResponse(html)
# ---- Batch Scan Progress Polling ----
@app.get("/api/watchlist/batch-scan-progress/{scan_id}")
async def api_batch_scan_progress(scan_id: str):
    p = _scan_progress.get(scan_id)
    if not p:
        return {"error": "not found"}
    return {"current": p["current"], "total": p["total"], "name": p.get("name", ""), "done": p["done"], "html": p.get("html", "")}



@app.get("/discover", response_class=HTMLResponse)
async def page_discover(request: Request):
    return templates.TemplateResponse(request, "discover.html", {"active_page": "discover"})

# ---- Discover high-score items by weapon type ----
_discover_progress: dict = {}
DISCOVER_WEAPONS = [
    "AK-47", "AWP", "沙漠之鹰", "M4A4",
    "USP", "MP7", "SSG 08", "法玛斯",
]

async def _run_discover_task(task_id: str, items: list):
    """Background: search each item via shared browser, analyze, sort by composite score."""
    from pipeline import collector_csqaq, item_analysis as _ia
    # Get market TH for context-aware filtering
    ms = _market_snapshot()
    market_th = ms["th"]
    _discover_progress[task_id]["market_th"] = market_th
    results = []
    analysis_objs = {}
    total = len(items)
    skipped = 0
    for i, (good_id, name, price_rmb) in enumerate(items):
        _discover_progress[task_id]["current"] = i + 1
        _discover_progress[task_id]["name"] = name
        try:
            item = await collector_csqaq.fetch_item_detail(good_id)
            if item is None:
                results.append(dict(name=name, error="详情获取失败"))
                continue
            exact_name = item.name or name
            daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
            if not daily_bars:
                _db_bars, _stale, _stale_date = _db_kline_fallback(good_id, exact_name)
                if _db_bars:
                    daily_bars = _db_bars
            prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else [price_rmb]

            # P0-2: 轻量预筛 - K线不足14天直接跳过(节省采集+分析耗时)
            if len(prices) < 14:
                skipped += 1
                continue
            current_p = prices[-1]
            pct_quick = sum(1 for p in prices if p < current_p) / len(prices) * 100
            if pct_quick > 75:
                skipped += 1
                continue

            vol_today, vol_map = await _fetch_volume_cached(good_id, item)
            _apply_volume_map(daily_bars, vol_map)
            volumes = [k.volume for k in daily_bars] if daily_bars else []
            supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []

            volume_day = vol_today if vol_today > 0 else max(1, (item.volume_total or 0) // 20)

            analysis = _ia.run_item_analysis(
                name=exact_name, prices=prices, volumes=volumes or None,
                supply_hist=supply_hist or None, order_book=item.order_book,
                index_change_7d=0,
                market_cycle=ms["cycle"],
                market_th_score=ms["th"],
                market_30d_change=ms["chg30"],
                market_drop21=ms.get("drop21", 0),
            )
            analysis_objs[exact_name] = analysis

            pos = analysis.position if hasattr(analysis, "position") else {}
            pct_val = getattr(pos, "percentile_90d", 50) if hasattr(pos, "percentile_90d") else 50
            z_val = getattr(pos, "zscore_90d", 0) if hasattr(pos, "zscore_90d") else 0
            score = analysis.value.score

            # P0-1 (2026-08): 综合分重排 - 数据质量 x 估值折价 x (评分+融合决策+趋势加权)
            dq_factor = {"good": 1.0, "medium": 0.85, "low": 0.6, "insufficient": 0.2}.get(getattr(analysis, "data_quality", "low"), 0.4)
            fd_action = (analysis.fusion_decision or {}).get("action", "") if isinstance(analysis.fusion_decision, dict) else ""
            action_bonus = {"buy": 1.0, "watch": 0.5, "hold": 0.0, "reduce": -0.5, "avoid": -1.0, "sell": -1.0}.get(fd_action, 0.0)
            th_score = (analysis.trend_health or {}).get("score", 50) if isinstance(analysis.trend_health, dict) else 50
            th_bonus = (th_score - 50) / 50 * 1.0  # TH 100 -> +1.0, TH 0 -> -1.0
            valuation_discount = max(0.5, 1.0 - pct_val / 200)
            composite = round((score + action_bonus + th_bonus) * valuation_discount * dq_factor, 1)

            # P3: Market-linked filter
            if market_th < 55 and score < 6.0 and composite < 5.0:
                skipped += 1
                continue

            results.append(dict(
                name=exact_name, good_id=good_id, price_rmb=price_rmb or item.price_rmb,
                grade=analysis.value.grade, score=score, composite=composite,
                data_quality=getattr(analysis, "data_quality", "low"),
                fd_action=fd_action, th_score=th_score,
                percentile_90d=pct_val, zscore_90d=round(z_val, 2),
                trend=analysis.trend_health,
                cycle_phase=getattr(analysis.cycle, "phase", "unknown"),
                cycle_label=getattr(analysis.cycle, "phase_label", ""),
                strategy=getattr(analysis.cycle, "phase_strategy", ""),
                fusion=getattr(analysis, "fusion_decision", {}),
                valuation_tier=getattr(analysis.position, "valuation_tier", ""),
                tier_label=getattr(analysis.position, "tier_label", ""),
            ))
        except Exception as e:
            _web_log.error(f"Discover analyze {name} error: {traceback.format_exc()}")
            results.append(dict(name=name, error=str(e)[:200]))

    _discover_progress[task_id]["skipped"] = skipped
    results.sort(key=lambda r: r.get("composite", 0) or r.get("score", 0) or 0, reverse=True)
    _discover_progress[task_id]["results"] = results
    _discover_progress[task_id]["done"] = True

    # 保存 top10 报告到 analysis_results + snapshots（查看报告不再重新分析）
    try:
        for _r in results[:10]:
            if _r.get("error"):
                continue
            _an = analysis_objs.get(_r.get("name", ""))
            if _an is None:
                continue
            try:
                _save_analysis_result(_an)
            except Exception as _se1:
                _web_log.warning(f"discover save analysis_result failed: {_se1}")
            try:
                _conn_d = db.get_conn()
                try:
                    _pid_d = db.upsert_item(_conn_d, name=_r["name"], good_id=_r.get("good_id", 0))
                    _conn_d.commit()
                finally:
                    _conn_d.close()
                _conn_s = db.get_conn()
                try:
                    _save_item_snapshot(_conn_s, _pid_d, _an, _an.price_rmb or 0)
                finally:
                    _conn_s.close()
            except Exception as _se2:
                _web_log.warning(f"discover save snapshot failed: {_se2}")
    except Exception as _se3:
        _web_log.warning(f"discover save reports failed: {_se3}")

    html = _render_discover_html(results, market_th)
    _discover_progress[task_id]["html"] = html
def _render_discover_html(results, market_th=50):
    """Render discover results with valuation columns, add-to-watchlist, and heatmap."""
    sorted_r = sorted(results, key=lambda r: -(r.get("composite", 0) or r.get("score", 0) or 0))
    top10 = sorted_r[:10]
    errors = [r for r in sorted_r if r.get("error")]
    ok_count = len(sorted_r) - len(errors)

    # ---- Heatmap: by weapon type ----
    from collections import defaultdict
    by_type = defaultdict(list)
    for r in sorted_r:
        if r.get("error"):
            continue
        wt = r["name"].split(" |")[0] if "|" in r["name"] else "other"
        by_type[wt].append(r)

    heatmap_rows = []
    for wt, items in sorted(by_type.items(), key=lambda x: -len(x[1])):
        if len(items) == 0:
            continue
        avg_score = sum(it.get("score", 0) for it in items) / len(items)
        avg_pct = sum(it.get("percentile_90d", 50) for it in items) / len(items)
        best = max(items, key=lambda x: x.get("composite", 0) or x.get("score", 0))
        pct_cls = "green" if avg_pct <= 25 else ("yellow" if avg_pct <= 50 else "red")
        heatmap_rows.append(
            f'<tr><td><strong>{wt}</strong></td>'
            f'<td>{len(items)}</td>'
            f'<td style="color:var(--green);">{avg_score:.1f}</td>'
            f'<td class="{pct_cls}">{avg_pct:.0f}%</td>'
            f'<td style="font-size:12px;">{best["name"][:30]}</td>'
            f'<td style="font-weight:600;">{best.get("composite", best.get("score",0)):.1f}</td></tr>'
        )
    heatmap_html = (
        '<div class="card" style="margin-bottom:16px;">'
        '<div class="card-header"><span class="card-title">\U0001f4ca \u54c1\u7c7b\u70ed\u529b\u56fe</span></div>'
        '<table style="width:100%;font-size:13px;">'
        '<thead><tr><th>\u6b66\u5668</th><th>\u6570\u91cf</th><th>\u5747\u5206</th><th>\u5747\u4f30\u503c</th><th>\u6700\u4f18\u54c1</th><th>\u7efc\u5408</th></tr></thead>'
        '<tbody>' + "".join(heatmap_rows) + '</tbody></table></div>'
    ) if len(by_type) >= 2 else ""

    # ---- Top 10 Table ----
    market_note = ""
    if market_th < 55:
        market_note = ' <span style="font-size:12px;color:var(--yellow);">(\u5927\u76d8TH=' + str(market_th) + ' \u504f\u5f31\uff0c\u4ec5\u5c55\u793a\u9ad8\u5206\u4f4e\u4f30\u54c1)</span>'

    lines = [
        f'<div class="card"><div class="card-header"><span class="card-title">\U0001f50d Top 10 \u9ad8\u5206\u9970\u54c1</span>'
        f'<span class="card-subtitle">\u5df2\u626b\u63cf {ok_count} \u4e2a\u9970\u54c1\uff0c\u5c55\u793a\u524d10{market_note}'
        f' <button class="btn btn-sm btn-outline" onclick="refreshDiscover()" style="margin-left:8px;">\U0001f504 \u5237\u65b0</button></span></div>'
        f'<div class="card-body" style="padding:0;"><table class="data-table" style="width:100%;">'
        f'<thead><tr><th>#</th><th>\u8bc4\u7ea7</th><th>\u540d\u79f0</th><th>\u4ef7\u683c</th><th>\u8bc4\u5206</th><th>\u7efc\u5408</th><th>%\u4f4d</th><th>\u5468\u671f</th><th>\u64cd\u4f5c</th></tr></thead><tbody>'
    ]
    for idx, r in enumerate(top10):
        if r.get("error"):
            lines.append(f'<tr><td colspan="9" style="color:var(--danger);padding:12px 16px;">{r["name"]}: {r["error"]}</td></tr>')
            continue
        g = r.get("grade", "Z")
        grade_cls = {"S":"grade-s","A":"grade-a","B":"grade-b","C":"grade-c"}.get(g, "grade-z")
        fusion = r.get("fusion", {}) or {}
        action = fusion.get("action", "") if isinstance(fusion, dict) else ""
        cp = r.get("cycle_label", "") or r.get("cycle_phase", "")
        pct = r.get("percentile_90d", 50)
        pct_clr = "green" if pct <= 25 else ("yellow" if pct <= 50 else "red")
        comp = r.get("composite", 0) or r.get("score", 0)
        rank_style = "font-weight:800;font-size:16px;" + ("color:#ffd700;" if idx == 0 else "color:var(--text-muted);")
        esc_name = r["name"].replace("'", "\\'").replace('"', '&quot;')
        lines.append(
            f'<tr><td style="{rank_style}">{idx+1}</td>'
            f'<td><span class="{grade_cls}">{g}</span></td>'
            f'<td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"><a href="javascript:void(0)" onclick="showDiscoverReport(\'{esc_name}\')" style="color:var(--accent);text-decoration:none;cursor:pointer;" title="\u67e5\u770b\u5206\u6790\u62a5\u544a">{r["name"]}</a></td>'
            f'<td>\u00a5{r.get("price_rmb",0):.2f}</td>'
            f'<td>{r.get("score",0):.1f}</td>'
            f'<td style="font-weight:600;">{comp:.1f}</td>'
            f'<td class="{pct_clr}">{pct:.0f}%</td>'
            f'<td style="font-size:12px;">{cp}</td>'
            f'<td><button class="btn btn-xs btn-outline" onclick="addToWatchlist(\'{esc_name}\')" title="\u52a0\u5165\u81ea\u9009">+</button></td></tr>'
        )
    lines.append("</tbody></table></div></div>")
    return heatmap_html + "\n".join(lines)

@app.post("/api/items/discover")
@app.post("/api/discover/scan-all")
async def api_discover_scan_all(request: Request):
    import time as _time
    task_id = f"discover_{int(_time.time())}"
    _discover_progress[task_id] = {"current": 0, "total": 999, "name": "", "done": False, "html": "", "results": []}
    asyncio.create_task(_run_discover_scan_all_task(task_id))
    return {"task_id": task_id}

async def _run_discover_scan_all_task(task_id: str):
    """Full discover pipeline: search all weapon types, analyze results."""
    from pipeline.collector_csqaq import _get_browser, CSQAQ_WEB
    from collections import defaultdict
    pw, browser = await _get_browser()
    if not browser:
        _discover_progress[task_id]["done"] = True
        _discover_progress[task_id]["html"] = '<div class="card" style="padding:20px;color:var(--danger);">\u65e0\u6cd5\u542f\u52a8\u6d4f\u89c8\u5668</div>'
        return
    all_items = []
    page = None
    try:
        page = await browser.new_page()
        seen = set()
        try:
            total_wt = len(DISCOVER_WEAPONS)
            for wt_idx, wt in enumerate(DISCOVER_WEAPONS):
                suggest = {}
                async def _on_suggest(response):
                    if "search/suggest" in response.url and response.ok:
                        try:
                            import json as _js
                            body = await response.text()
                            d = _js.loads(body)
                            if d.get("code") == 200 and d.get("data"):
                                suggest["items"] = d["data"]
                        except Exception:
                            pass
                page.on("response", _on_suggest)
                await page.goto(CSQAQ_WEB, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1200)
                js = "async(q)=>{const el=document.querySelector('#rc_select_0');if(!el)return;const fk=Object.keys(el).find(k=>k.startsWith('__reactFiber'));if(!fk)return;const f=el[fk];let n=f,t=0;while(n&&t<30){const p=n.memoizedProps;if(p&&(p.onChange||p.onSearch)){const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(el,q);if(p.onChange)p.onChange({target:{value:q}});else if(p.onSearch)p.onSearch(q);return}n=n.return||n.stateNode;t++}}"
                await page.evaluate(js, wt)
                await page.wait_for_timeout(2000)
                for sd in suggest.get("items", []):
                    try:
                        gid = int(sd.get("id", 0))
                        name = sd.get("value", "")
                        if gid > 0 and name and name not in seen:
                            if "\u5d2d\u65b0\u51fa\u5382" in name and "StatTrak" not in name and "\u7eaa\u5ff5\u54c1" not in name:
                                seen.add(name)
                                all_items.append((gid, name, 0))
                    except (ValueError, TypeError):
                        continue
                page.remove_listener("response", _on_suggest)
                _discover_progress[task_id]["current"] = wt_idx + 1
                _discover_progress[task_id]["name"] = f"\u641c\u7d22: {wt} ({wt_idx+1}/{total_wt})"
        finally:
            await page.close()
    except Exception as e:
        _web_log.error(f"Discover scan-all error: {e}")
        _discover_progress[task_id]["done"] = True
        _discover_progress[task_id]["html"] = f'<div class="card" style="padding:20px;color:var(--danger);">\u641c\u7d22\u5931\u8d25: {str(e)[:200]}</div>'
        return

    if not all_items:
        _discover_progress[task_id]["done"] = True
        _discover_progress[task_id]["html"] = '<div class="card" style="padding:20px;">\u672a\u627e\u5230\u9970\u54c1</div>'
        return

    by_type = defaultdict(list)
    for gid, name, price in all_items:
        key = name.split(" |")[0] if "|" in name else "unknown"
        by_type[key].append((gid, name, price))
    # P0-2 (2026-08): 每类扫6个(原3), 总量上限40(原24) 提升覆盖
    capped = []
    for wt_items in by_type.values():
        capped.extend(wt_items[:6])
    capped = capped[:40]

    _discover_progress[task_id]["total"] = len(capped)
    _discover_progress[task_id]["current"] = 0
    await _run_discover_task(task_id, capped)

    # Save cache for re-viewing
    import json as _json_cache
    from pathlib import Path as _Path_cache
    _cache_path = _Path_cache(__file__).resolve().parent.parent / 'data' / 'discover_latest.json'
    _cache_path.parent.mkdir(parents=True, exist_ok=True)
    _cache_data = {
        'time': __import__('datetime').datetime.now().isoformat(),
        'html': _discover_progress[task_id].get('html', ''),
        'results': _discover_progress[task_id].get('results', []),
        'market_th': _discover_progress[task_id].get('market_th', None),
    }
    _cache_path.write_text(_json_cache.dumps(_cache_data, ensure_ascii=False), encoding='utf-8')


@app.get("/api/discover/latest")
async def api_discover_latest():
    """Return cached discover result if available and < 24h old."""
    from pathlib import Path as _P
    import json as _J
    from datetime import datetime, timedelta
    cache_path = _P(__file__).resolve().parent.parent / "data" / "discover_latest.json"
    if not cache_path.exists():
        return {"found": False}
    try:
        data = _J.loads(cache_path.read_text(encoding="utf-8"))
        results = data.get("results", [])
        market_th = data.get("market_th", 50)
        # 用最新模板重新渲染，保证查看报告走弹窗（不再跳转重新分析）
        html = _render_discover_html(results, market_th) if results else data.get("html", "")
        return {"found": True, "time": data["time"], "html": html, "results": results}
    except Exception:
        return {"found": False}

@app.get("/api/items/discover-progress/{task_id}")
async def api_discover_progress(task_id: str):
    p = _discover_progress.get(task_id)
    if not p:
        return {"error": "not found"}
    return {"current": p["current"], "total": p["total"], "name": p.get("name", ""), "done": p["done"], "html": p.get("html", ""), "results": p.get("results", []) if p["done"] else []}
