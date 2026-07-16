"""
Market index multi-dimensional analysis engine — CS-SKIN SPECIFIC.
Based on:
  - cs-knowledge.md Ch5: CS2 market features (event-driven, no fundamentals, etc.)
  - trading-strategies.md: standardized entry/exit rules, cycle framework

Core algorithm path:
  percentile → position,  Z-score → reversal,
  percentile+Z → strategy zone,  cycle radar → phase,
  zone proximity → value score
"""

import statistics
from dataclasses import dataclass, field


# ============================================================
#  Strategy Constants (from trading-strategies.md)
# ============================================================

ENTRY_PERCENTILE_MAX = 30      # Entry only when percentile <= 30%
ENTRY_ZSCORE_MAX = -1.5        # Entry only when Z <= -1.5
EXIT_PERCENTILE_MIN = 65       # Conservative exit at 65%
EXIT_ZSCORE_MIN = 2.0          # Aggressive exit at Z >= +2.0
OPTIMAL_HOLD_DAYS_MIN = 15     # 15-45 day optimal hold
OPTIMAL_HOLD_DAYS_MAX = 45

_SEP = "、"  # Chinese enumeration comma


# ============================================================
#  Data Classes
# ============================================================

@dataclass
class PositionIntel:
    """Position intelligence — percentile + Z-score based.
    
    Signals aligned with trading-strategies.md entry/exit thresholds.
    """
    current_value: float = 0.0
    percentile_90d: float = 50.0
    zscore_90d: float = 0.0
    valuation_tier: str = "fair"          # undervalued / fair / overvalued / bubble

    # Strategy zone (from trading-strategies.md)
    strategy_zone: str = "neutral"        # entry / hold / exit
    zone_label: str = ""
    zone_action: str = ""

    # Multi-timeframe signals
    short_term_signal: str = "hold"       # dip_buy / hold / top_sell
    mid_term_signal: str = "hold"         # accumulate / hold / reduce
    long_term_signal: str = "hold"        # build / hold / exit

    support_levels: list = field(default_factory=list)
    resistance_levels: list = field(default_factory=list)

    @property
    def tier_label(self) -> str:
        return {
            "undervalued": "\U0001f7e2 \u4f4e\u4f30",
            "fair": "\U0001f7e1 \u5408\u7406",
            "overvalued": "\U0001f7e0 \u9ad8\u4f30",
            "bubble": "\U0001f534 \u6ce1\u6cab",
        }.get(self.valuation_tier, self.valuation_tier)


@dataclass
class ProbPrediction:
    """Probability prediction — Z-score mean-reversion + volatility regime."""
    prob_up_3d: float = 50.0
    prob_up_7d: float = 50.0
    prob_up_30d: float = 50.0
    expected_return_3d: float = 0.0
    expected_return_7d: float = 0.0
    expected_return_30d: float = 0.0
    key_support: float = 0.0
    key_resistance: float = 0.0
    volatility_regime: str = "normal"


@dataclass
class CycleAnalysis:
    """Cycle phase detection — aligned with trading-strategies.md framework.
    
    Four phases (percentile + Z-score driven, volatility as confirmation):
      - accumulation: low percentile, negative Z → 只买不卖
      - consolidation: oscillating, no clear signal → 卧倒持有
      - markup: percentile rising, Z turning positive → 持有减仓
      - distribution: high percentile, high positive Z → 只卖不买
    """
    phase: str = "unknown"
    phase_confidence: float = 0.0
    phase_description: str = ""
    phase_strategy: str = ""
    next_phase_trigger: str = ""

    @property
    def phase_label(self) -> str:
        return {
            "accumulation": "\U0001f4e5 \u5438\u7b79\u671f",
            "consolidation": "\U0001f4ca \u6d17\u76d8\u671f",
            "markup": "\U0001f680 \u62c9\u5347\u671f",
            "distribution": "\U0001f4c9 \u51fa\u8d27\u671f",
        }.get(self.phase, self.phase)


@dataclass
class ValueScore:
    """Investment value score 1-10 — strategy-aligned.
    
    Rewards proximity to optimal entry zone, penalizes proximity to exit zone.
    """
    score: int = 5
    entry_proximity: float = 1.25    # 0-2.5: closer to entry zone = higher
    risk_score: float = 1.25         # 0-2.5: calmer = higher
    cycle_score: float = 1.25        # 0-2.5: accumulation > markup > distribution
    sentiment_score: float = 1.25    # 0-2.5: contrarian (fear = high, greed = low)
    position_advice: str = ""        # light / build / full / hold / reduce / exit
    recommendation: str = ""


# ============================================================
#  Helpers
# ============================================================

def _percentile(prices: list, current: float) -> float:
    if not prices or current <= 0:
        return 50.0
    below = sum(1 for p in prices if p < current)
    return round(below / len(prices) * 100, 1)


def _zscore(prices: list, current: float) -> float:
    if len(prices) < 2 or current <= 0:
        return 0.0
    mean = statistics.mean(prices)
    std = statistics.stdev(prices)
    if std == 0:
        return 0.0
    return round((current - mean) / std, 2)


def _daily_returns(prices: list) -> list:
    return [(prices[i] / prices[i-1] - 1) * 100 for i in range(1, len(prices))
            if prices[i-1] > 0]


def _rolling_volatility(returns: list, window: int = 14) -> list:
    if len(returns) < window:
        return [statistics.stdev(returns)] if len(returns) > 1 else [0]
    vols = []
    for i in range(window, len(returns) + 1):
        wr = returns[i-window:i]
        vols.append(statistics.stdev(wr) if len(wr) > 1 else 0)
    return vols


def _momentum(prices: list, lookback: int) -> float:
    if len(prices) <= lookback or prices[-lookback-1] <= 0:
        return 0.0
    return round((prices[-1] / prices[-lookback-1] - 1) * 100, 1)


