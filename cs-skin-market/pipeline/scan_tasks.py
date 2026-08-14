# -*- coding: utf-8 -*-
"""批量扫描后台任务（C-1 拆模块第二批，2026-08-10）。

从 webapp/main.py 原样切出：_scan_progress 内存任务字典 + 进度落盘 + 逐品分析/批量扫描任务。
依赖 pipeline/ 与 webapp/analysis_service（无 FastAPI app 依赖），行为零变化。
"""
import asyncio, logging

from pipeline import db, collector_csqaq
from webapp.analysis_service import (
    KLINE_FRESH_BATCH, anchor_override, kline_db_fallback, kline_price_sane,
    market_snapshot, recent_buy_dates, resolve_item, save_analysis_result,
    save_item_snapshot, _today_str,
)

_web_log = logging.getLogger("webapp")


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
        supply_depth_missing = db.latest_supply_missing(daily_bars)
        analysis = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: item_analysis.run_item_analysis(
                name=exact_name, prices=prices,
                supply_hist=supply_hist or None, supply_depth_missing=supply_depth_missing, order_book=item.order_book,
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
            composite=item_analysis.composite_score(analysis),
            position_limit=float(_fd_lim),
            portfolio_advice=pa,
            buy_distance=summarize_buy_distance(getattr(analysis, "buy_distance", None) or {}),
            valuation_tier=getattr(analysis.position, "valuation_tier", "") if hasattr(analysis, "position") else "",
            percentile_90d=getattr(analysis.position, "percentile_90d", 50) if hasattr(analysis, "position") else 50,
            force_fallback=force_fallback,
            collected_at=getattr(item, "collected_at", "") or "",
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
            db.save_price_history_batch(conn_p, pid, daily_bars,
                                        collect_time=getattr(item, "collected_at", "") or "")
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
        # B1 风险预算层(2026-08-05): 总资产(单票敞口提示)；2026-08-11 起结果页不再展示回撤熔断条
        _conn_r = db.get_conn()
        try:
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
        final_html = build_scan_html(results, total, now_str=now_str, name_link=_item_report_link)
        _scan_progress[scan_id]["html"] = final_html
        _persist_scan_progress(scan_id)
        _scan_progress[scan_id]["done"] = True
        # Persist to disk (latest + 历史归档, 2026-08-04)
        _data_dir = _P(__file__).resolve().parent.parent / "data"
        _payload = {
            "time": __import__("datetime").datetime.now().isoformat(),
            "html": final_html,
            "results": results,
            "rows": rows,
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
