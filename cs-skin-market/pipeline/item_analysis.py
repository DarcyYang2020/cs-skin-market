"""
Single-item investment analysis engine --- CS2 skin specific.
Unifies: percentile/Z-score, cycle detection, liquidity scoring,
value scoring, probability prediction, and whale manipulation detection.

All statistical windows default to 90 days.
"""

import statistics
import math
from .trend_health import compute_trend_health, trend_health_summary, compute_fusion_decision, fusion_decision_summary
from .valuation import compute_valuation_grid, valuation_grid_summary
from .supply import analyze_supply, supply_summary
from .market_context import build_market_context, context_summary
from .market_macro import compute_sentiment_factor, compute_sentiment_score, event_risk_coefficient
from .config import ITEM_EXIT_RULES
from .config import ITEM_EXPECTANCY_STATS
from .index_analysis import compute_micro_th
from dataclasses import dataclass, field

# ============================================================
# Strategy Constants
# ============================================================
ENTRY_PERCENTILE_MAX = 30
ENTRY_ZSCORE_MAX = -1.5
EXIT_PERCENTILE_MIN = 65
EXIT_ZSCORE_MIN = 2.0

# ============================================================
# Strategy Constants
# ============================================================
ENTRY_PERCENTILE_MAX = 30
ENTRY_ZSCORE_MAX = -1.5
EXIT_PERCENTILE_MIN = 65
EXIT_ZSCORE_MIN = 2.0


# ============================================================
# Data Classes
# ============================================================

@dataclass
class ItemPositionIntel:
    """90-day percentile + Z-score valuation."""
    current_price: float = 0.0
    percentile_90d: float = 50.0
    zscore_90d: float = 0.0
    valuation_tier: str = "fair"       # undervalued / fair / overvalued / bubble
    tier_label: str = ""
    high_90d: float = 0.0
    low_90d: float = 0.0
    mean_90d: float = 0.0
    median_90d: float = 0.0
    data_points: int = 0
    decayed_pct_90d: float = 50.0
    valuation_slope: float = 0.0
    valuation_trend: str = "数据不足"

    def __post_init__(self):
        if self.percentile_90d <= 30:
            self.valuation_tier = "undervalued"
            self.tier_label = "低位低估"
        elif self.percentile_90d <= 70:
            self.valuation_tier = "fair"
            self.tier_label = "中性震荡"
        elif self.percentile_90d <= 90:
            self.valuation_tier = "overvalued"
            self.tier_label = "高估"
        else:
            self.valuation_tier = "bubble"
            self.tier_label = "泡沫高危"


@dataclass
class CycleAnalysis:
    """Four-phase cycle detection."""
    phase: str = "unknown"             # accumulation / consolidation / markup / distribution
    phase_label: str = ""
    phase_confidence: float = 0.0
    phase_description: str = ""
    phase_strategy: str = ""
    next_phase_trigger: str = ""


@dataclass
class LiquidityScore:
    """0-100 liquidity assessment."""
    score: int = 50
    level: str = "normal"              # excellent / good / normal / poor / critical
    level_label: str = ""
    risk_warning: str = ""
    breakdown: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.score >= 85:
            self.level = "excellent"
            self.level_label = "✅ 极佳"
        elif self.score >= 70:
            self.level = "good"
            self.level_label = "✅ 良好"
        elif self.score >= 50:
            self.level = "normal"
            self.level_label = "➖ 一般"
        elif self.score >= 30:
            self.level = "poor"
            self.level_label = "⚠️ 较差"
        else:
            self.level = "critical"
            self.level_label = "🔴 极差"
        if self.score < 70:
            self.risk_warning = "⚠️ 出货困难，谨慎持仓"


@dataclass
class ProbPrediction:
    """Probability prediction based on Z-score mean-reversion."""
    prob_up_3d: float = 50.0
    prob_up_7d: float = 50.0
    prob_up_30d: float = 50.0
    prob_range_3d: float = 30.0
    prob_range_7d: float = 30.0
    prob_range_30d: float = 30.0
    prob_down_3d: float = 20.0
    prob_down_7d: float = 20.0
    prob_down_30d: float = 20.0
    expected_return_3d: float = 0.0
    expected_return_7d: float = 0.0
    expected_return_30d: float = 0.0
    key_support: float = 0.0
    key_resistance: float = 0.0
    volatility_regime: str = "normal"


@dataclass
class ValueScore:
    """1-10 investment value score."""
    score: float = 5.0
    grade: str = "C"
    position_advice: str = ""
    recommendation: str = ""
    breakdown: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.score >= 8:
            self.grade = "S"
        elif self.score >= 6.5:
            self.grade = "A"
        elif self.score >= 4.5:
            self.grade = "B"
        else:
            self.grade = "C"


@dataclass
class WhaleDetection:
    """Whale/manipulation detection — four-factor weighted model."""
    probability: float = 0.0           # 0-100
    level: str = "natural"             # natural / weak_whale / strong_whale / extreme_whale
    level_label: str = ""
    volume_divergence_score: float = 0.0   # /40
    volatility_anomaly_score: float = 0.0  # /25
    position_lock_score: float = 0.0       # /20
    correlation_anomaly_score: float = 0.0 # /15
    anomaly_flags: list = field(default_factory=list)
    trading_rule: str = ""

    def __post_init__(self):
        if self.probability <= 12:
            self.level = "natural"
            self.level_label = "🌊 自然散户行情"
            self.trading_rule = "常规策略有效，可按百分位/Z-score正常操作"
        elif self.probability <= 30:
            self.level = "weak_whale"
            self.level_label = "🐋 弱控盘/资金抱团"
            self.trading_rule = "不做逆势单，跟随趋势，止盈收紧，不长期持仓"
        elif self.probability <= 55:
            self.level = "strong_whale"
            self.level_label = "🔴 强庄控盘"
            self.trading_rule = "禁止使用常规百分位/Z-score抄底策略，常规低估判定完全失效"
        else:
            self.level = "extreme_whale"
            self.level_label = "💀 高度庄盘/资金盘"
            self.trading_rule = "完全人为走势，随时暴力砸盘出货，高危避雷，禁止任何买入操作"


class AuxFactors:
    """Auxiliary volume-price factors."""
    mean_price_90d: float = 0.0
    mean_volume_7d: float = 0.0
    turnover_rate: float = 0.0           # 换手率 (daily vol / total supply %)
    ma_deviation: float = 0.0            # 均线乖离率 (price / ma30 - 1) * 100
    vol_flow_slope: float = 0.0          # 资金流入流出斜率


@dataclass
class ItemAnalysisResult:
    """Complete single-item analysis result."""
    name: str = ""
    price_rmb: float = 0.0
    volume_day: int = 0
    volume_total: int = 0
    trend: str = ""
    position: ItemPositionIntel = field(default_factory=ItemPositionIntel)
    aux: AuxFactors = field(default_factory=AuxFactors)
    cycle: CycleAnalysis = field(default_factory=CycleAnalysis)
    liquidity: LiquidityScore = field(default_factory=LiquidityScore)
    # ---- Supply analysis / Event risk ----
    supply_analysis: dict = field(default_factory=dict)

    # ---- Market Context ----
    market_context: dict = field(default_factory=dict)
    corr_label: str = ""
    probability: ProbPrediction = field(default_factory=ProbPrediction)
    conflicts: list = field(default_factory=list)
    decision_certainty: str = "medium"
    value: ValueScore = field(default_factory=ValueScore)
    whale: WhaleDetection = field(default_factory=WhaleDetection)
    data_quality: str = "low"
    trend_health: dict = field(default_factory=dict)
    fusion_decision: dict = field(default_factory=dict)
    price_zones: dict = field(default_factory=dict)
    valuation_grid: dict = field(default_factory=dict)
    risk_level: str = "C"
    risk_label: str = ""
    bid_support: dict = field(default_factory=dict)
    buy_distance: dict = field(default_factory=dict)


# ============================================================
#  Helper: Position / Percentile (90-day only)
# ============================================================