def _volatility_regime(vol_14d: float) -> str:
    if vol_14d < 1.0:
        return "calm"
    elif vol_14d < 2.5:
        return "normal"
    elif vol_14d < 5.0:
        return "elevated"
    else:
        return "extreme"


def _strategy_zone(percentile: float, zscore: float) -> tuple:
    """Determine strategy zone per trading-strategies.md thresholds.
    
    Returns: (zone_key, label, action)
    """
    # Entry zone: both conditions must be met
    if percentile <= ENTRY_PERCENTILE_MAX and zscore <= ENTRY_ZSCORE_MAX:
        return (
            "entry",
            "\U0001f7e2 \u5165\u573a\u533a",
            "\u7b56\u7565\u5165\u573a\u4fe1\u53f7\uff1a\u767e\u5206\u4f4d\u226430%\u4e14Z\u2264-1.5\uff0c\u53ef\u5206\u6279\u5efa\u4ed3\u3002\u5efa\u8bae\u6301\u6709\u5468\u671f15-45\u5929\u3002"
        )
    # Exit zone: either condition triggers
    elif percentile >= EXIT_PERCENTILE_MIN or zscore >= EXIT_ZSCORE_MIN:
        trigger = []
        if percentile >= EXIT_PERCENTILE_MIN:
            trigger.append("百分位≥" + str(EXIT_PERCENTILE_MIN) + "%")
        if zscore >= EXIT_ZSCORE_MIN:
            trigger.append("Z≥+" + str(EXIT_ZSCORE_MIN))
        return (
            "exit",
            "\U0001f534 \u79bb\u573a\u533a",
            "策略离场信号：" + sep.join(trigger) + "，建议止盈减仓。不要追高，等待回调。"
        )
    # Hold zone: between entry and exit
    else:
        return (
            "hold",
            "\U0001f7e1 \u6301\u6709\u533a",
            "\u4ecb\u4e8e\u5165\u573a\u548c\u79bb\u573a\u4e4b\u95f4\uff0c\u4fdd\u6301\u73b0\u6709\u4ed3\u4f4d\uff0c\u4e0d\u6025\u4e8e\u65b0\u5f00\u4ed3\u3002\u7b49\u5f85\u8d85\u8dcc\u4fe1\u53f7\u6216\u6b62\u76c8\u4fe1\u53f7\u3002"
        )


# ============================================================
#  1. Position Intelligence
# ============================================================

def analyze_position(values: list, n: int = 90) -> PositionIntel:
    result = PositionIntel()
    if len(values) < 10:
        return result

    current = values[-1]
    result.current_value = current
    window = values[-n:] if len(values) >= n else values

    result.percentile_90d = _percentile(window, current)
    result.zscore_90d = _zscore(window, current)

    pct = result.percentile_90d
    z = result.zscore_90d

    # ---- Valuation Tier ----
    if pct <= 15 and z < -1.0:
        result.valuation_tier = "undervalued"
    elif pct >= 85 and z > 1.5:
        result.valuation_tier = "bubble"
    elif pct >= 70:
        result.valuation_tier = "overvalued"
    else:
        result.valuation_tier = "fair"

    # ---- Strategy Zone (from trading-strategies.md) ----
    zone, zone_label, zone_action = _strategy_zone(pct, z)
    result.strategy_zone = zone
    result.zone_label = zone_label
    result.zone_action = zone_action

    # ---- Short-term: Z-score reversal ----
    if z <= -2.0:
        result.short_term_signal = "dip_buy"
    elif z <= -1.0:
        result.short_term_signal = "dip_buy"
    elif z >= 2.0:
        result.short_term_signal = "top_sell"
    elif z >= 1.0:
        result.short_term_signal = "top_sell"
    else:
        result.short_term_signal = "hold"

    # ---- Mid-term: percentile zone ----
    if result.valuation_tier == "undervalued":
        result.mid_term_signal = "accumulate"
    elif result.valuation_tier in ("bubble",):
        result.mid_term_signal = "reduce"
    elif result.valuation_tier == "overvalued":
        result.mid_term_signal = "reduce"
    else:
        result.mid_term_signal = "hold"

    # ---- Long-term: percentile anchor ----
    if pct <= 25:
        result.long_term_signal = "build"
    elif pct >= 75:
        result.long_term_signal = "exit"
    else:
        result.long_term_signal = "hold"

    # ---- Support / Resistance ----
    if len(window) >= 10:
        sorted_w = sorted(window)
        p25 = sorted_w[max(0, int(len(window) * 0.25))]
        p75 = sorted_w[min(len(window)-1, int(len(window) * 0.75))]
        result.support_levels = sorted(set(
            ([round(min(window[-30:]), 2)] if len(window) >= 30 else []) +
            [round(p25, 2)]
        ))
        result.support_levels = [s for s in result.support_levels if s < current]
        result.resistance_levels = sorted(set(
            [round(p75, 2)] +
            ([round(max(window[-30:]), 2)] if len(window) >= 30 else [])
        ))
        result.resistance_levels = [r for r in result.resistance_levels if r > current]

    return result


# ============================================================
#  2. Probability Prediction
# ============================================================

