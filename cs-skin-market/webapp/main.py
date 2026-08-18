"""CS-Market Web App - FastAPI application."""

import sys, io, asyncio, json, re, traceback, time
if getattr(sys.stdout, "encoding", "").lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if getattr(sys.stderr, "encoding", "").lower().replace("-", "") != "utf8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logging
from pipeline import db, collector, index_analysis
from pipeline import collector_csqaq
from pipeline.config import TZ_BJ
from pipeline.dashboards import _j2_status
from webapp.analysis_service import (
    AnalysisAbort, analyze_fresh, build_analysis_ctx,
    resolve_item, KLINE_FRESH_SINGLE, KLINE_FRESH_SINGLE_HOURS,
    kline_db_fallback, market_snapshot, bust_market_snapshot_cache,
    recent_buy_dates, _today_str,
    sticker_whale_fingerprint, render_sticker_whale_block,
)

from webapp.render_html import render_report_html, render_discover_html, spark_svg

from pipeline.scan_tasks import (
    _scan_progress, _scan_progress_file, _persist_scan_progress, _load_scan_progress,
    _run_batch_scan_task, _resolve_good_id,
)
from pipeline.discover_tasks import (
    _discover_progress, DISCOVER_WEAPONS, _discover_progress_file,
    _run_discover_pool_task, _run_discover_scan_all_task, _settle_discover_items,
)

_web_log = logging.getLogger("webapp")

# In-memory analysis cache
_analysis_cache = {}
_ANALYSIS_CACHE_MAX = 200  # 分析缓存上限 200 条（TTL 1800s）

def _cached_analysis(item_id, compute_fn):
    import time as _time
    now = _time.time()
    entry = _analysis_cache.get(item_id)
    if entry and (now - entry[0]) < 1800:
        return entry[1]
    result = compute_fn()
    if len(_analysis_cache) >= _ANALYSIS_CACHE_MAX:
        try:
            _oldest = next(iter(_analysis_cache))
            del _analysis_cache[_oldest]
        except (StopIteration, KeyError):
            pass
    _analysis_cache[item_id] = (now, result)
    return result

app = FastAPI(title="CS-Market")
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _ae(msg: str) -> str:
    """Wrap error message in styled HTML."""
    return f"""<div class="card" style="border-color: rgba(239,68,68,0.5);">
<div class="card-header"><span class="card-title">&#9888;&#65039; 错误</span></div>
<p style="color: var(--red);">{msg}</p>
</div>"""


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

def _market_status_card(analysis_data):
    """市场状态卡（2026-08-18 合并版，纯展示）：大盘信号+开火族+宏观 三合一。
    合并原「🧪 当前市场状态×信号族期望」「📡 大盘信号·风险仪表」「🌍 宏观环境」三卡；
    期望分层表/双基线风险视图从页面下架（数据链路与测试保留）。"""
    try:
        from pipeline.market_signal import market_signal as _ms
        conn = db.get_conn()
        try:
            sig = _ms(conn)
        finally:
            conn.close()
        macro = None
        if isinstance(analysis_data, dict) and analysis_data.get("macro_context"):
            mc = analysis_data["macro_context"]
            macro = {"breadth_7d": mc.get("breadth_7d"), "sentiment_score": mc.get("sentiment_score"),
                     "sentiment_label": mc.get("sentiment_label"), "online_score": mc.get("online_score"),
                     "card_score": mc.get("card_score")}
        return {"signal": sig, "macro": macro}
    except Exception:
        return None

def _upcoming_events(days: int = 45):
    """F-1 未来事件（2026-08-10，纯提示层）：读 EVENT_CALENDAR 未来条目，异常兜底空列表。"""
    try:
        from pipeline.market_macro import upcoming_events
        return upcoming_events(days=days)
    except Exception:
        return []

