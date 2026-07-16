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
from dataclasses import dataclass, field

# ============================================================
# Strategy Constants
# ============================================================
ENTRY_PERCENTILE_MAX = 30
ENTRY_ZSCORE_MAX = -1.5
EXIT_PERCENTILE_MIN = 65
EXIT_ZSCORE_MIN = 2.0

"""
Single-item investment analysis engine — CS2 skin specific.
Unifies: percentile/Z-score, cycle detection, liquidity scoring,
value scoring, probability prediction, and whale manipulation detection.

All statistical windows default to 90 days.
"""

import statistics
import math
from .trend_health import compute_trend_health, trend_health_summary, compute_fusion_decision, fusion_decision_summary
from .valuation import compute_valuation_grid, valuation_grid_summary
from .supply import analyze_supply, supply_summary
from dataclasses import dataclass, field

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
    mad_zscore_90d: float = 0.0
    valuation_slope: float = 0.0
    valuation_trend: str = "数据不足"

    def __post_init__(self):
        if self.percentile_90d <= 20:
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
    valuation_grid: dict = field(default_factory=dict)


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

    # Z-score
    if len(window) >= 3:
        mean = statistics.mean(window)
        std = statistics.stdev(window)
        if std > 0:
            pos.zscore_90d = round((current - mean) / std, 2)

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

    # --- MAD-based Z-score (unified with trend_health) ---
    if len(window) >= 5:
        try:
            import statistics as _st
            med = _st.median(window)
            mad_val = _st.median([abs(p - med) for p in window])
            if mad_val > 0:
                pos.mad_zscore_90d = round(0.6745 * (current - med) / mad_val, 2)
            else:
                pos.mad_zscore_90d = pos.zscore_90d
        except Exception:
            pos.mad_zscore_90d = pos.zscore_90d
    else:
        pos.mad_zscore_90d = pos.zscore_90d

    # Re-compute tier_label (post_init ran with default 50.0)
    if pos.percentile_90d <= 20:
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

def _analyze_cycle(prices, volumes=None):
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
        cyc.phase = "distribution"
        cyc.phase_label = "出货期"
        cyc.phase_description = "价格高位 + 短期均线远高于长期均线，资金可能派发"
        cyc.phase_strategy = "只卖不买，分批止盈离场"
        cyc.phase_confidence = min(80, 50 + pct_current * 0.3)
        cyc.next_phase_trigger = "百分位跌破50%或均线死叉"
    elif ma7 > ma30 and pct_current < 30:
        cyc.phase = "accumulation"
        cyc.phase_label = "吸筹期"
        cyc.phase_description = "低位 + 短期均线上穿，资金可能吸筹"
        cyc.phase_strategy = "分批建仓，耐心持仓"
        cyc.phase_confidence = min(80, 50 + (30 - pct_current) * 1.5)
        cyc.next_phase_trigger = "百分位突破50%进入拉升"
    elif ma7 > ma30 and 30 <= pct_current <= 65:
        cyc.phase = "markup"
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

    # --- Volume confirmation for markup phase ---
    if cyc.phase == "markup" and volumes and len(volumes) >= 20:
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

    # Volume score (40%)
    vol_day = volume_total // 20 if volume_total > 0 else 1  # rough daily estimate
    if volumes and len(volumes) >= 7:
        vol_day = max(1, sum(volumes[-7:]) // 7)

    if vol_day >= 100:
        vol_score = 40
    elif vol_day >= 30:
        vol_score = 32
    elif vol_day >= 10:
        vol_score = 24
    elif vol_day >= 3:
        vol_score = 16
    elif vol_day >= 1:
        vol_score = 8
    else:
        vol_score = 2
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

def analyze_probability(prices, trend_score=None, whale_prob=0, cycle_phase="unknown", market_pct=50):
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

    # Liquidity score (20%)
    liq_norm = liquidity.score / 100 * 2.0
    val.breakdown["liquidity"] = round(liq_norm, 1)

    # Probability score (15%)
    prob_norm = probability.prob_up_7d / 100 * 1.5
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
    if volumes and len(volumes) >= recent:
        vol_recent = volumes[-recent:]
        vol_mean = statistics.mean(vol_recent) if vol_recent else 1
        if vol_mean > 0:
            max_vol = max(vol_recent)
            vol_spike = max_vol / vol_mean if vol_mean > 0 else 1
            vol_score = min(40, max(0, (vol_spike - 2) * 10))
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

    # Decision certainty: fewer conflicts = higher certainty
    certainty = "high" if len(conflicts) == 0 else ("medium" if len(conflicts) <= 1 else "low")

    return conflicts, certainty


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
    item_meta: dict = None,
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
    cycle = _analyze_cycle(prices, volumes)
    liquidity = score_liquidity(prices, volumes, vol_total)

    # ---- Trend Health (with category params + cycle/whale/lock/liquidity corrections) ----
    th = compute_trend_health(
        prices, volumes,
        cycle_phase=cycle.phase,
        whale_prob=None,  # will be updated after whale detection
        position_lock_score=0,
        liquidity_score=liquidity.score,
        item_meta=item_meta,
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
        )
        th = th2
        th_dict = trend_health_summary(th)

    # ---- Probability (multi-feature: uses TH, whale, cycle, market) ----
    probability = analyze_probability(prices, trend_score=th.score, whale_prob=whale.probability, cycle_phase=cycle.phase, market_pct=market_pct_90d)

    # ---- Value Score ----
    value = compute_value_score(position, cycle, liquidity, probability)

    # ---- Fusion Decision ----
    fd = compute_fusion_decision(position.percentile_90d, th, liquidity.score, position.zscore_90d)

    # Market cycle filter: during market distribution, downgrade buy signals
    if market_cycle == "distribution" and fd.action in ("buy", "hold"):
        fd.action = "watch"
        fd.action_label = "\U0001f7e1 大盘出货期·观望"
        fd.action_detail = fd.action_detail + "（大盘处于出货期，建仓/持有信号降级为观望）"
        fd.deduction_sources.append("market_distribution_filter")

    fd_dict = fusion_decision_summary(fd)

    # ---- Valuation Grid (3x4) ----
    # Signal conflict detection
    conflicts, decision_certainty = detect_signal_conflicts(position, cycle, th.score, whale.probability)

    vg = compute_valuation_grid(position.percentile_90d, th, whale.probability)
    vg_dict = valuation_grid_summary(vg)

    # ---- Supply Analysis ----
    supply = analyze_supply(prices, supply_hist, vol_total, item_meta)
    supply_dict = supply_summary(supply)

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
    cycle.phase_label = fd.action_label
    cycle.phase_strategy = fd.action_detail

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
            from .market_context import build_market_context
            market_ctx = build_market_context(
                prices, market_history, market_cycle, market_zscore
            )
        except Exception:
            pass

    # ---- Build result ----
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
        market_context=market_ctx.context_summary() if market_ctx else {},
        corr_label="",
    )