def analyze_probability(values: list, zscore: float,
                         volatility: float, vol_regime: str) -> ProbPrediction:
    result = ProbPrediction()
    if len(values) < 5 or volatility <= 0:
        return result

    result.volatility_regime = vol_regime

    # ---- Base probability from Z-score (strategy-calibrated) ----
    if zscore < -2.5:
        base_prob = 85.0
    elif zscore < -2.0:
        base_prob = 75.0
    elif zscore < -1.5:
        base_prob = 68.0      # strategy entry threshold
    elif zscore < -0.5:
        base_prob = 55.0
    elif zscore < 0.5:
        base_prob = 50.0
    elif zscore < 1.5:
        base_prob = 45.0
    elif zscore < 2.0:
        base_prob = 32.0      # strategy exit threshold
    elif zscore < 2.5:
        base_prob = 25.0
    else:
        base_prob = 15.0

    # Volatility regime adjustment
    if vol_regime == "extreme":
        base_prob = base_prob * 0.4 + 50 * 0.6
    elif vol_regime == "elevated":
        base_prob = base_prob * 0.65 + 50 * 0.35

    # Time horizon
    result.prob_up_3d = round(base_prob, 0)
    result.prob_up_7d = round(base_prob + (50 - base_prob) * 0.12, 0)
    result.prob_up_30d = round(base_prob + (50 - base_prob) * 0.30, 0)
    result.prob_up_3d = max(5, min(95, result.prob_up_3d))
    result.prob_up_7d = max(5, min(95, result.prob_up_7d))
    result.prob_up_30d = max(5, min(95, result.prob_up_30d))

    avg_daily_move = volatility
    result.expected_return_3d = round(avg_daily_move * (result.prob_up_3d - 50) / 50 * 3, 2)
    result.expected_return_7d = round(avg_daily_move * (result.prob_up_7d - 50) / 50 * 7, 2)
    result.expected_return_30d = round(avg_daily_move * (result.prob_up_30d - 50) / 50 * 30, 2)

    recent = values[-90:] if len(values) >= 90 else values
    result.key_support = round(min(recent), 2)
    result.key_resistance = round(max(recent), 2)

    return result


# ============================================================
#  3. Cycle Analysis — STRATEGY ALIGNED
# ============================================================

def analyze_cycle(values: list, returns: list, volatility_14d: float,
                  mom_14d: float, mom_30d: float, vol_regime: str,
                  percentile: float, zscore: float) -> CycleAnalysis:
    """Cycle detection aligned with trading-strategies.md.
    
    Primary: percentile + Z-score
    Secondary: volatility + momentum as confirmation
    
    Strategy mapping:
      accumulation: percentile low, Z negative → 只买不卖
      consolidation: oscillating, no extreme → 卧倒持有
      markup: percentile rising, Z turning → 持有为主
      distribution: percentile high, Z positive → 只卖不买
    """
    result = CycleAnalysis()
    if len(values) < 14 or len(returns) < 14:
        result.phase = "unknown"
        result.phase_description = "\u6570\u636e\u4e0d\u8db3\uff0c\u65e0\u6cd5\u5224\u65ad\u5468\u671f"
        return result

    # Momentum consistency
    recent_returns = returns[-7:]
    up_days = sum(1 for r in recent_returns if r > 0.3)
    down_days = sum(1 for r in recent_returns if r < -0.3)
    mom_consistent = max(up_days, down_days) / 7 if recent_returns else 0

    # ---- Phase classification (percentile + Z primary) ----
    if percentile <= ENTRY_PERCENTILE_MAX and zscore <= -1.0:
        # Accumulation zone: cheap + depressed
        result.phase = "accumulation"
        conf = 0.80 if zscore <= ENTRY_ZSCORE_MAX else 0.65
        result.phase_description = (
            f"\u767e\u5206\u4f4d{percentile:.0f}%\uff0cZ={zscore:+.1f}"
            f"\u2014\u2014\u5438\u7b79\u671f\uff0c\u4ef7\u683c\u5904\u4e8e\u5386\u53f2\u4f4e\u4f4d\u3002"
            f"\u7b56\u7565\uff1a\u53ea\u4e70\u4e0d\u5356\u3001\u5206\u6279\u56e4\u8d27\u3001\u8010\u5fc3\u6301\u4ed3\u3002"
        )
        result.phase_strategy = "\U0001f4e5 \u53ea\u4e70\u4e0d\u5356\uff0c\u5206\u6279\u5efa\u4ed3"
        result.next_phase_trigger = "\u767e\u5206\u4f4d\u5347\u81f330-50%\u3001Z\u503c\u56de\u5347\u81f3-0.5\u4ee5\u4e0a\u65f6\u8fdb\u5165\u62c9\u5347\u671f"
        result.phase_confidence = conf

    elif percentile >= EXIT_PERCENTILE_MIN or zscore >= EXIT_ZSCORE_MIN:
        # Distribution zone: expensive + overbought
        result.phase = "distribution"
        conf = 0.80 if zscore >= EXIT_ZSCORE_MIN else 0.65
        trigger = []
        if percentile >= EXIT_PERCENTILE_MIN:
            trigger.append(f"\u767e\u5206\u4f4d{percentile:.0f}%\u2265{EXIT_PERCENTILE_MIN}%")
        if zscore >= EXIT_ZSCORE_MIN:
            trigger.append(f"Z={zscore:+.1f}\u2265+{EXIT_ZSCORE_MIN}")
        result.phase_description = (
            _SEP.join(trigger) +
            "——出货期，价格高位。" +
            "策略：只卖不买、空仓观望。"
        )
        result.phase_strategy = "\U0001f4e4 \u53ea\u5356\u4e0d\u4e70\uff0c\u6b62\u76c8\u79bb\u573a"
        result.next_phase_trigger = "\u767e\u5206\u4f4d\u56de\u843d\u81f350%\u4ee5\u4e0b\u65f6\u8fdb\u5165\u6d17\u76d8\u671f"
        result.phase_confidence = conf

    elif mom_14d > 2.0 and percentile < EXIT_PERCENTILE_MIN:
        # Markup: price rising but not yet at exit
        result.phase = "markup"
        result.phase_description = (
            f"\u767e\u5206\u4f4d{percentile:.0f}%\uff0c14\u65e5\u6da8\u5e45{mom_14d:+.1f}%"
            f"\u2014\u2014\u62c9\u5347\u671f\uff0c\u4ef7\u683c\u6b63\u5728\u56de\u5347\u3002"
            f"\u7b56\u7565\uff1a\u6301\u6709\u4e3a\u4e3b\u3001\u4e34\u8fd1\u9ad8\u4f4d\u51cf\u4ed3\uff08\u767e\u5206\u4f4d\u226565%\u65f6\uff09\u3002"
        )
        result.phase_strategy = "\U0001f4c8 \u6301\u6709\u4e3b\u52a8\uff0c\u4e34\u8fd1\u9ad8\u4f4d\u6b62\u76c8"
        result.next_phase_trigger = f"\u767e\u5206\u4f4d\u8fbe\u5230{EXIT_PERCENTILE_MIN}%\u6216Z\u8fbe\u5230+{EXIT_ZSCORE_MIN}\u65f6\u8fdb\u5165\u51fa\u8d27\u671f"
        result.phase_confidence = 0.60 if mom_14d > 4 else 0.50

    else:
        # Consolidation: no extreme signals
        result.phase = "consolidation"
        result.phase_description = (
            f"\u767e\u5206\u4f4d{percentile:.0f}%\uff0cZ={zscore:+.1f}"
            f"\u2014\u2014\u6d17\u76d8\u671f\uff0c\u9707\u8361\u53cd\u590d\u3002"
            f"\u7b56\u7565\uff1a\u4e0d\u52a0\u4ed3\u3001\u4e0d\u6b62\u635f\u3001\u6301\u6709\u5367\u5012\u3002"
        )
        result.phase_strategy = "\U0001f4ca \u4e0d\u52a0\u4ed3\u3001\u4e0d\u6b62\u635f\u3001\u5367\u5012\u6301\u6709"
        result.next_phase_trigger = "\u7a81\u7834\u9707\u8361\u533a\u95f4\u540e\u91cd\u65b0\u8bc4\u4f30\u65b9\u5411"
        result.phase_confidence = 0.35

    return result