@app.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    mi, last_update, chart_data = _dashboard_context()
    # Index analysis
    analysis_data = index_analysis.analyze_index_full(chart_data) if chart_data else None
    # I-1 市场状态标注(2026-08-06 接入；2026-08-16 起五时期口径): 接线 index_card 的 regime 占位, 纯展示层
    from pipeline.batch_scan import market_regime
    _ms_r = market_snapshot()
    _regime_label, _regime_cls, _regime_strategy = market_regime(
        _ms_r.get("chg180"), _ms_r.get("chg30"), _ms_r.get("sentiment"))
    # ---- 引擎状态徽章（J-2 监测，纯展示；读 j2_channel_status.json）----
    _engine_status = None
    _j2 = _j2_status()
    if _j2:
        try:
            _ch = _j2.get("channels") or {}
            _c = _ch.get("C") or {}
            _monthly = _c.get("monthly") or []
            _flagged = [mm for mm in _monthly if mm.get("flags")]
            _engine_status = {
                "engine_version": _j2.get("engine_version", ""),
                "monitor_start": _j2.get("monitor_start", ""),
                "sample_target_days": _j2.get("sample_target_days", ""),
                "a_value": (_ch.get("A") or {}).get("value"),
                "a_threshold": (_ch.get("A") or {}).get("threshold"),
                "a_status": (_ch.get("A") or {}).get("status"),
                "b_days": (_ch.get("B") or {}).get("value_days"),
                "b_threshold": (_ch.get("B") or {}).get("threshold_days"),
                "b_target": (_ch.get("B") or {}).get("target_date"),
                "c_flagged": len(_flagged),
                "c_latest_month": (_flagged[-1].get("month") if _flagged else None),
                "c_latest_flags": (_flagged[-1].get("flags") or []) if _flagged else [],
                "optimization_view": _j2.get("optimization_view"),
            }
        except Exception:
            _engine_status = None
    response = templates.TemplateResponse(request, "dashboard.html", {
        "active_page": "dashboard",
        "index": mi,
        "regime_label": _regime_label,
        "regime_class": _regime_cls,
        "regime_strategy": _regime_strategy,
        "last_update": last_update,
        "chart_data": chart_data,
        "analysis": analysis_data,
        "engine_status": _engine_status,
        "upcoming_events": _upcoming_events(),
        "market_status": _market_status_card(analysis_data),
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
        # ---- 买点接近度（自选快照 proximity，供排序）----
        for _it in all_items:
            _prox = None
            _wsum = None
            if _it.get("latest_summary"):
                try:
                    _wsum = json.loads(_it["latest_summary"])
                    _prox = _wsum.get("proximity")
                except Exception:
                    _wsum = None
            _it["proximity"] = _prox if isinstance(_prox, dict) else None
            _it["wl_summary"] = _wsum
        if ws == "name":
            filtered.sort(key=lambda i: (i.get("name") or "").lower())
        elif ws == "price_desc":
            filtered.sort(key=lambda i: i.get("latest_price") or 0, reverse=True)
        elif ws == "price_asc":
            filtered.sort(key=lambda i: i.get("latest_price") or 0)
        elif ws == "grade":
            _gorder = {"S": 0, "A": 1, "B": 2, "C": 3, "Z": 4}
            filtered.sort(key=lambda i: _gorder.get(i.get("latest_grade") or "Z", 4))
        elif ws == "proximity":
            filtered.sort(key=lambda i: (i.get("proximity") or {}).get("score", -1), reverse=True)

        # ---- per-item pnl + portfolio totals (holding items only) ----
        for item in all_items:
            item["pnl_pct"] = None
            if item.get("holding") and item.get("avg_cost", 0) > 0 and item.get("latest_price"):
                item["pnl_pct"] = (item["latest_price"] - item["avg_cost"]) / item["avg_cost"] * 100
        total_buy_cost = sum((i.get("avg_cost") or 0) * (i.get("quantity") or 0) for i in all_items if i.get("holding"))
        total_market = sum((i.get("latest_price") or 0) * (i.get("quantity") or 0) for i in all_items if i.get("holding"))
        floating_pnl = total_market - total_buy_cost
        realized_pnl = db.realized_pnl_total(conn)
        total_pnl = floating_pnl + realized_pnl
        total_pnl_pct = (total_pnl / total_assets * 100) if total_assets > 0 else 0
        net_assets = total_assets + total_pnl
        position_ratio = (total_buy_cost / total_assets * 100) if total_assets > 0 else 0

        # ---- 今日关注（A-3，2026-08-12）：当日事件聚合 + proximity 买点队列 + 破位止损 ----
        _today_str = datetime.now(TZ_BJ).strftime("%Y-%m-%d")
        _ev_rows = conn.execute(
            "SELECT item_id, item_name, event_type, level, detail, created_at FROM monitor_events "
            "WHERE date=? ORDER BY id DESC", (_today_str,)).fetchall()
        _buy_ev = []
        _warn_ev = []
        for _er in _ev_rows:
            _et = _er["event_type"]
            if _et == "new_buy_signal":
                _buy_ev.append(dict(_er))
            elif _et in ("stop_loss", "price_spike"):
                _warn_ev.append(dict(_er))
        _near = []
        _broken = []
        for _it in filtered:
            _prox = _it.get("proximity")
            _wsum = _it.get("wl_summary") or {}
            _act = _wsum.get("fusion_action")
            _sources = _wsum.get("deduction_sources") or []
            _is_sticker = bool((_it.get("name") or "").startswith("印花 |")) or "sticker_observation" in _sources
            if _prox and isinstance(_prox, dict) and _prox.get("score", 0) >= 60 and _act != "buy":
                _near.append({
                    "item_id": _it["id"], "name": _it["name"],
                    "score": _prox.get("score", 0), "nearest": _prox.get("nearest", ""),
                    "gaps": _prox.get("gaps") or [], "dedup_hit": bool(_prox.get("dedup_hit")),
                    "is_sticker": _is_sticker, "collected_at": _it.get("snapshot_created_at") or "",
                })
            if _it.get("holding") and _it.get("avg_cost", 0) > 0 and _it.get("latest_price"):
                if _it["latest_price"] <= _it["avg_cost"] * 0.75:
                    _broken.append({
                        "item_id": _it["id"], "name": _it["name"],
                        "latest_price": _it["latest_price"], "avg_cost": _it["avg_cost"],
                        "collected_at": _it.get("snapshot_created_at") or "",
                    })
        _near.sort(key=lambda x: x["score"], reverse=True)

        # ---- 今日 buy 信号（A-3 补充）：直接展示自选当前 fusion_action=buy/oversold_buy ----
        _buy_now = []
        _buy_ev_ids = {_e.get("item_id") for _e in _buy_ev if _e.get("item_id")}
        for _it in all_items:
            _wsum = _it.get("wl_summary") or {}
            _act = _wsum.get("fusion_action") or _wsum.get("action")
            if _act in ("buy", "oversold_buy") and _it.get("id") not in _buy_ev_ids:
                _detail_parts = []
                if _wsum.get("score") is not None:
                    _detail_parts.append("评分 {:.1f}".format(float(_wsum.get("score"))))
                if _wsum.get("valuation_tier"):
                    _detail_parts.append(str(_wsum.get("valuation_tier")))
                if _wsum.get("cycle_phase"):
                    _detail_parts.append(str(_wsum.get("cycle_phase")))
                if _it.get("latest_price"):
                    _detail_parts.append("¥{:.2f}".format(float(_it.get("latest_price"))))
                _buy_now.append({
                    "item_id": _it["id"],
                    "name": _it["name"],
                    "action": _act,
                    "score": float(_wsum.get("score") or 0),
                    "detail": " · ".join(_detail_parts) or "买入信号",
                    "collected_at": _it.get("snapshot_created_at") or "",
                })
        _buy_now.sort(key=lambda x: x["score"], reverse=True)

        # ---- EXEC-1 未记录 buy 提醒（2026-08-18）：近 7 天有 buy 信号但无执行记录的品 ----
        from pipeline.batch_scan import _recently_executed_names as _ren
        _recent_exec = _ren(7)
        _wl_names = {_it["name"] for _it in all_items}
        _d7 = (datetime.now(TZ_BJ) - timedelta(days=7)).strftime("%Y-%m-%d")
        _buy_sig = {}  # name -> {signal_date, latest_price}
        for _r in conn.execute(
            "SELECT item_name, signal_date FROM signal_tracking WHERE action='buy' AND signal_date >= ? "
            "ORDER BY signal_date DESC", (_d7,)).fetchall():
            _nm = _r["item_name"]
            if _nm in _wl_names:
                _buy_sig.setdefault(_nm, {"signal_date": _r["signal_date"], "latest_price": None})
        for _it in all_items:
            _wsum = _it.get("wl_summary") or {}
            _act = _wsum.get("fusion_action") or _wsum.get("action")
            if _act in ("buy", "oversold_buy"):
                _nm = _it["name"]
                _sd = (_it.get("snapshot_created_at") or _today_str)[:10]
                if _nm not in _buy_sig:
                    _buy_sig[_nm] = {"signal_date": _sd, "latest_price": _it.get("latest_price")}
                else:
                    _buy_sig[_nm]["latest_price"] = _it.get("latest_price")
        _unrecorded_buys = [
            {"name": _nm, "signal_date": _i["signal_date"], "latest_price": _i["latest_price"]}
            for _nm, _i in _buy_sig.items() if _nm not in _recent_exec
        ]
        _unrecorded_buys.sort(key=lambda x: x["signal_date"] or "", reverse=True)

        monitor = {
            "near_buys": _near[:5],
            "broken": _broken[:5],
            "buy_events": _buy_ev[:5],
            "buy_signals": _buy_now[:5],
            "warn_events": _warn_ev[:5],
            "unrecorded_buys": _unrecorded_buys,
            "has_focus": bool(_buy_ev or _buy_now or _near or _broken or _warn_ev or _unrecorded_buys),
            "today": _today_str,
        }

        # ---- A1-4 执行校准进度（A-6, 2026-08-12）：executions 计数供「录入 N/20」进度条 ----
        _exec_count = conn.execute("SELECT COUNT(*) AS c FROM executions").fetchone()["c"]

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

        # ---- 持仓盈亏可视化：30 日价格迷你走势 + 成本线 (2026-08-05) ----
        _spark_ids = [i["id"] for i in items if i.get("holding")]
        _spark_map = {}
        if _spark_ids:
            _marks = ",".join("?" * len(_spark_ids))
            for _sr in conn.execute(
                "SELECT item_id, date, price_rmb FROM price_history "
                "WHERE item_id IN (" + _marks + ") AND price_rmb>0 "
                "ORDER BY date DESC", _spark_ids).fetchall():
                _spark_map.setdefault(_sr["item_id"], []).append((_sr["date"], _sr["price_rmb"]))

        # ---- 卖出参考位（90日区间 + -25% 止损建议，纯展示）----
        _range_map = {}
        if _spark_ids:
            for _rr in conn.execute(
                "SELECT item_id, MAX(price_rmb) AS hi, MIN(price_rmb) AS lo FROM price_history "
                "WHERE item_id IN (" + _marks + ") AND price_rmb>0 GROUP BY item_id", _spark_ids).fetchall():
                _range_map[_rr["item_id"]] = (_rr["hi"], _rr["lo"])

        # ---- 建议来源信号（signal_tracking 最近一条 buy，纯展示）----
        _sig_map = {}
        if _spark_ids:
            for _sr in conn.execute(
                "SELECT item_id, signal_date, action_label, entry_price FROM signal_tracking "
                "WHERE item_id IN (" + _marks + ") ORDER BY signal_date DESC", _spark_ids).fetchall():
                _sig_map.setdefault(_sr["item_id"], []).append(dict(_sr))

        # Load trend health + parse latest_summary for each item
        import json as _json
        for item in items:
            _pts = _spark_map.get(item["id"], [])[:30][::-1] if item.get("holding") else []
            item["spark_svg"] = spark_svg(_pts, item.get("avg_cost") or 0)
            if item.get("holding") and item.get("avg_cost", 0) > 0:
                _ac = item["avg_cost"]
                _hi, _lo = _range_map.get(item["id"], (None, None))
                item["sell_ref"] = {
                    "stop_loss": round(_ac * 0.75, 2),
                    "high90": _hi,
                    "low90": _lo,
                    "broken": bool(item.get("latest_price") and item["latest_price"] <= _ac * 0.75),
                }
            _sigs = _sig_map.get(item["id"])
            item["latest_signal"] = None
            if _sigs:
                _ls = dict(_sigs[0])
                if _ls.get("entry_price") and item.get("latest_price"):
                    _ls["ret_vs_entry"] = (item["latest_price"] / _ls["entry_price"] - 1) * 100
                item["latest_signal"] = _ls
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
            "total_market": total_market,
            "floating_pnl": floating_pnl,
            "realized_pnl": realized_pnl,
            "net_assets": net_assets,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "position_ratio": position_ratio,
            "pagination": {"page": page, "total_pages": total_pages, "total_items": total_items},
            "wl_filter": wf,
            "wl_q": wq,
            "wl_sort": ws,
            "monitor": monitor,
            "exec_count": _exec_count,
            "all_items_json": json.dumps(
                [{"id": i["id"], "name": i["name"], "holding": bool(i.get("holding"))} for i in all_items],
                ensure_ascii=False),
        })
    finally:
        conn.close()

