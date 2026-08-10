"""CS-Market Web App - FastAPI application."""

import sys, io, asyncio, json, re, traceback, time
if getattr(sys.stdout, "encoding", "").lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if getattr(sys.stderr, "encoding", "").lower().replace("-", "") != "utf8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from datetime import datetime
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
    resolve_item, KLINE_FRESH_SINGLE, KLINE_FRESH_SINGLE_HOURS, KLINE_FRESH_BATCH, KLINE_FRESH_DISCOVER,
    anchor_override, kline_db_fallback, kline_price_sane,
    market_snapshot, recent_buy_dates, save_analysis_result, save_item_snapshot,
    _today_str,
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


def _signal_density():
    """回放信号密度：最近30日信号数 vs 历史30日窗口分位（纯展示，读 item_backtest_full_2025.json）。"""
    try:
        _p = Path(__file__).resolve().parent.parent / "data" / "item_backtest_full_2025.json"
        if not _p.exists():
            return None
        _d = json.loads(_p.read_text(encoding="utf-8"))
        _sigs = _d.get("signals") or []
        _dates = sorted(s.get("date", "") for s in _sigs if s.get("date"))
        if len(_dates) < 90:
            return None
        from collections import Counter
        _cnt = Counter(_dates)
        _day = sorted(_cnt.items())
        _win = []
        for _i in range(len(_day) - 29):
            _win.append(sum(c for _, c in _day[_i:_i + 30]))
        if not _win:
            return None
        _last = _win[-1]
        _pct = sum(1 for w in _win if w <= _last) / len(_win) * 100
        _lvl = "低" if _pct <= 33 else ("中" if _pct <= 66 else ("高" if _pct <= 90 else "过热"))
        return {
            "total": len(_sigs),
            "window": "%s ~ %s" % (_day[-30][0], _day[-1][0]),
            "count": _last,
            "pct": round(_pct, 0),
            "level": _lvl,
            "avg30": round(sum(_win) / len(_win), 1),
        }
    except Exception:
        return None


# ---- Dashboard page ----

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
    # I-1 市场状态标注(2026-08-06): 接线 index_card 的 regime 占位, 纯展示层
    from pipeline.batch_scan import market_regime
    _ms_r = market_snapshot()
    _regime_label, _regime_cls, _regime_strategy = market_regime(
        _ms_r.get("sentiment"), _ms_r.get("chg30"), _ms_r.get("th"))
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
        "signal_density": _signal_density(),
        "engine_status": _engine_status,
        "upcoming_events": _upcoming_events(),
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


def _spark_svg(pts, cost):
    """行内走势图：30日价格折线 + 成本线（纯展示，不触碰任何信号）。"""
    if not pts or len(pts) < 2:
        return ""
    W, H, PAD = 150, 40, 4
    lo = min(p[1] for p in pts)
    hi = max(p[1] for p in pts)
    if cost > 0:
        lo = min(lo, cost)
        hi = max(hi, cost)
    span = (hi - lo) or 1.0
    step = (W - 2 * PAD) / (len(pts) - 1)

    def _x(i):
        return PAD + i * step

    def _y(v):
        return H - PAD - (v - lo) / span * (H - 2 * PAD)

    path = " ".join(
        ("M" if i == 0 else "L") + f"{_x(i):.1f},{_y(p[1]):.1f}"
        for i, p in enumerate(pts))
    below_cost = cost > 0 and pts[-1][1] < cost
    color = "#DC2626" if below_cost else "#059669"
    parts = [f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>']
    if cost > 0:
        cy = _y(cost)
        if 0 <= cy <= H:
            parts.append(f'<line x1="{PAD}" y1="{cy:.1f}" x2="{W - PAD}" y2="{cy:.1f}" stroke="#B45309" stroke-width="1" stroke-dasharray="3,3"/>')
            parts.append(f'<text x="{W - PAD}" y="{cy - 2:.1f}" font-size="8" fill="#B45309" text-anchor="end">\u6210\u672c\u00a5{cost:.2f}</text>')
    lx, ly = _x(len(pts) - 1), _y(pts[-1][1])
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2" fill="{color}"/>')
    return f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">{"".join(parts)}</svg>'


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
        for _it in filtered:
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

        # ---- 监控摘要（纯展示）：接近买点 Top + 破位止损 ----
        _near = []
        _broken = []
        for _it in filtered:
            _prox = _it.get("proximity")
            _act = (_it.get("wl_summary") or {}).get("fusion_action")
            if _prox and isinstance(_prox, dict) and _prox.get("score", 0) >= 60 and _act != "buy":
                _near.append(_it)
            if _it.get("holding") and _it.get("avg_cost", 0) > 0 and _it.get("latest_price"):
                if _it["latest_price"] <= _it["avg_cost"] * 0.75:
                    _broken.append(_it)
        _near.sort(key=lambda x: (x.get("proximity") or {}).get("score", 0), reverse=True)
        monitor = {
            "near_buys": _near[:3],
            "broken": _broken[:5],
        }

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
            item["spark_svg"] = _spark_svg(_pts, item.get("avg_cost") or 0)
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
        mi, last_update, chart_data = _dashboard_context()
        analysis_data = index_analysis.analyze_index_full(chart_data) if chart_data else None
        # I-1 市场状态标注: 与首页 / 渲染口径一致（缺 regime_* 会导致 index_card 的「策略」徽章/提示消失）
        from pipeline.batch_scan import market_regime
        _ms_r = market_snapshot()
        _regime_label, _regime_cls, _regime_strategy = market_regime(
            _ms_r.get("sentiment"), _ms_r.get("chg30"), _ms_r.get("th"))
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
                                 market_th=b.get("market_th"), sentiment=b.get("sentiment", 50.0))
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
                                 market_th=b.get("market_th"), sentiment=b.get("sentiment", 50.0))
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
                                 market_th=b.get("market_th"), sentiment=b.get("sentiment", 50.0))
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


async def _report_view_rebuild(request: Request, name: str):
    """报告重建核心（F-3.7 2026-08-09；F-3.13 自选「报告」按钮同口径）：
    优先用 DB 新鲜 K 线（≤3天，F-3 采集复用口径）重建 analysis.html
    （与「分析」按钮同口径，持仓品带建议卡片）；数据不新鲜或无历史时回退已存快照报告。
    """
    try:
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
                                     market_th=b.get("market_th"), sentiment=b.get("sentiment", 50.0))
            return templates.TemplateResponse(request, "partials/analysis.html", ctx)
        return await _saved_report_response(name)
    except Exception as _rv_e:
        _web_log.warning(f"report-view rebuild failed {name}: {_rv_e}")
        return await _saved_report_response(name)