# ============================================================
#  4. Value Score — STRATEGY ALIGNED
# ============================================================

def analyze_value_score(values: list, returns: list, percentile: float,
                         zscore: float, volatility: float, vol_regime: str,
                         phase: str, mom_7d: float, mom_30d: float) -> ValueScore:
    """Value score 1-10 — strategy proximity based.
    
    Core logic: closer to entry zone = higher score.
    """
    
    # ---- Entry Proximity Score (0-2.5) ----
    # How close to strategy entry conditions?
    # Ideal: percentile <= 30% AND Z <= -1.5
    pct_dist = max(0, (ENTRY_PERCENTILE_MAX - percentile) / ENTRY_PERCENTILE_MAX)
    z_dist = max(0, (ENTRY_ZSCORE_MAX - zscore) / abs(ENTRY_ZSCORE_MAX))
    entry_proximity = round((pct_dist * 0.5 + z_dist * 0.5) * 2.5, 2)
    entry_proximity = max(0.0, min(2.5, entry_proximity))

    # ---- Risk Score (0-2.5) ----
    recent = values[-90:] if len(values) >= 90 else values
    peak = max(recent)
    current = values[-1]
    drawdown = (peak - current) / peak * 100 if peak > 0 else 0

    if vol_regime == "calm" and drawdown < 3:
        risk_score = 2.5
    elif vol_regime == "calm" or (vol_regime == "normal" and drawdown < 5):
        risk_score = 2.0
    elif vol_regime == "normal" and drawdown < 10:
        risk_score = 1.5
    elif vol_regime == "elevated":
        risk_score = 0.8
    else:
        risk_score = 0.3

    # ---- Cycle Score (0-2.5): strategy phase alignment ----
    if phase == "accumulation":
        cycle_score = 2.5
    elif phase == "markup" and percentile < EXIT_PERCENTILE_MIN:
        cycle_score = 1.8
    elif phase == "consolidation":
        cycle_score = 1.2
    elif phase == "distribution":
        cycle_score = 0.3
    else:
        cycle_score = 1.0

    # ---- Sentiment Score (0-2.5): contrarian ----
    if zscore < -2.5:
        sentiment_score = 2.5
    elif zscore < -1.5:
        sentiment_score = 2.0
    elif zscore < -0.5:
        sentiment_score = 1.5
    elif zscore < 0.5:
        sentiment_score = 1.0
    elif zscore < 1.5:
        sentiment_score = 0.5
    elif zscore < 2.5:
        sentiment_score = 0.3
    else:
        sentiment_score = 0.0

    # ---- Total ----
    total = entry_proximity + risk_score + cycle_score + sentiment_score
    score = max(1, min(10, round(total)))

    # ---- Position Advice ----
    if phase == "accumulation" and score >= 6:
        position_advice = "\U0001f4e5 \u5206\u6279\u5efa\u4ed3\uff08\u5165\u573a\u533a + \u5438\u7b79\u671f\uff0c\u6309\u7b56\u7565\u5206\u6279\u4e70\u5165\uff09"
    elif phase == "accumulation":
        position_advice = "\U0001f4e5 \u8f7b\u4ed3\u8bd5\u63a2\uff08\u5165\u573a\u533a\u4f46\u8bc4\u5206\u504f\u4f4e\uff0c\u5148\u89c2\u671b\uff09"
    elif phase == "markup" and percentile < EXIT_PERCENTILE_MIN:
        position_advice = "\u2796 \u6301\u4ed3\u4e0d\u52a0\u4ed3\uff08\u62c9\u5347\u671f\uff0c\u6301\u6709\u4e3b\u52a8\uff0c\u4e34\u8fd1\u9ad8\u4f4d\u6b62\u76c8\uff09"
    elif phase == "consolidation":
        position_advice = "\U0001f4ca \u5367\u5012\u6301\u6709\uff08\u6d17\u76d8\u671f\uff0c\u4e0d\u52a0\u4ed3\u4e0d\u6b62\u635f\uff09"
    elif phase == "distribution":
        position_advice = "\U0001f6aa \u6b62\u76c8\u79bb\u573a\uff08\u51fa\u8d27\u671f\uff0c\u53ea\u5356\u4e0d\u4e70\uff09"
    else:
        position_advice = "\u2796 \u89c2\u671b\u7b49\u5f85"

    # ---- Recommendation ----
    if score >= 7:
        rec = "\u7efc\u5408\u6027\u4ef7\u6bd4\u4f18\u79c0\uff0c\u5f53\u524d\u4f4d\u7f6e\u9002\u5408\u79ef\u6781\u5e03\u5c40\u3002\u5efa\u8bae\u6301\u6709\u5468\u671f15-45\u5929\u3002"
    elif score >= 5:
        rec = "\u6027\u4ef7\u6bd4\u4e2d\u7b49\uff0c\u53ef\u9002\u5f53\u914d\u7f6e\uff0c\u63a7\u5236\u4ed3\u4f4d"
    elif score >= 3:
        rec = "\u6027\u4ef7\u6bd4\u504f\u4f4e\uff0c\u5efa\u8bae\u89c2\u671b\u7b49\u5f85\u66f4\u4f73\u65f6\u673a"
    else:
        rec = "\u6027\u4ef7\u6bd4\u5f88\u5dee\uff0c\u5efa\u8bae\u56de\u907f\u6216\u7b49\u5f85\u8c03\u6574"

    return ValueScore(
        score=score,
        entry_proximity=round(entry_proximity, 2),
        risk_score=round(risk_score, 2),
        cycle_score=round(cycle_score, 2),
        sentiment_score=round(sentiment_score, 2),
        position_advice=position_advice,
        recommendation=rec,
    )