# ---- 数据备份 (P2-3, 2026-08-07: SQLite 一键备份到 data/backups) ----
@app.post("/api/backup/create")
async def api_backup_create():
    try:
        import sqlite3 as _sq
        _src_path = db.DB_PATH
        _bdir = Path(str(_src_path)).parent / "backups"
        _bdir.mkdir(exist_ok=True)
        _name = "cs-market-backup-%s.db" % datetime.now(TZ_BJ).strftime("%Y%m%d-%H%M%S")
        _src = _sq.connect(str(_src_path))
        _dst = _sq.connect(str(_bdir / _name))
        _src.backup(_dst)
        _dst.close(); _src.close()
        return {"ok": True, "file": _name, "size": (_bdir / _name).stat().st_size}
    except Exception as _e:
        return {"ok": False, "error": str(_e)}


@app.get("/api/backup/list")
async def api_backup_list():
    try:
        _bdir = Path(str(db.DB_PATH)).parent / "backups"
        _bdir.mkdir(exist_ok=True)
        _files = []
        for _p in sorted(_bdir.glob("*.db"), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
            _files.append({"name": _p.name, "size": _p.stat().st_size,
                           "time": datetime.fromtimestamp(_p.stat().st_mtime, TZ_BJ).strftime("%Y-%m-%d %H:%M")})
        return {"files": _files}
    except Exception as _e:
        return {"files": [], "error": str(_e)}


@app.get("/api/backup/download")
async def api_backup_download(file: str = Query("")):
    _bdir = Path(str(db.DB_PATH)).parent / "backups"
    _safe = Path(file).name
    _p = _bdir / _safe
    if not _safe or not _p.exists() or not _p.is_file():
        return JSONResponse({"error": "备份文件不存在"}, status_code=404)
    return FileResponse(str(_p), filename=_safe, media_type="application/octet-stream")


# ---- Market refresh ----
@app.post("/api/market/refresh")
async def api_market_refresh(request: Request):
    try:
        idx = await asyncio.to_thread(collector.fetch_market_index)
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
        bust_market_snapshot_cache()
        try:
            from pipeline.market_signal import bust_cache as _ms_bust
            _ms_bust()
        except Exception:
            pass
        mi, last_update, chart_data = _dashboard_context()
        analysis_data = index_analysis.analyze_index_full(chart_data) if chart_data else None
        # I-1 市场状态标注: 与首页 / 渲染口径一致（缺 regime_* 会导致 index_card 的「策略」徽章/提示消失）
        from pipeline.batch_scan import market_regime
        _ms_r = market_snapshot()
        _regime_label, _regime_cls, _regime_strategy = market_regime(
            _ms_r.get("chg180"), _ms_r.get("chg30"), _ms_r.get("sentiment"))
        return templates.TemplateResponse(request, "partials/dashboard_refresh.html", {
            "index": mi,
            "last_update": last_update,
            "chart_data": chart_data,
            "analysis": analysis_data,
            "regime_label": _regime_label,
            "regime_class": _regime_cls,
            "regime_strategy": _regime_strategy,
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
        item = await resolve_item(good_id, page_title or query, KLINE_FRESH_SINGLE, max_stale_hours=KLINE_FRESH_SINGLE_HOURS)
        if item is None:
            return HTMLResponse('<div class="card"><div class="empty-state" style="text-align:center;padding:40px;color:var(--text-muted);">获取详情失败，请重试</div></div>')

        exact_name = _clean_csqaq_name(item.name or page_title or query)
        if not _verify_item_name(query, exact_name):
            return HTMLResponse('<div class="card"><div class="empty-state" style="text-align:center;padding:40px;color:var(--text-muted);">搜索结果与查询不匹配，请尝试更精确的关键词</div></div>')

        # Step 3: 统一分析核心（2026-08-07 重构，原 ~90 行内联逻辑迁至 analysis_service.analyze_fresh）
        b = await analyze_fresh(item, good_id, exact_name, hard_error_no_kline=True)
        ctx = build_analysis_ctx(b["analysis"], b["kline_stale_days"], b["kline_stale_date"],
                                 holding_ctx=b.get("holding_ctx"),
                                 market_30d_change=b.get("market_30d_change"),
                                 market_th=b.get("market_th"), sentiment=b.get("sentiment", 50.0),
                                 collected_at=b.get("collected_at"))
        return templates.TemplateResponse(request, "partials/analysis.html", ctx)

    except AnalysisAbort as _ab:
        return HTMLResponse(_ae(_ab.msg))
    except Exception as e:
        import traceback
        _web_log.error(f"Search error: {e}\n{traceback.format_exc()}")
        return HTMLResponse(_ae(f"分析失败: {(str(e) or type(e).__name__)[:300]}"))


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
    try:
        good_id, page_title = await _resolve_good_id(name)
        if good_id == 0:
            return HTMLResponse(_ae("未找到物品: " + name))

        item = await resolve_item(good_id, name, KLINE_FRESH_SINGLE, max_stale_hours=KLINE_FRESH_SINGLE_HOURS)
        if item is None:
            return HTMLResponse(_ae(f"获取详情失败: good_id={good_id}"))
        exact_name = _clean_csqaq_name(item.name or page_title or name)

        if not _verify_item_name(name, exact_name):
            _web_log.warning(f"Item name '{exact_name}' does not match query '{name}', trying alternative search")
            simple_q = name.replace("(", "").replace(")", "").strip()
            if simple_q and simple_q != name:
                gid2, _ = await collector_csqaq.search_good_id(simple_q)
                if gid2 and gid2 != good_id:
                    item2 = await resolve_item(gid2, simple_q, KLINE_FRESH_SINGLE, max_stale_hours=KLINE_FRESH_SINGLE_HOURS)
                    if item2 and item2.name:
                        exact_name2 = item2.name
                        if _verify_item_name(name, exact_name2):
                            good_id, item = gid2, item2
                            exact_name = exact_name2
                            _web_log.info(f"Switched to good_id={gid2}, name={exact_name}")

        # 统一分析核心（2026-08-07 重构，原 ~90 行内联逻辑迁至 analysis_service.analyze_fresh）
        b = await analyze_fresh(item, good_id, exact_name)
        ctx = build_analysis_ctx(b["analysis"], b["kline_stale_days"], b["kline_stale_date"],
                                 holding_ctx=b.get("holding_ctx"),
                                 market_30d_change=b.get("market_30d_change"),
                                 market_th=b.get("market_th"), sentiment=b.get("sentiment", 50.0),
                                 collected_at=b.get("collected_at"))
        return templates.TemplateResponse(request, "partials/analysis.html", ctx)

    except AnalysisAbort as _ab:
        return HTMLResponse(_ae(_ab.msg))
    except Exception as e:
        try:
            with open("analysis_error.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== ERROR ===\n{traceback.format_exc()}\n=== END ===\n")
        except Exception:
            pass
        return HTMLResponse(_ae(f"分析失败: {(str(e) or type(e).__name__)[:300]}"))
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
        # 防重复条目（2026-08-06 USP 空格变体教训）：忽略半角/全角空格匹配已有条目，命中则复用规范名
        norm = name.replace(" ", "").replace("　", "")
        row = conn.execute(
            "SELECT id, name FROM items WHERE REPLACE(REPLACE(name,' ',''),?,'') = ? LIMIT 1",
            ("　", norm)).fetchone()
        if row and row["name"] != name:
            name = row["name"]
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
        row = conn.execute("SELECT name FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return HTMLResponse(_ae("物品不存在"))
        name = row["name"]
    finally:
        conn.close()

    try:
        good_id, page_title = await _resolve_good_id(name)
        if good_id == 0:
            return HTMLResponse(_ae(f"未找到: {name}"))

        item = await resolve_item(good_id, name, KLINE_FRESH_SINGLE, max_stale_hours=KLINE_FRESH_SINGLE_HOURS)
        if item is None:
            return HTMLResponse(_ae("详情获取失败"))

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

        # 统一分析核心；apply_anchor=False / allow_single_price 沿用
        # watchlist 历史行为（与 search/analyze 的锚价口径差异为历史遗留，数据先行验证后统一）
        b = await analyze_fresh(item, good_id, exact_name, db_item_id=item_id,
                                apply_anchor=False, allow_single_price=True)
        ctx = build_analysis_ctx(b["analysis"], b["kline_stale_days"], b["kline_stale_date"],
                                 holding_ctx=b.get("holding_ctx"),
                                 market_30d_change=b.get("market_30d_change"),
                                 market_th=b.get("market_th"), sentiment=b.get("sentiment", 50.0),
                                 collected_at=b.get("collected_at"))
        return templates.TemplateResponse(request, "partials/analysis.html", ctx)

    except AnalysisAbort as _ab:
        return HTMLResponse(_ae(_ab.msg))
    except Exception as e:
        try:
            with open("analysis_error.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== WL ERROR ===\n{traceback.format_exc()}\n=== END ===\n")
        except Exception:
            pass
        return HTMLResponse(_ae(f"分析失败: {(str(e) or type(e).__name__)[:300]}"))
@app.get("/api/watchlist/{item_id}/report")
async def api_watchlist_report(request: Request, item_id: int):
    """自选「报告」按钮（F-3.13，2026-08-09）：与批量扫描弹窗同口径——
    DB 重建完整分析页（持仓品带建议卡片），无新鲜数据/失败时回退已存快照报告。"""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT name FROM items WHERE id=?", (item_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return HTMLResponse(_ae("物品不存在"))
    return await _report_view_rebuild(request, row["name"])


# ---- Report view (批量扫描/自选「报告」弹窗统一入口, 2026-08-09) ----
@app.get("/api/items/report-view")
async def api_item_report_view(request: Request, name: str = Query(...)):
    """报告弹窗统一入口：DB 复用重建完整分析页（不重新采集），持仓品带补仓/止损双路径卡片。"""
    return await _report_view_rebuild(request, name)


def _recent_report_html(name: str, max_age_hours: float = 6.0):
    """近 N 小时内已存的完整报告（性能优化，2026-08-12）。

    - 持仓品（holding=1 且 avg_cost>0）返回 None：需重建以保留补仓/止损建议卡片；
    - 其余品命中 analysis_results（created_at>=cutoff）返回静态 HTML，
      语义=「查看报告」近实时已足够（6h 口径与 B-4 单品分析复用同源）。
    """
    try:
        conn = db.get_conn()
        try:
            _hr = conn.execute(
                "SELECT holding, avg_cost FROM items WHERE name=?", (name,)).fetchone()
            if _hr and _hr["holding"] and (_hr["avg_cost"] or 0) > 0:
                return None
            cutoff = (datetime.now(TZ_BJ) - timedelta(hours=max_age_hours)).strftime("%Y-%m-%d %H:%M:%S")
            row = conn.execute(
                "SELECT report_html FROM analysis_results WHERE name=? AND created_at>=? "
                "ORDER BY id DESC LIMIT 1",
                (name, cutoff),
            ).fetchone()
        finally:
            conn.close()
        if row and row["report_html"]:
            return row["report_html"]
    except Exception as _re:
        _web_log.warning(f"recent report cache miss {name}: {_re}")
    return None


async def _report_view_rebuild(request: Request, name: str):
    """报告重建核心（F-3.7 2026-08-09；F-3.13 自选「报告」按钮同口径）：
    优先用 DB 新鲜 K 线（≤3天，F-3 采集复用口径）重建 analysis.html
    （与「分析」按钮同口径，持仓品带建议卡片）；数据不新鲜或无历史时回退已存快照报告。
    2026-08-12 性能优化：非持仓品近 6h 已有完整报告时直接返回静态 HTML（不重跑引擎）；
    重建路径由 analyze_fresh 内部落 analysis_results，后续点击自动秒开。
    """
    try:
        _cached_html = _recent_report_html(name, max_age_hours=6)
        if _cached_html is not None:
            return HTMLResponse(_sticker_whale_inject(_cached_html, name))
        from webapp.analysis_service import db_kline_fresh, item_from_db, KLINE_FRESH_BATCH
        fresh = db_kline_fresh(None, name, max_stale_days=KLINE_FRESH_BATCH)
        if fresh and len(fresh.get("bars") or []) >= 14:
            conn_g = db.get_conn()
            try:
                _row = conn_g.execute(
                    "SELECT good_id FROM items WHERE id=?", (fresh["item_id"],)).fetchone()
            finally:
                conn_g.close()
            good_id = (_row["good_id"] if _row and _row["good_id"] else 0) or 0
            it = item_from_db(fresh, good_id)
            b = await analyze_fresh(it, good_id, fresh["db_name"], db_item_id=fresh["item_id"],
                                    apply_anchor=False, allow_single_price=True, auto_watchlist=False)
            ctx = build_analysis_ctx(b["analysis"], b["kline_stale_days"], b["kline_stale_date"],
                                     holding_ctx=b.get("holding_ctx"),
                                     market_30d_change=b.get("market_30d_change"),
                                     market_th=b.get("market_th"), sentiment=b.get("sentiment", 50.0),
                                     collected_at=b.get("collected_at"))
            return templates.TemplateResponse(request, "partials/analysis.html", ctx)
        return await _saved_report_response(name)
    except Exception as _rv_e:
        _web_log.warning(f"report-view rebuild failed {name}: {_rv_e}")
        return await _saved_report_response(name)


def _sticker_whale_inject(html: str, name: str) -> str:
    """贴纸庄盘指纹注入（静态缓存报告；实时路径走 build_analysis_ctx）。纯展示层。"""
    try:
        _wh = render_sticker_whale_block(sticker_whale_fingerprint(name))
        if _wh:
            _anchor = '<details style="margin-top:10px;font-size:12px;color:var(--text-secondary);">'
            if _anchor in html:
                html = html.replace(_anchor, _wh + _anchor, 1)
            else:
                html = html.rstrip() + "\n" + _wh
    except Exception as _we:
        _web_log.warning(f"sticker whale inject failed {name}: {_we}")
    return html


async def _saved_report_response(name: str):
    """已存报告兜底：analysis_results → snapshots → 空态提示（原 /api/discover/report 逻辑）。"""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT report_html FROM analysis_results WHERE name=? ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row and row["report_html"]:
            return HTMLResponse(_sticker_whale_inject(row["report_html"], name))
        item = conn.execute("SELECT id FROM items WHERE name=?", (name,)).fetchone()
        if item:
            snap = conn.execute(
                "SELECT report_html, report_md, date, grade, total_score FROM snapshots WHERE item_id=? ORDER BY date DESC LIMIT 1",
                (item["id"],),
            ).fetchone()
            if snap and (snap["report_html"] or snap["report_md"]):
                if snap["report_html"]:
                    return HTMLResponse(snap["report_html"])
                return HTMLResponse(render_report_html(snap["report_md"], snap["date"], snap["grade"], snap["total_score"] or 0))
        return HTMLResponse(
            '<div class="card" style="border-color: rgba(245,158,11,0.5);">'
            '<div class="card-header"><span class="card-title">⚠️ 暂无报告</span></div>'
            '<p style="color: var(--text-secondary);">该饰品尚未生成报告，请先执行「开始扫描」或单品分析。</p>'
            '</div>'
        )
    finally:
        conn.close()

# ---- Discover report (existing report, no re-analysis) ----
@app.get("/api/discover/report")
async def api_discover_report(request: Request, name: str = Query(...)):
    """Return saved report by item name without re-running analysis."""
    return await _saved_report_response(name)

# ---- Watchlist assets ----
@app.post("/api/watchlist/assets")
async def api_watchlist_set_assets(request: Request, amount: float = Form(...)):
    conn = db.get_conn()
    try:
        db.set_setting(conn, "total_assets", amount)
        conn.commit()
        return HTMLResponse(f'<div class="flash-msg flash-success">✅ 总资产已设置为 ¥{amount:,.2f}</div>')
    finally:
        conn.close()


# ---- Batch Scan Selected ----

# ---- Batch Scan Progress ----


def _prune_progress(store, max_age=86400, file_resolver=_scan_progress_file):
    """清理超过 max_age 秒的进度条目，防长跑任务内存无界增长。"""
    now = time.time()
    stale = [k for k, v in store.items() if isinstance(v, dict) and (now - v.get("ts", 0)) > max_age]
    for k in stale:
        store.pop(k, None)
        try:
            file_resolver(k).unlink(missing_ok=True)
        except Exception:
            pass

def _active_task(store):
    """C-5（2026-08-10）：返回未完成（done != True）的任务 id；防同类型任务重复并发。"""
    for k, v in store.items():
        if isinstance(v, dict) and not v.get("done"):
            return k
    return None


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


@app.get("/api/watchlist/scan-history")
async def api_scan_history():
    """批量扫描历史归档列表（watchlist 历史下拉）。"""
    import json as _J
    from pathlib import Path as _P
    _hist_dir = _P(__file__).resolve().parent.parent / "data" / "scan_history"
    scans = []
    if _hist_dir.exists():
        for f in sorted(_hist_dir.glob("scan_*.json"), reverse=True)[:30]:
            try:
                d = _J.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            scans.append({
                "scan_id": f.stem.replace("scan_", ""),
                "time": d.get("time", ""),
                "results_count": d.get("results_count", 0),
                "market_th": d.get("market_th"),
            })
    return {"found": bool(scans), "scans": scans}


@app.get("/api/watchlist/scan-history/{scan_id}")
async def api_scan_history_detail(scan_id: str):
    """查看历史归档详情（复用 HTML, 展示层）。"""
    import json as _J
    from pathlib import Path as _P
    if not scan_id or not all(ch.isdigit() or ch in "_" for ch in scan_id):
        return {"found": False}
    _f = _P(__file__).resolve().parent.parent / "data" / "scan_history" / ("scan_" + scan_id + ".json")
    if not _f.exists():
        return {"found": False}
    try:
        d = _J.loads(_f.read_text(encoding="utf-8"))
        return {"found": True, "time": d.get("time", ""), "html": d.get("html", ""),
                "results_count": d.get("results_count", 0), "market_th": d.get("market_th")}
    except Exception:
        return {"found": False}


# ---- 执行记录 (P0-2, 2026-08-04): 按建议执行 + 14/30天自动复盘 ----
EXEC_ACTIONS = ("buy", "add", "reduce", "sell", "hold")  # F-1.2: 观望也可记录（仅记账不同步持仓）


def _settle_expired_executions(conn, today=None):
    """对已到 14/30 天的执行记录，用 price_history 惰性结算并回填（复盘）。

    净收益率 = (结算价/成交价 - 1)*100 - 2%（双边成本，与回测 net14 口径一致）。
    无历史价格时跳过（下次再试），不影响其它记录。
    """
    from datetime import date, timedelta
    today = date.fromisoformat(today) if today else date.today()
    rows = conn.execute(
        "SELECT id, item_id, advice_date, exec_price, settle_14, settle_30 FROM executions").fetchall()
    for r in rows:
        try:
            adv = date.fromisoformat(r["advice_date"])
        except (TypeError, ValueError):
            continue
        upd = {}
        for _days, _col_px, _col_pnl in ((14, "settle_14", "pnl_14"), (30, "settle_30", "pnl_30")):
            if r[_col_px] is not None:
                continue
            due = adv + timedelta(days=_days)
            if due > today:
                continue
            px = db.closing_price_on(conn, r["item_id"], due.isoformat())
            if px is None:
                continue
            upd[_col_px] = px
            upd[_col_pnl] = round((px / r["exec_price"] - 1) * 100 - 2.0, 2)
        if upd:
            _sets = ", ".join(f"{k}=?" for k in upd)
            conn.execute(f"UPDATE executions SET {_sets} WHERE id=?", (*upd.values(), r["id"]))
    conn.commit()


@app.get("/api/watchlist/executions")
async def api_executions():
    """执行记录列表（自动结算到期记录）。"""
    conn = db.get_conn()
    try:
        _settle_expired_executions(conn)
        return {"ok": True, "executions": db.list_executions(conn)}
    finally:
        conn.close()


@app.get("/api/executions/review")
async def api_executions_review():
    """执行复盘对照（F-2, 2026-08-08）：真实执行 vs 纸面信号统计。"""
    from pipeline import dashboards
    conn = db.get_conn()
    try:
        _settle_expired_executions(conn)
        return {"ok": True, **dashboards.execution_review(conn)}
    finally:
        conn.close()

@app.get("/api/executions/flywheel")
async def api_executions_flywheel():
    """E1 执行飞轮健康度（2026-08-15）：只读聚合展示层，不碰业务逻辑。"""
    from pipeline import dashboards
    conn = db.get_conn()
    try:
        _settle_expired_executions(conn)
        return {"ok": True, **dashboards.execution_flywheel(conn)}
    finally:
        conn.close()


@app.get("/api/watchlist/executions/ref-price")
async def api_execution_ref_price(name: str = "", date: str = ""):
    """执行记录参考价（P1 执行闭环，2026-08-06）：按名称+日期带出 price_history 锚定收盘价（悠悠定价锚）。

    只带出不写库——持仓均价仍以用户确认的 exec_price 为准，避免参考价污染持仓成本。
    """
    conn = db.get_conn()
    try:
        name = name.strip()
        if not name:
            return {"ok": False, "error": "缺少物品名称"}
        row = conn.execute("SELECT id FROM items WHERE name=? LIMIT 1", (name,)).fetchone()
        if not row:
            return {"ok": False, "error": "未匹配到系统物品，请先添加自选"}
        item_id = row["id"]
        if date:
            r = conn.execute(
                "SELECT price_rmb, date FROM price_history WHERE item_id=? AND date<=? ORDER BY date DESC LIMIT 1",
                (item_id, date)).fetchone()
        else:
            r = conn.execute(
                "SELECT price_rmb, date FROM price_history WHERE item_id=? ORDER BY date DESC LIMIT 1",
                (item_id,)).fetchone()
        if r and r["price_rmb"] and r["price_rmb"] > 0:
            return {"ok": True, "price": round(float(r["price_rmb"]), 2), "date": r["date"]}
        return {"ok": False, "error": "该日期区间无价格记录"}
    finally:
        conn.close()


@app.post("/api/watchlist/executions")
async def api_add_execution(request: Request):
    """新增执行记录（按建议执行：建仓/补仓/减仓/清仓）。"""
    body = await request.json()
    name = str(body.get("name", "")).strip()
    action = str(body.get("action", "")).strip()
    source = str(body.get("source", "manual") or "manual").strip()[:64]  # D-3: push:{push_id} / manual
    try:
        qty = max(1, int(body.get("qty", 1)))
        price = float(body.get("exec_price", 0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "数量和价格格式不正确"}
    advice_date = str(body.get("advice_date", "")).strip() or __import__("datetime").date.today().isoformat()
    try:
        advice_price = float(body["advice_price"]) if body.get("advice_price") else None
    except (TypeError, ValueError):
        advice_price = None
    if not name:
        return {"ok": False, "error": "请选择物品"}
    if action not in EXEC_ACTIONS:
        return {"ok": False, "error": "动作类型不正确"}
    if price <= 0:
        return {"ok": False, "error": "成交价必须大于0"}
    conn = db.get_conn()
    try:
        item_id = 0
        try:
            _pid = int(body.get("item_id", 0))
        except (TypeError, ValueError):
            _pid = 0
        row = conn.execute("SELECT id FROM items WHERE id=? AND name=?", (_pid, name)).fetchone()
        if row:
            item_id = row["id"]
        else:
            row2 = conn.execute("SELECT id FROM items WHERE name=?", (name,)).fetchone()
            if row2:
                item_id = row2["id"]
        eid = db.add_execution(conn, item_id, name, action, advice_date, price, qty,
                               advice_signal=body.get("advice_signal", "") or "",
                               advice_price=advice_price, source=source)
        # 2026-08-05: 执行记录同步持仓（buy/add 摊薄均价+累计买入; reduce/sell 减数量）
        warning = ""
        if item_id > 0:
            db.apply_execution_to_position(conn, item_id, action, price, qty)
        else:
            warning = "未匹配到系统物品(id=0)，已记录但未同步持仓；可先添加自选再录入"
        return {"ok": True, "id": eid, "warning": warning}
    finally:
        conn.close()


@app.put("/api/watchlist/executions/{eid}")
async def api_update_execution(eid: int, request: Request):
    """编辑执行记录（2026-08-09）：改动作/日期/价格/数量后自动分段重放，同步持仓与资产。"""
    body = await request.json()
    action = str(body.get("action", "")).strip()
    try:
        qty = max(1, int(body.get("qty", 1)))
        price = float(body.get("exec_price", 0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "数量和价格格式不正确"}
    advice_date = str(body.get("advice_date", "")).strip()
    try:
        advice_price = float(body["advice_price"]) if body.get("advice_price") else None
    except (TypeError, ValueError):
        advice_price = None
    if action not in EXEC_ACTIONS:
        return {"ok": False, "error": "动作类型不正确"}
    if price <= 0:
        return {"ok": False, "error": "成交价必须大于0"}
    if not advice_date:
        return {"ok": False, "error": "日期不能为空"}
    conn = db.get_conn()
    try:
        result = db.update_execution(conn, eid, action, advice_date, price, qty,
                                     advice_signal=str(body.get("advice_signal", "") or ""),
                                     advice_price=advice_price)
        if result is None:
            return {"ok": False, "error": "执行记录不存在"}
        return {"ok": True, **result}
    finally:
        conn.close()


@app.delete("/api/watchlist/executions/{eid}")
async def api_delete_execution(eid: int):
    """删除执行记录（2026-08-09）：同步回滚该品持仓数量/均价/累计买入，资产汇总随之恢复。"""
    conn = db.get_conn()
    try:
        result = db.delete_execution(conn, eid)
        return {"ok": True, **(result or {})}
    finally:
        conn.close()

# ---- 仪表盘 (P0-3 数据积累 / P0-4 组合仓位, 2026-08-04): 纯展示层 ----
@app.get("/api/data/progress")
async def api_data_progress():
    """数据积累进度: 大盘/价格K线/在售量覆盖度（2026-08-07 去量）。"""
    from pipeline import dashboards
    conn = db.get_conn()
    try:
        return {"ok": True, **dashboards.data_progress(conn)}
    finally:
        conn.close()


@app.get("/api/health/status")
async def api_health_status():
    """数据健康监控：实时运行只读检查（run_data_health.run_checks）+ 最近一次自动检查时间。

    实时检查避免 health_checks 快照过期导致误报（2026-08-06: 22:00 自动检查 FAIL 后数据已修复，
    但快照仍显示 FAIL）。检查为纯 SQLite 只读查询，毫秒级。
    """
    from run_data_health import run_checks
    try:
        checks = run_checks()
    except Exception as e:
        return {"found": False, "error": str(e)}
    fail_list = [n for n, lv, _ in checks if lv == "FAIL"]
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT date, status, created_at FROM health_checks ORDER BY date DESC, id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    data_date = None
    try:
        conn_d = db.get_conn()
        try:
            _r = conn_d.execute("SELECT MAX(date) FROM market_index").fetchone()
            data_date = _r[0] if _r else None
        finally:
            conn_d.close()
    except Exception:
        _web_log.warning("cs-skin-market/webapp/main.py unexpected error near line 1324", exc_info=True)
    return {"found": True, "date": datetime.now().strftime("%Y-%m-%d"), "data_date": data_date,
            "status": "fail" if fail_list else "pass",
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_auto": {"date": row["date"], "created_at": row["created_at"], "status": row["status"]} if row else None,
            "checks": [{"name": n, "level": lv, "detail": dt} for n, lv, dt in checks],
            "fail_list": fail_list, "fail_count": len(fail_list)}


@app.get("/api/portfolio/dashboard")
async def api_portfolio_dashboard():
    """组合仓位仪表: 持仓分布。"""
    from pipeline import dashboards
    conn = db.get_conn()
    try:
        return {"ok": True, **dashboards.portfolio_dashboard(conn)}
    finally:
        conn.close()


@app.get("/api/market/signal")
async def api_market_signal():
    """大盘信号 + 风险仪表（2026-08-17 模块 A+D，只读）：五时期→动作区+大盘前视证据+风险档位。
    数据=生产库大盘指数（3 年）+ HQ 池广度；纯引擎无关。异常兜底 ok=False。"""
    try:
        from pipeline.market_signal import market_signal as _ms
        conn = db.get_conn()
        try:
            return _ms(conn)
        finally:
            conn.close()
    except Exception as _e:
        return {"ok": False, "error": str(_e)[:200]}


@app.get("/api/paper/status")
async def api_paper_status():
    """模拟盘 v2 生产镜像状态（2026-08-17，只读）：
    读 data/paper_trading_status.json（每日任务产物）+ 实库在仓/最近成交。
    异常一律返回 ok=False（前端静默降级），不阻断页面。"""
    try:
        import json as _json
        from pathlib import Path as _P
        from pipeline import paper_trading as _pt
        _path = _P(__file__).resolve().parent.parent / "data" / "paper_trading_status.json"
        _st = {}
        if _path.exists():
            _st = _json.loads(_path.read_text(encoding="utf-8"))
        conn = db.get_conn()
        try:
            _pt.ensure_schema(conn)
            _px = _pt._latest_prices(conn)
            pos = conn.execute(
                "SELECT item_name, family, signal_date, entry_price, qty, limit_pct, "
                "stop_pct, take_pct, sc30_open FROM paper_positions WHERE closed=0 "
                "ORDER BY signal_date DESC").fetchall()
            trades = conn.execute(
                "SELECT item_name, family, entry_price, exit_price, net_pct, hold_days, "
                "exit_reason, closed_at FROM paper_trades ORDER BY closed_at DESC, id DESC LIMIT 20"
            ).fetchall()
        finally:
            conn.close()
        _pos = [dict(r) for r in pos]
        for _p in _pos:
            _p["price_now"] = _px.get(_p.get("item_id")) if _p.get("item_id") is not None else None
        return {"ok": True, "status": _st,
                "positions": _pos, "trades": [dict(r) for r in trades]}
    except Exception as _e:
        return {"ok": False, "error": str(_e)[:200]}

@app.post("/api/watchlist/batch-scan-selected")
async def api_watchlist_batch_scan_selected(request: Request):
    body = await request.json()
    ids = body.get("ids", [])
    force_refresh = bool(body.get("force_refresh", False))
    try:
        concurrency = min(3, max(1, int(body.get("concurrency", 2))))
    except (TypeError, ValueError):
        concurrency = 2
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
    return _launch_batch_scan([dict(r) for r in rows], force_refresh=force_refresh, concurrency=concurrency)


def _launch_batch_scan(rows, force_refresh=False, concurrency=2):
    """批量扫描启动公共逻辑（F-3.20，2026-08-11）：检查忙/生成 scan_id/后台任务/进度卡片。
    “批量扫描已选”与结果页“刷新（强制联网）”共用。"""
    import uuid
    _prune_progress(_scan_progress)
    _busy = _active_task(_scan_progress)
    if _busy:
        return HTMLResponse('<div class="card" style="padding:20px;color:var(--yellow);">\u5df2\u6709\u6279\u91cf\u626b\u63cf\u8fdb\u884c\u4e2d\uff08' + _busy + '\uff09\uff0c\u8bf7\u7b49\u5f85\u5b8c\u6210\u540e\u518d\u53d1\u8d77</div>')
    scan_id = uuid.uuid4().hex[:8]
    _scan_progress[scan_id] = {"current": 0, "total": len(rows), "name": "", "done": False, "html": "", "ts": time.time()}
    _persist_scan_progress(scan_id)
    asyncio.create_task(_run_batch_scan_task(scan_id, rows, force_refresh=force_refresh, concurrency=concurrency))
    html = '<div class="card" id="scan-progress-{sid}" data-scanid="{sid}"><div class="card-header"><span class="card-title">\u626b\u63cf\u8fdb\u5ea6</span></div><div class="card-body" id="scan-status-{sid}"><p style="text-align:center;padding:20px;">\u6b63\u5728\u51c6\u5907\u626b\u63cf... <span class="spinner"></span></p></div></div>'.format(sid=scan_id)
    return HTMLResponse(html)


@app.post("/api/watchlist/batch-scan-refresh")
async def api_watchlist_batch_scan_refresh():
    """批量扫描结果「刷新」（F-3.20，2026-08-11）：按最近一次扫描的物品强制联网重扫（绕过缓存）。"""
    import json as _J
    from pathlib import Path as _P
    cache_path = _P(__file__).resolve().parent.parent / "data" / "batch_scan_latest.json"
    if not cache_path.exists():
        return HTMLResponse('<div class="card" style="padding:20px;color:var(--yellow);">\u6682\u65e0\u6279\u91cf\u626b\u63cf\u7f13\u5b58\uff0c\u8bf7\u5148\u6267\u884c\u4e00\u6b21\u6279\u91cf\u626b\u63cf</div>')
    try:
        data = _J.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return HTMLResponse('<div class="card" style="padding:20px;color:var(--red);">\u6279\u91cf\u626b\u63cf\u7f13\u5b58\u8bfb\u53d6\u5931\u8d25</div>')
    rows = data.get("rows") or []
    if not rows:
        return HTMLResponse('<div class="card" style="padding:20px;color:var(--yellow);">\u7f13\u5b58\u4e2d\u65e0\u7269\u54c1\u4fe1\u606f\uff0c\u8bf7\u91cd\u65b0\u53d1\u8d77\u6279\u91cf\u626b\u63cf</div>')
    return _launch_batch_scan(rows, force_refresh=True)


@app.post("/api/watchlist/batch-scan-item-refresh")
async def api_watchlist_batch_scan_item_refresh(request: Request):
    """批量扫描结果行级强制刷新（F-3.21，2026-08-11）：
    按名称单品行级强制联网重采+重算（与批量扫描 _scan_item 同口径），
    更新 batch_scan_latest.json 该条结果并按综合评分重排，返回重建后的结果 HTML。"""
    import json as _json_r
    from pathlib import Path as _Path_r
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "缺少物品名"})
    from pipeline.scan_tasks import _scan_item as _scan_item_fn, _item_report_link
    from pipeline.batch_scan import build_scan_html, sort_results
    cache_path = _Path_r(__file__).resolve().parent.parent / "data" / "batch_scan_latest.json"
    if not cache_path.exists():
        return JSONResponse({"ok": False, "error": "无批量扫描缓存，请先执行一次批量扫描"})
    try:
        data = _json_r.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "error": "批量扫描缓存读取失败"})
    results = data.get("results") or []
    old = next((r for r in results if (r.get("name") or "") == name), None)
    if old is None:
        return JSONResponse({"ok": False, "error": "缓存中未找到该物品：" + name})
    _row = next((r for r in (data.get("rows") or []) if (r.get("name") or "") == name), None)
    if not _row:
        _row = {"id": 0, "name": name, "holding": int(old.get("holding") or 0),
                "avg_cost": old.get("avg_cost") or 0, "quantity": old.get("qty") or 0}
    # 优先用库内 good_id 直接采集，避免重复搜索；无则回退搜索
    good_id_override = None
    if _row.get("id"):
        _conn_g = db.get_conn()
        try:
            _gr = _conn_g.execute("SELECT good_id FROM items WHERE id=?", (int(_row["id"]),)).fetchone()
            if _gr and _gr["good_id"]:
                good_id_override = int(_gr["good_id"])
        finally:
            _conn_g.close()
    ms = market_snapshot()
    _conn_r = db.get_conn()
    try:
        _total_assets = float(db.get_setting(_conn_r, "total_assets", 0) or 0)
    finally:
        _conn_r.close()
    _idx = await asyncio.to_thread(collector.fetch_market_index)
    if _idx is None or getattr(_idx, "value", 0) == 0:
        _idx = type("obj", (object,), {"value": 0, "change_7d": 0})()
    result = await _scan_item_fn(_row, _idx, ms, ms["th"], ms["sentiment"],
                                 total_assets=_total_assets, force_refresh=True,
                                 good_id_override=good_id_override)
    if result is None or result.get("error"):
        return JSONResponse({"ok": False, "error": (result or {}).get("error") or "刷新失败"})
    _ri = next(i for i, r in enumerate(results) if (r.get("name") or "") == name)
    results[_ri] = result
    results = sort_results(results)
    now_str = datetime.now(TZ_BJ).strftime("%H:%M:%S")
    html = build_scan_html(results, len(results), now_str=now_str, name_link=_item_report_link)
    data["results"] = results
    data["html"] = html
    try:
        cache_path.write_text(_json_r.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        _web_log.warning("cs-skin-market/webapp/main.py unexpected error near line 1461", exc_info=True)
    return JSONResponse({"ok": True, "name": result.get("name", name), "html": html,
                         "composite": result.get("composite")})
# ---- Batch Scan Progress Polling ----
@app.get("/api/watchlist/batch-scan-progress/{scan_id}")
async def api_batch_scan_progress(scan_id: str):
    p = _load_scan_progress(scan_id)
    if not p:
        return {"error": "not found"}
    return {"current": p["current"], "total": p["total"], "name": p.get("name", ""), "done": p["done"], "html": p.get("html", "")}


# ---- 信号体检页 (P2-1, 2026-08-07: J-2 C 通道月度 + 实盘信号跟踪) ----
@app.get("/checkup", response_class=HTMLResponse)
async def page_checkup(request: Request):
    _j2 = _j2_status()
    _signals = []
    _conn = db.get_conn()
    try:
        for _r in _conn.execute(
            "SELECT item_name, signal_date, action_label, entry_price, position_limit, "
            "fwd14, fwd30, net14, net30, engine_version FROM signal_tracking ORDER BY id DESC LIMIT 100").fetchall():
            _signals.append(dict(_r))
    finally:
        _conn.close()
    return templates.TemplateResponse(request, "checkup.html", {
        "active_page": "checkup",
        "j2": _j2,
        "signals": _signals,
    })


@app.get("/replay", response_class=HTMLResponse)
async def page_replay(request: Request):
    """\u4fe1\u53f7\u590d\u76d8\uff1a\u5386\u53f2 buy \u4fe1\u53f7\u7684 14d/30d \u8868\u73b0\u56de\u653e\u3002"""
    return templates.TemplateResponse(request, "replay.html", {"active_page": "replay"})


def _event_note(signal_date, fwd_series):
    """信号 fwd30 窗口与黑天鹅事件影响期重叠 → 标注（外生冲击不算策略负贡献）。"""
    from pipeline.market_macro import historical_event_impact
    hits = historical_event_impact(signal_date, horizon_days=30)
    if not hits:
        return None
    # 仅当 fwd30 实际可观察（信号后有足够行情）才标注
    if len(fwd_series) < 30:
        return None
    return "受事件影响：" + "、".join(hits)


@app.get("/api/signals/replay")
async def api_signals_replay():
    """信号复盘：读回放产物 data/_exp_cycle_replay_period_route.json（189 信号，v2-T13 官方 HQ 口径，DISPLAY-7 切换）回放历史 buy 信号，叠加 DB 实盘最新价对照展示。"""
    import json as _J
    from pathlib import Path as _P
    p = _P(__file__).resolve().parent.parent / 'data' / '_exp_cycle_replay_period_route.json'
    if not p.exists():
        return {"found": False}
    data = _J.loads(p.read_text(encoding='utf-8'))
    signals = data.get('signals', [])
    conn = db.get_conn()
    try:
        for s in signals:
            s['latest_price'] = None
            s['latest_ret'] = None
            s['net21'] = None
            s['event_note'] = _event_note(s.get('date'), s.get('fwd_series') or [])
            _fs = s.get('fwd_series') or []
            if len(_fs) > 20 and s.get('entry_price'):
                s['net21'] = round((_fs[20] - s['entry_price']) / s['entry_price'] * 100 - 2.0, 1)
            try:
                row = conn.execute("SELECT id FROM items WHERE name=?", (s.get('name', ''),)).fetchone()
                if not row:
                    continue
                px = conn.execute(
                    "SELECT price_rmb FROM price_history WHERE item_id=? AND price_rmb>0 ORDER BY date DESC LIMIT 1",
                    (row['id'],)).fetchone()
                if px and px['price_rmb'] and s.get('entry_price'):
                    s['latest_price'] = px['price_rmb']
                    s['latest_ret'] = round((px['price_rmb'] - s['entry_price']) / s['entry_price'] * 100, 1)
            except Exception:
                continue
    finally:
        conn.close()
    _dates = [s.get('date') for s in signals if s.get('date')]
    return {"found": True, "signals": signals,
            "meta": {"count": len(signals),
                     "engine": "v2-T13",
                     "caliber": "官方 HQ 口径",
                     "frozen_note": "旧 317 基线已冻结为 HIST-FULL 存证（item_backtest_full_2025.json），不在复盘页主数据源",
                     "generated": data.get("generated"),
                     "range": (min(_dates), max(_dates)) if _dates else None}}


@app.get("/discover", response_class=HTMLResponse)
async def page_discover(request: Request):
    return templates.TemplateResponse(request, "discover.html", {"active_page": "discover"})

# ---- Discover high-score items by weapon type ----


@app.post("/api/discover/refresh-item")
async def api_discover_refresh_item(request: Request):
    """发现高分品行级强制刷新（2026-08-10 方案A）：
    单品行级强制联网重采（绕过 DB 新鲜复用，与批量扫描 force_refresh 同链路），
    重算该品 discover 指标并合并回 discover_latest.json（排名随 composite 重排），
    前端重拉列表即可看到更新。采集被锚校验拦截时回退库内 K 线并返回 warning。
    """
    import json as _json_r
    from pathlib import Path as _Path_r
    body = await request.json()
    name = (body.get("name") or "").strip()
    good_id = int(body.get("good_id") or 0)
    if not name:
        return JSONResponse({"ok": False, "error": "缺少物品名"})
    try:
        if good_id <= 0:
            good_id, _ = await _resolve_good_id(name)
        item = await resolve_item(good_id, name, KLINE_FRESH_SINGLE, force_refresh=True)
        if item is None:
            return JSONResponse({"ok": False, "error": "采集失败（无返回数据）"})
        exact_name = item.name or name
        daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
        warning = ""
        if not daily_bars:
            _db_bars, _stale, _stale_date = kline_db_fallback(good_id, exact_name)
            if _db_bars:
                daily_bars = _db_bars
                warning = "联网采集被判脏（锚校验拦截），已回退库内数据（stale %sd）" % _stale
            else:
                return JSONResponse({"ok": False, "error": "采集失败（被锚校验拦截且无库内数据）"})
        # F-3 落库：新 K 线立即写入 price_history（与 discover 池扫描同口径）
        conn_p = db.get_conn()
        try:
            _pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id,
                                  yyyp_id=getattr(item, "yyyp_id", "") or "", in_watchlist=None)
            db.save_price_history_batch(conn_p, _pid, daily_bars)
            conn_p.commit()
        finally:
            conn_p.close()
        # 重算该品 discover 指标（与 _analyze_one 同口径：run_item_analysis + P0-1 composite）
        from pipeline import item_analysis as _ia
        prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else [getattr(item, "price_rmb", 0) or 0]
        if len(prices) < 14:
            return JSONResponse({"ok": False, "error": "K 线不足 14 天（%s）" % len(prices)})
        supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []
        supply_depth_missing = db.latest_supply_missing(daily_bars)
        ms = market_snapshot()
        try:
            _conn_rb = db.get_conn()
            try:
                _rb_row = _conn_rb.execute("SELECT id FROM items WHERE name=?", (exact_name,)).fetchone()
                _recent_buys = recent_buy_dates(_conn_rb, _rb_row["id"]) if _rb_row else []
            finally:
                _conn_rb.close()
        except Exception:
            _recent_buys = []
        analysis = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _ia.run_item_analysis(
                name=exact_name, prices=prices, supply_hist=supply_hist or None, supply_depth_missing=supply_depth_missing,
                order_book=getattr(item, "order_book", None),
                index_change_7d=ms["chg7"], market_history=ms["history"],
                market_pct_90d=ms["pct"], market_zscore=ms["z"],
                market_cycle=ms["cycle"], market_th_score=ms["th"],
                market_30d_change=ms["chg30"], market_drop21=ms.get("drop21", 0),
                recent_buy_dates=_recent_buys, signal_date=_today_str(),
                price_anchor=getattr(item, "price_rmb", 0) or 0,
                survive_count=getattr(item, "survive_count", 0),
            ))
        pos = analysis.position if hasattr(analysis, "position") else {}
        pct_val = getattr(pos, "percentile_90d", 50) if hasattr(pos, "percentile_90d") else 50
        z_val = getattr(pos, "zscore_90d", 0) if hasattr(pos, "zscore_90d") else 0
        score = analysis.value.score
        fd_action = (analysis.fusion_decision or {}).get("action", "") if isinstance(analysis.fusion_decision, dict) else ""
        th_score = (analysis.trend_health or {}).get("score", 50) if isinstance(analysis.trend_health, dict) else 50
        composite = _ia.composite_score(analysis)
        new_res = dict(
            name=exact_name, good_id=good_id,
            collected_at=getattr(item, "collected_at", "") or "",
            price_rmb=prices[-1] or getattr(item, "price_rmb", 0) or 0,
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
        )
        # 合并回 discover_latest.json 并重渲染（排名随 composite 重排）
        _cache_path = _Path_r(__file__).resolve().parent.parent / "data" / "discover_latest.json"
        try:
            if _cache_path.exists():
                _cache_data = _json_r.loads(_cache_path.read_text(encoding="utf-8"))
                _cache_data["results"] = [new_res if (r.get("name") == exact_name) else r for r in (_cache_data.get("results") or [])]
                _cache_data["html"] = render_discover_html(_cache_data["results"], _cache_data.get("market_th", 50))
                _cache_data["time"] = datetime.now().isoformat()
                _cache_path.write_text(_json_r.dumps(_cache_data, ensure_ascii=False), encoding="utf-8")
        except Exception as _ce:
            _web_log.warning("discover refresh merge latest failed: %s", _ce)
        return JSONResponse({"ok": True, "name": exact_name, "price_rmb": new_res["price_rmb"],
                             "score": score, "composite": composite, "warning": warning})
    except Exception:
        _web_log.error("discover refresh item %s error: %s", name, traceback.format_exc())
        return JSONResponse({"ok": False, "error": "刷新失败"})

@app.post("/api/items/discover")
@app.post("/api/discover/scan-all")
async def api_discover_scan_all(request: Request, mode: str = Query("pool"), scope: str = Query("all")):
    """发现高分品扫描（F-3.4, 2026-08-08）：默认 pool 模式——从池内活跃品跑（DB 新鲜 K 线复用，
    不依赖 csQAQ 搜索 suggest，规避滑块验证码）；mode=search 保留原全网搜索扩池路径。
    scope（2026-08-12 双榜独立刷新，pool 模式生效）：all=全池 / skin=综合榜（非贴纸）/ sticker=贴纸榜。"""
    import time as _time
    _prune_progress(_discover_progress, file_resolver=_discover_progress_file)
    _busy = _active_task(_discover_progress)
    if _busy:
        return {"task_id": "", "error": "已有 discover 扫描进行中（" + _busy + "），请等待完成后再发起"}
    task_id = f"discover_{int(_time.time())}"
    _discover_progress[task_id] = {"current": 0, "total": len(DISCOVER_WEAPONS), "name": "", "done": False, "html": "", "results": [], "ts": time.time()}
    if mode == "search":
        asyncio.create_task(_run_discover_scan_all_task(task_id))
    else:
        # 2026-08-13 ?????sticker ?????? skin??????????
        if scope == "sticker":
            scope = "skin"
        elif scope not in ("all", "skin"):
            scope = "all"
        asyncio.create_task(_run_discover_pool_task(task_id, scope))
    return {"task_id": task_id}


@app.get("/api/discover/history")
async def api_discover_history():
    """高分品追踪：每天最新一次扫描 top10 + 14/30d 回测表现（同日只保留最新，2026-08-09）。"""
    from pathlib import Path as _P
    import json as _J
    _hist_dir = _P(__file__).resolve().parent.parent / 'data' / 'discover_history'
    entries = []
    if _hist_dir.exists():
        seen_days = set()
        for f in sorted(_hist_dir.glob('discover_*.json'), reverse=True):
            try:
                d = _J.loads(f.read_text(encoding='utf-8'))
            except Exception:
                continue
            day = str(d.get('time', ''))[:10]
            if not day or day in seen_days:
                continue
            seen_days.add(day)
            settled = _settle_discover_items(d.get('items', []), d.get('time', ''))
            entries.append({
                'time': d.get('time', ''),
                'market_th': d.get('market_th'),
                'n': len(d.get('items', [])),
                'avg14': settled['avg14'], 'win14': settled['win14'],
                'avg30': settled['avg30'], 'win30': settled['win30'],
                'items': settled['items'],
            })
            if len(entries) >= 30:
                break
    return {"entries": entries}


@app.get("/api/discover/latest")
async def api_discover_latest():
    """Return cached discover result if available and < 24h old."""
    from pathlib import Path as _P
    import json as _J
    cache_path = _P(__file__).resolve().parent.parent / "data" / "discover_latest.json"
    if not cache_path.exists():
        return {"found": False}
    try:
        data = _J.loads(cache_path.read_text(encoding="utf-8"))
        results = data.get("results", [])
        market_th = data.get("market_th", 50)
        # 用最新模板重新渲染，保证查看报告走弹窗（不再跳转重新分析）
        html = render_discover_html(results, market_th) if results else data.get("html", "")
        return {"found": True, "time": data["time"], "html": html, "results": results}
    except Exception:
        return {"found": False}

@app.get("/api/items/discover-progress/{task_id}")
async def api_discover_progress(task_id: str):
    p = _discover_progress.get(task_id)
    if p is None:
        try:
            fp = _discover_progress_file(task_id)
            if fp.exists():
                import json as _json
                data = _json.loads(fp.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "ts" in data:
                    _discover_progress[task_id] = data
                    p = data
        except Exception:
            pass
    if not p:
        return {"error": "not found"}
    return {"current": p.get("current", 0), "total": p.get("total", 0), "name": p.get("name", ""),
            "done": p.get("done", False), "html": p.get("html", ""), "skipped": p.get("skipped", 0),
            "results": p.get("results", []) if p.get("done") else []}
