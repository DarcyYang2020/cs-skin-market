"""
Four-factor scoring engine for CS skin valuation (v2).

Factors: Scarcity(35%) + Volume(25%) + Liquidity(15%) + Market(25%)
Modifiers: Sector heat + Momentum signal + Event overlay
"""

from dataclasses import dataclass, field
from typing import Optional

from .trends import analyze_trends, TrendSignals
from .supply import analyze_supply, SupplySignals
from .config import (
    RARITY_COEF, SOURCE_MULTIPLIER,
    VOLUME_SCORES, MARKET_SCORES,
    LIQUIDITY_SPREAD_SCORES, LIQUIDITY_DEPTH_SCORES,
    SECTOR_RANK_MODIFIER, VOLUME_SPIKE_MODIFIER,
    EVENT_MODIFIERS, ACTIVE_EVENTS,
    WEIGHT_SCARCITY, WEIGHT_VOLUME, WEIGHT_LIQUIDITY, WEIGHT_MARKET,
    GRADE_THRESHOLDS, TAKE_PROFIT_STEPS, STOP_LOSS_STEPS,
)


# Inline type definitions (avoid collector import dependency)
from dataclasses import dataclass, field

@dataclass
class OrderBook:
    lowest_sell: float = 0.0
    highest_buy: float = 0.0
    sell_count: int = 0
    buy_count: int = 0
    spread_rmb: float = 0.0
    spread_pct: float = 0.0
    bid_depth: float = 0.0


@dataclass
class SectorFlow:
    name: str = ""
    change_pct: float = 0.0
    rank: int = 99
    momentum: str = ""


@dataclass
class KLinePoint:
    date: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0



@dataclass
class ScoreResult:
    scarcity: float = 0.0
    volume: float = 0.0
    liquidity: float = 0.0
    market: float = 0.0
    total: float = 0.0
    grade: str = "C"
    # Modifier details
    sector_mod: float = 0.0
    momentum_mod: float = 0.0
    event_mod: float = 0.0
    trend_mod: float = 0.0
    supply_mod: float = 0.0
    sector_name: str = ""
    sector_rank: int = 99
    volume_spike_ratio: float = 1.0
    active_events: list[str] = field(default_factory=list)
    # Trend + Supply signals
    trend_signals: Optional[TrendSignals] = None
    supply_signals: Optional[SupplySignals] = None


def calc_scarcity(
    rarity: str,
    source: str = "case",
    is_discontinued: bool = False,
    discontinued_years: float = 0,
) -> float:
    rc = RARITY_COEF.get(rarity.lower(), 1.0)
    if is_discontinued:
        if discontinued_years >= 5:
            source = "discontinued_long"
        else:
            source = "discontinued_case"
    sm = SOURCE_MULTIPLIER.get(source.lower(), 1.0)
    return round(rc * sm, 2)


def calc_volume(daily_volume: int) -> float:
    for lo, hi, score in VOLUME_SCORES:
        if lo <= daily_volume < hi or (hi == float("inf") and daily_volume >= lo):
            return score
    return 0.4