def _analyze_position(prices):
    """Compute 90-day percentile + Z-score position."""
    pos = ItemPositionIntel()
    if not prices or len(prices) < 5:
        return pos

    current = prices[-1]
    n = len(prices)
    window = prices[-min(90, n):]

    pos.current_price = current
    pos.data_points = len(window)

    # Percentile
    below = sum(1 for p in window if p < current)
    pos.percentile_90d = round(below / len(window) * 100, 1)

    # MAD-based Z-score (unified with index_analysis)
    if len(window) >= 3:
        med = statistics.median(window)
        mad = statistics.median([abs(v - med) for v in window])
        if mad > 0:
            pos.zscore_90d = round((current - med) / (mad * 1.4826), 2)

    pos.high_90d = round(max(window), 2)
    pos.low_90d  = round(min(window), 2)
    pos.mean_90d = round(statistics.mean(window), 2)
    pos.median_90d = round(statistics.median(window), 2)

    # --- Time-decay weighted percentile (心理锚点修正) ---
    tw = len(window)
    if tw >= 7:
        weights = []
        for j in range(tw):
            age = tw - 1 - j
            if age < 7:
                weights.append(3.0)
            elif age < 30:
                weights.append(2.0)
            else:
                weights.append(1.0)
        total_w = sum(weights)
        # Compute weighted percentile: sum of weights for prices below current
        weighted_below = sum(w for w, p in zip(weights, window) if p < current)
        pos.decayed_pct_90d = round(weighted_below / total_w * 100, 1)
    else:
        pos.decayed_pct_90d = pos.percentile_90d

    # --- Valuation slope: 14-day percentile change rate ---
    if len(window) >= 14:
        older_pct = sum(1 for p in window[:-14] if p < current) / (len(window) - 14) * 100 if len(window) > 14 else 50
        pos.valuation_slope = round(pos.percentile_90d - older_pct, 1)
        if pos.valuation_slope > 15:
            pos.valuation_trend = "估值持续抬升"
        elif pos.valuation_slope < -15:
            pos.valuation_trend = "估值持续回落"
        else:
            pos.valuation_trend = "估值震荡"
    else:
        pos.valuation_slope = 0.0
        pos.valuation_trend = "数据不足"

# Re-compute tier_label (post_init ran with default 50.0)
    if pos.percentile_90d <= 30:
        pos.valuation_tier = 'undervalued'
        pos.tier_label = '低位低估'
    elif pos.percentile_90d <= 70:
        pos.valuation_tier = 'fair'
        pos.tier_label = '中性震荡'
    elif pos.percentile_90d <= 90:
        pos.valuation_tier = 'overvalued'
        pos.tier_label = '高估'
    else:
        pos.valuation_tier = 'bubble'
        pos.tier_label = '泡沫高危'

    return pos


# ============================================================
#  Helper: Cycle Detection (4-phase)
# ============================================================

