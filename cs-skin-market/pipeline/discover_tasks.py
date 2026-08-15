# -*- coding: utf-8 -*-
"""发现高分品后台任务（C-1 拆模块第二批，2026-08-10）。

从 webapp/main.py 原样切出：_discover_progress 内存任务字典 + DISCOVER_WEAPONS 武器池 +
discover 三种扫描任务与落盘。依赖 pipeline/ 与 webapp（无 FastAPI app 依赖）。
"""
import asyncio, logging, traceback

from pipeline import db
from webapp.analysis_service import (
    KLINE_FRESH_DISCOVER, kline_db_fallback, market_snapshot, recent_buy_dates,
    resolve_item, save_analysis_result, save_item_snapshot, _today_str,
)
from pipeline.item_categories import discover_category
from webapp.render_html import render_discover_html, split_discover_top10
from pipeline.trend_health import liquidity_supply_floor

_web_log = logging.getLogger("webapp")


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
        _web_log.warning("cs-skin-market/pipeline/discover_tasks.py unexpected error near line 35", exc_info=True)

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
        _web_log.warning("cs-skin-market/pipeline/discover_tasks.py unexpected error near line 59", exc_info=True)

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
            supply_depth_missing = db.latest_supply_missing(daily_bars)
            # F-3.5 高分榜流动性预筛（2026-08-14 用户口径）：按最新单价分档设置最低在售量
            # 单价 <10000 -> 最新在售量 <200 跳过；单价 >=10000 -> 最新在售量 <100 跳过
            # 与决策层 F-3.5 的 supply_depth<15 闸门分属两层：此处只决定是否进入高分榜。
            if supply_hist:
                _latest_sale = next((s for s in reversed(supply_hist) if s), 0)
                _min_sale = liquidity_supply_floor(current_p)
                if 0 < _latest_sale < _min_sale:
                    skipped += 1
                    return "skip", "流动性不足(单价¥{:.0f}/在售{}<{})".format(current_p, _latest_sale, _min_sale)

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
                _web_log.warning("cs-skin-market/pipeline/discover_tasks.py unexpected error near line 189", exc_info=True)
            analysis = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _ia.run_item_analysis(
                    name=exact_name, prices=prices,
                    supply_hist=supply_hist or None, supply_depth_missing=supply_depth_missing, order_book=item.order_book,
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
            composite = _ia.composite_score(analysis)
            fd_action = (analysis.fusion_decision or {}).get("action", "") if isinstance(analysis.fusion_decision, dict) else ""
            th_score = (analysis.trend_health or {}).get("score", 50) if isinstance(analysis.trend_health, dict) else 50

            # P3: Market-linked filter
            if market_th < 55 and score < 6.0 and composite < 5.0:
                skipped += 1
                return "skip", "市场弱过滤"

            results.append(dict(
                name=exact_name, good_id=good_id, price_rmb=price_rmb or item.price_rmb,
                collected_at=getattr(item, "collected_at", "") or "",
                category=discover_category(exact_name),
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

    # 保存榜单报告到 analysis_results + snapshots（查看报告不再重新分析）
    # 2026-08-12 贴纸独立 Top10 后：综合榜 + 贴纸榜双榜单可见行均落库
    # （原 results[:10] 只覆盖综合榜前 10，贴纸 2-10 名无报告，点击显示「暂无报告」）
    try:
        _top10, _sticker_top10 = split_discover_top10(results)
        _save_rows, _seen_names = [], set()
        for _r in _top10 + _sticker_top10:
            if _r.get("error") or _r.get("name") in _seen_names:
                continue
            _seen_names.add(_r.get("name"))
            _save_rows.append(_r)
        for _r in _save_rows:
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

    html = render_discover_html(results, market_th)
    _discover_progress[task_id]["html"] = html

    # 扫描完成，清理进度落盘文件
    try:
        _discover_progress_file(task_id).unlink(missing_ok=True)
    except Exception:
        pass

async def _run_discover_pool_task(task_id: str, scope: str = "all"):
    """从池内跑 discover（F-3.4, 2026-08-08）：加载活跃池品，DB 新鲜 K 线复用优先，
    按综合分排序出高分品。池内 90 日 K 线每日采集已在库，纯 DB 扫描，只有过期品才触发网络补齐。
    scope: sticker collection paused 2026-08-13; all/skin both exclude stickers, sticker maps to skin."""
    if scope == "sticker":
        scope = "skin"
    conn_p = db.get_conn()
    try:
        # M-6 (2026-08-11): 发现空间扩展——无磨损品类（印花/武器箱/挂件/收藏品/胶囊）
        # 与崭新出厂枪皮同进发现榜；角色/特工（非以上品类）暂不入榜。
        _scope_sql = ""
        if scope == "sticker":
            _scope_sql = " AND i.name LIKE '印花 |%'"
        elif scope == "skin":
            _scope_sql = " AND i.name NOT LIKE '印花 |%'"
        rows = conn_p.execute(
            "SELECT i.id, i.good_id, i.name FROM items i "
            "WHERE i.good_id>0 AND (i.name LIKE '%崭新出厂%' "
            "OR i.name LIKE '挂件 |%' "
            "OR i.name LIKE '%武器箱' OR i.name LIKE '%收藏品' OR i.name LIKE '%胶囊') "
            "AND (i.notes IS NULL OR (i.notes NOT LIKE '%存世量过低%' "
            "AND i.notes NOT LIKE '%活跃池淘汰%' AND i.notes NOT LIKE '%贴纸模块停采%'))" + _scope_sql + " ORDER BY i.id"
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
    _save_discover_artifacts(task_id, scope)

def _save_discover_artifacts(task_id: str, scope: str = "all"):
    """discover 完成产物统一落盘（F-3.4, 2026-08-08）：latest cache + top10 历史存档 + 池维护台账。
    pool/search 两条路径共用，避免尾部逻辑漂移。
    scope（2026-08-12 双榜独立刷新）：非 all 时结果合并回现有 cache（另一榜保留）、
    重渲染两榜完整 HTML、不写 discover_history（快照仅由全量扫描驱动）。"""
    import json as _json_cache
    from pathlib import Path as _Path_cache
    _cache_path = _Path_cache(__file__).resolve().parent.parent / 'data' / 'discover_latest.json'
    _cache_path.parent.mkdir(parents=True, exist_ok=True)
    _results = _discover_progress[task_id].get('results', [])
    _market_th = _discover_progress[task_id].get('market_th', None)
    _skip_history = False
    if scope != "all":
        # 2026-08-12 双榜独立刷新：scope 结果合并回现有 cache（另一榜旧行保留），
        # 合并后重渲染两榜完整 HTML（进度轮询取 progress.html 时榜单完整）；history 仅由全量扫描驱动
        _skip_history = True
        try:
            _old = _json_cache.loads(_cache_path.read_text(encoding='utf-8')) if _cache_path.exists() else {}
            _old_results = _old.get('results') or []
        except Exception:
            _old_results = []
        _scope_rows = {r.get('name'): r for r in _results if r.get('name')}

        def _is_stk(r):
            return (r.get('category') or discover_category(r.get('name') or '')) == 'sticker'
        if scope == "sticker":
            _merged = [r for r in _old_results if not _is_stk(r) and r.get('name') not in _scope_rows]
        else:  # scope == "skin"：综合榜 = 非贴纸
            _merged = [r for r in _old_results if _is_stk(r) and r.get('name') not in _scope_rows]
        _merged.extend(_scope_rows.get(n) for n in _scope_rows)
        _results = _merged
        if _market_th is None:
            _market_th = _old.get('market_th')
        try:
            _new_html = render_discover_html(_results, _market_th or 50)
            _discover_progress[task_id]["html"] = _new_html
        except Exception:
            _new_html = _discover_progress[task_id].get('html', '')
    _cache_data = {
        'time': __import__('datetime').datetime.now().isoformat(),
        'html': _discover_progress[task_id].get('html', ''),
        'results': _results,
        'market_th': _market_th,
    }
    _cache_path.write_text(_json_cache.dumps(_cache_data, ensure_ascii=False), encoding='utf-8')

    # 高分品追踪 (2026-08-05): top10 存档，14/30d 后回测表现
    # 2026-08-12 scope 独立刷新：不写 discover_history（避免覆盖当天全量快照），台账留痕后直接结束
    if _skip_history:
        _finalize_discover(task_id, note="completed scope=" + scope)
        return
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
                'category': discover_category(r.get('name', '')),
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
                js = "async(q)=>{const el=document.querySelector('#rc_select_0');if(!el)return;const fk=Object.keys(el).find(k=>k.startsWith('__reactFiber'));if(!fk)return;const f=el[fk];let n=f,t=0;while(n&&t<30){const p=n.memoizedProps;if(p&&(p.onChange||p.onSearch)){const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(el,q);if(p.onChange)p.onChange({target:{value:q}});else if(p.onSearch)p.onSearch(q);return}n=n.return||n.stateNode;t++}}"
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
                            _web_log.warning("cs-skin-market/pipeline/discover_tasks.py unexpected error near line 479", exc_info=True)
                page.on("response", _on_suggest)
                for _attempt in range(3):
                    try:
                        await page.goto(CSQAQ_WEB, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(1200)
                        try:
                            await page.wait_for_selector("#rc_select_0", timeout=6000)
                        except Exception:
                            pass
                        await page.evaluate(js, wt)
                        await page.wait_for_timeout(2500)
                    except Exception as _e:
                        _web_log.warning(f"Discover suggest 搜索异常 {wt} 第{_attempt+1}次: {str(_e)[:80]}")
                    if suggest.get("items"):
                        break
                    await page.wait_for_timeout(2500)
                if not suggest.get("items"):
                    _web_log.warning(f"Discover suggest 搜索 {wt} 3 次尝试未捕获下拉（csQAQ 限流/前端不稳），跳过该武器类")
                for sd in suggest.get("items", []):
                    try:
                        gid = int(sd.get("id", 0))
                        name = sd.get("value", "")
                        if gid > 0 and name and name not in seen:
                            if discover_category(name) != "other" and "StatTrak" not in name and "纪念品" not in name:
                                seen.add(name)
                                all_items.append((gid, name, 0))
                    except (ValueError, TypeError):
                        continue
                page.remove_listener("response", _on_suggest)
                _discover_progress[task_id]["current"] = wt_idx + 1
                _discover_progress[task_id]["name"] = f"搜索: {wt} ({wt_idx+1}/{total_wt})"
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
