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
from pipeline import collector_csqaq, collector_steamdt

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


# ---- Watchlist page ----
@app.get("/watchlist", response_class=HTMLResponse)
async def page_watchlist(request: Request):
    conn = db.get_conn()
    try:
        items_raw = db.watchlist_list_with_snapshots(conn)
        total_assets = float(db.get_setting(conn, "total_assets", 0) or 0)
        # Convert sqlite3.Row to dict for .get() access
        all_items = [dict(r) for r in items_raw]
        total_buy_cost = sum((i.get("avg_cost") or 0) * (i.get("quantity") or 0) for i in all_items)
        position_ratio = (total_buy_cost / total_assets * 100) if total_assets > 0 else 0

        # Pagination: 10 per page, ordered by add time (id)
        PAGE_SIZE = 10
        total_items = len(all_items)
        total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        page = min(page, total_pages)
        items = all_items[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

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
            "position_ratio": position_ratio,
            "pagination": {"page": page, "total_pages": total_pages, "total_items": total_items},
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
        # Step 1: Search via Playwright
        good_id, page_title = await collector_csqaq.search_good_id(query)
        if good_id == 0:
            items = collector.search_items(query)
            if not items:
                return HTMLResponse('<div class="card"><div class="empty-state" style="text-align:center;padding:40px;color:var(--text-muted);">未找到相关饰品，请尝试简化关键词</div></div>')
            # Multiple results via API - pick first and continue
            name = items[0].name
            good_id2, _ = await collector_csqaq.search_good_id(name)
            if good_id2 == 0:
                return HTMLResponse('<div class="card"><div class="empty-state" style="text-align:center;padding:40px;color:var(--text-muted);">未找到相关饰品</div></div>')
            good_id = good_id2

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
        # Fetch steamdt "??????" as real daily volume (csqaq K-line has no volume data)
        steamdt_vol = 0
        if hasattr(item, 'steam_name') and item.steam_name:
            try:
                sv = await collector_steamdt.fetch_steamdt_volume(item.steam_name)
                if isinstance(sv, dict) and sv:
                    steamdt_vol = list(sv.values())[0]
            except Exception:
                pass

        volume_day = steamdt_vol if steamdt_vol > 0 else max(1, volume_total // 20)
        if steamdt_vol > 0 and daily_bars and len(daily_bars) > 0:
            daily_bars[-1].volume = steamdt_vol
        if steamdt_vol > 0 and daily_bars and len(daily_bars) > 0:
            daily_bars[-1].volume = steamdt_vol  # fill latest bar with real volume

        price_history = [k.close for k in daily_bars if k.close > 0] if daily_bars else []
        volume_history = [k.volume for k in daily_bars] if daily_bars else []
        supply_history = [k.in_sale_count for k in daily_bars] if daily_bars else []

        # Build market context
        conn_m = db.get_conn()
        market_history = []
        market_pct = 50
        market_z = 0.0
        try:
            rows = conn_m.execute(
                "SELECT date, value FROM market_index ORDER BY date ASC"
            ).fetchall()
            market_history = [(r["date"], float(r["value"])) for r in rows] if rows else []
            if market_history:
                values = [v for _, v in market_history if v > 0]
                if len(values) >= 30:
                    current_m = values[-1]
                    below = sum(1 for v in values if v < current_m)
                    market_pct = round(below / len(values) * 100, 1)
                    mean_m = sum(values) / len(values)
                    std_m = (sum((v - mean_m) ** 2 for v in values) / len(values)) ** 0.5
                    market_z = round((current_m - mean_m) / std_m, 2) if std_m > 0 else 0
        finally:
            conn_m.close()

        analysis = item_analysis.run_item_analysis(
            name=exact_name,
            prices=price_history,
            volumes=volume_history if volume_history else None,
            supply_hist=supply_history if supply_history else None,
            order_book=item.order_book,
            index_change_7d=idx.change_7d,
            market_history=market_history,
            market_pct_90d=market_pct,
            market_zscore=market_z,
        )
        analysis.volume_day = volume_day
        analysis.volume_total = volume_total
        if hasattr(analysis, 'aux') and analysis.aux:
            analysis.aux.turnover_rate = round(volume_day / volume_total * 100, 3) if volume_total > 0 else 0
            analysis.aux.mean_volume_7d = volume_day
    
        # Persist 90-day kline data to price_history table
        if daily_bars:
            try:
                conn_p = db.get_conn()
                pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id, in_watchlist=1)
                db.save_price_history_batch(conn_p, pid, daily_bars)
                conn_p.commit()
                conn_p.close()
            except Exception as _pe:
                _web_log.warning("kline persist failed: " + str(_pe))

        # Save to analysis_results table
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
            "error": None,"oob_price":"","oob_grade":"",
            "price_zones": analysis.price_zones,
        })
        try:
            conn_save = db.get_conn()
            conn_save.execute("""
                INSERT OR REPLACE INTO analysis_results (name, price_rmb, grade, trend_dir, trend_score, report_html, created_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))
            """, (analysis.name, analysis.price_rmb, grade, trend_dir, trend_score, report_html))
            conn_save.commit()
            conn_save.close()
        except Exception as _e:
            _web_log.warning(f"Failed to save analysis result: {_e}")

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
            "price_zones": analysis.price_zones,
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

        good_id, page_title = await collector_csqaq.search_good_id(name)
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
        # Fetch steamdt volume (csqaq K-line has no volume data)
        steamdt_vol = 0
        if hasattr(item, 'steam_name') and item.steam_name:
            try:
                sv = await collector_steamdt.fetch_steamdt_volume(item.steam_name)
                if isinstance(sv, dict) and sv:
                    steamdt_vol = list(sv.values())[0]
            except Exception as _vol_err:
                _web_log.warning(f"steamdt volume failed: {_vol_err}")

        volume_day = steamdt_vol if steamdt_vol > 0 else max(1, volume_total // 20)
        if steamdt_vol > 0 and daily_bars and len(daily_bars) > 0:
            daily_bars[-1].volume = steamdt_vol
        if steamdt_vol > 0 and daily_bars and len(daily_bars) > 0:
            daily_bars[-1].volume = steamdt_vol  # fill latest bar with real volume

        price_history = [k.close for k in daily_bars if k.close > 0] if daily_bars else []
        volume_history = [k.volume for k in daily_bars] if daily_bars else []
        supply_history = [k.in_sale_count for k in daily_bars] if daily_bars else []

        # Build market context
        conn_m = db.get_conn()
        market_history = []
        market_pct = 50
        market_z = 0.0
        try:
            rows = conn_m.execute(
                "SELECT date, value FROM market_index ORDER BY date ASC"
            ).fetchall()
            market_history = [(r["date"], float(r["value"])) for r in rows] if rows else []
            if market_history:
                values = [v for _, v in market_history if v > 0]
                if len(values) >= 30:
                    current_m = values[-1]
                    below = sum(1 for v in values if v < current_m)
                    market_pct = round(below / len(values) * 100, 1)
                    mean_m = sum(values) / len(values)
                    std_m = (sum((v - mean_m) ** 2 for v in values) / len(values)) ** 0.5
                    market_z = round((current_m - mean_m) / std_m, 2) if std_m > 0 else 0
        finally:
            conn_m.close()

        analysis = item_analysis.run_item_analysis(
            name=exact_name,
            prices=price_history,
            volumes=volume_history if volume_history else None,
            supply_hist=supply_history if supply_history else None,
            order_book=item.order_book,
            index_change_7d=idx.change_7d,
            market_history=market_history,
            market_pct_90d=market_pct,
            market_zscore=market_z,
        )
        analysis.volume_day = volume_day
        analysis.volume_total = volume_total
        if hasattr(analysis, 'aux') and analysis.aux:
            analysis.aux.turnover_rate = round(volume_day / volume_total * 100, 3) if volume_total > 0 else 0
            analysis.aux.mean_volume_7d = volume_day
    # Persist 90-day kline data
        if daily_bars:
            try:
                conn_p = db.get_conn()
                pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id, in_watchlist=1)
                db.save_price_history_batch(conn_p, pid, daily_bars)
                conn_p.commit()
                conn_p.close()
            except Exception as _pe:
                _web_log.warning("kline persist failed: " + str(_pe))


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
            "price_zones": analysis.price_zones,
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

        good_id, page_title = await collector_csqaq.search_good_id(name)
        if good_id == 0:
            return HTMLResponse(_ae(f"未找到: {name}"))

        item = await collector_csqaq.fetch_item_detail(good_id)
        if item is None:
            return HTMLResponse(_ae(f"详情获取失败"))

        exact_name = _clean_csqaq_name(item.name or page_title or name)
        price_rmb = item.price_rmb
        volume_total = item.volume_total
        if volume_total == 0 and hasattr(item, 'in_sale_count') and item.in_sale_count:
            volume_total = item.in_sale_count

        daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
        supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []
        prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else []
        # Fetch steamdt volume (csqaq K-line has no volume data)
        steamdt_vol = 0
        if hasattr(item, 'steam_name') and item.steam_name:
            try:
                sv = await collector_steamdt.fetch_steamdt_volume(item.steam_name)
                if isinstance(sv, dict) and sv:
                    steamdt_vol = list(sv.values())[0]
            except Exception:
                pass
        volume_day = steamdt_vol if steamdt_vol > 0 else max(1, volume_total // 20)
        if steamdt_vol > 0 and daily_bars and len(daily_bars) > 0:
            daily_bars[-1].volume = steamdt_vol
        volumes = [k.volume for k in daily_bars] if daily_bars else []

        # Build market context from stored index history
        conn_m = db.get_conn()
        market_history = []
        market_pct = 50
        market_z = 0.0
        market_cycle = "unknown"
        market_th = 50
        market_7d_change = 0.0
        market_30d_change = 0.0
        try:
            rows = conn_m.execute(
                "SELECT date, value FROM market_index ORDER BY date ASC"
            ).fetchall()
            market_history = [(r["date"], float(r["value"])) for r in rows] if rows else []
            if market_history:
                values = [v for _, v in market_history if v > 0]
                if len(values) >= 30:
                    current_m = values[-1]
                    below = sum(1 for v in values if v < current_m)
                    market_pct = round(below / len(values) * 100, 1)
                    mean_m = sum(values) / len(values)
                    std_m = (sum((v - mean_m) ** 2 for v in values) / len(values)) ** 0.5
                    market_z = round((current_m - mean_m) / std_m, 2) if std_m > 0 else 0
                    # Compute market 7d and 30d change
                    m7 = values[-7] if len(values) >= 7 else values[0]
                    m30 = values[-30] if len(values) >= 30 else values[0]
                    market_7d_change = round((current_m - m7) / m7 * 100, 1) if m7 > 0 else 0
                    market_30d_change = round((current_m - m30) / m30 * 100, 1) if m30 > 0 else 0
                    # Determine market cycle
                    vol_7d = 0.0
                    if len(values) >= 7:
                        vol_7d = (sum((v - mean_m) ** 2 for v in values[-7:]) / 7) ** 0.5 / mean_m * 100 if mean_m > 0 else 0
                    if market_30d_change > 5 and market_7d_change > 1:
                        market_cycle = "bull"
                    elif market_30d_change < -5 and market_7d_change < -1:
                        market_cycle = "bear"
                    elif vol_7d > 3:
                        market_cycle = "volatile"
                    elif abs(market_30d_change) <= 3 and abs(market_7d_change) <= 1:
                        market_cycle = "sideways"
                    elif market_30d_change < -2:
                        market_cycle = "distribution" if market_7d_change < 0 else "accumulation"
                    else:
                        market_cycle = "sideways"
                    # Market trend health: normalize 30d change to 0-100 score
                    market_th = max(0, min(100, 50 + market_30d_change * 3))
        finally:
            conn_m.close()

        analysis = item_analysis.run_item_analysis(
            name=exact_name,
            prices=prices if prices else [price_rmb],
            volumes=volumes if volumes else None,
            supply_hist=supply_hist if supply_hist else None,
            order_book=item.order_book,
            index_change_7d=idx.change_7d,
            market_history=market_history,
            market_pct_90d=market_pct,
            market_zscore=market_z,
            market_cycle=market_cycle,
            market_th_score=market_th,
        )
        analysis.volume_day = volume_day
        analysis.volume_total = volume_total
        if hasattr(analysis, 'aux') and analysis.aux:
            analysis.aux.turnover_rate = round(volume_day / volume_total * 100, 3) if volume_total > 0 else 0
            analysis.aux.mean_volume_7d = volume_day
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
            from datetime import datetime as _dt
            today = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
            # Check if snapshot exists for today, update or insert
            existing = conn_save.execute(
                "SELECT id FROM snapshots WHERE item_id=? AND date=?",
                (item_id, today)
            ).fetchone()
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
                    "error": None,"oob_price":"","oob_grade":"",
                "price_zones": analysis.price_zones,
                "analysis_time": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            if existing:
                conn_save.execute(
                    "UPDATE snapshots SET report_html=?, total_score=?, grade=?, price_rmb=?, score_scarcity=?, score_volume=?, score_market=?, score_liquidity=?, report_md=? WHERE id=?",
                    (report_html, score, grade, analysis.price_rmb,
                     analysis.value.scarcity if hasattr(analysis.value, "scarcity") else 0,
                     analysis.value.volume if hasattr(analysis.value, "volume") else 0,
                     analysis.value.market_sentiment if hasattr(analysis.value, "market_sentiment") else 0,
                     analysis.value.liquidity if hasattr(analysis.value, "liquidity") else 0,
                     "", existing["id"])
                )
            else:
                conn_save.execute(
                    "INSERT INTO snapshots (item_id, date, report_html, total_score, grade, price_rmb, score_scarcity, score_volume, score_market, score_liquidity) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (item_id, today, report_html, score, grade, analysis.price_rmb,
                     analysis.value.scarcity if hasattr(analysis.value, "scarcity") else 0,
                     analysis.value.volume if hasattr(analysis.value, "volume") else 0,
                     analysis.value.market_sentiment if hasattr(analysis.value, "market_sentiment") else 0,
                     analysis.value.liquidity if hasattr(analysis.value, "liquidity") else 0)
                )
            conn_save.commit()
        except Exception as _se:
            import traceback as _tb
            with open("snapshot_error.log", "a", encoding="utf-8") as _ef:
                _ef.write(f"\n=== SNAPSHOT ERROR {str(item_id)} ===\n{_tb.format_exc()}\n=== END ===\n")
            _web_log.warning(f"Failed to save snapshot: {_se}")
        finally:
            conn_save.close()

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
            "price_zones": analysis.price_zones,
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