def _analyze_cycle(prices, volumes=None, sentiment_factor=0.0):
    """Four-phase market cycle detection."""
    cyc = CycleAnalysis()
    n = len(prices)
    if n < 15:
        cyc.phase = "unknown"
        cyc.phase_label = "数据不足"
        cyc.phase_confidence = 0.0
        return cyc

    # Compute percentiles for recent vs mid window
    current = prices[-1]
    window_90 = prices[-min(90, n):]
    mid_start = max(0, len(window_90) // 2)

    # Use simple trend indicators
    ma7  = sum(prices[-min(7, n):]) / min(7, n)
    ma30 = sum(prices[-min(30, n):]) / min(30, n)

    pct_current = sum(1 for p in window_90 if p < current) / len(window_90) * 100

    # Recent 14-day momentum
    recent_chg = (prices[-1] / prices[-min(15, n)] - 1) * 100 if n >= 15 else 0

    # Compute deviation for mild pullback detection
    ma_dev = abs(ma7 / ma30 - 1) * 100 if ma30 > 0 else 100

    if ma7 > ma30 * 1.05 and pct_current > 65:
        cyc.phase = "markup"
        cyc.phase_label = "强势拉升期"
        cyc.phase_description = "价格高位 + 短期均线强势上行，拉升阶段"
        cyc.phase_strategy = "持有为主，逐步止盈"
        cyc.phase_confidence = min(80, 50 + pct_current * 0.3)
        cyc.next_phase_trigger = "百分位跌破50%或均线死叉"
    elif ma7 > ma30 and pct_current < 30:
        cyc.phase = "accumulation"
        cyc.phase_label = "吸筹期"
        cyc.phase_description = "低位 + 短期均线上穿，资金可能吸筹"
        cyc.phase_strategy = "分批建仓，耐心持仓"
        cyc.phase_confidence = min(80, 50 + (30 - pct_current) * 1.5)
        cyc.next_phase_trigger = "百分位突码50%进入拉升"
    elif ma7 > ma30 and 30 <= pct_current <= 65:
        cyc.phase = "markup"
        cyc.phase_label = "拉升期"
        cyc.phase_label = "拉升期"
        cyc.phase_description = "价格在合理区间持续上行"
        cyc.phase_strategy = "持有为主，临近高位减仓"
        cyc.phase_confidence = 60
        cyc.next_phase_trigger = "百分位突破65%进入出货"
    elif ma7 < ma30 and pct_current > 70 and ma_dev > 3:
        # Significant pullback at high percentile: true distribution risk
        cyc.phase = "distribution"
        cyc.phase_label = "出货期"
        cyc.phase_description = "短期明显走弱，高位回落风险"
        cyc.phase_strategy = "逐步减仓"
        cyc.phase_confidence = 60
    elif ma7 < ma30 and pct_current > 50 and ma_dev <= 3:
        # Mild pullback at moderate-high percentile: likely healthy consolidation
        cyc.phase = "consolidation"
        cyc.phase_label = "洗盘/换手期"
        cyc.phase_description = "小幅回调整理，可能为健康换手"
        cyc.phase_strategy = "持有观察，关注MA30支撑"
        cyc.phase_confidence = 50
        cyc.next_phase_trigger = "MA7重新上穿MA30确认继续拉升"
    elif ma7 < ma30 and pct_current > 70:
        # High percentile + pullback (but deviation < 3% already handled)
        cyc.phase = "distribution"
        cyc.phase_label = "出货期"
        cyc.phase_description = "高位回落，注意风险"
        cyc.phase_strategy = "逐步减仓"
        cyc.phase_confidence = 55
    elif ma7 < ma30 and pct_current <= 50:
        cyc.phase = "consolidation"
        cyc.phase_label = "洗盘期"
        cyc.phase_description = "价格震荡整理，方向不明"
        cyc.phase_strategy = "不加仓不止损，持有卧倒"
        cyc.phase_confidence = 50
        cyc.next_phase_trigger = "放量突破MA30确认方向"
    else:
        cyc.phase = "consolidation"
        cyc.phase_label = "洗盘期"
        cyc.phase_description = "震荡整理中"
        cyc.phase_strategy = "保持观望"
        cyc.phase_confidence = 45

    # Sentiment-based confidence adjustment: fear → accumulation confidence up
    if sentiment_factor != 0.0:
        if cyc.phase == "accumulation":
            cyc.phase_confidence = min(90, cyc.phase_confidence + sentiment_factor * 10)
        elif cyc.phase == "distribution":
            cyc.phase_confidence = min(90, cyc.phase_confidence - sentiment_factor * 10)
        elif cyc.phase == "consolidation":
            cyc.phase_confidence = min(90, cyc.phase_confidence + sentiment_factor * 5)

    # --- Volume confirmation for markup phase ---
    if cyc.phase == "markup" and volumes and sum(1 for v in volumes if v and v > 0) >= 20:
        avg_vol_5d = sum(volumes[-5:]) / 5
        avg_vol_20d = sum(volumes[-20:]) / 20
        if avg_vol_5d < avg_vol_20d * 0.7:
            cyc.phase = "consolidation"
            cyc.phase_label = "无量拉升·警惕"
            cyc.phase_description = "价格上涨但成交量萎缩，可能是庄家对倒或散户跟风不足"
            cyc.phase_strategy = "不建议追涨，已有持仓可分批止盈"
            cyc.phase_confidence = 40

    # --- MA90 filter: no markup/distribution if below MA90 ---
    if n >= 90:
        ma90 = sum(prices[-90:]) / 90
        if ma90 > 0 and prices[-1] < ma90 * 0.97:
            if cyc.phase in ("markup", "distribution"):
                cyc.phase = "consolidation"
                cyc.phase_label = "修复反弹(MA90压制)"
                cyc.phase_description = "短期走强但价格长期受MA90压制，可能只是超跌反弹"
                cyc.phase_strategy = "谨慎参与，设好止损"
                cyc.phase_confidence = 35
                cyc.next_phase_trigger = "放量突破MA90确认趋势反转"

    # --- Duration estimation (consecutive days in current phase state) ---
    if n >= 20:
        # Count days since most recent MA7/MA30 cross
        cross_days = 0
        for i in range(n-1, max(0, n-90), -1):
            ma7_i = sum(prices[max(0,i-6):i+1]) / min(7, i+1)
            ma30_i = sum(prices[max(0,i-29):i+1]) / min(30, i+1)
            ma7_prev = sum(prices[max(0,i-7):i]) / min(7, i)
            ma30_prev = sum(prices[max(0,i-30):i]) / min(30, i)
            if (ma7_i > ma30_i) != (ma7_prev > ma30_prev):
                break
            cross_days += 1
        cyc.next_phase_trigger = (cyc.next_phase_trigger or "") + f" | 已持续{cross_days}天"

    return cyc


# ============================================================
#  Helper: Liquidity Score (0-100)
# ============================================================

def score_liquidity(prices, volumes, volume_total):
    """Score liquidity 0-100 based on volume, spread, and supply depth."""
    liq = LiquidityScore()
    liq.breakdown = {}

    # Volume score (40%): 相对量能——当日/7日均量 vs 30日真实量基准
    vol_day = volume_total // 20 if volume_total > 0 else 1  # rough daily estimate
    if volumes and len(volumes) >= 7:
        vol_day = max(1, sum(volumes[-7:]) // 7)

    # 相对量基准：近 30 日真实成交量均值；真实量不足时用近 7 日均值兜底
    vol_base = 0
    recent7 = [v for v in volumes[-7:] if v and v > 0] if volumes else []
    recent30 = [v for v in volumes[-30:] if v and v > 0] if volumes else []
    if len(recent30) >= 20:
        vol_base = statistics.mean(recent30)
    elif len(recent7) >= 3:
        vol_base = statistics.mean(recent7)

    if vol_base > 0:
        vol_ratio = vol_day / vol_base
        if vol_ratio >= 3:
            vol_score = 20
        elif vol_ratio >= 2:
            vol_score = 16
        elif vol_ratio >= 1.5:
            vol_score = 12
        elif vol_ratio >= 1:
            vol_score = 8
        elif vol_ratio >= 0.5:
            vol_score = 4
        else:
            vol_score = 1
    else:
        # 无历史真实量：绝对量兜底（低频市场，不参与相对判定）
        if vol_day >= 100:
            vol_score = 20
        elif vol_day >= 30:
            vol_score = 16
        elif vol_day >= 10:
            vol_score = 12
        elif vol_day >= 3:
            vol_score = 8
        elif vol_day >= 1:
            vol_score = 4
        else:
            vol_score = 1
    liq.breakdown["volume"] = vol_score

    # Supply depth score (30%)
    if volume_total >= 500:
        supply_score = 30
    elif volume_total >= 200:
        supply_score = 24
    elif volume_total >= 100:
        supply_score = 20
    elif volume_total >= 50:
        supply_score = 15
    elif volume_total >= 10:
        supply_score = 8
    else:
        supply_score = 3
    liq.breakdown["supply"] = supply_score

    # Stability score (30%) - price volatility
    if prices and len(prices) >= 10:
        rets = []
        for i in range(1, min(len(prices), 30)):
            if prices[-i-1] > 0:
                rets.append(abs(prices[-i] / prices[-i-1] - 1) * 100)
        if rets:
            avg_vol = statistics.mean(rets)
            if avg_vol < 1:
                stab_score = 30
            elif avg_vol < 2:
                stab_score = 25
            elif avg_vol < 4:
                stab_score = 18
            elif avg_vol < 7:
                stab_score = 10
            else:
                stab_score = 4
            liq.breakdown["stability"] = stab_score
        else:
            stab_score = 15
            liq.breakdown["stability"] = stab_score
    else:
        stab_score = 15
        liq.breakdown["stability"] = stab_score

    liq.score = min(100, int(vol_score + supply_score + stab_score))

    # Level label via __post_init__ handles this
    return liq


# ============================================================
#  Helper: Probability Prediction (Z-score mean-reversion)
# ============================================================

def analyze_probability(prices, trend_score=None, whale_prob=0, cycle_phase="unknown", market_pct=50, sentiment_factor=0.0):
    """Probability of price direction 3d/7d/30d based on Z-score reversion."""
    prob = ProbPrediction()
    if not prices or len(prices) < 5:
        return prob

    n = len(prices)
    window = prices[-min(90, n):]
    current = prices[-1]

    if len(window) < 5:
        return prob

    mean = statistics.mean(window)
    std = statistics.stdev(window) if len(window) >= 3 else 1.0
    z = (current - mean) / std if std > 0 else 0

    # Base probability: Z < -2 -> 70% up bias, Z > +2 -> 70% down bias
    base_up = 50.0 - z * 10.0
    base_up = max(15, min(85, base_up))

    # Decay with trend_score: if TH < 30, up probability cut in half
    if trend_score is not None and trend_score < 30:
        base_up = base_up * 0.5 + (100 - base_up) * 0.5  # pull toward 50

    # Expected return based on Z-score mean reversion
    exp_ret = -z * 3.0  # rough: Z=-2 -> +6% expected return

    # Timeframe adjustments
    prob.prob_up_3d  = round(base_up * 1.05, 1)
    prob.prob_up_7d  = round(base_up * 1.10, 1)
    prob.prob_up_30d = round(base_up * 1.15, 1)

    prob.prob_down_3d  = round(100 - prob.prob_up_3d, 1)
    prob.prob_down_7d  = round(100 - prob.prob_up_7d, 1)
    prob.prob_down_30d = round(100 - prob.prob_up_30d, 1)

    prob.prob_range_3d  = round(abs(z) * 5, 1)
    prob.prob_range_7d  = round(abs(z) * 8, 1)
    prob.prob_range_30d = round(abs(z) * 15, 1)

    prob.expected_return_3d  = round(exp_ret * 0.3, 2)
    prob.expected_return_7d  = round(exp_ret * 0.6, 2)
    prob.expected_return_30d = round(exp_ret, 2)

    # Volatility regime
    rets = []
    for i in range(1, len(window)):
        if window[i-1] > 0:
            rets.append(abs(window[i] / window[i-1] - 1) * 100)
    avg_vol = sum(rets) / len(rets) if rets else 1
    if avg_vol > 5:
        prob.volatility_regime = "high_volatile"
    elif avg_vol > 2.5:
        prob.volatility_regime = "volatile"
    elif avg_vol < 0.8:
        prob.volatility_regime = "stable"
    else:
        prob.volatility_regime = "normal"

    # Key levels
    # --- Multi-feature probability correction ---
    # Base weight: Z-score 40%, TH 20%, whale 20%, cycle 10%, market 10%
    if trend_score is not None:
        th_bias = (trend_score - 50) / 50 * 15  # TH 0-100 -> -15 to +15 bias
        base_up = base_up + th_bias * 0.20

    if whale_prob > 30:
        base_up = base_up - (whale_prob - 30) * 0.15  # whale reduces up confidence

    if cycle_phase == "distribution":
        base_up = base_up * 0.90
    elif cycle_phase == "accumulation":
        base_up = base_up * 1.10

    if market_pct > 80:
        base_up = base_up * 0.95
    elif market_pct < 20:
        base_up = base_up * 1.05

    base_up = max(10, min(90, base_up))

    # --- Confidence label ---
    avg_vol_regime = prob.volatility_regime
    data_quality = "high" if n >= 60 else ("medium" if n >= 20 else "low")
    if avg_vol_regime in ("high_volatile", "volatile") or data_quality == "low":
        confidence = "low"
    elif avg_vol_regime == "normal" and data_quality == "high":
        confidence = "high"
    else:
        confidence = "medium"

    prob.prob_up_3d  = round(base_up * 1.05, 1)
    prob.prob_up_7d  = round(base_up * 1.10, 1)
    prob.prob_up_30d = round(base_up * 1.15, 1)
    prob.prob_down_3d  = round(100 - prob.prob_up_3d, 1)
    prob.prob_down_7d  = round(100 - prob.prob_up_7d, 1)
    prob.prob_down_30d = round(100 - prob.prob_up_30d, 1)

    # --- Enhanced support/resistance with MA levels ---
    ma30 = sum(window[-min(30, len(window)):]) / min(30, len(window)) if len(window) >= 10 else current
    ma90 = sum(window) / len(window) if len(window) >= 30 else current
    prob.key_support    = round(max(min(current * 0.85, mean - 2 * std), ma90 * 0.95), 2) if std > 0 else round(current * 0.88, 2)
    prob.key_resistance  = round(min(max(current * 1.15, mean + 2 * std), current * 1.35), 2) if std > 0 else round(current * 1.12, 2)

    return prob


# ============================================================
#  Helper: Value Score (1-10)
# ============================================================

def compute_value_score(position, cycle, liquidity, probability):
    """Compute 1-10 investment value score."""
    val = ValueScore()
    val.breakdown = {}

    # Position score (40%): lower percentile = better value
    pct = position.percentile_90d
    if pct <= 15:
        pos_score = 4.0
    elif pct <= 30:
        pos_score = 3.0
    elif pct <= 50:
        pos_score = 2.5
    elif pct <= 70:
        pos_score = 1.5
    elif pct <= 85:
        pos_score = 1.0
    else:
        pos_score = 0.5
    val.breakdown["position"] = round(pos_score, 1)

    # Cycle score (25%): accumulation > markup > consolidation > distribution
    if cycle.phase == "accumulation":
        cyc_score = 2.5
    elif cycle.phase == "markup":
        cyc_score = 2.0
    elif cycle.phase == "consolidation":
        cyc_score = 1.2
    elif cycle.phase == "distribution":
        cyc_score = 0.5
    else:
        cyc_score = 1.0
    val.breakdown["cycle"] = round(cyc_score, 1)

    # Liquidity score (15%) ? reduced from 20%, volume data has limited accuracy
    liq_norm = liquidity.score / 100 * 1.5
    val.breakdown["liquidity"] = round(liq_norm, 1)

    # Probability score (20%) ? increased from 15% to compensate
    prob_norm = probability.prob_up_7d / 100 * 2.0
    val.breakdown["probability"] = round(prob_norm, 1)

    val.score = round(pos_score + cyc_score + liq_norm + prob_norm, 1)

    # Position advice
    if val.score >= 8:
        val.position_advice = "强烈买入"
        val.recommendation = "多维度评分优秀，适合重仓配置"
    elif val.score >= 6.5:
        val.position_advice = "建议买入"
        val.recommendation = "综合评分良好，逢低可入"
    elif val.score >= 4.5:
        val.position_advice = "中性观望"
        val.recommendation = "部分指标尚可，轻仓或等待"
    else:
        val.position_advice = "建议回避"
        val.recommendation = "综合指标偏弱，不建议介入"

    return val


# ============================================================
#  Helper: Whale Detection (4-factor weighted)
# ============================================================

def analyze_whale(prices, volumes):
    """Whale/manipulation detection model."""
    wh = WhaleDetection()
    if not prices or len(prices) < 10:
        return wh

    n = len(prices)
    recent = min(15, n)

    # 1. Volume divergence (40%): volume spike without price movement
    # 真实量 < 20 天时不参与（避免采样假量干扰）
    real_vol_days = sum(1 for v in (volumes or []) if v and v > 0)
    if volumes and len(volumes) >= recent and real_vol_days >= 20:
        vol_recent = volumes[-recent:]
        vol_mean = statistics.mean(vol_recent) if vol_recent else 1
        if vol_mean > 0:
            max_vol = max(vol_recent)
            vol_spike = max_vol / vol_mean if vol_mean > 0 else 1
            vol_score = min(20, max(0, (vol_spike - 2) * 5))  # reduced weight (volume data limited)
            wh.volume_divergence_score = round(vol_score, 1)

    # 2. Volatility anomaly (25%): low volatility + price rise = lock
    if len(prices) >= recent:
        rets_recent = []
        for i in range(1, recent):
            if prices[-i-1] > 0:
                rets_recent.append(abs(prices[-i] / prices[-i-1] - 1) * 100)
        if rets_recent:
            vol_recent = statistics.stdev(rets_recent) if len(rets_recent) >= 3 else 0
            # Longer history vol
            all_rets = []
            for i in range(1, n):
                if prices[-i-1] > 0:
                    all_rets.append(abs(prices[-i] / prices[-i-1] - 1) * 100)
            vol_all = statistics.stdev(all_rets) if len(all_rets) >= 3 else vol_recent
            if vol_all > 0:
                ratio = vol_recent / vol_all
                # Low recent vol = potential lock
                wh.volatility_anomaly_score = round(max(0, min(25, (1 - ratio) * 40)), 1)

    # 3. Position lock (20%): price stuck in tight range while market moves
    if len(prices) >= recent:
        high_r = max(prices[-recent:])
        low_r = min(prices[-recent:])
        mid_r = (high_r + low_r) / 2
        if mid_r > 0:
            range_pct = (high_r - low_r) / mid_r * 100
            if range_pct < 5:
                wh.position_lock_score = 15
            elif range_pct < 10:
                wh.position_lock_score = 8
            else:
                wh.position_lock_score = 2

    # 4. Correlation anomaly (15%): default low
    wh.correlation_anomaly_score = 5

    wh.probability = round(
        wh.volume_divergence_score +
        wh.volatility_anomaly_score +
        wh.position_lock_score +
        wh.correlation_anomaly_score, 1
    )

    # Level
    # --- Whale type classification ---
    whale_type = "unknown"
    percentile = 50
    if prices and len(prices) >= 90:
        window = prices[-90:]
        current = prices[-1]
        below = sum(1 for p in window if p < current)
        percentile = below / len(window) * 100

    if wh.probability >= 35:
        pct = percentile
        vol_sig = ""
        # Check volume trend
        if volumes and len(volumes) >= 10:
            recent_vol = sum(volumes[-5:]) / 5
            prev_vol = sum(volumes[-10:-5]) / 5
            if prev_vol > 0:
                vol_ratio = recent_vol / prev_vol
                if vol_ratio > 1.5:
                    vol_sig = "volume_up"
                elif vol_ratio < 0.6:
                    vol_sig = "volume_down"

        if pct < 30 and wh.position_lock_score > 10:
            whale_type = "低位吸筹锁仓"
            wh.trading_rule = "疑似庄家低位吸筹锁仓，价格可能被压制，可轻仓试探但需耐心等待拉升"
        elif pct > 70 and vol_sig == "volume_down":
            whale_type = "无量拉升诱多"
            wh.trading_rule = "疑似无量拉升诱多，庄家可能在高位派发，禁止追涨，持仓应立即减仓"
        elif pct > 70 and vol_sig == "volume_up":
            whale_type = "高位放量出货"
            wh.trading_rule = "疑似高位放量出货，庄家在拉高过程中逐步派发，持仓应分批清仓"
        else:
            whale_type = "异常控盘"
    else:
        whale_type = "自然交易"

    wh.anomaly_flags.append(whale_type)

    if wh.probability >= 60:
        wh.level = "extreme_whale"
        wh.level_label = "极度庄控"
        wh.anomaly_flags.append("extreme_manipulation")
    elif wh.probability >= 35:
        wh.level = "strong_whale"
        wh.level_label = "强庄控盘"
        wh.anomaly_flags.append("strong_manipulation")
    elif wh.probability >= 15:
        wh.level = "weak_whale"
        wh.level_label = "轻度疑似"
    else:
        wh.level = "natural"
        wh.level_label = "自然交易"
        wh.trading_rule = "正常交易，按标准策略操作"

    return wh


# ============================================================
#  Main: Run Item Analysis
# ============================================================

# ============================================================
#  Signal Conflict Detection
# ============================================================

def detect_signal_conflicts(position, cycle, th_score, whale_prob):
    """Detect conflicting signals between modules and assess decision certainty.

    Returns:
        list of conflict dicts, each with: modules, description, interpretation
    """
    conflicts = []

    # Conflict 1: Undervalued + strong whale
    if position.valuation_tier == "undervalued" and whale_prob > 35:
        conflicts.append({
            "modules": "估值定位 vs 庄盘识别",
            "severity": "high",
            "description": "估值低估(" + str(position.percentile_90d) + "%)但庄盘概率" + str(whale_prob) + "%",
            "interpretation": "庄家可能在压价吸筹，也可能是流动性差导致的伪低估。建议轻仓试探，等庄盘概率下降后再加仓"
        })

    # Conflict 2: High TH + distribution cycle
    if th_score >= 60 and cycle.phase == "distribution":
        conflicts.append({
            "modules": "趋势健康度 vs 周期判定",
            "severity": "medium",
            "description": "趋势健康度高(" + str(th_score) + ")但处于出货期",
            "interpretation": "趋势表面强劲但周期不利，可能是诱多拉升。建议以周期信号为准，分批减仓"
        })

    # Conflict 3: Undervalued + market distribution
    if position.valuation_tier == "undervalued" and cycle.phase == "distribution":
        conflicts.append({
            "modules": "估值定位 vs 周期判定",
            "severity": "medium",
            "description": "估值低估但处于出货期",
            "interpretation": "出货期的低估可能是下跌中继，不是抄底时机。等待周期信号确认后再介入"
        })

    # Conflict 4: Overvalued + high TH + low whale
    if position.valuation_tier in ("overvalued", "bubble") and th_score >= 60 and whale_prob < 15:
        conflicts.append({
            "modules": "估值定位 vs 庄盘识别",
            "severity": "low",
            "description": "高估但无庄盘迹象，趋势健康",
            "interpretation": "可能是自然的市场追捧，非资金操纵。但仍需警惕高位风险，可持有但设好止盈"
        })

    # Conflict 5: Cycle distribution + fusion buy/hold
    if cycle.phase == "distribution" and th_score >= 60:
        conflicts.append({
            "modules": "周期判定 vs 趋势健康",
            "severity": "high",
            "description": "周期判定出货期但趋势健康度偏高(" + str(th_score) + ")",
            "interpretation": "趋势表面强劲但周期不利，可能是诱多拉升。建议以周期信号为准，分批减仓"
        })

    # Conflict 6: Cycle accumulation + fusion sell/avoid
    if cycle.phase == "accumulation" and th_score < 40:
        conflicts.append({
            "modules": "周期判定 vs 趋势健康",
            "severity": "medium",
            "description": "周期判定吸筹期但趋势健康度偏低(" + str(th_score) + ")",
            "interpretation": "虽处于低位区域但趋势疲弱，可能是下跌中继而非吸筹。建议等待趋势确认后再介入"
        })


    # Decision certainty: fewer conflicts = higher certainty
    certainty = "high" if len(conflicts) == 0 else ("medium" if len(conflicts) <= 1 else "low")

    return conflicts, certainty



def compute_bid_support(order_book):
    """0-100 求购承接信号：真实买盘意愿快照，仅辅助修正不开仓。

    三维评分：
      - 断层宽度 0-35：<=3% 承接强；>15% 流动性断层
      - 断层收窄/扩张 vs 30日均值 0-30
      - 求购价 7/30 日趋势 0-35
    """
    if not order_book or not isinstance(order_book, dict):
        return {"score": 50, "signals": [], "note": "无订单簿数据"}
    score = 0
    signals = []
    spread_pct = order_book.get("spread_pct")

    # 1. 断层宽度 (0-35)
    if spread_pct is not None:
        if spread_pct <= 3:
            score += 35
            signals.append(f"断层窄{spread_pct:.1f}%")
        elif spread_pct <= 8:
            score += 25
        elif spread_pct <= 15:
            score += 15
            signals.append("断层偏宽")
        else:
            signals.append("流动性断层")

    # 2. 断层收窄/扩张 vs 30日均值 (0-30)
    spread_avg = order_book.get("spread_avg")
    if spread_avg and spread_pct is not None and spread_avg > 0:
        if spread_pct < spread_avg * 0.9:
            score += 30
            signals.append("断层收窄")
        elif spread_pct < spread_avg:
            score += 18
        elif spread_pct > spread_avg * 1.15:
            score += 5
            signals.append("断层扩张")

    # 3. 求购价 7/30 日趋势 (0-35)
    bid7 = order_book.get("bid_7d_chg")
    bid30 = order_book.get("bid_30d_chg")
    if bid7 is not None and bid30 is not None:
        trend = bid7 * 0.6 + bid30 * 0.4
        score += max(0, min(35, int(35 * (trend + 10) / 20)))
        if trend > 1:
            signals.append("求购价上行")
        elif trend < -3:
            signals.append("求购价走弱")

    return {"score": min(100, score), "signals": signals, "note": ""}

def run_item_analysis(
    name: str,
    prices: list,
    volumes: list = None,
    supply_hist: list = None,
    order_book: dict = None,
    index_change_7d: float = 0,
    market_history: list = None,
    market_pct_90d: float = 50,
    market_cycle: str = "unknown",
    market_zscore: float = 0,
    market_th_score: int = 50,
    market_30d_change: float = 0,
    market_drop21: float = 0,
    recent_buy_dates: list = None,
    signal_date: str = None,
    item_meta: dict = None,
    price_anchor: float = None,
):
    """
    Complete single-item analysis pipeline.

    Args:
        name: item display name
        prices: daily close prices, oldest-first (90-day)
        volumes: daily volumes (optional)
        supply_hist: supply count history (optional, for supply analysis)
        order_book: bid/ask spread info (optional)
        index_change_7d: market index 7-day change for context
        market_history: market index history for correlation
        market_cycle: market cycle phase
        market_zscore: market Z-score
        item_meta: dict with type_name, rarity_name, quality_name, case_discontinued

    Returns:
        ItemAnalysisResult with all analysis modules populated
    """
    if volumes is None:
        volumes = []
    if supply_hist is None:
        supply_hist = []

    n = len(prices)
    if n < 2:
        # Not enough data, return defaults
        return ItemAnalysisResult(
            name=name,
            price_rmb=prices[-1] if prices else 0,
            data_quality="insufficient" if n < 2 else "low",
        )

    # Default risk labels
    risk_level, risk_label = "C", "较高风险·谨慎介入"

    current = prices[-1]
    vol_total = supply_hist[-1] if supply_hist else 0
    vol_day = max(1, sum(volumes[-7:]) // 7) if volumes and len(volumes) >= 7 else max(1, vol_total // 20)

    # ---- Data Quality ----
    dq = "good" if n >= 60 else ("medium" if n >= 20 else "low")

    # ---- Auxiliary Factors ----
    aux = AuxFactors()
    window_90 = prices[-min(90, n):]
    aux.mean_price_90d = round(statistics.mean(window_90), 2)
    aux.mean_volume_7d = round(statistics.mean(volumes[-7:]), 1) if volumes and len(volumes) >= 7 else vol_day
    aux.turnover_rate = round(vol_day / vol_total * 100, 3) if vol_total > 0 else 0
    if n >= 30:
        ma30 = sum(prices[-30:]) / 30
        aux.ma_deviation = round((current / ma30 - 1) * 100, 2) if ma30 > 0 else 0

    # Volume flow slope (simple linear regression on volumes)
    if volumes and len(volumes) >= 10:
        vs = volumes[-10:]
        xs = list(range(10))
        mx = 4.5
        num = sum((x - mx) * v for x, v in zip(xs, vs))
        den = sum((x - mx) ** 2 for x in xs)
        aux.vol_flow_slope = round(num / den, 3) if den else 0

    # ---- Core Analyses ----
    position = _analyze_position(prices)
    cycle = _analyze_cycle(prices, volumes, sentiment_factor=compute_sentiment_factor())
    liquidity = score_liquidity(prices, volumes, vol_total)

    # ---- Trend Health (with category params + cycle/whale/lock/liquidity corrections) ----
    th = compute_trend_health(
        prices, volumes,
        cycle_phase=cycle.phase,
        whale_prob=None,
        position_lock_score=0,
        liquidity_score=liquidity.score,
        item_meta=item_meta,
        zscore_90d=position.zscore_90d,
    )
    th_dict = trend_health_summary(th)

    # ---- Whale Detection ----
    whale = analyze_whale(prices, volumes)

    # Re-run trend health with whale info for better detection
    if whale.probability > 0:
        th2 = compute_trend_health(
            prices, volumes,
            cycle_phase=cycle.phase,
            whale_prob=whale.probability,
            position_lock_score=whale.position_lock_score,
            liquidity_score=liquidity.score,
            item_meta=item_meta,
            zscore_90d=position.zscore_90d,
        )
        th = th2
        th_dict = trend_health_summary(th)

    # ---- Probability (multi-feature: uses TH, whale, cycle, market) ----
    probability = analyze_probability(prices, trend_score=th.score, whale_prob=whale.probability, cycle_phase=cycle.phase, market_pct=market_pct_90d, sentiment_factor=compute_sentiment_factor())

    # ---- Value Score ----
    value = compute_value_score(position, cycle, liquidity, probability)

    sentiment_score = compute_sentiment_score()
    fd = compute_fusion_decision(
        position.percentile_90d, th, liquidity.score, position.zscore_90d,
        cycle_phase=cycle.phase,
        market_cycle=market_cycle,
        market_30d_change=market_30d_change,
        item_7d_change=index_change_7d,
        event_risk_discount=event_risk_coefficient(),
        prices=prices,
        sentiment_score=sentiment_score,
    )

    # ---- P0-1: Market environment hard filter (2026-07 item signals all lost in bear market) ----
    if fd.action == "buy":
        if market_th_score < 45 and market_30d_change < 0:
            fd.action = "watch"
            fd.action_label = "🟡 大盘走弱·观望"
            fd.action_detail = f"大盘TH={market_th_score}且30日跌幅{market_30d_change:.1f}%，弱势环境禁止新开仓"
            fd.deduction_sources.append("market_weak_filter")
        elif sentiment_score <= 30:
            fd.action = "watch"
            fd.action_label = "🟡 情绪贪婪·禁止追买"
            fd.action_detail = f"市场情绪贪婪(sent={sentiment_score:.0f})，追买期望为负"
            fd.deduction_sources.append("greedy_no_buy")

    # ---- P0-3: Half-way downgrade (pct 25~40 non-resonance: backtest 14d win 28%) ----
    if fd.action == "buy" and position.percentile_90d is not None:
        if 25 <= position.percentile_90d <= 40 and sentiment_score < 85:
            fd.action = "watch"
            fd.action_label = "🟡 半山腰·观望"
            fd.action_detail = f"pct={position.percentile_90d:.0f}%处于半山腰且无恐慌共振，回测14d胜率仅28%"
            fd.deduction_sources.append("halfway_downgrade")

    # ---- P0-2: 7-day signal clustering (same item, avoid repeat buy spam) ----
    if fd.action == "buy" and recent_buy_dates:
        from datetime import datetime as _dt
        if signal_date is None:
            signal_date = _dt.now().strftime("%Y-%m-%d")
        for d0 in recent_buy_dates:
            try:
                gap = (_dt.strptime(signal_date[:10], "%Y-%m-%d") - _dt.strptime(d0[:10], "%Y-%m-%d")).days
            except ValueError:
                continue
            if 0 <= gap <= 7:
                fd.action = "watch"
                fd.action_label = "🟡 已在买点区·等待回调"
                fd.action_detail = f"7日内({d0[:10]})已触发买入信号，避免重复建仓"
                fd.deduction_sources.append("buy_cluster_dedup")
                break

    # ---- P0-4: Extreme oversold falling-knife confirmation (z<-2 must stabilize) ----
    # Backtest 2025-11~2026-07: z<-2 signals still making new lows lost 100% (0/2).
    # Keep deep-oversold buys only when decline decelerates (no new low OR 3d up).
    if fd.action == "buy" and position.zscore_90d is not None and position.zscore_90d < -2 and len(prices) >= 4:
        low3 = min(prices[-3:])
        chg3d = (current - prices[-4]) / prices[-4] * 100
        if current <= low3 and chg3d <= 0:
            fd.action = "watch"
            fd.action_label = "🟡 飞刀未止跌·观望"
            fd.action_detail = f"Z={position.zscore_90d:.1f}深度超跌但仍在创新低且3日续跌{chg3d:.1f}%，等待止跌确认"
            fd.deduction_sources.append("falling_knife_filter")

    # ---- P0-5: Panic-resonance reversal upgrade (V-bottom capture, 2026-05-22~27) ----
    # Backtest: watch/avoid missed the 5/22-5/27 capitulation window entirely
    # (fwd14 +16%~+292%). Deep oversold + 14d reversal + extreme fear is a
    # high-expected-value entry even when the broad market TH is weak.
    micro_th = compute_micro_th(prices)
    # P0-7 (2026-08-02, 181d backtest): panic-resonance item/market filters.
    # Full-window data: raw resonance 30d 51%; non-sticker + price>=15 + z>=-2.2
    # + market 21d drop<=-18% -> 14d 100% / 30d 86% (n=14). Filters out the 04-23
    # half-way bottom (market only -13%) and cold-item traps (deep z, stickers).
    _pr_item_ok = ("\u5370\u82b1" not in (name or "") and "\u8d34\u7eb8" not in (name or "")
                   and current >= 15 and position.zscore_90d is not None and position.zscore_90d >= -2.2)
    _pr_market_ok = market_drop21 <= -18
    if fd.action in ("watch", "avoid") and micro_th >= 60 and sentiment_score >= 75 and _pr_item_ok and _pr_market_ok:
        if (position.percentile_90d is not None and position.percentile_90d <= 15
                and position.zscore_90d is not None and position.zscore_90d <= -1.5):
            _dup = False
            if recent_buy_dates:
                from datetime import datetime as _dt
                if signal_date is None:
                    signal_date = _dt.now().strftime("%Y-%m-%d")
                for _d0 in recent_buy_dates:
                    try:
                        _gap = (_dt.strptime(signal_date[:10], "%Y-%m-%d") - _dt.strptime(_d0[:10], "%Y-%m-%d")).days
                    except ValueError:
                        continue
                    if 0 <= _gap <= 7:
                        _dup = True
                        break
            if not _dup:
                fd.action = "buy"
                fd.action_label = "\U0001f7e2 \u6050\u614c\u5171\u632f\u00b7\u5206\u6279\u5efa\u4ed3"
                fd.action_detail = (f"\u6781\u7aef\u6050\u614c(sent={sentiment_score:.0f})+\u6df1\u5ea6\u8d85\u8dcc("
                                    f"pct={position.percentile_90d:.0f}%,Z={position.zscore_90d:.1f})+"
                                    f"\u77ed\u671f\u53cd\u8f6c(microTH={micro_th})")
                fd.deduction_sources.append("panic_resonance_upgrade")


    # P0-7b (2026-08-02, 181d backtest): cycle-accumulation buy needs deep market drop too.
    # Full-window replay: 4 accumulate buys had 30d avg -20% (1/4 positive) because they
    # fired outside capitulation (03-22/06-11/06-19/07-02, market 21d drop only -3~+8%).
    # D-exemption (2026-08-02, 181d replay, ex-珊瑚树): deep-dip low-buy. When the market 21d
    # drop is not deep enough but the item is in a deep drawdown from its 30d high (dd30<=-22)
    # with 14d change still weak (chg14<=-6), keep the accumulation buy. Grid-scan (dd30 x chg14)
    # on the 181d window: -22/-6 is the optimum zone - 14d total exp 2555 (peak 2556), 30d total
    # exp 2203 (highest in grid), 14d win 88%, PF 7.5 vs baseline 41 signals / 100% / +22%.
    if fd.action == "buy" and "\u5438\u7b79" in fd.action_label and market_drop21 > -18:
        dd30 = (current / max(prices[-30:]) - 1) * 100 if len(prices) >= 30 else 0.0
        chg14 = (current / prices[-15] - 1) * 100 if len(prices) >= 15 else 0.0
        if dd30 <= -22 and chg14 <= -6:
            fd.action_label = "\U0001f7e2 \u6df1\u5ea6\u56de\u8c03\u4f4e\u5438\u00b7\u5206\u6279\u5efa\u4ed3"
            fd.action_detail = ("\u5468\u671f\u5438\u7b79\u4f46\u5927\u76d8\u672a\u6df1\u8dcc\uff0c\u5355\u54c1\u6df1\u5ea6\u56de\u8c03"
                                f"(dd30={dd30:.0f}%,chg14={chg14:.0f}%)\u4e8c\u6b21\u63a2\u5e95\uff0c\u56de\u6d4b14d\u671f\u671b\u6b63\u503c")
            fd.deduction_sources.append("deep_dip_exemption")
        else:
            fd.action = "watch"
            fd.action_label = "\U0001f7e1 \u5468\u671f\u5438\u7b79\u9700\u5927\u76d8\u5171\u632f\u00b7\u89c2\u671b"
            fd.action_detail = "\u5468\u671f\u5438\u7b79\u4f46\u5927\u76d820\u65e5\u8dcc\u5e45" + str(round(market_drop21, 1)) + "%~18%\uff0c\u7b49\u5927\u76d8\u6df1\u8dcc\u5171\u632f\u518d\u5efa\u4ed3\uff08\u56de\u6d4b\uff1a\u975e\u6df1\u8dcc\u573a\u666f4/4\u4fe1\u53f730d\u8d1f\u671f\u671b\uff09"
            fd.deduction_sources.append("cycle_accumulation_needs_market_drop")
            fd.position_limit = 0.0
        fd_dict = fusion_decision_summary(fd)

    # ---- P0-6: Micro-TH buy confirmation (weak short-term momentum blocks buy) ----
    if fd.action == "buy" and micro_th < 45:
        fd.action = "watch"
        fd.action_label = "\U0001f7e1 \u77ed\u671f\u52a8\u80fd\u5f31\u00b7\u89c2\u671b"
        fd.action_detail = f"14\u65e5\u5fae\u578bTH={micro_th}\uff0c\u77ed\u671f\u52a8\u80fd\u4e0d\u8db3\uff0c\u7b49\u5f85\u53cd\u8f6c\u786e\u8ba4"
        fd.deduction_sources.append("micro_th_weak")

    # ---- Bid support (v4.6): real buy-side willingness snapshot ----
    bid_support = compute_bid_support(order_book)
    bid_score = bid_support["score"]
    if bid_score <= 25 and fd.action == "buy":
        fd.action = "watch"
        fd.action_label = "🟡 求购承接弱·观望"
        fd.action_detail = f"求购承接弱(score={bid_score})，买盘意愿不足，暂缓建仓"
        fd.deduction_sources.append("bid_support_weak")
    elif bid_score >= 75 and fd.action == "watch" and position.percentile_90d <= 30:
        fd.action_label = "🟡 底部观察·承接增强"
        fd.action_detail = "低位但求购承接增强，可轻仓试探"
        fd.position_limit = max(fd.position_limit, 0.08)

    # Market cycle filter: during market distribution, downgrade buy signals
    if market_cycle == "distribution" and fd.action in ("buy", "hold"):
        fd.action = "watch"
        fd.action_label = "\U0001f7e1 大盘出货期·观望"
        fd.action_detail = fd.action_detail + "（大盘处于出货期，建仓/持有信号降级为观望）"
        fd.deduction_sources.append("market_distribution_filter")


    # ---- Item-level Z-gate: tighten buy at shallow dips ----
    if fd.action == "buy" and position.zscore_90d is not None:
        item_z_gates = {"accumulation": -0.5, "consolidation": -1.0, "distribution": -1.5, "markup": 0, "unknown": -1.0}
        item_z_threshold = item_z_gates.get(cycle.phase, -1.0)
        if position.zscore_90d > item_z_threshold:
            fd.action = "watch"
            fd.action_label = "🟡 Z偏高·等待更优入场"
            fd.action_detail = f"Z={position.zscore_90d} 要求≤{item_z_threshold}，估值未达极端低位"
            fd.deduction_sources.append("item_z_gate")


    # ---- Consecutive buy suppression (3-day cooldown) ----
    if fd.action == "buy" and n >= 7 and position.percentile_90d > 5:
        price_3d = prices[-4]
        chg_3d = (current - price_3d) / price_3d * 100
        if abs(chg_3d) < 1.5:
            fd.action = "watch"
            fd.action_label = "🟡 已在买入区·等待回调"
            fd.action_detail = f"3日价格变动{chg_3d:+.1f}%，无需重复触发买入"
            fd.deduction_sources.append("consecutive_buy")

    # ---- Position limit (graded by value + sentiment) ----
    if fd.action in ("buy", "hold"):
        pl_score = value.score
        if sentiment_score >= 75:
            pl_score += 2.0
        elif sentiment_score <= 30:
            pl_score -= 1.5
        if pl_score >= 8.5:
            fd.position_limit = 0.30
        elif pl_score >= 7.0:
            fd.position_limit = 0.20
        elif pl_score >= 5.0:
            fd.position_limit = 0.12
        elif pl_score >= 3.0:
            fd.position_limit = 0.05
        else:
            fd.position_limit = 0.0
    else:
        fd.position_limit = 0.0

    # ---- Risk level label (A/B/C/D) ----
    risk_score = 0
    risk_score += 3 if th.score >= 55 else (2 if th.score >= 40 else 1)
    if position.zscore_90d is not None:
        risk_score += 3 if position.zscore_90d <= -1.5 else (2 if position.zscore_90d <= -0.5 else 1)
    risk_score += 3 if liquidity.score >= 50 else (2 if liquidity.score >= 30 else 1)
    risk_score += 3 if whale.level in ("none", "accumulation") else 1
    if risk_score >= 12:
        risk_level, risk_label = "A", "低风险·可关注"
    elif risk_score >= 9:
        risk_level, risk_label = "B", "中等风险·正常操作"
    elif risk_score >= 6:
        risk_level, risk_label = "C", "较高风险·谨慎介入"
    else:
        risk_level, risk_label = "D", "极度危险·回避"

    fd_dict = fusion_decision_summary(fd)


    # ---- Valuation Grid (3x4) ----
    # Signal conflict detection
    conflicts, decision_certainty = detect_signal_conflicts(position, cycle, th.score, whale.probability)

    vg = compute_valuation_grid(position.percentile_90d, th, whale.probability)
    vg_dict = valuation_grid_summary(vg)

    # ---- Supply Analysis ----
    supply = analyze_supply(prices, supply_hist, vol_total, item_meta)
    supply_dict = supply_summary(supply)

    # ---- Supply-expansion filter (2026-08-02 data fit) ----
    # 42 buy 信号回测：供给扩张(in_sale 30日变化>5%) 的5个信号30d胜率0%，均为负期望
    # 过滤后剩 37 个信号，14d 89%/30d 76%；供给扩张时 buy 不开仓
    # 深度回调低吸(D方案)例外：恐慌共振供给扩张为负期望，
    # 但深度回调场景供给扩张反而是正期望(dedup 37信号 14d胜率67.6%均+14.9)
    if fd.action in ("buy", "oversold_buy") and supply.supply_change_30d and supply.supply_change_30d > 5 \
            and "deep_dip_exemption" not in fd.deduction_sources:
        fd.action = "watch"
        fd.action_label = "\U0001f7e1 \u4f9b\u7ed9\u6269\u5f20\u00b7\u89c2\u671b"
        fd.action_detail = ("\u5728\u552e\u91cf30\u65e5\u6269\u5f20" + str(round(supply.supply_change_30d, 1)) +
                            "%\uff0c\u629b\u538b\u5806\u79ef\uff0c\u5386\u53f2buy\u4fe1\u53f730d\u80dc\u73870%(\u56de\u6d4b5/5\u8d1f\u671f\u671b)")
        fd.deduction_sources.append("supply_expansion_filter")
        fd.position_limit = 0.0
        fd_dict = fusion_decision_summary(fd)

    # ---- P0-8: Deep-value stable-market low-buy (2026-08-03, 24,123-day replay) ----
    # A??(????)?????: 2????????????(mth<40), ???????????
    # ???????????: pct<=20 z<=-0.5 ??TH>=35 ??TH>=40 40<=sent<=65 drop21>=-5
    # 266 ????(???buy???,7???): 14d 48.1%/+4.20, 30d 45.5%/+8.17
    # pre-1/23 ???? 80 ??: 14d 61.3%/+10.05, 30d 61.3%/+17.60
    # 1/23~2/12 ??? 17 ??: 14d 70.6%/+4.10, 30d 76.5%/+27.29
    # ?????(??-0.47/-1.14), ?????? -> ??0.10??
    if fd.action in ("watch", "avoid") and position.percentile_90d is not None and position.zscore_90d is not None:
        _dv_ok = (position.percentile_90d <= 20 and position.zscore_90d <= -0.5
                  and th.score >= 35 and market_th_score >= 40
                  and 40 <= sentiment_score <= 65 and market_drop21 >= -5)
        if _dv_ok:
            _dup = False
            if recent_buy_dates:
                from datetime import datetime as _dt
                _d_now = signal_date or _dt.now().strftime("%Y-%m-%d")
                for _d0 in recent_buy_dates:
                    try:
                        _gap = (_dt.strptime(_d_now[:10], "%Y-%m-%d") - _dt.strptime(_d0[:10], "%Y-%m-%d")).days
                    except ValueError:
                        continue
                    if 0 <= _gap <= 7:
                        _dup = True
                        break
            if not _dup:
                fd.action = "buy"
                fd.action_label = "🟢 ????????????"
                fd.action_detail = (f"?????(pct={position.percentile_90d:.0f}%,Z={position.zscore_90d:.1f})"
                                    f"+????(TH={market_th_score},21???{market_drop21:.1f}%)?"
                                    f"??14d??+4.2%/30d+8.2%??????")
                fd.deduction_sources.append("deep_value_stable_market")
                fd.position_limit = 0.10
                fd_dict = fusion_decision_summary(fd)

    # ---- Apply fusion decision to value score ----
    if fd.action == "buy":
        value.score = min(10, value.score + 1.5)
    elif fd.action in ("sell", "avoid"):
        value.score = max(0, value.score - 2.0)
    elif fd.action == "reduce":
        value.score = max(0, value.score - 1.0)

    # Adjust by corrected trend health
    th_boost = round((th.score - 50) / 50 * 2.0, 1)
    value.score = round(max(0, min(10, value.score + th_boost)), 1)

    # Re-calculate grade
    if value.score >= 8:
        value.grade = "S"
    elif value.score >= 6.5:
        value.grade = "A"
    elif value.score >= 4.5:
        value.grade = "B"
    else:
        value.grade = "C"

    # Override cycle labels based on fusion decision
    # Cycle labels kept independent from fusion decision (no override)
    # cycle.phase_label and cycle.phase_strategy now stay as cycle-detected values
    pass
    # Apply event risk discount from supply analysis
    if supply.has_event_risk and supply.event_risk_discount < 1.0:
        value.score = round(value.score * supply.event_risk_discount, 1)
        if supply.event_risk_discount < 0.9:
            value.position_advice += " [事件风险折价]"

    # If whale-controlled, override value score
    if whale.level in ("strong_whale", "extreme_whale"):
        value.recommendation = f"\u26a0\ufe0f {whale.level_label}标的 -- 常规估值方法失效。" + whale.trading_rule
        if whale.level == "extreme_whale":
            value.score = min(value.score, 2.0)
            value.grade = "C"
            value.position_advice = "禁止买入 -- 高危资金盘，随时崩盘"

    # ---- Market Context (optional anchor) ----
    market_ctx = None
    if market_history and len(market_history) >= 5 and n >= 5:
        try:
            # import moved to top
            market_ctx = build_market_context(
                prices, market_history, market_cycle, market_zscore
            )
        except Exception:
            pass

    # ---- Build result ----


    # ---- Price Zones (volatility-scaled, anchored to current price) ----
    price_zones = {}
    if n >= 10:
        # ---- Volatility anchor (14d return std) ----
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(max(1, n-14), n) if prices[i-1] > 0]
        atr_pct = (sum(abs(r) for r in returns) / len(returns)) if returns else 0.03
        atr_pct = max(0.01, min(0.10, atr_pct))  # clamp 1%-10%

        cycle_phase = cycle.phase if hasattr(cycle, 'phase') else 'unknown'
        th_score = th.score if hasattr(th, 'score') else 50
        whale_prob = whale.probability if hasattr(whale, 'probability') else 0
        whale_level = whale.level if hasattr(whale, 'level') else 'none'

        # ---- Cycle-adjusted volatility multipliers ----
        buy_widen = 1.0
        sell_widen = 1.0
        if cycle_phase == 'accumulation':
            buy_widen = 1.3
            sell_widen = 0.85
        elif cycle_phase == 'markup':
            buy_widen = 0.75
            sell_widen = 1.2
        elif cycle_phase == 'distribution':
            buy_widen = 0.7
            sell_widen = 0.7
        elif cycle_phase == 'consolidation':
            buy_widen = 1.0
            sell_widen = 1.0

        if th_score >= 70:
            buy_widen *= 0.85
            sell_widen *= 1.15
        elif th_score <= 30:
            buy_widen *= 1.3
            sell_widen *= 0.85

        if whale_level in ('strong_whale', 'extreme_whale') and whale_prob >= 40:
            buy_widen *= 1.2
            sell_widen *= 0.8

        # ---- Compute zones (anchored to current price) ----
        entry_low  = round(current * (1 - atr_pct * 1.5 * buy_widen), 2)
        entry_high = round(current * (1 - atr_pct * 0.4 * buy_widen), 2)
        exit_low   = round(current * (1 + atr_pct * 0.4 * sell_widen), 2)
        exit_high  = round(current * (1 + atr_pct * 1.5 * sell_widen), 2)
        stop_loss  = round(current * (1 - atr_pct * 2.5 * buy_widen), 2)
        take_profit = round(current * (1 + atr_pct * 2.5 * sell_widen), 2)

        # ---- Sanity: clamp to historical range ----
        hist_low = min(prices)
        hist_high = max(prices)
        entry_low = max(entry_low, round(hist_low * 0.9, 2))
        entry_high = max(entry_high, round(current * 0.95, 2))
        exit_high = min(exit_high, round(hist_high * 1.1, 2))
        stop_loss = max(stop_loss, round(current * 0.80, 2))
        take_profit = min(take_profit, round(current * 1.30, 2))

        # Ensure entry < current < exit
        entry_high = min(entry_high, round(current * 0.98, 2))
        exit_low = max(exit_low, round(current * 1.02, 2))
        entry_low = min(entry_low, entry_high - 0.01)
        exit_high = max(exit_high, exit_low + 0.01)

        # ---- Downtrend guard: suppress buy zone when falling ----
        # 融合决策最终为 buy（如恐慌共振升级）时保留买入区间，避免与决策条矛盾
        if (th_score < 40 or cycle_phase == 'distribution') and fd.action != 'buy':
            entry_low = 0
            entry_high = 0
            stop_loss = 0
            exit_low = round(current * (1 + atr_pct * 0.3), 2)
            exit_high = round(current * (1 + atr_pct * 0.8), 2)

        # ---- Sentiment-adaptive stop/take (P1 data fit, run_item_exit_backtest.py) ----
        # 42 buy signals 2026-04-21~08-01: fear window keeps wide -30% stop and raises TP
        # to +40% (same win rate as +30%, higher expectancy); neutral TP +15% beats the old
        # +2.5xATR (~+7%) on both win rate and expectancy; greed window unchanged (few data).
        stop_loss_note = ""
        if sentiment_score >= 75:
            stop_loss = round(current * ITEM_EXIT_RULES["fear"]["stop_pct"], 2)
            take_profit = round(current * ITEM_EXIT_RULES["fear"]["take_pct"], 2)
            stop_loss_note = ("\u6781\u5ea6\u6050\u614c\u7a97\u53e3\u5e38\u73b0-20%+\u6df1\u6d17\u76d8(\u56de\u6d4b5/22\u4e70\u5165\u540e3-5\u65e5\u56de\u64a4-21%~-28%\u518d\u53cd\u5f39)\uff0c"
                              "\u6b62\u635f\u653e\u5bbd\u81f3-30%\u907f\u514d\u88ab\u6d17\uff1b\u6b62\u76c8\u653e\u5bbd\u81f3+40%\u8ba9\u5229\u6da6\u5954\u8dd1")
        elif sentiment_score <= 30:
            take_profit = round(current * (1 + atr_pct * 1.5), 2)
            stop_loss = round(current * ITEM_EXIT_RULES["greed"]["stop_pct"], 2)
            stop_loss_note = "\u60c5\u7eea\u8d2a\u5a6a\u7a97\u53e3\u53ca\u65f6\u6b62\u76c8\u3001\u6536\u7d27\u6b62\u635f\u81f3-8%\u843d\u888b"
        else:
            take_profit = round(current * ITEM_EXIT_RULES["neutral"]["take_pct"], 2)

        # ---- Expectancy label (backtest-derived, shown for buy signals) ----
        expectancy = None
        if fd.action in ("buy", "oversold_buy"):
            if "\u6050\u614c" in fd.action_label:
                _stats = ITEM_EXPECTANCY_STATS["panic"]
            elif "\u6df1\u503c" in fd.action_label:
                _stats = ITEM_EXPECTANCY_STATS["deep_value"]
            else:
                _stats = ITEM_EXPECTANCY_STATS["accumulate"]
            expectancy = dict(_stats)

        # ---- ATH override ----
        ath_mode = current > hist_high * 0.98
        if ath_mode:
            atr_val = round(current * atr_pct * 2, 2)
            price_zones = {
                "entry": {"low": round(current * 0.90, 2), "high": round(current * 0.96, 2)},
                "exit": {"low": round(current * 1.04, 2), "high": round(current * 1.10, 2)},
                "stop_loss": round(current * 0.82, 2),
                "take_profit": round(current * 1.18, 2),
                "current": round(current, 2),
                "ath_warning": True,
                "ath_price": hist_high,
                "entry_pct": {"low": 10, "high": 20},
                "exit_pct": {"low": 75, "high": 90},
                "expectancy": expectancy,
                "strategy": "创历史新高(¥" + str(hist_high) + ")，无历史回朔参考区间。基于近期波动率估算: 回调" + str(atr_val) + "可轻仓试多，突破前高" + str(round(current * 1.04, 2)) + "加仓",
            }
        else:
            # Strategy explanation
            phase_names = {
                'markup': '拉升期',
                'accumulation': '吸筹期',
                'distribution': '出货期',
                'consolidation': '洗盘期',
            }
            phase_cn = phase_names.get(cycle_phase, cycle_phase)
            strat = []
            if cycle_phase != 'unknown':
                strat.append(phase_cn)
            if th_score >= 60:
                strat.append('趋势偏强(' + str(th_score) + '分)')
            elif th_score <= 40:
                strat.append('趋势偏弱(' + str(th_score) + '分)')
            if whale_prob >= 40:
                strat.append('庄家风险' + str(whale_prob) + '%')
            if stop_loss_note:
                strat.append(stop_loss_note)
            if fd.action in ("buy", "hold"):
                _hold = ITEM_EXIT_RULES["fear" if sentiment_score >= 75 else "neutral"]["hold_days"]
                strat.append("\u5efa\u8bae\u6301\u4ed3\u7ea6" + str(_hold) + "\u5929(\u56de\u6d4b\u671f\u671b\u6700\u4f18)")

            price_zones = {
                "entry": {"low": entry_low, "high": entry_high},
                "exit": {"low": exit_low, "high": exit_high},
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "current": round(current, 2),
                "entry_pct": {"low": round(entry_low / current * 100, 1), "high": round(entry_high / current * 100, 1)},
                "exit_pct": {"low": round(exit_low / current * 100, 1), "high": round(exit_high / current * 100, 1)},
                "expectancy": expectancy,
                "strategy": " | ".join(strat) if strat else "",
            }
    # ---- Buy-distance quantization (display layer, never changes decisions) ----
    buy_distance = {}
    try:
        from .buy_distance import compute_buy_distance
        _th_score = th.score if hasattr(th, 'score') else 50
        buy_distance = compute_buy_distance(
            prices, position, _th_score,
            price_zones=price_zones,
            cycle_phase=cycle.phase if hasattr(cycle, 'phase') else 'unknown',
            action=fd.action,
            anchor_price=price_anchor,
        ) or {}
    except Exception:
        buy_distance = {}

    return ItemAnalysisResult(
        name=name,
        price_rmb=current,
        conflicts=conflicts,
        decision_certainty=decision_certainty,
        volume_day=vol_day,
        volume_total=vol_total,
        position=position,
        aux=aux,
        cycle=cycle,
        liquidity=liquidity,
        probability=probability,
        value=value,
        whale=whale,
        data_quality=dq,
        trend_health=th_dict,
        fusion_decision=fd_dict,
        valuation_grid=vg_dict,
        supply_analysis=supply_dict,
        market_context=context_summary(market_ctx) if market_ctx else {},
        risk_level=risk_level,
        bid_support=bid_support,
        risk_label={"A":"低风险·可关注","B":"中等风险·正常操作","C":"较高风险·谨慎介入","D":"极度危险·回避"}.get(risk_level, ""),
        price_zones=price_zones,
        buy_distance=buy_distance,
    )