# ============================================================
#  Main Entry Point
# ============================================================

def analyze_index(index_history: list) -> dict:
    if not index_history or len(index_history) < 5:
        return {"has_data": False}

    values = [v for _, v in index_history if v > 0]
    if len(values) < 5:
        return {"has_data": False}

    returns_list = _daily_returns(values)
    rolling_vols = _rolling_volatility(returns_list, 14)
    vol_14d = rolling_vols[-1] if rolling_vols else 0
    vol_regime = _volatility_regime(vol_14d)
    mom_7d = _momentum(values, 7)
    mom_14d = _momentum(values, 14)
    mom_30d = _momentum(values, min(30, len(values)-1))
    z = _zscore(values[-90:], values[-1])
    pct = _percentile(values[-90:], values[-1])

    position = analyze_position(values)
    probability = analyze_probability(values, z, vol_14d, vol_regime)
    cycle = analyze_cycle(values, returns_list, vol_14d, mom_14d, mom_30d, vol_regime, pct, z)
    value_score = analyze_value_score(
        values, returns_list, pct, z, vol_14d, vol_regime, cycle.phase, mom_7d, mom_30d
    )

    st_labels = {"dip_buy": "\U0001f4c8 \u8d85\u8dcc\u4e70\u5165", "hold": "\u2796 \u6301\u6709", "top_sell": "\U0001f4c9 \u9ad8\u4f4d\u5356\u51fa"}
    mt_labels = {"accumulate": "\U0001f4e5 \u5206\u6279\u5efa\u4ed3", "hold": "\u2796 \u6301\u6709", "reduce": "\U0001f4e4 \u9010\u6b65\u51cf\u4ed3"}
    lt_labels = {"build": "\U0001f3d7\ufe0f \u957f\u7ebf\u5e03\u5c40", "hold": "\u2796 \u6301\u6709", "exit": "\U0001f6aa \u9000\u51fa\u89c2\u671b"}

    return {
        "has_data": True,
        "position": {
            "current_value": position.current_value,
            "percentile_90d": position.percentile_90d,
            "zscore_90d": position.zscore_90d,
            "valuation_tier": position.valuation_tier,
            "tier_label": position.tier_label,
            "strategy_zone": position.strategy_zone,
            "zone_label": position.zone_label,
            "zone_action": position.zone_action,
            "short_term_signal": position.short_term_signal,
            "short_term_label": st_labels.get(position.short_term_signal, position.short_term_signal),
            "mid_term_signal": position.mid_term_signal,
            "mid_term_label": mt_labels.get(position.mid_term_signal, position.mid_term_signal),
            "long_term_signal": position.long_term_signal,
            "long_term_label": lt_labels.get(position.long_term_signal, position.long_term_signal),
            "support_levels": position.support_levels,
            "resistance_levels": position.resistance_levels,
        },
        "probability": {
            "prob_up_3d": probability.prob_up_3d,
            "prob_up_7d": probability.prob_up_7d,
            "prob_up_30d": probability.prob_up_30d,
            "expected_return_3d": probability.expected_return_3d,
            "expected_return_7d": probability.expected_return_7d,
            "expected_return_30d": probability.expected_return_30d,
            "key_support": probability.key_support,
            "key_resistance": probability.key_resistance,
            "volatility_regime": probability.volatility_regime,
        },
        "cycle": {
            "phase": cycle.phase,
            "phase_label": cycle.phase_label,
            "phase_confidence": cycle.phase_confidence,
            "phase_description": cycle.phase_description,
            "phase_strategy": cycle.phase_strategy,
            "next_phase_trigger": cycle.next_phase_trigger,
        },
        "value_score": {
            "score": value_score.score,
            "entry_proximity": value_score.entry_proximity,
            "risk_score": value_score.risk_score,
            "cycle_score": value_score.cycle_score,
            "sentiment_score": value_score.sentiment_score,
            "position_advice": value_score.position_advice,
            "recommendation": value_score.recommendation,
        },
    }




# ============================================================
#  Enhanced Cycle Detection with Probability Distribution
# ============================================================

