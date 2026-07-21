"""Batch scan all watchlist items with shared browser session."""
import asyncio, json, logging, traceback
from datetime import datetime

from . import collector_csqaq, collector_steamdt, collector, db, item_analysis, index_analysis

_log = logging.getLogger("batch_scan")


async def batch_scan_watchlist():
    """Scan all watchlist items using a shared browser session.
    Returns dict with held_items, unheld_items, errors.
    """
    from .collector_csqaq import _get_browser
    pw, browser = await _get_browser()
    if not browser:
        return {"error": "无法启动浏览器"}
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT id, name, holding, avg_cost, quantity FROM items WHERE in_watchlist=1").fetchall()
    finally:
        conn.close()

    idx = collector.fetch_market_index()
    if idx is None or idx.value == 0:
        idx = collector.MarketIndex(value=0, change_7d=0, mood="neutral")

    results = []
    total = len(rows)
    for i, row in enumerate(rows):
        item_id, name, holding, avg_cost, qty = row["id"], row["name"], row["holding"] or 0, row["avg_cost"] or 0, row["quantity"] or 0
        try:
            _log.info(f"[{i+1}/{total}] scanning {name}")
            good_id, _ = await collector_csqaq.search_good_id(name)
            if good_id == 0:
                results.append(dict(id=item_id, name=name, holding=holding, avg_cost=avg_cost, quantity=qty, error="未找到"))
                continue
            item = await collector_csqaq.fetch_item_detail(good_id)
            if item is None:
                results.append(dict(id=item_id, name=name, holding=holding, avg_cost=avg_cost, quantity=qty, error="详情获取失败"))
                continue
            exact_name = item.name or name
            price_rmb = item.price_rmb
            daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
            prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else [price_rmb]
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
            volume_total = item.volume_total or 0

            analysis = item_analysis.run_item_analysis(
                name=exact_name, prices=prices, volumes=volumes or None,
                supply_hist=supply_hist or None, order_book=item.order_book,
                index_change_7d=idx.change_7d,
            )
            analysis.volume_day = volume_day
            analysis.volume_total = volume_total

            # Personalized portfolio advice
            portfolio_advice = _portfolio_advice(holding, avg_cost, qty, price_rmb, analysis)

            results.append(dict(
                id=item_id, name=exact_name, holding=holding, avg_cost=avg_cost, quantity=qty,
                price_rmb=price_rmb, volume_day=volume_day, volume_total=volume_total,
                grade=analysis.value.grade, score=analysis.value.score,
                trend=analysis.trend_health,
                cycle_phase=getattr(analysis.cycle, "phase", "unknown"),
                cycle_label=getattr(analysis.cycle, "phase_label", ""),
                strategy=getattr(analysis.cycle, "phase_strategy", ""),
                fusion=getattr(analysis, "fusion_decision", {}),
                valuation_tier=getattr(analysis.position, "valuation_tier", ""),
                percentile_90d=getattr(analysis.position, "percentile_90d", 50),
                portfolio_advice=portfolio_advice,
                data_quality=getattr(analysis, "data_quality", "low"),
                error=None,
            ))

            # Persist
            conn_p = db.get_conn()
            try:
                pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id)
                db.save_price_history_batch(conn_p, pid, daily_bars)
                conn_p.execute("""INSERT OR REPLACE INTO snapshots (item_id, date, total_score, grade, price_rmb, report_md)
                    VALUES (?, date('now','localtime'), ?, ?, ?, ?)""",
                    (pid, analysis.value.score, analysis.value.grade, price_rmb, ""))
                conn_p.commit()
            finally:
                conn_p.close()
        except Exception as e:
            _log.error(f"scan failed for {name}: {e}")
            results.append(dict(id=item_id, name=name, holding=holding, avg_cost=avg_cost, quantity=qty, error=str(e)))

    held = [r for r in results if r.get("holding") and r.get("error") is None]
    unheld = [r for r in results if not r.get("holding") and r.get("error") is None]
    errors = [r for r in results if r.get("error")]
    return {"held": held, "unheld": unheld, "errors": errors, "total": total, "ok": len(results) - len(errors)}


def _portfolio_advice(holding, avg_cost, qty, current_price, analysis):
    """Generate personalized portfolio advice based on cost basis and current position."""
    if not holding or avg_cost <= 0:
        # Non-held: entry advice
        th = analysis.trend_health or {}
        th_score = th.get("score", 50)
        cycle_phase = getattr(analysis.cycle, "phase", "unknown")
        pct = getattr(analysis.position, "percentile_90d", 50)
        fusion = getattr(analysis, "fusion_decision", {})
        fusion_action = fusion.get("action", "") if isinstance(fusion, dict) else ""

        if th_score < 30 or cycle_phase in ("distribution", "decline"):
            return {"action": "暂不建议入场", "reason": "趋势偏弱/出货阶段", "risk": "high"}
        if pct <= 20:
            return {"action": "可轻仓试探入场", "reason": f"处于90日低位(pct={pct:.0f}%)", "risk": "medium", "note": "建议分批建仓"}
        if pct >= 80:
            return {"action": "偏高估，等待回调", "reason": f"处于90日高位(pct={pct:.0f}%)", "risk": "high"}
        return {"action": "观望等待机会", "reason": f"估值中等(pct={pct:.0f}%), 趋势得分{th_score}", "risk": "medium"}

    # Held: personalized advice
    cost_total = avg_cost * qty
    market_value = current_price * qty
    pnl_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
    th = analysis.trend_health or {}
    th_score = th.get("score", 50)
    cycle_phase = getattr(analysis.cycle, "phase", "unknown")

    advice = {"cost_price": avg_cost, "current_price": current_price, "qty": qty,
              "pnl_pct": round(pnl_pct, 1), "cost_total": round(cost_total, 2), "market_value": round(market_value, 2)}

    if pnl_pct > 20 and th_score < 40:
        advice["action"] = "建议止盈减仓"
        advice["reason"] = f"盈利{pnl_pct:.0f}%且趋势转弱"
        advice["suggest"] = f"可卖出{max(1, qty//2)}件锁定利润"
    elif pnl_pct > 50:
        advice["action"] = "大幅盈利，部分止盈"
        advice["reason"] = f"盈利{pnl_pct:.0f}%，建议卖出1/3~1/2"
        advice["suggest"] = f"可卖出{max(1, qty//3)}~{max(1, qty//2)}件"
    elif pnl_pct < -15 and cycle_phase in ("accumulation", "bottom"):
        advice["action"] = "可逢低补仓"
        advice["reason"] = f"浮亏{pnl_pct:.0f}%但处于底部区域"
        advice["suggest"] = f"可加仓{max(1, qty//3)}件拉低成本"
    elif pnl_pct < -10 and th_score < 30:
        advice["action"] = "趋势走弱，考虑止损"
        advice["reason"] = f"浮亏{pnl_pct:.0f}%且趋势得分{th_score}"
        advice["suggest"] = "建议设置止损线"
    elif abs(pnl_pct) < 10 and th_score >= 50:
        advice["action"] = "继续持有观望"
        advice["reason"] = f"盈亏不大({pnl_pct:.1f}%)且趋势健康({th_score})"
    else:
        advice["action"] = "持有观察"
        advice["reason"] = f"建议结合大盘走势决策"
    return advice
