"""
Market regime detection: trending, ranging, volatile states.
Uses csQAQ index history data.
"""

import statistics
from dataclasses import dataclass


REGIME_STRATEGY = {
    "trending_up": {
        "label": "\U0001f7e2 \u4e0a\u6da8\u5e02",
        "position": "70%",
        "strategy": "\u8d8b\u52bf\u8ddf\u968f\uff0c\u91cd\u4ed3\u9ad8\u8bc4\u7ea7\u6807\u7684\uff0c\u6b62\u635f\u653e\u5bbd\u5230 -15%",
    },
    "trending_down": {
        "label": "\U0001f534 \u4e0b\u8dcc\u5e02",
        "position": "30%",
        "strategy": "\u9632\u5fa1\u4e3a\u4e3b\uff0c\u53ea\u6301 S/A \u7ea7\uff0c\u6b62\u635f\u6536\u7d27\u5230 -8%",
    },
    "ranging": {
        "label": "\U0001f7e1 \u9707\u8361\u5e02",
        "position": "50%",
        "strategy": "\u9ad8\u629b\u4f4e\u5438\uff0c\u4f4e\u4f30\u4e70\u5165\u9ad8\u4f30\u5356\u51fa",
    },
    "volatile": {
        "label": "\U0001f7e0 \u9ad8\u6ce2\u5e02",
        "position": "30%",
        "strategy": "\u964d\u4f4e\u4ed3\u4f4d\uff0c\u7b49\u6ce2\u52a8\u7387\u56de\u5f52",
    },
    "no_data": {
        "label": "\u2796 \u6570\u636e\u4e0d\u8db3",
        "position": "50%",
        "strategy": "\u9ed8\u8ba4\u4e2d\u6027\uff0c\u7b49\u5f85\u66f4\u591a\u6570\u636e",
    },
}


@dataclass
class RegimeResult:
    regime: str = "unknown"
    trend_strength: str = "weak"
    index_current: float = 0.0
    momentum_7d: float = 0.0
    momentum_30d: float = 0.0
    volatility_30d: float = 0.0
    position_advice: str = ""
    confidence: str = "low"


def detect_regime(index_history=None, current_value=0, change_7d=0, mood=""):
    """Detect market regime from daily index K-line data.
    
    Args:
        index_history: list of (timestamp, value) tuples from /api/user/statistics/v2/chart
                       ~91 daily data points spanning ~3 months
        current_value: current index value
        change_7d: daily change ratio from API summary (not 7d - just daily)
        mood: market mood string from API
    """
    result = RegimeResult()
    result.index_current = current_value

    if not index_history or len(index_history) < 5:
        result.regime = "no_data"
        result.confidence = "low"
        cfg = REGIME_STRATEGY["no_data"]
        result.position_advice = cfg["position"]
        return result

    # API returns oldest-first chronological order
    values = [v for _, v in index_history if v > 0]
    
    if len(values) < 5:
        result.regime = "no_data"
        result.confidence = "low"
        cfg = REGIME_STRATEGY["no_data"]
        result.position_advice = cfg["position"]
        return result

    # 7d momentum: last 7 bars vs 7 bars ago
    if len(values) >= 7:
        result.momentum_7d = round((values[-1] / values[-7] - 1) * 100, 1) if values[-7] > 0 else 0
    elif len(values) >= 2:
        result.momentum_7d = round((values[-1] / values[0] - 1) * 100, 1) if values[0] > 0 else 0

    # 30d momentum
    lookback_30 = min(len(values), 30)
    if lookback_30 >= 5:
        result.momentum_30d = round((values[-1] / values[-lookback_30] - 1) * 100, 1) if values[-lookback_30] > 0 else 0

    # Volatility: stdev of daily returns
    daily_returns = []
    for i in range(1, len(values)):
        if values[i-1] > 0:
            daily_returns.append((values[i] / values[i-1] - 1) * 100)
    
    if len(daily_returns) >= 5:
        recent_returns = daily_returns[-30:]  # last 30 days of returns
        result.volatility_30d = round(statistics.stdev(recent_returns), 2) if len(recent_returns) > 1 else 0

    # Regime classification with daily-data-calibrated thresholds
    # Daily volatility > 2.5% stdev = high vol regime
    # Low momentum: |7d| < 2% and |30d| < 5%
    high_vol = result.volatility_30d > 2.5
    low_momentum = abs(result.momentum_7d) < 2.0 and abs(result.momentum_30d) < 5.0

    if high_vol:
        result.regime = "volatile"
    elif low_momentum:
        result.regime = "ranging"
    elif result.momentum_7d > 0 and result.momentum_30d > 0:
        result.regime = "trending_up"
        result.trend_strength = "strong" if result.momentum_30d > 15 else "moderate"
    elif result.momentum_7d < 0 and result.momentum_30d < 0:
        result.regime = "trending_down"
        result.trend_strength = "strong" if result.momentum_30d < -15 else "moderate"
    else:
        result.regime = "ranging"

    cfg = REGIME_STRATEGY.get(result.regime, REGIME_STRATEGY["no_data"])
    result.position_advice = cfg["position"]
    result.confidence = "high" if len(values) >= 30 else ("medium" if len(values) >= 15 else "low")

    return result
def regime_label(result):
    cfg = REGIME_STRATEGY.get(result.regime, REGIME_STRATEGY["no_data"])
    return cfg["label"]


def regime_strategy(result):
    return REGIME_STRATEGY.get(result.regime, REGIME_STRATEGY["no_data"])