def analyze_cycle_probability(prices, pct_90d, zscore_90d) -> dict:
    """Return 4-phase probability distribution (sums to 100%).

    Uses: percentile + Z-score + MA crossover + market breadth + greed sentiment.
    """
    from .market_macro import compute_breadth_score, compute_sentiment_score

    if not prices or len(prices) < 14:
        return {"accumulation": 25, "consolidation": 25, "markup": 25, "distribution": 25}

    # Short MAs
    n = len(prices)
    ma7 = sum(prices[-min(7, n):]) / min(7, n)
    ma30 = sum(prices[-min(30, n):]) / min(30, n)
    ma7_prev = sum(prices[-min(14, n):-min(7, n)]) / max(min(7, n-7), 1) if n >= 14 else ma7
    ma_cross_up = ma7 > ma30 and ma7_prev <= ma30

    breadth = compute_breadth_score(7)
    sentiment = compute_sentiment_score()

    # Score each phase independently (0-100)
    scores = {"accumulation": 0, "consolidation": 0, "markup": 0, "distribution": 0}

    # --- Accumulation signals ---
    if pct_90d <= 20:
        scores["accumulation"] += 35
    elif pct_90d <= 30:
        scores["accumulation"] += 25
    elif pct_90d <= 40:
        scores["accumulation"] += 15

    if zscore_90d <= -1.5:
        scores["accumulation"] += 25
    elif zscore_90d <= -0.5:
        scores["accumulation"] += 15

    if breadth <= 25:
        scores["accumulation"] += 20
    elif breadth <= 40:
        scores["accumulation"] += 10

    if sentiment >= 70:
        scores["accumulation"] += 20
    elif sentiment >= 55:
        scores["accumulation"] += 10

    # --- Consolidation signals ---
    if 20 <= pct_90d <= 60:
        scores["consolidation"] += 30
    elif 15 <= pct_90d <= 70:
        scores["consolidation"] += 20

    if -1.0 <= zscore_90d <= 1.0:
        scores["consolidation"] += 30
    elif -1.5 <= zscore_90d <= 1.5:
        scores["consolidation"] += 20

    if 30 <= breadth <= 60:
        scores["consolidation"] += 20
    elif 20 <= breadth <= 70:
        scores["consolidation"] += 10

    if 40 <= sentiment <= 60:
        scores["consolidation"] += 20

    # --- Markup signals ---
    if pct_90d >= 40 and ma_cross_up:
        scores["markup"] += 30
    elif ma_cross_up:
        scores["markup"] += 20
    elif ma7 > ma30:
        scores["markup"] += 15

    if zscore_90d >= 0.5 and ma7 > ma30:
        scores["markup"] += 20

    if breadth >= 65:
        scores["markup"] += 25
    elif breadth >= 50:
        scores["markup"] += 15

    if 20 <= pct_90d <= 70:
        scores["markup"] += 15

    # --- Distribution signals ---
    if pct_90d >= 70:
        scores["distribution"] += 35
    elif pct_90d >= 60:
        scores["distribution"] += 20

    if zscore_90d >= 1.5:
        scores["distribution"] += 25
    elif zscore_90d >= 0.5:
        scores["distribution"] += 15

    if ma7 < ma30 and pct_90d >= 50:
        scores["distribution"] += 20
    elif ma7 < ma30:
        scores["distribution"] += 10

    if sentiment <= 30:
        scores["distribution"] += 20
    elif sentiment <= 45:
        scores["distribution"] += 10

    # Softmax-like normalization
    import math
    total = sum(math.exp(s / 15) for s in scores.values())
    probs = {k: round(math.exp(v / 15) / total * 100, 1) for k, v in scores.items()}

    # Adjust to sum exactly 100
    diff = 100.0 - sum(probs.values())
    if diff != 0:
        max_k = max(probs, key=probs.get)
        probs[max_k] = round(probs[max_k] + diff, 1)

    return probs



# ============================================================
#  Integrated Probability Prediction (Z-score + macro modifiers)
# ============================================================