async def _saved_report_response(name: str):
    """已存报告兜底：analysis_results → snapshots → 空态提示（原 /api/discover/report 逻辑）。"""
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

# ---- Discover report (existing report, no re-analysis) ----
@app.get("/api/discover/report")
async def api_discover_report(request: Request, name: str = Query(...)):
    """Return saved report by item name without re-running analysis."""
    return await _saved_report_response(name)


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
        conn.commit()
        return HTMLResponse(f'<div class="flash-msg flash-success">✅ 总资产已设置为 ¥{amount:,.2f}</div>')
    finally:
        conn.close()


# ---- Batch Scan Selected ----

# ---- Batch Scan Progress ----
_scan_progress: dict = {}


def _scan_progress_file(scan_id):
    from pathlib import Path as _P
    return _P(__file__).resolve().parent.parent / "data" / ("scan_progress_" + scan_id + ".json")


def _persist_scan_progress(scan_id):
    """内存进度落盘（Phase 4 持久化）：服务重启后仍可查询进度与结果。"""
    import json as _json
    p = _scan_progress.get(scan_id)
    if not p:
        return
    try:
        _scan_progress_file(scan_id).write_text(
            _json.dumps({k: p.get(k) for k in ("current", "total", "name", "done", "html", "ts")},
                        ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_scan_progress(scan_id):
    """内存优先，磁盘恢复兜底（Phase 4）。"""
    p = _scan_progress.get(scan_id)
    if p is not None:
        return p
    try:
        fp = _scan_progress_file(scan_id)
        if fp.exists():
            import json as _json
            data = _json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "ts" in data:
                _scan_progress[scan_id] = data
                return data
    except Exception:
        pass
    return None



def _discover_progress_file(task_id):
    from pathlib import Path as _P
    return _P(__file__).resolve().parent.parent / "data" / ("discover_progress_" + task_id + ".json")


def _persist_discover_progress(task_id):
    """discover 扫描进度落盘（F-3, 2026-08-08）：重启后进度可查；配合复用优先实现断点续扫语义。"""
    import json as _json
    p = _discover_progress.get(task_id)
    if not p:
        return
    try:
        _discover_progress_file(task_id).write_text(
            _json.dumps({k: p.get(k) for k in ("current", "total", "name", "done", "html", "ts", "skipped")},
                        ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _finalize_discover(task_id: str, note: str = "completed"):
    """discover 扫描收尾台账（F-3.2）：无论成功/空结果/搜索失败/浏览器失败都留痕。"""
    try:
        from pipeline.pool_log import append_pool_log
        from pipeline import db as _db
        _pc = _db.get_conn()
        _pool_now = _pc.execute("SELECT COUNT(*) FROM items WHERE good_id>0").fetchone()[0]
        _pc.close()
        _p = _discover_progress.get(task_id) or {}
        _res = _p.get("results") or []
        append_pool_log({
            "type": "discover",
            "task_id": task_id,
            "note": note,
            "candidates": len(_res) + (_p.get("skipped") or 0),
            "ok": sum(1 for _x in _res if not _x.get("error")),
            "error": sum(1 for _x in _res if _x.get("error")),
            "skipped": _p.get("skipped", 0),
            "market_th": _p.get("market_th"),
            "pool_size_now": _pool_now,
        })
    except Exception:
        pass


def _prune_progress(store, max_age=86400):
    """清理超过 max_age 秒的进度条目，防长跑任务内存无界增长。"""
    now = time.time()
    stale = [k for k, v in store.items() if isinstance(v, dict) and (now - v.get("ts", 0)) > max_age]
    for k in stale:
        store.pop(k, None)
        try:
            _scan_progress_file(k).unlink(missing_ok=True)
        except Exception:
            pass

def _active_task(store):
    """C-5（2026-08-10）：返回未完成（done != True）的任务 id；防同类型任务重复并发。"""
    for k, v in store.items():
        if isinstance(v, dict) and not v.get("done"):
            return k
    return None


def _item_report_link(name):
    """批量扫描结果中可点击的名称链接：弹窗查看已存报告（不重新分析）。"""
    esc = str(name).replace("'", "\\'").replace('"', "&quot;")
    return ('<a href="javascript:void(0)" onclick="showItemReport(\'' + esc + '\')" '
            'style="color:var(--accent);text-decoration:none;cursor:pointer;font-weight:600;">' + str(name) + '</a>')

async def _scan_item(row, idx, ms, market_th_score, sentiment_score, total_assets=0.0, force_refresh=False, good_id_override=None):
    """批量扫描单个物品（可并发调用，共享 Playwright 浏览器多 page）。

    2026-08-10：good_id_override 由任务层在搜索串行阶段预解析后传入，
    采集/分析阶段可并行（锚校验兜底脏 chart），避免搜索 UI 并发串品。
    """
    import json as _json
    from pipeline.batch_scan import _portfolio_advice, summarize_buy_distance
    from pipeline import item_analysis
    item_id, name, holding, avg_cost, qty = row["id"], row["name"], row["holding"] or 0, row["avg_cost"] or 0, row["quantity"] or 0
    try:
        if good_id_override:
            good_id = good_id_override
        else:
            good_id, _ = await _resolve_good_id(name)
        if good_id == 0:
            return dict(name=name, holding=holding, error="未找到")
        item = await resolve_item(good_id, name, KLINE_FRESH_BATCH, force_refresh=force_refresh)
        if item is None:
            return dict(name=name, holding=holding, error="详情获取失败")
        exact_name = item.name or name
        daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
        force_fallback = False
        if not daily_bars:
            _db_bars, _stale, _stale_date = kline_db_fallback(good_id, exact_name)
            if _db_bars:
                daily_bars = _db_bars
                if force_refresh:
                    force_fallback = True
                    _web_log.warning(f"batch scan force refresh fallback {exact_name}: 采集被锚校验拦截(脏chart)，回退DB缓存 stale={_stale}d")
        # 价格合理性校验：csQAQ 偶发串品/脏价，脏数据不落库。
        # 新规则（2026-08-04）：出现偏差时统一以悠悠锚价为准——新鲜 chart 判脏先试 DB 缓存 K 线，
        # DB 仍判脏且悠悠锚价可用时，把最新价校正为锚价继续分析（不再跳过/保留旧数据）。
        _anchor_px = getattr(item, "price_rmb", 0) or 0
        conn_c = db.get_conn()
        try:
            _sane, _sane_msg = kline_price_sane(daily_bars, item_id, anchor_price=_anchor_px, conn=conn_c)
            if not _sane:
                _db_bars, _db_stale, _db_stale_date = kline_db_fallback(good_id, exact_name)
                if _db_bars:
                    _base_sane, _base_msg = kline_price_sane(_db_bars, item_id, anchor_price=_anchor_px, conn=conn_c)
                    if _base_sane:
                        _web_log.warning(f"batch scan DB kline fallback {exact_name}: {_sane_msg}")
                        daily_bars = _db_bars
                    elif _anchor_px and _anchor_px > 0:
                        daily_bars = anchor_override(_db_bars, _anchor_px, label=exact_name)
                        _web_log.warning(f"batch scan anchor override {exact_name}: {_base_msg} -> 统一以悠悠锚¥{_anchor_px:.2f}为准")
                    else:
                        _web_log.warning(f"batch scan skip {exact_name}: {_base_msg}")
                        return dict(name=exact_name, holding=holding, error="价格校验未通过，保留旧数据")
                else:
                    if _anchor_px and _anchor_px > 0:
                        daily_bars = anchor_override(daily_bars, _anchor_px, label=exact_name)
                        _web_log.warning(f"batch scan anchor override {exact_name}: {_sane_msg} -> 统一以悠悠锚¥{_anchor_px:.2f}为准")
                    else:
                        _web_log.warning(f"batch scan skip {exact_name}: {_sane_msg}")
                        return dict(name=exact_name, holding=holding, error="价格校验未通过，保留旧数据")
            recent_buys = recent_buy_dates(conn_c, item_id)
        finally:
            conn_c.close()
        prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else [item.price_rmb]
        supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []
        analysis = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: item_analysis.run_item_analysis(
                name=exact_name, prices=prices,
                supply_hist=supply_hist or None, order_book=item.order_book,
                index_change_7d=getattr(idx, "change_7d", 0),
                market_cycle=ms["cycle"],
                market_th_score=ms["th"],
                market_30d_change=ms["chg30"],
                market_drop21=ms.get("drop21", 0),
                recent_buy_dates=recent_buys,
                signal_date=_today_str(),
                price_anchor=item.price_rmb,
                survive_count=getattr(item, "survive_count", 0),
            ),
        )
        # 报告价格锚定悠悠有品 DOM 价（chart fallback 价只补 K 线不参与定价）
        if getattr(item, "price_rmb", 0) and item.price_rmb > 0:
            analysis.price_rmb = item.price_rmb
        # F-3.14 已执行止损感知：近30天卖出件数传入持仓建议（减半止损以原始量50%为目标，不重复建议）
        conn_sold = db.get_conn()
        try:
            _sold_recent = db.sold_qty_recent(conn_sold, item_id)
        finally:
            conn_sold.close()
        pa = _portfolio_advice(holding, avg_cost, qty, item.price_rmb, analysis, market_th=market_th_score, sentiment_score=sentiment_score, market_30d_change=ms["chg30"], total_assets=total_assets, sold_recent=_sold_recent)
        _fd_lim = (getattr(analysis, "fusion_decision", {}) or {}).get("position_limit", 0) or 0
        result = dict(
            name=exact_name, holding=holding, avg_cost=avg_cost, qty=qty,
            price_rmb=item.price_rmb, grade=analysis.value.grade, score=analysis.value.score,
            position_limit=float(_fd_lim),
            portfolio_advice=pa,
            buy_distance=summarize_buy_distance(getattr(analysis, "buy_distance", None) or {}),
            valuation_tier=getattr(analysis.position, "valuation_tier", "") if hasattr(analysis, "position") else "",
            percentile_90d=getattr(analysis.position, "percentile_90d", 50) if hasattr(analysis, "position") else 50,
            force_fallback=force_fallback,
            error=None,
        )
        # Save to analysis_results (同步至单品报告)
        save_analysis_result(analysis)
        # 生产实盘信号跟踪 (2026-08-07 C 通道实盘化): 批量扫描 buy 信号同样记录
        try:
            _fd = getattr(analysis, "fusion_decision", None) or {}
            if isinstance(_fd, dict) and _fd.get("action") in ("buy", "oversold_buy"):
                _entry = daily_bars[-1].close if daily_bars and getattr(daily_bars[-1], "close", 0) > 0 else (getattr(item, "price_rmb", 0) or 0)
                conn_t = db.get_conn()
                try:
                    from pipeline.signal_tracking import record_buy_signal
                    record_buy_signal(conn_t, item_id=item_id, item_name=exact_name,
                                      signal_date=_today_str(), action=_fd.get("action", "buy"),
                                      action_label=_fd.get("action_label", "") or "",
                                      entry_price=_entry, position_limit=_fd.get("position_limit") or 0.10,
                                      source="batch_scan")
                finally:
                    conn_t.close()
        except Exception as _te:
            _web_log.warning(f"batch signal tracking failed {exact_name}: {_te}")
        # Persist
        conn_p = db.get_conn()
        try:
            pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id, yyyp_id=item.yyyp_id, in_watchlist=None)
            db.save_price_history_batch(conn_p, pid, daily_bars)
            conn_p.commit()
        finally:
            conn_p.close()
        # Snapshot + summary
        conn_s = db.get_conn()
        try:
            save_item_snapshot(conn_s, item_id, analysis, item.price_rmb, order_book=getattr(item, "order_book", None))
            db.set_setting(conn_s, f"th_{pid}", _json.dumps(analysis.trend_health, ensure_ascii=False) if analysis.trend_health else "")
            conn_s.commit()
        except Exception as _se:
            import traceback as _tb
            # C-3（2026-08-10）：错误日志统一写入 data/ 目录（原裸写 CWD 工作目录）
            try:
                from pathlib import Path as _P2
                _efp = _P2(__file__).resolve().parent.parent / "data" / "snapshot_error.log"
                with _efp.open("a", encoding="utf-8") as _ef:
                    _ef.write("\n=== BATCH ERROR " + str(item_id) + " ===\n" + _tb.format_exc() + "\n=== END ===\n")
            except Exception:
                pass
            _web_log.warning(f"Batch save error: {_se}")
        finally:
            conn_s.close()
        return result
    except Exception as e:
        _web_log.error(f"batch scan item failed: {name}: {e}")
        return dict(name=name, holding=holding, error=str(e)[:100])


async def _run_batch_scan_task(scan_id: str, rows: list, force_refresh=False, concurrency=2):
    """批量扫描：搜索阶段串行 + 采集/分析阶段小并发（默认 2，可 1~3），结果排序 + 结构化缓存。

    2026-08-10 提速设计：2026-08-04 曾因「并发页面导航串出脏 chart」改全串行；
    现采集链路已有串品锚校验自愈（chart vs 悠悠锚不符→重试→清空回退 DB，不落脏数据），
    故放开采集并发；搜索阶段（Playwright 下拉 UI）保持串行避免串品，good_id 由任务层预解析。
    concurrency=1 即还原旧串行行为。

    整体 try/except：任何未预期异常也会置 done=True，避免前端弹窗无限轮询。
    """
    import json as _json
    from pathlib import Path as _P
    from pipeline.batch_scan import build_scan_html, sort_results, _esc
    from pipeline import collector
    try:
        idx = await asyncio.to_thread(collector.fetch_market_index)
        if idx is None or idx.value == 0:
            idx = type("obj", (object,), {"value": 0, "change_7d": 0})()
        # Compute market TH + sentiment once for resonance-aware portfolio advice
        ms = market_snapshot()
        market_th_score = ms["th"]
        sentiment_score = ms["sentiment"]
        # B1 风险预算层(2026-08-05): 组合回撤熔断状态 + 总资产(单票敞口提示)
        from pipeline import portfolio_risk
        _conn_r = db.get_conn()
        try:
            _dd_status = portfolio_risk.drawdown_status(_conn_r)
            _total_assets = float(db.get_setting(_conn_r, "total_assets", 0) or 0)
        finally:
            _conn_r.close()
        total = len(rows)
        _scan_progress[scan_id]["total"] = total
        _scan_progress[scan_id]["name"] = "准备扫描..."
        _persist_scan_progress(scan_id)
        # 2026-08-10 提速：搜索阶段串行（DB 秒回为主，Playwright 搜索兜底避免 UI 并发串品），
        # 采集/分析阶段小并发（锚校验兜底脏 chart；并发高会加剧 csQAQ 限流，故 clamp 1~3）
        sem_search = asyncio.Semaphore(1)
        sem_fetch = asyncio.Semaphore(concurrency)
        done = 0

        async def _one(row):
            nonlocal done
            async with sem_search:
                _gid, _gt = await _resolve_good_id(row["name"])
            async with sem_fetch:
                res = await _scan_item(row, idx, ms, market_th_score, sentiment_score,
                                       total_assets=_total_assets, force_refresh=force_refresh,
                                       good_id_override=_gid)
                done += 1
                _scan_progress[scan_id]["current"] = done
                if res:
                    _scan_progress[scan_id]["name"] = res.get("name", "")
                _persist_scan_progress(scan_id)
                return res

        raw_results = await asyncio.gather(*(_one(r) for r in rows))
        results = [r for r in raw_results if r is not None]
        results = sort_results(results)

        now_str = __import__("datetime").datetime.now().strftime("%H:%M:%S")
        final_html = build_scan_html(
            results, total,
            {"th": market_th_score, "sentiment": sentiment_score, "cycle": ms["cycle"],
             "index": getattr(idx, "value", 0), "chg30": ms.get("chg30")},
            now_str=now_str,
            name_link=_item_report_link,
            risk_ctx={"drawdown": _dd_status},
        )
        _scan_progress[scan_id]["html"] = final_html
        _persist_scan_progress(scan_id)
        _scan_progress[scan_id]["done"] = True
        # Persist to disk (latest + 历史归档, 2026-08-04)
        _data_dir = _P(__file__).resolve().parent.parent / "data"
        _payload = {
            "time": __import__("datetime").datetime.now().isoformat(),
            "html": final_html,
            "results": results,
            "market_th": market_th_score,
        }
        try:
            _cache_path = _data_dir / "batch_scan_latest.json"
            _cache_path.write_text(_json.dumps(_payload, ensure_ascii=False, default=str), encoding="utf-8")
        except Exception:
            pass
        # 历史归档: 每次扫描留存（信号中心/复盘数据源），保留最近 30 份
        try:
            from pipeline.batch_scan import extract_signals
            _hist_dir = _data_dir / "scan_history"
            _hist_dir.mkdir(exist_ok=True)
            _ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
            (_hist_dir / ("scan_" + _ts + ".json")).write_text(_json.dumps({
                "time": _payload["time"], "market_th": market_th_score,
                "results_count": len(results),
                "signals": extract_signals(results),
                "html": final_html,
            }, ensure_ascii=False, default=str), encoding="utf-8")
            _olds = sorted(_hist_dir.glob("scan_*.json"))
            for _f in _olds[:-30]:
                try:
                    _f.unlink()
                except Exception:
                    pass
        except Exception:
            pass
    except Exception as _e:
        import traceback as _tb
        _web_log.error(f"batch scan task crashed: {_e}\n{_tb.format_exc()}")
        _scan_progress[scan_id]["html"] = ('<div class="card" style="padding:20px;color:var(--red);">批量扫描异常：'
                                           + _esc(str(_e))[:200] + "</div>")
        _scan_progress[scan_id]["done"] = True

        _persist_scan_progress(scan_id)


    # 数据保留清理（365/90/7 天 + VACUUM，口径 references/data-layer.md）
    try:
        from pipeline.db import run_retention_cleanup
        _rc = run_retention_cleanup(vacuum=True)
        if _rc["deleted"] or _rc["files"]:
            _web_log.info(f"batch scan retention cleanup: deleted={_rc['deleted']} files={_rc['files']} vacuum={_rc['vacuum']}")
    except Exception as _re:
        _web_log.warning(f"batch scan retention cleanup failed: {_re}")

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
        pass
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


# ---- M1 监控模式页面 (2026-08-08): 每日自选品异动事件 + 历史归档（纯展示） ----
@app.get("/monitor", response_class=HTMLResponse)
async def page_monitor(request: Request, days: int = Query(default=7)):
    from pipeline.monitor import list_events, _TYPE_LABEL
    events = list_events(days=days)
    by_date = {}
    for _e in events:
        _key = (_e["date"], _e.get("slot", "night"))
        by_date.setdefault(_key, []).append(_e)
    return templates.TemplateResponse(request, "monitor.html", {
        "active_page": "monitor",
        "days": days,
        "events": events,
        "by_date": by_date,
        "type_label": _TYPE_LABEL,
        "counts": {
            "danger": sum(1 for e in events if e["level"] == "danger"),
            "warn": sum(1 for e in events if e["level"] == "warn"),
            "info": sum(1 for e in events if e["level"] == "info"),
        },
    })


@app.get("/api/monitor/events")
async def api_monitor_events(days: int = Query(default=7)):
    from pipeline.monitor import list_events
    return {"events": list_events(days=days)}


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
    """信号复盘：读回放产物 data/item_backtest_full_2025.json（K-2 预研，2026-08-06）回放历史 buy 信号，叠加 DB 实盘最新价对照展示。"""
    import json as _J
    from pathlib import Path as _P
    p = _P(__file__).resolve().parent.parent / 'data' / 'item_backtest_full_2025.json'
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
                     "generated": data.get("generated"),
                     "range": (min(_dates), max(_dates)) if _dates else None}}


