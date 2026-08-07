"""
Supply-side analysis for CS2 skins.

Leverages csQAQ chart.num_data (in-sale count history) and
buff_sell_num (current total supply) to compute supply trends.
"""

import statistics
from dataclasses import dataclass, field


@dataclass
class SupplyAnalysis:
    """Supply trend analysis result."""
    current_supply: int = 0              # buff_sell_num
    supply_trend: str = "stable"         # expanding / contracting / stable
    supply_change_7d: float = 0.0        # % change over 7 days
    supply_change_30d: float = 0.0       # % change over 30 days
    supply_change_90d: float = 0.0       # % change over 90 days
    supply_risk: str = "normal"          # normal / hoarding / dumping
    supply_risk_label: str = ""
    is_alchemy_material: bool = False    # rarity == Covert (Red)
    is_alchemy_output: bool = False      # knife or glove
    has_event_risk: bool = False
    event_risk_factors: list = field(default_factory=list)
    event_risk_discount: float = 1.0     # 1.0 = no discount


def analyze_supply(prices, num_data, vol_total, item_meta=None):
    """Analyze supply trends from chart num_data (in-sale count history).

    Args:
        prices: daily close prices (for alignment)
        num_data: raw num_data array from chart API (in-sale count per point)
        vol_total: current buff_sell_num
        item_meta: optional dict with type_name, rarity_name, quality_name, 
                   case_discontinued

    Returns:
        SupplyAnalysis with trend and risk assessment
    """
    sa = SupplyAnalysis()
    sa.current_supply = vol_total

    # Supply trend from num_data (if available)
    if num_data and len(num_data) > 7:
        # Aggregate num_data similarly to how prices are aggregated to daily
        # Use simple windows
        n = len(num_data)
        recent_7 = statistics.mean(num_data[-min(7, n):]) if n >= 7 else num_data[-1]
        recent_30 = statistics.mean(num_data[-min(30, n):]) if n >= 30 else recent_7
        older_30 = statistics.mean(num_data[-min(60, n):-min(30, n)]) if n >= 60 else recent_30

        if older_30 > 0:
            sa.supply_change_30d = round((recent_30 / older_30 - 1.0) * 100, 1)

        # 7-day change
        if n >= 14:
            older_7 = statistics.mean(num_data[-14:-7])
            if older_7 > 0:
                sa.supply_change_7d = round((recent_7 / older_7 - 1.0) * 100, 1)

        # 90-day
        if n >= 90:
            older_90 = statistics.mean(num_data[:30])
            if older_90 > 0:
                sa.supply_change_90d = round((recent_30 / older_90 - 1.0) * 100, 1)

        # Determine trend
        if sa.supply_change_30d > 5:
            sa.supply_trend = "expanding"
        elif sa.supply_change_30d < -5:
            sa.supply_trend = "contracting"
        else:
            sa.supply_trend = "stable"

    # Supply risk detection
    if sa.supply_trend == "contracting" and prices and len(prices) >= 7:
        # Supply shrinking + price stable/up = hoarding (accumulation)
        price_change_7d = (prices[-1] / prices[-min(8, len(prices))] - 1) * 100
        if price_change_7d > -3:
            sa.supply_risk = "hoarding"
            sa.supply_risk_label = "\U0001f4e6 \u5438\u7b79\u4e2d"
    elif sa.supply_trend == "expanding" and prices and len(prices) >= 7:
        price_change_7d = (prices[-1] / prices[-min(8, len(prices))] - 1) * 100
        if price_change_7d < 3:
            sa.supply_risk = "dumping"
            sa.supply_risk_label = "\U0001f4a6 \u6d3e\u53d1\u4e2d"

    # Event risk from item metadata
    if item_meta:
        rarity = item_meta.get("rarity_name", "")
        type_name = item_meta.get("type_name", "")
        quality = item_meta.get("quality_name", "")
        case_disc = item_meta.get("case_discontinued", True)

        # Alchemy material: Covert (Red) rarity, not knife/glove
        if rarity == "\u9690\u79d8" and type_name not in ("\u5200", "\u624b\u5957"):
            sa.is_alchemy_material = True
            sa.has_event_risk = True
            sa.event_risk_factors.append("alchemy_material")
            sa.event_risk_discount *= 0.85

        # Alchemy output: knife or glove (affected by 5-in-1 recipe)
        if type_name in ("\u5200", "\u624b\u5957"):
            sa.is_alchemy_output = True
            sa.has_event_risk = True
            sa.event_risk_factors.append("alchemy_output")
            sa.event_risk_discount *= 0.85

        # Case still active (not discontinued)
        if not case_disc:
            sa.has_event_risk = True
            sa.event_risk_factors.append("case_active")
            sa.event_risk_discount *= 0.9

        # Souvenir/collection risk
        if quality == "\u7eaa\u5ff5\u54c1":
            sa.has_event_risk = True
            sa.event_risk_factors.append("souvenir_shock")
            sa.event_risk_discount *= 0.8

    return sa


def supply_summary(sa):
    """Convert to JSON-safe dict for templates."""
    return {
        "current_supply": sa.current_supply,
        "supply_trend": sa.supply_trend,
        "supply_change_7d": sa.supply_change_7d,
        "supply_change_30d": sa.supply_change_30d,
        "supply_change_90d": sa.supply_change_90d,
        "supply_risk": sa.supply_risk,
        "supply_risk_label": sa.supply_risk_label,
        "is_alchemy_material": sa.is_alchemy_material,
        "is_alchemy_output": sa.is_alchemy_output,
        "has_event_risk": sa.has_event_risk,
        "event_risk_factors": sa.event_risk_factors,
        "event_risk_discount": round(sa.event_risk_discount, 3),
    }
