"""
Historical valuation analysis: percentile rank, z-score, cheap/expensive signals.
"""

import statistics
from dataclasses import dataclass


@dataclass
class ValuationResult:
    current_price: float = 0.0
    percentile_30d: float = 50.0    # 0=cheapest, 100=most expensive
    percentile_90d: float = 50.0
    zscore_30d: float = 0.0
    zscore_90d: float = 0.0
    median_30d: float = 0.0
    median_90d: float = 0.0
    mean_30d: float = 0.0
    high_30d: float = 0.0
    low_30d: float = 0.0
    data_points_30d: int = 0
    data_points_90d: int = 0
    label: str = "fair"   # cheap / fair / expensive / no_data


def calc_percentile(prices, current):
    """Percentile rank: what % of historical prices are below current.
    Returns 0-100, where 0=at absolute low, 100=at absolute high."""
    if not prices or current <= 0:
        return 50.0
    below = sum(1 for p in prices if p < current)
    return round(below / len(prices) * 100, 1)


def calc_zscore(prices, current):
    """Z-score: how many standard deviations from mean."""
    if len(prices) < 2 or current <= 0:
        return 0.0
    mean = statistics.mean(prices)
    std = statistics.stdev(prices)
    if std == 0:
        return 0.0
    return round((current - mean) / std, 2)


def get_valuation_summary(conn, item_id):
    """Query price_history and compute valuation metrics."""
    rows = conn.execute(
        "SELECT price_rmb, date FROM price_history WHERE item_id=? ORDER BY date ASC",
        (item_id,)
    ).fetchall()

    if not rows:
        return ValuationResult(label="no_data")

    prices = [float(r["price_rmb"]) for r in rows]
    current = prices[-1]

    # 30-day window
    prices_30d = prices[-30:] if len(prices) >= 30 else prices
    # 90-day window
    prices_90d = prices[-90:] if len(prices) >= 90 else prices

    pct_30 = calc_percentile(prices_30d, current)
    pct_90 = calc_percentile(prices_90d, current)
    z30 = calc_zscore(prices_30d, current)
    z90 = calc_zscore(prices_90d, current)

    # Label
    if pct_30 <= 20:
        label = "cheap"
    elif pct_30 >= 80:
        label = "expensive"
    else:
        label = "fair"

    return ValuationResult(
        current_price=current,
        percentile_30d=pct_30,
        percentile_90d=pct_90,
        zscore_30d=z30,
        zscore_90d=z90,
        median_30d=round(statistics.median(prices_30d), 2) if prices_30d else 0,
        median_90d=round(statistics.median(prices_90d), 2) if prices_90d else 0,
        mean_30d=round(statistics.mean(prices_30d), 2) if prices_30d else 0,
        high_30d=round(max(prices_30d), 2) if prices_30d else 0,
        low_30d=round(min(prices_30d), 2) if prices_30d else 0,
        data_points_30d=len(prices_30d),
        data_points_90d=len(prices_90d),
        label=label,
    )


def get_valuation_from_prices(prices):
    """Compute valuation from an in-memory price list (e.g. from K-line API).
    Uses 90-day K-line data from csqaq for accurate percentile/Z-score."""
    if not prices or len(prices) < 2:
        return ValuationResult(label="no_data")

    current = prices[-1]
    prices_30d = prices[-30:] if len(prices) >= 30 else prices
    prices_90d = prices[-90:] if len(prices) >= 90 else prices

    pct_30 = calc_percentile(prices_30d, current)
    pct_90 = calc_percentile(prices_90d, current)
    z30 = calc_zscore(prices_30d, current)
    z90 = calc_zscore(prices_90d, current)

    if pct_30 <= 20:
        label = "cheap"
    elif pct_30 >= 80:
        label = "expensive"
    else:
        label = "fair"

    return ValuationResult(
        current_price=current,
        percentile_30d=pct_30,
        percentile_90d=pct_90,
        zscore_30d=z30,
        zscore_90d=z90,
        median_30d=round(statistics.median(prices_30d), 2) if prices_30d else 0,
        median_90d=round(statistics.median(prices_90d), 2) if prices_90d else 0,
        mean_30d=round(statistics.mean(prices_30d), 2) if prices_30d else 0,
        high_30d=round(max(prices_30d), 2) if prices_30d else 0,
        low_30d=round(min(prices_30d), 2) if prices_30d else 0,
        data_points_30d=len(prices_30d),
        data_points_90d=len(prices_90d),
        label=label,
    )


# ============================================================
#  3x4 Valuation Grid (percentile x trend health strength)
# ============================================================

@dataclass
class ValuationGrid:
    """3x4 grid: 3 percentile rows x 4 trend strength columns."""
    percentile: float = 50.0
    zscore: float = 0.0
    trend_score: int = 50             # corrected trend health score
    trend_direction: str = "flat"
    trend_strength: str = "neutral"   # strong_up / weak_up / ranging / weak_down
    grid_row: str = "fair"            # undervalued / fair / overvalued
    grid_col: str = "ranging"         # strong_up / weak_up / ranging / weak_down
    grid_label: str = ""
    grid_action: str = ""
    grid_emoji: str = ""
    is_extreme_bubble: bool = False   # 90%+ warning
    position_sizing: str = ""        # 轻仓/中仓/重仓 + 分批节奏
    stop_loss_advice: str = ""       # 止盈/止损参考