async def _run_batch_scan_task(scan_id: str, rows: list):
    import json as _json
    from pipeline.batch_scan import _portfolio_advice
    from pipeline import collector_csqaq, collector_steamdt, item_analysis, collector
    idx = collector.fetch_market_index()
    if idx is None or idx.value == 0:
        idx = type("obj", (object,), {"value": 0, "change_7d": 0})()
    # Compute market TH once for resonance-aware portfolio advice
    market_th_score = 50
    try:
        conn_m = db.get_conn()
        rows_m = conn_m.execute('SELECT value FROM market_index ORDER BY date DESC LIMIT 90').fetchall()
        conn_m.close()
        if len(rows_m) >= 14:
            vals_m = [r['value'] for r in reversed(rows_m)]
            from pipeline.market_th import compute_market_trend_health
            mth_m = compute_market_trend_health(vals_m)
            market_th_score = mth_m.corrected_score if hasattr(mth_m, 'corrected_score') else mth_m.score
    except Exception:
        pass
    results = []
    total = len(rows)
    for i, row in enumerate(rows):
        item_id, name, holding, avg_cost, qty = row["id"], row["name"], row["holding"] or 0, row["avg_cost"] or 0, row["quantity"] or 0
        _scan_progress[scan_id]["current"] = i + 1
        _scan_progress[scan_id]["name"] = name
        try:
            good_id, _ = await collector_csqaq.search_good_id(name)
            if good_id == 0:
                results.append(dict(name=name, holding=holding, error="\u672a\u627e\u5230"))
                continue
            item = await collector_csqaq.fetch_item_detail(good_id)
            if item is None:
                results.append(dict(name=name, holding=holding, error="\u8be6\u60c5\u83b7\u53d6\u5931\u8d25"))
                continue
            exact_name = item.name or name
            daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
            prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else [item.price_rmb]
            volumes = [k.volume for k in daily_bars] if daily_bars else []
            supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []
            steamdt_vol = 0
            if hasattr(item, "steam_name") and item.steam_name:
                try:
                    sv = await collector_steamdt.fetch_steamdt_volume(item.steam_name)
                    if sv and isinstance(sv, dict):
                        steamdt_vol = list(sv.values())[0]
                except Exception:
                    pass
            volume_day = steamdt_vol if steamdt_vol > 0 else max(1, (item.volume_total or 0) // 20)
            analysis = item_analysis.run_item_analysis(
                name=exact_name, prices=prices, volumes=volumes or None,
                supply_hist=supply_hist or None, order_book=item.order_book,
                index_change_7d=getattr(idx, "change_7d", 0),
            )
            analysis.volume_day = volume_day
            analysis.volume_total = item.volume_total or 0
            pa = _portfolio_advice(holding, avg_cost, qty, item.price_rmb, analysis, market_th=market_th_score)
            results.append(dict(
                name=exact_name, holding=holding, avg_cost=avg_cost, qty=qty,
                price_rmb=item.price_rmb, grade=analysis.value.grade, score=analysis.value.score,
                portfolio_advice=pa,
                valuation_tier=getattr(analysis.position, "valuation_tier", "") if hasattr(analysis, "position") else "",
                percentile_90d=getattr(analysis.position, "percentile_90d", 50) if hasattr(analysis, "position") else 50,
                error=None,
            ))
            # Persist
            conn_p = db.get_conn()
            try:
                pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id, in_watchlist=1)
                db.save_price_history_batch(conn_p, pid, daily_bars)
                conn_p.commit()
            finally:
                conn_p.close()
            # Snapshot + summary
            conn_s = db.get_conn()
            try:
                today = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                report_html = templates.get_template("partials/analysis.html").render({
                    "name": analysis.name, "price_rmb": item.price_rmb,
                    "volume_day": analysis.volume_day, "volume_total": item.volume_total or 0,
                    "position": analysis.position, "aux": analysis.aux,
                    "cycle": analysis.cycle, "liquidity": analysis.liquidity,
                    "probability": analysis.probability, "value": analysis.value,
                    "whale": analysis.whale, "data_quality": analysis.data_quality,
                    "trend_health": analysis.trend_health, "fusion_decision": analysis.fusion_decision,
                    "error": None, "oob_price": "", "oob_grade": "",
                    "price_zones": analysis.price_zones,
                    "analysis_time": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                score = analysis.value.score
                grade = analysis.value.grade
                summary_json = _json.dumps({
                    "valuation_tier": getattr(analysis.position, "valuation_tier", "") if hasattr(analysis, "position") else "",
                    "percentile_90d": getattr(analysis.position, "percentile_90d", 50) if hasattr(analysis, "position") else 50,
                    "cycle_phase": getattr(analysis.cycle, "phase", "") if hasattr(analysis, "cycle") else "",
                    "fusion_action": analysis.fusion_decision.get("action", "") if isinstance(getattr(analysis, "fusion_decision", None), dict) else "",
                    "score": score, "grade": grade,
                }, ensure_ascii=False)
                existing = conn_s.execute("SELECT id FROM snapshots WHERE item_id=? AND date=?", (item_id, today)).fetchone()
                if existing:
                    conn_s.execute("UPDATE snapshots SET report_html=?, total_score=?, grade=?, price_rmb=?, recommendation=? WHERE id=?", (report_html, score, grade, item.price_rmb, summary_json, existing["id"]))
                else:
                    conn_s.execute("INSERT INTO snapshots (item_id, date, report_html, total_score, grade, price_rmb, recommendation) VALUES (?,?,?,?,?,?,?)", (item_id, today, report_html, score, grade, item.price_rmb, summary_json))
                conn_s.commit()
                db.set_setting(conn_s, f"th_{pid}", _json.dumps(analysis.trend_health, ensure_ascii=False) if analysis.trend_health else "")
                conn_s.commit()
            except Exception as _se:
                import traceback as _tb
                with open("snapshot_error.log", "a", encoding="utf-8") as _ef:
                    _ef.write("\n=== BATCH ERROR " + str(item_id) + " ===\n" + _tb.format_exc() + "\n=== END ===\n")
                _web_log.warning(f"Batch save error: {_se}")
            finally:
                conn_s.close()
        except Exception as e:
            _web_log.error(f"batch scan item failed: {name}: {e}")
            results.append(dict(name=name, holding=holding, error=str(e)[:100]))
    
    # Build HTML
    held = [r for r in results if r.get("holding") and r.get("error") is None]
    unheld = [r for r in results if not r.get("holding") and r.get("error") is None]
    errors = [r for r in results if r.get("error")]
    html = ["<div class=\"card\" id=\"batch-result-{scan_id}\"><div class=\"card-header\" style=\"justify-content:space-between;\"><span class=\"card-title\">\u6279\u91cf\u626b\u63cf\u5b8c\u6210</span>".format(scan_id=scan_id)]
    now_str = __import__("datetime").datetime.now().strftime("%H:%M:%S")
    html.append("<span style=\"font-size:13px;color:var(--text-muted);\">" + now_str + " | \u6210\u529f " + str(len(results)) + "/" + str(total) + " | \u5237\u65b0\u540e\u4ecd\u4fdd\u7559</span></div></div>")
    if held:
        html.append("<div class=\"card\" style=\"margin-bottom:16px;\"><div class=\"card-header\"><span class=\"card-title\">\u6301\u4ed3\u5206\u6790 (" + str(len(held)) + ")</span></div><div class=\"table-wrap\"><table><thead><tr><th>\u7269\u54c1</th><th>\u6210\u672c/\u73b0\u4ef7</th><th>\u76c8\u4e8f</th><th>\u8bc4\u5206</th><th>\u5efa\u8bae</th></tr></thead><tbody>")
        for r in held:
            pnl_pct = (r["price_rmb"] - r["avg_cost"]) / r["avg_cost"] * 100 if r.get("avg_cost", 0) > 0 else 0
            pa = r.get("portfolio_advice", {})
            pnl_c = "green" if pnl_pct > 5 else ("red" if pnl_pct < -5 else "")
            g = (r.get("grade") or "?").lower()
            html.append("<tr><td><strong>" + str(r["name"]) + "</strong></td>")
            html.append("<td>\u00a5" + "%.2f" % r["avg_cost"] + " \u2192 <strong>\u00a5" + "%.2f" % r["price_rmb"] + "</strong></td>")
            html.append("<td class=\"" + pnl_c + "\">" + "%.1f" % pnl_pct + "%</td>")
            html.append("<td><span class=\"badge badge-" + g + "\">" + str(r.get("grade","?")) + "</span></td>")
            html.append("<td><span style=\"font-size:12px;font-weight:600;color:var(--accent);\">" + pa.get("action","") + "</span><br><span style=\"font-size:11px;color:var(--text-muted);\">" + pa.get("suggest","") + "</span></td></tr>")
        html.append("</tbody></table></div></div>")
    if unheld:
        html.append("<div class=\"card\" style=\"margin-bottom:16px;\"><div class=\"card-header\"><span class=\"card-title\">\u5173\u6ce8\u5217\u8868 (" + str(len(unheld)) + ")</span></div><div class=\"table-wrap\"><table><thead><tr><th>\u7269\u54c1</th><th>\u73b0\u4ef7</th><th>\u8bc4\u5206</th><th>\u4f30\u503c</th><th>\u5efa\u8bae</th></tr></thead><tbody>")
        for r in unheld:
            pa = r.get("portfolio_advice", {})
            g = (r.get("grade") or "?").lower()
            html.append("<tr><td><strong>" + str(r["name"]) + "</strong></td>")
            html.append("<td>\u00a5" + "%.2f" % r["price_rmb"] + "</td>")
            html.append("<td><span class=\"badge badge-" + g + "\">" + str(r.get("grade","?")) + "</span></td>")
            html.append("<td style=\"font-size:12px;\">" + str(r.get("valuation_tier","?")) + "<br><span style=\"color:var(--text-muted);\">pct=" + "%.1f" % r.get("percentile_90d",50) + "%</span></td>")
            html.append("<td><span style=\"font-size:12px;font-weight:600;color:var(--accent);\">" + pa.get("action","") + "</span></td></tr>")
        html.append("</tbody></table></div></div>")
    if errors:
        html.append("<div class=\"card\" style=\"border-color:var(--red);\"><div class=\"card-header\"><span class=\"card-title\">\u626b\u63cf\u5931\u8d25</span></div>")
        for e in errors:
            html.append("<div style=\"margin-bottom:4px;\"><strong>" + str(e["name"]) + "</strong>: <span style=\"color:var(--red);\">" + str(e.get("error","")) + "</span></div>")
        html.append("</div>")
    _scan_progress[scan_id]["html"] = final_html = "\n".join(html)
    _scan_progress[scan_id]["done"] = True
    # Persist to disk
    try:
        import json as _jcache
        from pathlib import Path as _P
        _cache_path = _P(__file__).resolve().parent.parent / "data" / "batch_scan_latest.json"
        _cache_path.write_text(_jcache.dumps({"time": __import__("datetime").datetime.now().isoformat(), "html": final_html}, ensure_ascii=False), encoding="utf-8")
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
        return {"found": True, "time": data["time"], "html": data.get("html", "")}
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
    from pipeline import collector_csqaq, collector_steamdt, item_analysis as _ia
    # Get market TH for context-aware filtering
    market_th = 50
    try:
        conn_m = db.get_conn()
        rows_m = conn_m.execute('SELECT value FROM market_index ORDER BY date DESC LIMIT 90').fetchall()
        conn_m.close()
        if len(rows_m) >= 14:
            vals_m = [r['value'] for r in reversed(rows_m)]
            from pipeline.market_th import compute_market_trend_health
            mth_m = compute_market_trend_health(vals_m)
            market_th = mth_m.corrected_score if hasattr(mth_m, 'corrected_score') else mth_m.score
    except Exception:
        pass
    results = []
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
            prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else [price_rmb]

            # P0: Pre-filter - skip items with high percentile (overvalued)
            if len(prices) >= 14:
                current_p = prices[-1]
                pct_quick = sum(1 for p in prices if p < current_p) / len(prices) * 100
                if pct_quick > 75:
                    skipped += 1
                    continue

            volumes = [k.volume for k in daily_bars] if daily_bars else []
            supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []

            steamdt_vol = 0
            if hasattr(item, "steam_name") and item.steam_name:
                try:
                    sv = await collector_steamdt.fetch_steamdt_volume(item.steam_name)
                    if sv and isinstance(sv, dict):
                        steamdt_vol = list(sv.values())[0]
                except Exception:
                    pass
            volume_day = steamdt_vol if steamdt_vol > 0 else max(1, (item.volume_total or 0) // 20)

            analysis = _ia.run_item_analysis(
                name=exact_name, prices=prices, volumes=volumes or None,
                supply_hist=supply_hist or None, order_book=item.order_book,
                index_change_7d=0,
            )

            pos = analysis.position if hasattr(analysis, "position") else {}
            pct_val = getattr(pos, "percentile_90d", 50) if hasattr(pos, "percentile_90d") else 50
            z_val = getattr(pos, "zscore_90d", 0) if hasattr(pos, "zscore_90d") else 0
            score = analysis.value.score

            # P1: Composite score = score * valuation discount
            valuation_discount = max(0.5, 1.0 - pct_val / 200)
            composite = round(score * valuation_discount, 1)

            # P3: Market-linked filter
            if market_th < 55 and score < 6.0 and composite < 5.0:
                skipped += 1
                continue

            results.append(dict(
                name=exact_name, price_rmb=price_rmb or item.price_rmb,
                grade=analysis.value.grade, score=score, composite=composite,
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
            f'<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{r["name"]}</td>'
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
    capped = []
    for wt_items in by_type.values():
        capped.extend(wt_items[:3])
    capped = capped[:24]

    _discover_progress[task_id]["total"] = len(capped)
    _discover_progress[task_id]["current"] = 0
    await _run_discover_task(task_id, capped)

    # Save cache for re-viewing
    import json as _json_cache
    from pathlib import Path as _Path_cache
    _cache_path = _Path_cache(__file__).resolve().parent.parent / 'data' / 'discover_latest.json'
    _cache_path.parent.mkdir(parents=True, exist_ok=True)
    _cache_data = {'time': __import__('datetime').datetime.now().isoformat(), 'html': _discover_progress[task_id].get('html', '')}
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
        return {"found": True, "time": data["time"], "html": data.get("html", "")}
    except Exception:
        return {"found": False}

@app.get("/api/items/discover-progress/{task_id}")
async def api_discover_progress(task_id: str):
    p = _discover_progress.get(task_id)
    if not p:
        return {"error": "not found"}
    return {"current": p["current"], "total": p["total"], "name": p.get("name", ""), "done": p["done"], "html": p.get("html", ""), "results": p.get("results", []) if p["done"] else []}