@app.get("/discover", response_class=HTMLResponse)
async def page_discover(request: Request):
    return templates.TemplateResponse(request, "discover.html", {"active_page": "discover"})

# ---- Discover high-score items by weapon type ----
_discover_progress: dict = {}
# F-3 扩容 (2026-08-08 第二轮): 8 -> 13 个武器；仍只采「崭新出厂 + 非 StatTrak + 非纪念品」
DISCOVER_WEAPONS = [
    "AK-47", "AWP", "沙漠之鹰", "M4A4",
    "USP", "MP7", "SSG 08", "法玛斯",
    "M4A1 消音版", "格洛克 18 型", "MP9", "Tec-9", "加利尔 AR",
]

async def _run_discover_task(task_id: str, items: list):
    """Background: analyze each discover candidate, sort by composite score.

    F-3 (2026-08-08): 采集复用优先——DB 有新鲜 K 线（<=3 天）直接复用不重复采集；
    失败品重试一轮（复用优先，DB 已新鲜的秒过）；进度逐品落盘，重启后仍可查。
    """
    from pipeline import item_analysis as _ia
    # Get market TH for context-aware filtering
    ms = market_snapshot()
    market_th = ms["th"]
    _discover_progress[task_id]["market_th"] = market_th
    results = []
    analysis_objs = {}
    skipped = 0

    async def _analyze_one(good_id, name, price_rmb):
        """分析单个候选（复用优先取数）。返回 (status, reason)；status: ok / error / skip。"""
        nonlocal skipped
        try:
            item = await resolve_item(good_id, name, KLINE_FRESH_DISCOVER)
            if item is None:
                return "error", "详情获取失败"
            exact_name = item.name or name
            daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
            if not daily_bars:
                _db_bars, _stale, _stale_date = kline_db_fallback(good_id, exact_name)
                if _db_bars:
                    daily_bars = _db_bars
            # 串品防护 (2026-08-08): fetch_item_detail 偶发捕获到 Buff/Steam chart
            # （钴蓝禁锢 13:53 曾捕获 Steam 价 1187 vs 悠悠锚 824），discover 直接消费
            # kline 会产出错误报告。用悠悠锚（DOM 价 + info/good 悠悠在售量）双重校验，
            # 不合格重取一次，仍不合格回退 DB K线（悠悠口径），再不行跳过该品。
            anchor_price = getattr(item, "price_rmb", 0) or 0
            anchor_sell = getattr(item, "sell_num_yyyp", 0) or 0
            def _kline_dev():
                """返回 (是否串品, 最新价, 最新在售)；空 K 线不判串品（交给既有跳过逻辑）。"""
                if not daily_bars:
                    return False, 0, 0
                _closes = [k.close for k in daily_bars if k.close and k.close > 0]
                if not _closes:
                    return False, 0, 0
                _last_close = _closes[-1]
                _last_sale = 0
                for _k in reversed(daily_bars):
                    if getattr(_k, "in_sale_count", 0) or 0:
                        _last_sale = _k.in_sale_count
                        break
                _bad = (
                    (anchor_price > 0 and abs(_last_close / anchor_price - 1) > 0.20)
                    or (anchor_sell > 0 and _last_sale > 0 and abs(_last_sale / anchor_sell - 1) > 0.30)
                )
                return _bad, _last_close, _last_sale
            _suspect, _lc, _ls = _kline_dev()
            if _suspect:
                _web_log.warning(f"Discover kline 串品防护 {exact_name}: 最新价¥{_lc}/在售{_ls} vs 悠悠锚¥{anchor_price}/{anchor_sell} 偏差超限 -> 重取一次")
                _item2 = await resolve_item(good_id, exact_name, KLINE_FRESH_DISCOVER)
                if _item2 and _item2.kline_90d:
                    item = _item2
                    daily_bars = item.kline_90d
                    anchor_price = getattr(item, "price_rmb", 0) or anchor_price
                    anchor_sell = getattr(item, "sell_num_yyyp", 0) or anchor_sell
            _suspect, _lc, _ls = _kline_dev()
            if _suspect:
                _db_bars2, _stale2, _date2 = kline_db_fallback(good_id, exact_name)
                if _db_bars2:
                    _web_log.warning(f"Discover kline 串品防护 {exact_name}: 重取仍异常(最新价¥{_lc}/在售{_ls}) -> 回退 DB K线 (stale {_stale2}d)")
                    daily_bars = _db_bars2
                else:
                    _web_log.warning(f"Discover kline 串品防护 {exact_name}: 重取与 DB 回退均失败 -> 跳过")
                    skipped += 1
                    return "skip", "串品防护跳过"
            # F-3 扩池落库 (2026-08-08): 网络采集的 K 线立即写入 price_history（无论预筛是否通过），
            # 让新品开始积累 14 天历史；DB 复用（from_db=True）的品已在库，跳过
            if daily_bars and not getattr(item, "from_db", False):
                try:
                    conn_p = db.get_conn()
                    try:
                        _pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id,
                                              yyyp_id=getattr(item, "yyyp_id", "") or "",
                                              in_watchlist=None)
                        db.save_price_history_batch(conn_p, _pid, daily_bars)
                        conn_p.commit()
                    finally:
                        conn_p.close()
                except Exception as _pe:
                    _web_log.warning(f"Discover persist {exact_name} failed: {_pe}")
            prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else [price_rmb]

            # P0-2: 轻量预筛 - K线不足14天直接跳过(节省采集+分析耗时)
            if len(prices) < 14:
                skipped += 1
                return "skip", "K线不足14天"
            current_p = prices[-1]
            pct_quick = sum(1 for p in prices if p < current_p) / len(prices) * 100
            if pct_quick > 75:
                skipped += 1
                return "skip", "分位过高"

            supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []
            # F-3.5 流动性闸门 (2026-08-08): 近 7 天平均在售量 <15 -> 结构性无流动性，不入高分榜
            if supply_hist:
                _recent_sale = [s for s in supply_hist[-7:] if s]
                if _recent_sale and sum(_recent_sale) / len(_recent_sale) < 15:
                    skipped += 1
                    return "skip", "流动性不足(avg7在售<15)"

            _recent_buys = []
            try:
                _conn_rb = db.get_conn()
                try:
                    _rb_row = _conn_rb.execute("SELECT id FROM items WHERE name=?", (exact_name,)).fetchone()
                    if _rb_row:
                        _recent_buys = recent_buy_dates(_conn_rb, _rb_row["id"])
                finally:
                    _conn_rb.close()
            except Exception:
                pass
            analysis = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _ia.run_item_analysis(
                    name=exact_name, prices=prices,
                    supply_hist=supply_hist or None, order_book=item.order_book,
                    index_change_7d=ms["chg7"],
                    market_history=ms["history"],
                    market_pct_90d=ms["pct"],
                    market_zscore=ms["z"],
                    market_cycle=ms["cycle"],
                    market_th_score=ms["th"],
                    market_30d_change=ms["chg30"],
                    market_drop21=ms.get("drop21", 0),
                    recent_buy_dates=_recent_buys,
                    signal_date=_today_str(),
                    price_anchor=anchor_price,
                    survive_count=getattr(item, "survive_count", 0),
                ),
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
                return "skip", "市场弱过滤"

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
            return "ok", ""
        except Exception as e:
            _web_log.error(f"Discover analyze {name} error: {traceback.format_exc()}")
            return "error", str(e)[:200]

    deferred_errors = {}
    for i, (good_id, name, price_rmb) in enumerate(items):
        _discover_progress[task_id]["current"] = i + 1
        _discover_progress[task_id]["name"] = name
        _persist_discover_progress(task_id)
        status, reason = await _analyze_one(good_id, name, price_rmb)
        if status == "error":
            deferred_errors[(good_id, name, price_rmb)] = reason

    # F-3 失败重试一轮：复用优先，DB 已新鲜的秒过；仍失败才记 error
    if deferred_errors:
        _web_log.warning(f"Discover retry round: {len(deferred_errors)} items")
        for (good_id, name, price_rmb), reason in list(deferred_errors.items()):
            _discover_progress[task_id]["name"] = name
            status, _reason = await _analyze_one(good_id, name, price_rmb)
            if status != "error":
                deferred_errors.pop((good_id, name, price_rmb))
    for (good_id, name, price_rmb), reason in deferred_errors.items():
        results.append(dict(name=name, error=reason or "采集失败"))

    _discover_progress[task_id]["skipped"] = skipped
    results.sort(key=lambda r: r.get("composite", 0) or r.get("score", 0) or 0, reverse=True)
    _discover_progress[task_id]["results"] = results
    _discover_progress[task_id]["done"] = True
    _persist_discover_progress(task_id)

    # 保存 top10 报告到 analysis_results + snapshots（查看报告不再重新分析）
    try:
        for _r in results[:10]:
            if _r.get("error"):
                continue
            _an = analysis_objs.get(_r.get("name", ""))
            if _an is None:
                continue
            try:
                save_analysis_result(_an)
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
                    save_item_snapshot(_conn_s, _pid_d, _an, _an.price_rmb or 0)
                finally:
                    _conn_s.close()
            except Exception as _se2:
                _web_log.warning(f"discover save snapshot failed: {_se2}")
    except Exception as _se3:
        _web_log.warning(f"discover save reports failed: {_se3}")

    html = _render_discover_html(results, market_th)
    _discover_progress[task_id]["html"] = html

    # 扫描完成，清理进度落盘文件
    try:
        _discover_progress_file(task_id).unlink(missing_ok=True)
    except Exception:
        pass


