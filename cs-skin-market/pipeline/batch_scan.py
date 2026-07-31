"""Batch scan, discover high-score items, and portfolio advice."""
import asyncio, json, logging, traceback
from datetime import datetime

from . import collector_csqaq, collector_steamdt, collector, db, item_analysis, index_analysis

_log = logging.getLogger("batch_scan")

def _portfolio_advice(holding, avg_cost, qty, current_price, analysis, market_th=None):
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
        if market_th is not None and market_th < 55:
            advice["action"] = "暂缓补仓"
            advice["reason"] = f"浮亏{pnl_pct:.0f}%但大盘TH={market_th}，等趋势转强"
            advice["suggest"] = "大盘趋势偏弱，等TH≥55后再补"
        else:
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