def analyze_probability_integrated(prices, pct_90d, zscore_90d,
                                     volatility_regime="normal") -> dict:
    """Enhanced probability prediction with macro modifiers.

    Base: Z-score mean-reversion probability.
    Modifiers: breadth, sentiment, online trend, position.
    """
    import statistics
    from .market_macro import (compute_breadth_score, compute_sentiment_score,
                                 compute_online_trend_score)

    if not prices or len(prices) < 5:
        return {"prob_up_3d": 50, "prob_up_7d": 50, "prob_up_30d": 50,
                "confidence": "low", "modifiers_applied": []}

    # Base: Z-score mean-reversion for 3 timeframes
    def _base_prob(z, horizon_days, vol_regime):
        mean_rev_strength = -z / 3.0
        base = 50 + mean_rev_strength * 15
        if vol_regime == "high_volatile":
            base = 50 + mean_rev_strength * 8
        elif vol_regime == "volatile":
            base = 50 + mean_rev_strength * 12
        factor = min(1.0, horizon_days / 10.0)
        base = 50 + (base - 50) * factor
        return max(5, min(95, base))

    prob3 = _base_prob(zscore_90d, 3, volatility_regime)
    prob7 = _base_prob(zscore_90d, 7, volatility_regime)
    prob30 = _base_prob(zscore_90d, 30, volatility_regime)

    # Macro modifiers
    modifiers = []
    breadth = compute_breadth_score(7)
    sentiment = compute_sentiment_score()
    online = compute_online_trend_score()

    # Breadth modifier: bearish breadth dampens upside, bullish amplifies
    if breadth <= 25:
        b_mod = 0.7
        modifiers.append("广度极弱 x0.7")
    elif breadth <= 40:
        b_mod = 0.85
        modifiers.append("广度偏弱 x0.85")
    elif breadth >= 75:
        b_mod = 1.15
        modifiers.append("广度强劲 x1.15")
    elif breadth >= 65:
        b_mod = 1.08
        modifiers.append("广度较好 x1.08")
    else:
        b_mod = 1.0

    # Sentiment modifier: extreme fear boosts upside (contrarian)
    if sentiment >= 80:
        s_mod = 1.15
        modifiers.append("极度恐惧(反转) x1.15")
    elif sentiment >= 70:
        s_mod = 1.08
        modifiers.append("恐惧(反转) x1.08")
    elif sentiment <= 20:
        s_mod = 0.85
        modifiers.append("极度贪婪(反转) x0.85")
    elif sentiment <= 35:
        s_mod = 0.92
        modifiers.append("贪婪(反转) x0.92")
    else:
        s_mod = 1.0

    # Online trend modifier
    if online <= 15:
        o_mod = 0.88
        modifiers.append("玩家骤降 x0.88")
    elif online <= 30:
        o_mod = 0.94
        modifiers.append("玩家下降 x0.94")
    elif online >= 75:
        o_mod = 1.10
        modifiers.append("玩家激增 x1.10")
    else:
        o_mod = 1.0

    # Position modifier: low percentile = stronger mean reversion
    if pct_90d <= 10:
        p_mod = 1.12
        modifiers.append("极度低估 x1.12")
    elif pct_90d <= 20:
        p_mod = 1.06
        modifiers.append("低估 x1.06")
    elif pct_90d >= 85:
        p_mod = 0.88
        modifiers.append("极度高估 x0.88")
    elif pct_90d >= 70:
        p_mod = 0.94
        modifiers.append("高估 x0.94")
    else:
        p_mod = 1.0

    total_mod = b_mod * s_mod * o_mod * p_mod
    prob3 = max(3, min(97, prob3 * total_mod))
    prob7 = max(3, min(97, prob7 * total_mod))
    prob30 = max(3, min(97, prob30 * total_mod))

    # Bearish macro cap: if breadth is very bearish AND players declining,
    # cap upside probability because mean-reversion logic breaks in downtrends
    bearish_score = 0
    if breadth <= 25:
        bearish_score += 2
    elif breadth <= 40:
        bearish_score += 1
    if online <= 30:
        bearish_score += 1
    if sentiment <= 40:
        bearish_score += 1  # greedy but not fearful = no contrarian boost

    if bearish_score >= 3:
        # Strong bearish: cap up-prob at 45%
        prob3 = min(prob3, 45)
        prob7 = min(prob7, 45)
        prob30 = min(prob30, 45)
        modifiers.append("熊市封顶 ≤45%")
    elif bearish_score >= 2:
        prob3 = min(prob3, 55)
        prob7 = min(prob7, 55)
        prob30 = min(prob30, 55)
        modifiers.append("熊市封顶 ≤55%")

    # Confidence: based on how extreme the modifiers are
    if abs(total_mod - 1.0) > 0.2:
        confidence = "high"
    elif abs(total_mod - 1.0) > 0.1:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "prob_up_3d": round(prob3, 1),
        "prob_up_7d": round(prob7, 1),
        "prob_up_30d": round(prob30, 1),
        "confidence": confidence,
        "modifiers_applied": modifiers,
        "base_probs": {
            "prob_up_3d": round(_base_prob(zscore_90d, 3, volatility_regime), 1),
            "prob_up_7d": round(_base_prob(zscore_90d, 7, volatility_regime), 1),
            "prob_up_30d": round(_base_prob(zscore_90d, 30, volatility_regime), 1),
        },
    }



# ============================================================
#  Bottom-Fishing Signal (pre-trend leading indicator)
# ============================================================

def compute_bottom_signal_wrapper(prices, pct_90d, zscore_90d) -> dict:
    """Wrapper that calls market_macro.compute_bottom_signal."""
    from .market_macro import compute_bottom_signal, bottom_signal_summary
    bs = compute_bottom_signal(pct_90d, zscore_90d, prices)
    return bottom_signal_summary(bs)

# ============================================================
#  Extended analysis with Market Trend Health + Fusion Decision
# ============================================================

