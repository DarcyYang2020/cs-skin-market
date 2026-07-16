
"""
Multi-timeframe trend analysis for CS skin prices.
Computes momentum, moving averages, volume analysis across 7/30/90 day windows.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TrendSignals:
    # Momentum (price change %)
    momentum_7d: float = 0.0
    momentum_30d: float = 0.0
    momentum_90d: float = 0.0
    momentum_alignment: str = "neutral"  # bullish / bearish / mixed

    # Moving averages
    ma7: float = 0.0
    ma30: float = 0.0
    ma_crossover: str = "none"  # golden_cross / death_cross / none

    # Volatility
    volatility_7d: float = 0.0
    volatility_30d: float = 0.0

    # Volume analysis
    volume_trend: str = "stable"  # rising / falling / stable / spike
    volume_price_signal: str = "none"  # accumulation / distribution / none

    # Price position
    price_vs_ma7: str = "at"  # above / below / at
    price_vs_ma30: str = "at"

    # Summary
    trend_score: float = 0.0  # -1.0 (bearish) to +1.0 (bullish)
    confidence: str = "low"   # low / medium / high (based on data points)


def analyze_trends(prices: list[float], volumes: list[int] = None,
                   dates: list[str] = None) -> TrendSignals:
    """Compute multi-timeframe trend signals from price series.

    Args:
        prices: list of prices ordered oldest -> newest
        volumes: corresponding daily volumes (optional)
        dates: corresponding dates (optional)
    """
    n = len(prices)
    if n < 2:
        return TrendSignals()

    sig = TrendSignals()
    latest = prices[-1]

    # ---- Momentum ----
    if n >= 7:
        sig.momentum_7d = round((latest / prices[-7] - 1) * 100, 1) if prices[-7] > 0 else 0
    if n >= 30:
        sig.momentum_30d = round((latest / prices[-30] - 1) * 100, 1) if prices[-30] > 0 else 0
    if n >= 90:
        sig.momentum_90d = round((latest / prices[-90] - 1) * 100, 1) if prices[-90] > 0 else 0

    # Momentum alignment
    if sig.momentum_7d > 0 and sig.momentum_30d > 0:
        sig.momentum_alignment = "bullish"
    elif sig.momentum_7d < 0 and sig.momentum_30d < 0:
        sig.momentum_alignment = "bearish"
    else:
        sig.momentum_alignment = "mixed"

    # ---- Moving Averages ----
    if n >= 7:
        sig.ma7 = round(sum(prices[-7:]) / 7, 2)
    if n >= 30:
        sig.ma30 = round(sum(prices[-30:]) / 30, 2)

    # MA crossover (compare last 2 periods)
    if n >= 30:
        # Current: latest MA7 vs MA30
        cur_ma7 = sum(prices[-7:]) / 7
        cur_ma30 = sum(prices[-30:]) / 30
        # Previous: MA7 vs MA30 one day ago
        prev_prices = prices[:-1]
        prev_ma7 = sum(prev_prices[-7:]) / 7 if len(prev_prices) >= 7 else cur_ma7
        prev_ma30 = sum(prev_prices[-30:]) / 30 if len(prev_prices) >= 30 else cur_ma30

        if cur_ma7 > cur_ma30 and prev_ma7 <= prev_ma30:
            sig.ma_crossover = "golden_cross"
        elif cur_ma7 < cur_ma30 and prev_ma7 >= prev_ma30:
            sig.ma_crossover = "death_cross"

    # Price vs MA
    sig.price_vs_ma7 = "above" if latest > sig.ma7 else ("below" if latest < sig.ma7 else "at")
    sig.price_vs_ma30 = "above" if latest > sig.ma30 else ("below" if latest < sig.ma30 else "at")

    # ---- Volatility ----
    if n >= 7:
        import statistics
        subset = prices[-7:]
        mean7 = statistics.mean(subset)
        std7 = statistics.stdev(subset) if len(subset) > 1 else 0
        sig.volatility_7d = round(std7 / mean7 * 100, 2) if mean7 > 0 else 0
    if n >= 30:
        import statistics
        subset30 = prices[-30:]
        mean30 = statistics.mean(subset30)
        std30 = statistics.stdev(subset30) if len(subset30) > 1 else 0
        sig.volatility_30d = round(std30 / mean30 * 100, 2) if mean30 > 0 else 0

    # ---- Volume Analysis ----
    if volumes and len(volumes) >= 7:
        recent_vol = volumes[-3:] if len(volumes) >= 3 else volumes[-1:]
        older_vol = volumes[-10:-3] if len(volumes) >= 10 else volumes[:-3]
        if older_vol and sum(older_vol) > 0:
            vol_ratio = sum(recent_vol) / (sum(older_vol) / len(older_vol) * len(recent_vol))
            if vol_ratio > 2.0:
                sig.volume_trend = "spike"
            elif vol_ratio > 1.2:
                sig.volume_trend = "rising"
            elif vol_ratio < 0.5:
                sig.volume_trend = "falling"
            else:
                sig.volume_trend = "stable"

        # Volume-price signal
        if sig.volume_trend == "spike" and sig.momentum_7d > 3:
            sig.volume_price_signal = "accumulation"
        elif sig.volume_trend == "spike" and sig.momentum_7d < -3:
            sig.volume_price_signal = "distribution"

    # ---- Trend Score (-1 to +1) ----
    score = 0.0
    # Momentum contribution
    if sig.momentum_alignment == "bullish":
        score += 0.4
    elif sig.momentum_alignment == "bearish":
        score -= 0.4
    # MA contribution
    if sig.ma_crossover == "golden_cross":
        score += 0.3
    elif sig.ma_crossover == "death_cross":
        score -= 0.3
    elif sig.price_vs_ma7 == "above" and sig.price_vs_ma30 == "above":
        score += 0.15
    elif sig.price_vs_ma7 == "below" and sig.price_vs_ma30 == "below":
        score -= 0.15
    # Volume contribution
    if sig.volume_price_signal == "accumulation":
        score += 0.3
    elif sig.volume_price_signal == "distribution":
        score -= 0.3
    sig.trend_score = round(max(-1.0, min(1.0, score)), 2)

    # Confidence
    if n >= 30 and volumes and len(volumes) >= 30:
        sig.confidence = "high"
    elif n >= 7:
        sig.confidence = "medium"

    return sig


def trend_signals_to_dict(sig: TrendSignals) -> dict:
    """Convert TrendSignals to a dict for storage/display."""
    return {
        "momentum_7d": sig.momentum_7d,
        "momentum_30d": sig.momentum_30d,
        "momentum_90d": sig.momentum_90d,
        "alignment": sig.momentum_alignment,
        "ma7": sig.ma7,
        "ma30": sig.ma30,
        "ma_crossover": sig.ma_crossover,
        "volatility_7d": sig.volatility_7d,
        "volume_trend": sig.volume_trend,
        "volume_signal": sig.volume_price_signal,
        "trend_score": sig.trend_score,
        "confidence": sig.confidence,
    }