def _render_discover_html(results, market_th=50):
    """Render discover results with valuation columns, add-to-watchlist, and heatmap."""
    # 2026-08-09：已在自选的品渲染「已自选」禁用态，其余渲染「➕ 加入自选」
    _wl_names = set()
    try:
        _conn_wl = db.get_conn()
        try:
            for _rw in _conn_wl.execute("SELECT name FROM items WHERE in_watchlist=1"):
                _wl_names.add(_rw["name"])
        finally:
            _conn_wl.close()
    except Exception:
        pass
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
        f'<div class="card-body" style="padding:0;"><div class="table-wrap"><table class="data-table" style="width:100%;">'
        f'<thead><tr><th>#</th><th>\u8bc4\u7ea7</th><th>\u540d\u79f0</th><th>\u4ef7\u683c</th><th>\u8bc4\u5206</th><th>\u7efc\u5408</th><th>%\u4f4d</th><th>\u5468\u671f</th><th>\u64cd\u4f5c</th></tr></thead><tbody>'
    ]
    for idx, r in enumerate(top10):
        if r.get("error"):
            lines.append(f'<tr><td colspan="9" style="color:var(--danger);padding:12px 16px;">{r["name"]}: {r["error"]}</td></tr>')
            continue
        g = r.get("grade", "Z")
        grade_cls = {"S":"grade-s","A":"grade-a","B":"grade-b","C":"grade-c"}.get(g, "grade-z")
        cp = r.get("cycle_label", "") or r.get("cycle_phase", "")
        pct = r.get("percentile_90d", 50)
        pct_clr = "green" if pct <= 25 else ("yellow" if pct <= 50 else "red")
        comp = r.get("composite", 0) or r.get("score", 0)
        rank_style = "font-weight:800;font-size:16px;" + ("color:#ffd700;" if idx == 0 else "color:var(--text-muted);")
        esc_name = r["name"].replace("'", "\\'").replace('"', '&quot;')
        _btn_html = ('<button class="btn btn-xs btn-outline" disabled style="opacity:.55;cursor:default;" title="已在自选">✓ 已自选</button>'
                     if r["name"] in _wl_names else
                     '<button class="btn btn-xs btn-outline" onclick="addToWatchlist(\'' + esc_name + '\', this)" title="加入自选">➕ 加入自选</button>')
        _refresh_btn = ('<button class="btn btn-xs btn-outline" onclick="refreshDiscoverItem(\'' + esc_name + '\', this)" '
                        'title="强制联网重采此品并重算评分">⚡ 刷新</button>')
        lines.append(
            f'<tr><td style="{rank_style}">{idx+1}</td>'
            f'<td><span class="{grade_cls}">{g}</span></td>'
            f'<td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"><a href="javascript:void(0)" onclick="showDiscoverReport(\'{esc_name}\')" style="color:var(--accent);text-decoration:none;cursor:pointer;" title="\u67e5\u770b\u5206\u6790\u62a5\u544a">{r["name"]}</a></td>'
            f'<td>\u00a5{r.get("price_rmb",0):.2f}</td>'
            f'<td>{r.get("score",0):.1f}</td>'
            f'<td style="font-weight:600;">{comp:.1f}</td>'
            f'<td class="{pct_clr}">{pct:.0f}%</td>'
            f'<td style="font-size:12px;">{cp}</td>'
            f'<td style="white-space:nowrap;">{_btn_html} {_refresh_btn}</td></tr>'
        )
    lines.append("</tbody></table></div></div></div>")
    return heatmap_html + "\n".join(lines)


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
                name=exact_name, prices=prices, supply_hist=supply_hist or None,
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
        dq_factor = {"good": 1.0, "medium": 0.85, "low": 0.6, "insufficient": 0.2}.get(getattr(analysis, "data_quality", "low"), 0.4)
        fd_action = (analysis.fusion_decision or {}).get("action", "") if isinstance(analysis.fusion_decision, dict) else ""
        action_bonus = {"buy": 1.0, "watch": 0.5, "hold": 0.0, "reduce": -0.5, "avoid": -1.0, "sell": -1.0}.get(fd_action, 0.0)
        th_score = (analysis.trend_health or {}).get("score", 50) if isinstance(analysis.trend_health, dict) else 50
        th_bonus = (th_score - 50) / 50 * 1.0
        valuation_discount = max(0.5, 1.0 - pct_val / 200)
        composite = round((score + action_bonus + th_bonus) * valuation_discount * dq_factor, 1)
        new_res = dict(
            name=exact_name, good_id=good_id,
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
                _cache_data["html"] = _render_discover_html(_cache_data["results"], _cache_data.get("market_th", 50))
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
async def api_discover_scan_all(request: Request, mode: str = Query("pool")):
    """发现高分品扫描（F-3.4, 2026-08-08）：默认 pool 模式——从池内活跃品跑（DB 新鲜 K 线复用，
    不依赖 csQAQ 搜索 suggest，规避滑块验证码）；mode=search 保留原全网搜索扩池路径。"""
    import time as _time
    _prune_progress(_discover_progress)
    _busy = _active_task(_discover_progress)
    if _busy:
        return {"task_id": "", "error": "已有 discover 扫描进行中（" + _busy + "），请等待完成后再发起"}
    task_id = f"discover_{int(_time.time())}"
    _discover_progress[task_id] = {"current": 0, "total": len(DISCOVER_WEAPONS), "name": "", "done": False, "html": "", "results": [], "ts": time.time()}
    if mode == "search":
        asyncio.create_task(_run_discover_scan_all_task(task_id))
    else:
        asyncio.create_task(_run_discover_pool_task(task_id))
    return {"task_id": task_id}

async def _run_discover_pool_task(task_id: str):
    """从池内跑 discover（F-3.4, 2026-08-08）：加载活跃池品，DB 新鲜 K 线复用优先，
    按综合分排序出高分品。池内 90 日 K 线每日采集已在库，纯 DB 扫描，只有过期品才触发网络补齐。"""
    conn_p = db.get_conn()
    try:
        rows = conn_p.execute(
            "SELECT i.id, i.good_id, i.name FROM items i "
            "WHERE i.good_id>0 AND i.name LIKE '%崭新出厂%' "
            "AND (i.notes IS NULL OR (i.notes NOT LIKE '%存世量过低%' "
            "AND i.notes NOT LIKE '%活跃池淘汰%')) ORDER BY i.id"
        ).fetchall()
    finally:
        conn_p.close()
    items = [(r["good_id"], r["name"], 0) for r in rows]
    if not items:
        _discover_progress[task_id]["done"] = True
        _discover_progress[task_id]["html"] = '<div class="card" style="padding:20px;">池内无活跃品</div>'
        _finalize_discover(task_id, note="empty")
        return
    _discover_progress[task_id]["total"] = len(items)
    _discover_progress[task_id]["current"] = 0
    _discover_progress[task_id]["name"] = "池内扫描准备中"
    await _run_discover_task(task_id, items)
    _save_discover_artifacts(task_id)


def _save_discover_artifacts(task_id: str):
    """discover 完成产物统一落盘（F-3.4, 2026-08-08）：latest cache + top10 历史存档 + 池维护台账。
    pool/search 两条路径共用，避免尾部逻辑漂移。"""
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

    # 高分品追踪 (2026-08-05): top10 存档，14/30d 后回测表现
    try:
        _hist_dir = _Path_cache(__file__).resolve().parent.parent / 'data' / 'discover_history'
        _hist_dir.mkdir(parents=True, exist_ok=True)
        _top = [r for r in (_discover_progress[task_id].get('results') or []) if not r.get('error')][:10]
        _snap = {
            'time': _cache_data['time'],
            'market_th': _cache_data['market_th'],
            'items': [{
                'name': r.get('name', ''), 'good_id': r.get('good_id'),
                'price_rmb': r.get('price_rmb'), 'score': r.get('score'),
                'composite': r.get('composite'), 'pct_90d': r.get('percentile_90d'),
            } for r in _top],
        }
        (_hist_dir / ('discover_' + task_id.replace('discover_', '') + '.json')).write_text(
            _json_cache.dumps(_snap, ensure_ascii=False), encoding='utf-8')
        # 2026-08-09 需求：高分品追踪「同一天只保留最新推荐」，按天滚动保留最多 30 天
        _keep = {}
        for _f in sorted(_hist_dir.glob('discover_*.json'), reverse=True):
            try:
                _day = str(_json_cache.loads(_f.read_text(encoding='utf-8')).get('time', ''))[:10]
            except Exception:
                _day = ''
            if _day and _day not in _keep:
                _keep[_day] = _f
        _keep_days = set(sorted(_keep)[-30:])
        for _f in _hist_dir.glob('discover_*.json'):
            try:
                _day = str(_json_cache.loads(_f.read_text(encoding='utf-8')).get('time', ''))[:10]
            except Exception:
                _day = ''
            if _day not in _keep_days:
                try:
                    _f.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    # 池维护台账 (F-3.2, 2026-08-08): discover 扫描完成统一留痕（成功/空/失败全覆盖）
    _finalize_discover(task_id)


async def _run_discover_scan_all_task(task_id: str):
    """Full discover pipeline: search all weapon types, analyze results."""
    from pipeline.collector_csqaq import _get_browser, CSQAQ_WEB
    from collections import defaultdict
    pw, browser = await _get_browser()
    if not browser:
        _discover_progress[task_id]["done"] = True
        _discover_progress[task_id]["html"] = '<div class="card" style="padding:20px;color:var(--danger);">\u65e0\u6cd5\u542f\u52a8\u6d4f\u89c8\u5668</div>'
        _finalize_discover(task_id, note="browser_fail")
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
        _finalize_discover(task_id, note="search_error")
        return

    if not all_items:
        _discover_progress[task_id]["done"] = True
        _discover_progress[task_id]["html"] = '<div class="card" style="padding:20px;">\u672a\u627e\u5230\u9970\u54c1</div>'
        _finalize_discover(task_id, note="empty")
        return

    by_type = defaultdict(list)
    for gid, name, price in all_items:
        key = name.split(" |")[0] if "|" in name else "unknown"
        by_type[key].append((gid, name, price))
    # P0-2 (2026-08): 每类扫6个(原3), 总量上限40(原24) 提升覆盖
    # F-3 扩池 (2026-08-08): 每类 20 个、总量 120；排除已在库且新鲜的品，名额给库外新品
    capped = []
    for wt_items in by_type.values():
        capped.extend(wt_items[:20])
    capped = capped[:240]  # 13 武器 x 每类 20 = 260 候选，总量 240 让新武器候选都能进
    fresh_gids = set()
    conn_f = db.get_conn()
    try:
        for _r in conn_f.execute(
            "SELECT i.good_id FROM items i JOIN price_history p ON p.item_id=i.id "
            "WHERE i.good_id>0 GROUP BY i.id HAVING MAX(p.date)>=date('now','-3 day')").fetchall():
            fresh_gids.add(_r["good_id"])
        # F-3.1 活跃池淘汰品不重新采集（数据保留，避免淘汰后又被 discover 捞回）
        for _r in conn_f.execute(
            "SELECT good_id FROM items WHERE good_id>0 AND notes LIKE '%活跃池淘汰%'").fetchall():
            fresh_gids.add(_r["good_id"])
    finally:
        conn_f.close()
    capped = [x for x in capped if x[0] not in fresh_gids]

    _discover_progress[task_id]["total"] = len(capped)
    _discover_progress[task_id]["current"] = 0
    await _run_discover_task(task_id, capped)

    # 完成产物统一落盘：latest cache + top10 历史存档 + 池维护台账（F-3.4 抽公共函数）
    _save_discover_artifacts(task_id)


def _settle_discover_items(items, scan_time):
    """\u4ece price_history \u7ed3\u7b97\u5feb\u7167\u54c1\u7684 14/30d \u6536\u76ca\uff08\u626b\u63cf\u65e5\u540e\u7b2c 14/30 \u4e2a\u4ea4\u6613\u65e5 vs \u626b\u63cf\u65e5\u4ef7\uff09\u3002\u7eaf\u5c55\u793a\u5c42\u3002"""
    from datetime import datetime as _dt
    try:
        scan_date = _dt.fromisoformat((scan_time or '')[:10]).strftime('%Y-%m-%d')
    except Exception:
        return {'avg14': None, 'win14': None, 'avg30': None, 'win30': None, 'items': []}
    out = []
    f14, f30 = [], []
    conn = db.get_conn()
    try:
        for it in items:
            rec = {'name': it.get('name', ''), 'entry': it.get('price_rmb'), 'fwd14': None, 'fwd30': None, 'days': 0}
            gid = it.get('good_id')
            try:
                row = conn.execute(
                    "SELECT id FROM items WHERE good_id=? AND name=? LIMIT 1", (gid, it.get('name', ''))).fetchone()
                item_id = row['id'] if row else None
            except Exception:
                item_id = None
            if item_id and it.get('price_rmb'):
                rows = conn.execute(
                    "SELECT date, price_rmb FROM price_history WHERE item_id=? AND date>=? AND price_rmb>0 ORDER BY date",
                    (item_id, scan_date)).fetchall()
                prices = [r['price_rmb'] for r in rows]
                if len(prices) >= 2:
                    base = prices[0]
                    if len(prices) > 14:
                        rec['fwd14'] = round((prices[14] - base) / base * 100, 1)
                    if len(prices) > 30:
                        rec['fwd30'] = round((prices[30] - base) / base * 100, 1)
                    rec['days'] = len(prices)
            out.append(rec)
            if rec['fwd14'] is not None:
                f14.append(rec['fwd14'])
            if rec['fwd30'] is not None:
                f30.append(rec['fwd30'])
    finally:
        conn.close()

    def _agg(vals):
        if not vals:
            return None
        wins = sum(1 for v in vals if v > 0)
        return round(sum(vals) / len(vals), 1), round(wins / len(vals) * 100, 0)

    a14, a30 = _agg(f14), _agg(f30)
    return {
        'avg14': a14[0] if a14 else None, 'win14': a14[1] if a14 else None,
        'avg30': a30[0] if a30 else None, 'win30': a30[1] if a30 else None,
        'items': out,
    }


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
        html = _render_discover_html(results, market_th) if results else data.get("html", "")
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