def compute_valuation_grid(pct_90d: float, trend_health=None, whale_prob: float = 0) -> ValuationGrid:
    """Compute 3x4 grid position from percentile + trend health + whale check.

    Rows: undervalued(0-30%) / fair(30-70%) / overvalued(70-100%)
    Cols: strong_up(TH>=75) / weak_up(TH 60-74) / ranging(TH 40-59) / weak_down(TH<40)
    """
    vg = ValuationGrid()
    vg.percentile = pct_90d

    # Trend strength from corrected trend health score
    if trend_health is not None:
        ts = trend_health.score
        vg.trend_score = ts
        vg.trend_direction = trend_health.direction

        # Check for fake bull (whale pooling override)
        if whale_prob > 60 and ts >= 60:
            vg.trend_strength = "weak_down"
            vg.trend_direction = "fake_up"
        elif ts >= 75:
            vg.trend_strength = "strong_up"
        elif ts >= 60:
            vg.trend_strength = "weak_up"
        elif ts >= 40:
            vg.trend_strength = "ranging"
        else:
            vg.trend_strength = "weak_down"
    else:
        vg.trend_score = 50
        vg.trend_strength = "ranging"

    # Row: percentile zone
    if pct_90d <= 30:
        vg.grid_row = "undervalued"
    elif pct_90d <= 70:
        vg.grid_row = "fair"
    else:
        vg.grid_row = "overvalued"
        if pct_90d >= 90:
            vg.is_extreme_bubble = True

    vg.grid_col = vg.trend_strength

    # 3x4 Grid: (row, col) -> (label, action, emoji, sizing, stop)
    grid = {
        # === undervalued (0-30%) ===
        ("undervalued", "strong_up"): (
            "反弹确认·重仓建仓", "buy_zone", "🟢",
            "总资金20-30%, 分3批: 底仓50% + 回踩加30% + 突破加20%",
            "移动止盈: 百分位升至60%减半仓, 70%清仓; 止损: 跌破90日最低价-3%"
        ),
        ("undervalued", "weak_up"): (
            "温和反弹·轻仓试错", "buy_zone", "🟢",
            "总资金10-15%, 分2批: 首仓60% + 确认加40%",
            "止盈: 百分位升至50%减1/3, 60%清仓; 止损: 跌破成本价-5%"
        ),
        ("undervalued", "ranging"): (
            "筑底中·观察等待", "watch", "🟡",
            "不加仓, 已有持仓不动", "等待趋势确认(TH>=60)后再操作"
        ),
        ("undervalued", "weak_down"): (
            "持续下跌·禁止抄底", "wait", "🔴",
            "严禁任何买入", "等待Z-score触底回升 + 出现连续3日阳线"
        ),

        # === fair (30-70%) ===
        ("fair", "strong_up"): (
            "健康上涨·重仓持有", "hold", "🟢",
            "现有仓位不动, 不加仓", "移动止盈: 百分位升至70%减半仓, 80%清仓"
        ),
        ("fair", "weak_up"): (
            "温和上涨·持仓观望", "hold", "🟡",
            "保持现有仓位, 不加仓", "止盈收紧至百分位65%, 或TH跌破40清仓"
        ),
        ("fair", "ranging"): (
            "震荡·观望不操作", "wait", "🟡",
            "不加仓不止损, 持有卧倒", "等待方向确认: TH>=75做多, TH<40离场"
        ),
        ("fair", "weak_down"): (
            "回调中·关注反转", "watch", "🟡",
            "已有持仓减至半仓", "观察百分位是否跌破30%, 跌破则清仓"
        ),

        # === overvalued (70-100%) ===
        ("overvalued", "strong_up"): (
            "强势拉升·分批止盈", "reduce", "🟠",
            "禁止新开仓, 每上涨8%减仓1/3", "止盈目标: 百分位回落至80%以下清仓"
        ),
        ("overvalued", "weak_up"): (
            "高位缓涨·加速减仓", "reduce", "🔴",
            "禁止新开仓, 立即减仓50%", "剩余仓位: TH跌破40或百分位>95%时全部清仓"
        ),
        ("overvalued", "ranging"): (
            "高位横盘·清仓离场", "sell", "🔴",
            "立即减仓70%以上", "横盘超过14天大概率崩盘, 剩余仓位设3%止损"
        ),
        ("overvalued", "weak_down"): (
            "趋势反转·立即清仓", "sell", "🔴",
            "全部清仓, 不留任何仓位", "下跌趋势确认, 反弹到成本价附近也是离场机会"
        ),
    }

    key = (vg.grid_row, vg.grid_col)
    if key in grid:
        vg.grid_label, vg.grid_action, vg.grid_emoji, vg.position_sizing, vg.stop_loss_advice = grid[key]

    # Extreme bubble override
    if vg.is_extreme_bubble:
        vg.grid_label = "极度泡沫·危险勿入" if vg.trend_strength == "weak_down" else "极度泡沫·立即清仓"
        vg.grid_emoji = "💀"
        if vg.grid_action not in ("sell",):
            vg.grid_action = "sell"
            vg.position_sizing = "全部清仓, 不留任何仓位"
            vg.stop_loss_advice = "90%+极度泡沫区间, 历史回测显示1个月内暴跌概率>70%"

    return vg


def valuation_grid_summary(vg):
    """Convert ValuationGrid to JSON-safe dict for templates."""
    return {
        "percentile": vg.percentile,
        "zscore": vg.zscore,
        "trend_score": vg.trend_score,
        "trend_direction": vg.trend_direction,
        "trend_strength": vg.trend_strength,
        "grid_row": vg.grid_row,
        "grid_col": vg.grid_col,
        "grid_label": vg.grid_label,
        "grid_action": vg.grid_action,
        "grid_emoji": vg.grid_emoji,
        "is_extreme_bubble": vg.is_extreme_bubble,
        "position_sizing": vg.position_sizing,
        "stop_loss_advice": vg.stop_loss_advice,
    }