def calc_liquidity(order_book: Optional[OrderBook] = None,
                    daily_volume: int = 0,
                    volume_total: int = 0) -> float:
    """Calculate liquidity score 0-2+ with volume fallback when no order book.

    With order_book: spread (50%) + depth from sell_count (50%).
    Without order_book: estimate from daily_volume relative to total supply.
    """
    if order_book is not None:
        # Spread score (0-1.3)
        spread_score = 1.0
        for lo, hi, s in LIQUIDITY_SPREAD_SCORES:
            if lo <= order_book.spread_pct < hi:
                spread_score = s
                break

        # Depth score: use sell_count as proxy
        if order_book.sell_count > 200:
            depth_score = 1.3
        elif order_book.sell_count > 50:
            depth_score = 1.1
        elif order_book.sell_count > 10:
            depth_score = 1.0
        elif order_book.sell_count > 0:
            depth_score = 0.7
        else:
            depth_score = 0.4

        return round(spread_score * 0.5 + depth_score * 0.5, 2)

    # Fallback: estimate liquidity from volume data
    if daily_volume <= 0:
        return 0.5  # truly unknown

    # Base score from daily volume (log scale, 0.3-1.3 range)
    import math
    vol_base = min(1.3, max(0.3, 0.3 + math.log10(max(1, daily_volume)) * 0.5))

    # Turnover adjustment: higher turnover = better liquidity
    if volume_total > 0:
        turnover_pct = daily_volume / volume_total * 100
        if turnover_pct >= 1.0:
            turnover_bonus = 0.3
        elif turnover_pct >= 0.5:
            turnover_bonus = 0.2
        elif turnover_pct >= 0.1:
            turnover_bonus = 0.1
        elif turnover_pct >= 0.02:
            turnover_bonus = 0.0
        else:
            turnover_bonus = -0.1
    else:
        turnover_bonus = 0.0

    return round(max(0.2, vol_base + turnover_bonus), 2)


def calc_market(index_change_7d: float) -> float:
    for lo, hi, score in MARKET_SCORES:
        if lo <= index_change_7d < hi:
            return score
    return 1.0


def calc_sector_modifier(sectors: list[SectorFlow], item_sector: str) -> tuple[float, int, str]:
    for s in sectors:
        if s.name in item_sector or item_sector in s.name:
            for rank_threshold, mod in SECTOR_RANK_MODIFIER:
                if s.rank <= rank_threshold:
                    return mod, s.rank, s.name
            break
    return 0.0, 99, item_sector or "unknown"


def calc_momentum_modifier(volume_day: int, kline_30d: list[KLinePoint]) -> tuple[float, float]:
    if not kline_30d or len(kline_30d) < 5:
        return 0.0, 1.0

    # Average volume over last N days
    volumes = [k.volume for k in kline_30d[-20:] if k.volume > 0]
    if not volumes:
        return 0.0, 1.0

    avg_vol = sum(volumes) / len(volumes)
    if avg_vol == 0:
        return 0.0, 1.0

    spike_ratio = volume_day / avg_vol if volume_day > 0 else 1.0

    for lo, hi, mod in VOLUME_SPIKE_MODIFIER:
        if lo <= spike_ratio < hi:
            return mod, round(spike_ratio, 2)

    return 0.0, round(spike_ratio, 2)


