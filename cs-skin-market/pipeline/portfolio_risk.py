# -*- coding: utf-8 -*-
"""B1 风险预算层（2026-08-05）：组合回撤熔断 + 单票敞口提示。

回测依据 data/b1_risk_validation.json（301 信号组合回放, 2025-11-02~2026-07-13）：
- cap0.8 基线: 总收益+54.6% / 最大回撤-15.3%
- cap0.8 + 组合回撤熔断10%（权益自峰值回撤10%暂停新信号，收复峰值解除）:
  总收益+60.5% / 最大回撤-12.0%，熔断生效约18%交易日
- 熔断阈值15%+ 几乎不触发（无效）；单票10%硬上限误伤 panic 0.3 仓位
  （收益跌至+24.6%）→ 单票只做提示，不做拒绝。

纯展示/风控层：不改变任何信号引擎决策。权益曲线为「当前持仓数量 × 历史价」
的 mark-to-market 代理（仅覆盖全部持仓均有价的公共日期区间）。
"""
import logging

from .config import PORTFOLIO_DRAWDOWN_BREAKER, POSITION_CAP_SINGLE

_log = logging.getLogger("portfolio_risk")


def portfolio_equity_curve(conn, min_days=2):
    """按日组合市值曲线 [(date, value), ...]（当前持仓数量 × 当日价）。

    仅保留「全部持仓当日都有价」的公共区间，避免新品加入造成虚假峰值。
    无持仓或公共区间不足 min_days 天时返回空列表。
    """
    held = conn.execute(
        "SELECT id, quantity FROM items WHERE holding=1 AND quantity>0"
    ).fetchall()
    if not held:
        return []
    series = []
    for row in held:
        item_id, qty = row["id"], row["quantity"]
        rows = conn.execute(
            "SELECT date, price_rmb FROM price_history "
            "WHERE item_id=? AND price_rmb>0", (item_id,)
        ).fetchall()
        series.append((qty, {r["date"]: r["price_rmb"] for r in rows}))
    if len(series) == 1:
        common = set(series[0][1].keys())
    else:
        common = set.intersection(*[set(m.keys()) for _, m in series])
    curve = []
    for d in sorted(common):
        value = sum(qty * prices.get(d, 0) for qty, prices in series)
        if value > 0:
            curve.append((d, round(value, 2)))
    return curve if len(curve) >= min_days else []


def drawdown_from_curve(curve, threshold=None):
    """从权益曲线计算峰值回撤状态（纯函数，便于测试）。

    返回 {peak, current, drawdown_pct, threshold_pct, breaker_active, days}；
    数据不足（<2 天）返回 None。
    """
    threshold = PORTFOLIO_DRAWDOWN_BREAKER if threshold is None else threshold
    if not curve or len(curve) < 2:
        return None
    peak = max(v for _, v in curve)
    current = curve[-1][1]
    if peak <= 0:
        return None
    drawdown_pct = (current / peak - 1) * 100
    return {
        "peak": round(peak, 2),
        "current": round(current, 2),
        "drawdown_pct": round(drawdown_pct, 2),
        "threshold_pct": round(threshold * 100, 1),
        "breaker_active": bool(drawdown_pct <= -threshold * 100),
        "days": len(curve),
    }


def drawdown_status(conn, threshold=None):
    """DB 便捷入口：组合回撤熔断状态（数据不足返回 None）。"""
    return drawdown_from_curve(portfolio_equity_curve(conn), threshold)


def single_position_exposure(market_value, add_amount, total_assets, cap=None):
    """单票敞口提示（纯函数）：(持仓市值 + 建议补仓额) / 总资产。

    返回 {base_pct, after_pct, cap_pct, over, over_pct}；total_assets<=0 返回 None。
    仅提示不回绝信号——回测显示单票硬上限会误伤 panic 大仓位信号。
    """
    cap = POSITION_CAP_SINGLE if cap is None else cap
    if not total_assets or total_assets <= 0:
        return None
    base = market_value / total_assets
    after = (market_value + max(0.0, add_amount)) / total_assets
    return {
        "base_pct": round(base * 100, 1),
        "after_pct": round(after * 100, 1),
        "cap_pct": round(cap * 100, 1),
        "over": bool(after > cap),
        "over_pct": round(max(0.0, after - cap) * 100, 1),
    }