def analyze_index_full(index_history: list) -> dict:
    """Enhanced index analysis with market trend health and fusion decision."""
    result = analyze_index(index_history)
    if not result.get("has_data"):
        return result

    values = [v for _, v in index_history if v > 0]
    if len(values) < 10:
        return result

    try:
        from .market_th import (
            compute_market_trend_health, market_th_summary,
            compute_market_fusion_decision, market_fd_summary,
        )

        # Compute daily volumes from K-line if available
        # For market index K-line from csQAQ, we approximate volumes from price changes
        volumes = None
        try:
            from .collector import fetch_index_kline
            kline = fetch_index_kline()
            if kline and len(kline) > 0:
                if hasattr(kline[0], 'volume'):
                    volumes = [k.volume for k in kline[-len(values):]]
                elif isinstance(kline[0], (list, tuple)) and len(kline[0]) >= 6:
                    volumes = [float(k[5]) for k in kline[-len(values):] if len(k) >= 6]
        except Exception:
            pass

        pct = result["position"]["percentile_90d"]
        z = result["position"]["zscore_90d"]
        cycle_phase = result.get("cycle", {}).get("phase", "unknown")

        mth = compute_market_trend_health(
            prices=values[-90:],
            volumes=volumes[-90:] if volumes else None,
            cycle_phase=cycle_phase,
        )

        mfd = compute_market_fusion_decision(
            percentile_90d=pct,
            th=mth,
            zscore_90d=z,
        )

        result["market_trend_health"] = market_th_summary(mth)
        result["market_fusion_decision"] = market_fd_summary(mfd)

        # --- New: enhanced analysis (v4) ---
        result["cycle_probability"] = analyze_cycle_probability(
            values[-90:], pct, z)

        # Derive unified cycle phase from probability distribution
        cp = result["cycle_probability"]
        max_phase = max(cp, key=cp.get)
        phase_labels = {
            "accumulation": ("accumulation", "📥 吸筹期", "分批建仓囤货，耐心持仓"),
            "consolidation": ("consolidation", "📊 洗盘期", "不加仓不止损，持有卧倒"),
            "markup": ("markup", "🚀 拉升期", "持有为主，临近高位减仓"),
            "distribution": ("distribution", "📉 出货期", "只卖不买，空仓观望"),
        }
        if max_phase in phase_labels:
            ph, pl, ps = phase_labels[max_phase]
            if "cycle" in result:
                result["cycle"]["phase"] = ph
                result["cycle"]["phase_label"] = pl
                result["cycle"]["phase_strategy"] = ps
                result["cycle"]["phase_confidence"] = round(cp[max_phase] / 100, 2)

        # Recompute value_score fields based on unified v4 cycle phase
        if "value_score" in result and max_phase in phase_labels:
            new_phase = max_phase
            vs = result["value_score"]
            pct_val = result["position"]["percentile_90d"]

            # Recompute cycle_score
            if new_phase == "accumulation":
                new_cycle_score = 2.5
            elif new_phase == "markup" and pct_val < EXIT_PERCENTILE_MIN:
                new_cycle_score = 1.8
            elif new_phase == "consolidation":
                new_cycle_score = 1.2
            elif new_phase == "distribution":
                new_cycle_score = 0.3
            else:
                new_cycle_score = 1.0

            # Recompute total score
            new_total = vs["entry_proximity"] + vs["risk_score"] + new_cycle_score + vs["sentiment_score"]
            new_score = max(1, min(10, round(new_total)))

            # Update position_advice
            if new_phase == "accumulation" and new_score >= 6:
                new_advice = "\U0001f4e5 \u5206\u6279\u5efa\u4ed3\uff08\u5165\u573a\u533a + \u5438\u7b79\u671f\uff0c\u6309\u7b56\u7565\u5206\u6279\u4e70\u5165\uff09"
            elif new_phase == "accumulation":
                new_advice = "\U0001f4e5 \u8f7b\u4ed3\u8bd5\u63a2\uff08\u5165\u573a\u533a\u4f46\u8bc4\u5206\u504f\u4f4e\uff0c\u5148\u89c2\u671b\uff09"
            elif new_phase == "markup" and pct_val < EXIT_PERCENTILE_MIN:
                new_advice = "\u2796 \u6301\u4ed3\u4e0d\u52a0\u4ed3\uff08\u62c9\u5347\u671f\uff0c\u6301\u6709\u4e3b\u52a8\uff0c\u4e34\u8fd1\u9ad8\u4f4d\u6b62\u76c8\uff09"
            elif new_phase == "consolidation":
                new_advice = "\U0001f4ca \u5367\u5012\u6301\u6709\uff08\u6d17\u76d8\u671f\uff0c\u4e0d\u52a0\u4ed3\u4e0d\u6b62\u635f\uff09"
            elif new_phase == "distribution":
                new_advice = "\U0001f6aa \u6b62\u76c8\u79bb\u573a\uff08\u51fa\u8d27\u671f\uff0c\u53ea\u5356\u4e0d\u4e70\uff09"
            else:
                new_advice = "\u2796 \u89c2\u671b\u7b49\u5f85"

            # Update recommendation
            if new_score >= 7:
                new_rec = "\u7efc\u5408\u6027\u4ef7\u6bd4\u4f18\u79c0\uff0c\u5f53\u524d\u4f4d\u7f6e\u9002\u5408\u79ef\u6781\u5e03\u5c40\u3002\u5efa\u8bae\u6301\u6709\u5468\u671f15-45\u5929\u3002"
            elif new_score >= 5:
                new_rec = "\u6027\u4ef7\u6bd4\u4e2d\u7b49\uff0c\u53ef\u9002\u5f53\u914d\u7f6e\uff0c\u63a7\u5236\u4ed3\u4f4d"
            elif new_score >= 3:
                new_rec = "\u6027\u4ef7\u6bd4\u504f\u4f4e\uff0c\u5efa\u8bae\u89c2\u671b\u7b49\u5f85\u66f4\u4f73\u65f6\u673a"
            else:
                new_rec = "\u6027\u4ef7\u6bd4\u5f88\u5dee\uff0c\u5efa\u8bae\u56de\u907f\u6216\u7b49\u5f85\u8c03\u6574"

            vs["cycle_score"] = round(new_cycle_score, 2)
            vs["score"] = new_score
            vs["position_advice"] = new_advice
            vs["recommendation"] = new_rec

        result["probability_integrated"] = analyze_probability_integrated(
            values[-90:], pct, z,
            volatility_regime=result.get("probability", {}).get("volatility_regime", "normal"))
        # Overwrite old probability prob_up values with integrated (bearish-capped) values
        pi = result["probability_integrated"]
        if "probability" in result:
            result["probability"]["prob_up_3d"] = pi["prob_up_3d"]
            result["probability"]["prob_up_7d"] = pi["prob_up_7d"]
            result["probability"]["prob_up_30d"] = pi["prob_up_30d"]
            result["probability"]["prob_confidence"] = pi.get("confidence", "low")
            result["probability"]["prob_modifiers"] = pi.get("modifiers_applied", [])

        result["bottom_signal"] = compute_bottom_signal_wrapper(
            values[-90:], pct, z)

        # --- Macro context ---
        try:
            from .market_macro import (
                compute_breadth_score, breadth_label,
                compute_sentiment_score, sentiment_label, get_greedy_current,
                compute_online_trend_score, online_label, get_online_current,
                compute_card_trend_score, card_label,
            )
            result["macro_context"] = {
                "breadth_7d": compute_breadth_score(7),
                "breadth_7d_label": breadth_label(compute_breadth_score(7)),
                "breadth_90d": compute_breadth_score(90),
                "breadth_90d_label": breadth_label(compute_breadth_score(90)),
                "sentiment_score": compute_sentiment_score(),
                "sentiment_label": sentiment_label(compute_sentiment_score()),
                "greedy_current": get_greedy_current(),
                "online_score": compute_online_trend_score(),
                "online_label": online_label(compute_online_trend_score()),
                "online_current": get_online_current(),
                "card_score": compute_card_trend_score(),
                "card_label": card_label(compute_card_trend_score()),
            }
        except Exception:
            pass

    except Exception:
        import traceback
        traceback.print_exc()

    return result