def calc_event_modifier() -> tuple[float, list[str]]:
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    today = datetime.now(tz).date()

    total_mod = 0.0
    active = []

    for evt in ACTIVE_EVENTS:
        try:
            start = datetime.strptime(evt["start"], "%Y-%m-%d").date()
            end = datetime.strptime(evt["end"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue

        if start <= today <= end:
            cfg = EVENT_MODIFIERS.get(evt["type"], {})
            mod = cfg.get("during", 0.0)
            total_mod += mod
            active.append(evt.get("label", evt["type"]))

    return round(total_mod, 2), active


def score_item(
    rarity: str,
    daily_volume: int = 0,
    index_change_7d: float = 0.0,
    source: str = "case",
    is_discontinued: bool = False,
    discontinued_years: float = 0,
    volume_total: int = 0,
    order_book: Optional[OrderBook] = None,
    sectors: Optional[list[SectorFlow]] = None,
    item_sector: str = "",
    kline_30d: Optional[list[KLinePoint]] = None,
    price_history: Optional[list[float]] = None,
    volume_history: Optional[list[int]] = None,
    supply_history: Optional[list[int]] = None,
) -> ScoreResult:
    s_scarcity  = calc_scarcity(rarity, source, is_discontinued, discontinued_years)
    s_volume    = calc_volume(daily_volume)
    s_liquidity = calc_liquidity(order_book, daily_volume, volume_total)
    s_market    = calc_market(index_change_7d)

    # Base total
    base_total = (
        s_scarcity  * WEIGHT_SCARCITY
        + s_volume    * WEIGHT_VOLUME
        + s_liquidity * WEIGHT_LIQUIDITY
        + s_market    * WEIGHT_MARKET
    )

    # Modifiers
    sector_mod, sector_rank, sector_name = calc_sector_modifier(
        sectors or [], item_sector
    )
    momentum_mod, spike_ratio = calc_momentum_modifier(daily_volume, kline_30d or [])
    event_mod, active_events = calc_event_modifier()

    # Apply modifiers (additive, clamped)
    total_mod = sector_mod + momentum_mod + event_mod
    total_mod = max(-0.4, min(0.5, total_mod))  # clamp

    # Trend modifier
    trend_sig = TrendSignals()
    trend_mod = 0.0
    if price_history and len(price_history) >= 7:
        trend_sig = analyze_trends(price_history, volume_history)
        trend_mod = round(trend_sig.trend_score * 0.15, 2)  # scale to +/- 0.15

    # Supply modifier
    supply_sig = SupplySignals()
    supply_mod = 0.0
    if supply_history and len(supply_history) >= 5:
        supply_sig = analyze_supply(supply_history, price_history)
        supply_mod = round(supply_sig.supply_score * 0.3, 2)  # scale to +/- 0.09

    total = round(base_total + total_mod + trend_mod + supply_mod, 2)

    # Grade
    grade = "C"
    for g, threshold in sorted(GRADE_THRESHOLDS.items(), key=lambda x: -x[1]):
        if total >= threshold:
            grade = g
            break

    return ScoreResult(
        scarcity=s_scarcity,
        volume=s_volume,
        liquidity=s_liquidity,
        market=s_market,
        total=total,
        grade=grade,
        sector_mod=sector_mod,
        momentum_mod=momentum_mod,
        event_mod=event_mod,
        trend_mod=trend_mod,
        supply_mod=supply_mod,
        sector_name=sector_name,
        sector_rank=sector_rank,
        volume_spike_ratio=spike_ratio,
        active_events=active_events,
        trend_signals=trend_sig,
        supply_signals=supply_sig,
    )


def get_recommendation(grade: str, trend: str = "", momentum_mod: float = 0.0,
                        liquidity: float = 0.0) -> str:
    if liquidity < 0.5:
        return "avoid_low_liquidity"
    if momentum_mod > 0.1:
        if grade in ("S", "A"):
            return "buy_momentum"
    recs = {
        "S": "buy",
        "A": "buy_dip" if trend == "down" else "buy",
        "B": "hold" if trend == "up" else "watch",
        "C": "sell" if trend == "down" else "avoid",
    }
    return recs.get(grade, "watch")


def calc_take_profit_steps(entry_price: float, liquidity: float = 1.0) -> list[dict]:
    steps = []
    cumulative_sell = 0.0
    # For low liquidity, widen targets by 10%
    liq_adj = 1.1 if liquidity < 0.6 else 1.0
    for pct, sell_pct in TAKE_PROFIT_STEPS:
        adj_pct = pct * liq_adj
        target = round(entry_price * (1 + adj_pct), 2)
        cumulative_sell += sell_pct
        steps.append({
            "target_price": target,
            "gain_pct": f"+{adj_pct*100:.0f}%",
            "sell_pct": f"{sell_pct*100:.0f}%",
            "cumulative_sell": f"{cumulative_sell*100:.0f}%",
        })
    return steps


def calc_stop_loss_steps(entry_price: float) -> list[dict]:
    steps = []
    for pct, sell_pct in STOP_LOSS_STEPS:
        target = round(entry_price * (1 + pct), 2)
        label = "alert" if sell_pct == 0 else (
            "clear" if sell_pct >= 1.0 else f"sell {sell_pct*100:.0f}%"
        )
        steps.append({
            "trigger_price": target,
            "loss_pct": f"{pct*100:.0f}%",
            "action": label,
        })
    return steps
