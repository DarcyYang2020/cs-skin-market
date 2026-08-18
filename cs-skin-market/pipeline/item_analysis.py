"""
Single-item investment analysis engine --- CS2 skin specific.
Unifies: percentile/Z-score, cycle detection, liquidity scoring,
value scoring, probability prediction, and whale manipulation detection.

All statistical windows default to 90 days.
"""

import logging
import os, statistics

logger = logging.getLogger(__name__)
from .trend_health import compute_trend_health, trend_health_summary, compute_fusion_decision, fusion_decision_summary, liquidity_supply_floor
from .valuation import compute_valuation_grid, valuation_grid_summary
from .supply import analyze_supply, supply_summary
from .market_context import build_market_context, context_summary, state_bucket
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
    """Auxiliary price factors."""
    mean_price_90d: float = 0.0
    ma_deviation: float = 0.0            # 均线乖离率 (price / ma30 - 1) * 100


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
    # 2026-08-14 #5：供给收缩三态研究标注的只读指标（展示层，不参与任何决策）。
    research_metrics: dict = field(default_factory=dict)


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

def _analyze_cycle(prices, sentiment_factor=0.0, supply=None):
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

    # Use simple trend indicators
    ma7  = sum(prices[-min(7, n):]) / min(7, n)
    ma30 = sum(prices[-min(30, n):]) / min(30, n)

    pct_current = sum(1 for p in window_90 if p < current) / len(window_90) * 100

    # Recent 14-day momentum

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

    # --- Supply confirmation for markup phase (去量 2026-08-07：在售量扩张 → 供给涌入警惕) ---
    if cyc.phase == "markup" and supply and sum(1 for s in supply if s and s > 0) >= 20:
        avg_s5 = sum(supply[-5:]) / 5
        avg_s20 = sum(supply[-20:]) / 20
        if avg_s20 > 0 and avg_s5 > avg_s20 * 1.3:
            cyc.phase = "consolidation"
            cyc.phase_label = "供给扩张·警惕"
            cyc.phase_description = "价格上涨但在售量骤增，供给涌入，可能是派发或热度假象"
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
                cyc.next_phase_trigger = "供给配合突破MA90确认趋势反转"

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

def score_liquidity(prices, volume_total):
    """Score liquidity 0-100 based on supply depth and price stability (去量 2026-08-07)."""
    liq = LiquidityScore()
    liq.breakdown = {}

    # Supply depth score (50%): 当前在售量（可交易池深度）
    if volume_total >= 500:
        supply_score = 50
    elif volume_total >= 200:
        supply_score = 40
    elif volume_total >= 100:
        supply_score = 33
    elif volume_total >= 50:
        supply_score = 25
    elif volume_total >= 10:
        supply_score = 13
    else:
        supply_score = 5
    liq.breakdown["supply"] = supply_score

    # Stability score (50%) - price volatility
    if prices and len(prices) >= 10:
        rets = []
        for i in range(1, min(len(prices), 30)):
            if prices[-i-1] > 0:
                rets.append(abs(prices[-i] / prices[-i-1] - 1) * 100)
        if rets:
            avg_vol = statistics.mean(rets)
            if avg_vol < 1:
                stab_score = 50
            elif avg_vol < 2:
                stab_score = 42
            elif avg_vol < 4:
                stab_score = 30
            elif avg_vol < 7:
                stab_score = 17
            else:
                stab_score = 7
            liq.breakdown["stability"] = stab_score
        else:
            stab_score = 25
            liq.breakdown["stability"] = stab_score
    else:
        stab_score = 25
        liq.breakdown["stability"] = stab_score

    liq.score = min(100, int(supply_score + stab_score))

    # Level label via __post_init__ handles this
    return liq


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

    # 2026-08-10 去 z 化（消除与位置 40% 的双计权）：base_up 改由波动率 regime 主导
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

    # Base probability: 低波动趋势延续性好 -> up bias 高；高波动不确定性大 -> 中性偏弱
    base_up = {"stable": 65.0, "normal": 55.0, "volatile": 48.0, "high_volatile": 42.0}.get(
        prob.volatility_regime, 55.0)

    # Decay with trend_score: if TH < 30, up probability pulled toward 50
    if trend_score is not None and trend_score < 30:
        base_up = 50.0

    # Expected return based on Z-score mean reversion (展示口径，不参与 value 计权)
    exp_ret = -z * 3.0  # rough: Z=-2 -> +6% expected return

    # H-2（2026-08-10）：首段 prob_up/down 赋值被多特征修正后重算覆盖（死代码），已移除
    prob.prob_range_3d  = round(abs(z) * 5, 1)
    prob.prob_range_7d  = round(abs(z) * 8, 1)
    prob.prob_range_30d = round(abs(z) * 15, 1)

    prob.expected_return_3d  = round(exp_ret * 0.3, 2)
    prob.expected_return_7d  = round(exp_ret * 0.6, 2)
    prob.expected_return_30d = round(exp_ret, 2)

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

    # (Confidence label removed in dead-code cleanup 2026-08-05: 
    #  probability correction is carried by the prob object itself)
    prob.prob_up_3d  = round(base_up * 1.05, 1)
    prob.prob_up_7d  = round(base_up * 1.10, 1)
    prob.prob_up_30d = round(base_up * 1.15, 1)
    prob.prob_down_3d  = round(100 - prob.prob_up_3d, 1)
    prob.prob_down_7d  = round(100 - prob.prob_up_7d, 1)
    prob.prob_down_30d = round(100 - prob.prob_up_30d, 1)

    # --- Enhanced support/resistance with MA levels ---
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

    # Cycle score (25%): consolidation > accumulation > markup > distribution
    # 2026-08-10 反转依据（回放 369 buy 信号）：洗盘期 win14 82.2%/+18.9、win30 +30.6 最优；
    # 吸筹期（MA7>MA30 已启动）win30 +15.8 平庸、拉升期（追高）win14 63% 最差。
    # 第一性原理：CS 饰品「洗盘期」=低位横盘潜伏区，评分应奖励潜伏期而非已启动/追高段。
    if cycle.phase == "consolidation":
        cyc_score = 2.5
    elif cycle.phase == "accumulation":
        cyc_score = 2.0
    elif cycle.phase == "markup":
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


def composite_score(analysis):
    """综合评分（P0-1 同口径，2026-08-11 抽公共函数；TH 偏移 2026-08-11 M-5 反向）：
    数据质量 x 估值折价 x (基础评分 + 融合决策加分 + 趋势加权反向)。
    发现高分品 Top10 排序与批量扫描结果排序共用此口径；
    纯展示层派生，不改任何引擎信号。
    TH 偏移依据（M-2 消融，2026-08-11）：365d 回放 317 buy 信号，TH 与 net14 负相关
    spearman -0.344（TH<35 win14 80.8% / TH>55 60.8%，拉升/追高段最差）；原版加分排序
    负相关(-0.093)，反向(-1.0) 后 Q5 桶 win14 67.2%→73.4% 单调正向(spearman +0.015)，
    见 data/_exp_composite_ablation.json。
    """
    dq_factor = {"good": 1.0, "medium": 0.85, "low": 0.6, "insufficient": 0.2}.get(
        getattr(analysis, "data_quality", "low"), 0.4)
    fd_action = ""
    if isinstance(getattr(analysis, "fusion_decision", None), dict):
        fd_action = (analysis.fusion_decision or {}).get("action", "") or ""
    action_bonus = {"buy": 1.0, "watch": 0.5, "hold": 0.0, "reduce": -0.5,
                    "avoid": -1.0, "sell": -1.0}.get(fd_action, 0.0)
    th_score = 50
    if isinstance(getattr(analysis, "trend_health", None), dict):
        th_score = (analysis.trend_health or {}).get("score", 50) or 50
    th_bonus = (float(th_score) - 50) / 50 * (-1.0)
    pct_val = 50.0
    _pos = getattr(analysis, "position", None)
    if _pos is not None:
        try:
            pct_val = float(getattr(_pos, "percentile_90d", 50) or 50)
        except (TypeError, ValueError):
            pct_val = 50.0
    valuation_discount = max(0.5, 1.0 - pct_val / 200)
    score = 0.0
    _val = getattr(analysis, "value", None)
    if _val is not None:
        try:
            score = float(getattr(_val, "score", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
    return round((score + action_bonus + th_bonus) * valuation_discount * dq_factor, 1)


# ============================================================
#  Helper: Whale Detection (4-factor weighted)
# ============================================================

def analyze_whale(prices, supply=None):
    """Whale/manipulation detection model."""
    wh = WhaleDetection()
    if not prices or len(prices) < 10:
        return wh

    n = len(prices)
    recent = min(15, n)

    # 1. Supply divergence (40%): 在售量骤增（供给堆积/派发嫌疑），替代原成交量维度（2026-08-07 去量）
    # 在售量 < 20 天时不参与（避免采样干扰）
    real_s_days = sum(1 for s in (supply or []) if s and s > 0)
    if supply and len(supply) >= recent and real_s_days >= 20:
        s_recent = supply[-recent:]
        s_mean = statistics.mean(s_recent) if s_recent else 1
        if s_mean > 0:
            max_s = max(s_recent)
            s_spike = max_s / s_mean if s_mean > 0 else 1
            s_score = min(20, max(0, (s_spike - 1.5) * 8))  # 供给骤增 = 派发嫌疑
            wh.volume_divergence_score = round(s_score, 1)

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
        # Check supply trend (去量：在售量趋势替代成交量)
        if supply and len(supply) >= 10:
            recent_s = sum(supply[-5:]) / 5
            prev_s = sum(supply[-10:-5]) / 5
            if prev_s > 0:
                s_ratio = recent_s / prev_s
                if s_ratio > 1.5:
                    vol_sig = "supply_up"
                elif s_ratio < 0.6:
                    vol_sig = "supply_down"

        if pct < 30 and wh.position_lock_score > 10:
            whale_type = "低位吸筹锁仓"
            wh.trading_rule = "疑似庄家低位吸筹锁仓，价格可能被压制，可轻仓试探但需耐心等待拉升"
        elif pct > 70 and vol_sig == "supply_down":
            whale_type = "供给收缩拉升"
            wh.trading_rule = "在售量收缩但价格高位拉升，疑似锁仓诱多，禁止追涨，持仓注意减仓"
        elif pct > 70 and vol_sig == "supply_up":
            whale_type = "高位供给涌出"
            wh.trading_rule = "疑似高位供给涌出，庄家在拉高过程中逐步派发，持仓应分批清仓"
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


# ============================================================
# 统一大脑阶段3：信号族注册制 + 状态桶 + 统一决策核心
# ============================================================
# 设计依据 references/engine-unified.md §3：
# - 不做期望排序/分档（阶段2 walk-forward 已证伪：条件期望跨时段漂移）
# - 固定经验优先级（与阶段2 前串行链代码顺序一致，重构保真）
# - 每族 = {触发条件, 状态桶标注, 固定仓位, 适用闸门集, 标签/详情/来源}
# - 闸门层按族声明：基础族全闸门，恐慌族守卫2+供给，后置族自带条件不额外加闸门
# - 新增信号族（S2回踩/牛动量）只需向 SIGNAL_FAMILIES 注册并声明闸门


@dataclass
class SignalFamily:
    """信号族定义（注册制）。

    - trigger: callable(features) -> bool，命中即候选
    - buckets: 状态桶标注（引擎口径，暂不硬性门控，供展示与研究）
    - guards:  命中后追加的闸门键（见 _GUARDS）；() = 自带条件不再追加
    - detail/sources: 决策条详情与 deduction 来源
    """

    key: str
    label: str
    priority: int
    limit: float | None = None
    trigger: object = None
    buckets: tuple = ()
    guards: tuple = ()
    detail: object = None
    sources: tuple = ()
    # 三要素元数据（2026-08-12 第四批 ①，量化专家框架）：假设 / 盈利对手盘 / 适用场景 / 失效信号
    hypothesis: str = ""
    counterparty: str = ""
    scenario: str = ""
    failure_signal: str = ""


def _dedup_hit(recent_buy_dates, signal_date, min_prio=None):
    """7 天内同品已触发买入信号 → 返回命中日期（用于去重）。

    min_prio（2026-08-16 优先级感知去重，CS_ENGINE_DEDUP_PRIO=1 时生效）：
    仅统计优先级 ≥ min_prio 的历史信号——低优先级信号（如买涨腿 28）不得借去重闸门
    压制高优先级信号（如供给收缩 30）的后续触发。条目格式 "YYYY-MM-DD" 或 "YYYY-MM-DD|P"
    （P=信号族优先级；无标签按 0=基础族处理）。
    """
    if not recent_buy_dates:
        return None
    from datetime import datetime as _dt
    if signal_date is None:
        signal_date = _dt.now().strftime("%Y-%m-%d")
    for d0 in recent_buy_dates:
        tag = d0
        prio = None  # 无标签（生产实盘路径）= 未知优先级 → 拦一切（保守）
        if "|" in str(d0):
            tag, _, p = str(d0).partition("|")
            try:
                prio = int(p)
            except ValueError:
                prio = None
        if min_prio is not None and prio is not None and prio < min_prio:
            continue
        try:
            gap = (_dt.strptime(signal_date[:10], "%Y-%m-%d") - _dt.strptime(tag[:10], "%Y-%m-%d")).days
        except ValueError:
            continue
        if 0 <= gap <= 7:
            return tag[:10]
    return None


DEDUP_PRIO_BY_LABEL = {"恐慌共振": 60, "深值": 50, "恐慌退潮": 40,
                       "供给收缩": 30, "吸筹型上涨": 28, "惜售中段": 25,
                       "相对强度": 32, "逆市走强": 31}


def dedup_prio_for_label(label):
    """action_label → 去重优先级（单一事实源）；未识别的 buy 标签（基础族/超跌等）按 0。"""
    lab = label or ""
    for k, v in DEDUP_PRIO_BY_LABEL.items():
        if k in lab:
            return v
    return 0


def _dedup_gate(F, prio):
    """7 日去重闸门统一入口：优先级感知（v2-T11 默认开）——低优先级历史信号不得拦
    高优先级新信号（防跨族抢跑顶替，实证见 decision-log 2026-08-16 去重修复条目；
    回归：开关关=186 基线逐键一致；开关开=+4 信号全胜/+2.83pp/maxDD 持平）。
    CS_ENGINE_DEDUP_PRIO=0 回退旧口径。"""
    if os.environ.get("CS_ENGINE_DEDUP_PRIO", "1") == "1":
        return _dedup_hit(F["recent_buy_dates"], F["signal_date"], min_prio=prio)
    return _dedup_hit(F["recent_buy_dates"], F["signal_date"])


def _state_bucket(market_180d_change, market_30d_change):
    """大盘五时期状态桶（2026-08-16 定稿，单一来源 market_context.state_bucket；旧六态已退役）。"""
    return state_bucket(market_180d_change, market_30d_change)


def _vol7_of(prices):
    """7 日波动率（近 7 日收益 std；D 族震荡吸筹指纹）。数据不足返回 None。"""
    try:
        if not prices or len(prices) < 8:
            return None
        rets = [(prices[j] - prices[j - 1]) / prices[j - 1]
                for j in range(len(prices) - 6, len(prices)) if prices[j - 1] > 0]
        if len(rets) < 3:
            return None
        m = sum(rets) / len(rets)
        return (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5
    except Exception:
        return None


def _dd20_of(prices):
    """20 日高点回撤（C 族二波：回调带）。数据不足返回 None。"""
    try:
        if not prices or len(prices) < 21:
            return None
        return (prices[-1] / max(prices[-21:-1]) - 1.0) * 100
    except Exception:
        return None


def _dd20_age_of(prices):
    """距 20 日高点的交易日数（C 族二波：回调龄）。数据不足返回 None。"""
    try:
        if not prices or len(prices) < 21:
            return None
        win = prices[-21:-1]
        return len(win) - 1 - win.index(max(win))
    except Exception:
        return None


def _bid_near(bid_history, date_str, span_days=4):
    """bid_history: [(date, price)] 升序；返回 ≤date_str 且在其前 span_days 内最近的价。"""
    try:
        if not bid_history:
            return None
        import bisect as _bis
        from datetime import datetime as _dt, timedelta as _td
        ds = str(date_str)[:10]
        d0 = _dt.strptime(ds, "%Y-%m-%d")
        lo = (d0 - _td(days=span_days)).strftime("%Y-%m-%d")
        keys = [x[0] for x in bid_history]
        i = _bis.bisect_right(keys, ds)
        cand = [v for dt, v in bid_history[max(0, i - 40):i] if dt >= lo]
        return cand[-1] if cand else None
    except Exception:
        return None


def _peak_date_of(signal_date, age):
    """20 日高点的日历近似日期（信号日减回调龄天）。"""
    try:
        from datetime import datetime as _dt, timedelta as _td
        if not signal_date or age is None:
            return None
        return (_dt.strptime(str(signal_date)[:10], "%Y-%m-%d") - _td(days=max(1, age))).strftime("%Y-%m-%d")
    except Exception:
        return None


def _rise_chg7_cap():
    """买涨腿 v2（2026-08-16）：chg7 上限开关。默认 15（3<chg7≤15 剔抛物线追涨）；
    ≤0 = 不设上限（v1 旧口径，已引擎级证伪）。env: CS_ENGINE_RISE_CHG7_CAP。"""
    try:
        cap = float(os.environ.get("CS_ENGINE_RISE_CHG7_CAP", "15"))
    except ValueError:
        cap = 15.0
    return cap


SIGNAL_FAMILIES = (
    SignalFamily(
        key="panic_resonance",
        label="🟢 恐慌共振·分批建仓",
        priority=60,
        limit=0.30,
        trigger=lambda F: (
            F["micro_th"] >= 60 and F["sent"] >= 75
            and "印花" not in F["name"] and "贴纸" not in F["name"]
            and F["current"] >= 15 and F["z"] is not None and F["z"] >= -2.2
            and F["drop21"] <= -18
            and F["pct"] is not None and F["pct"] <= 15
            and F["z"] is not None and F["z"] <= -1.5
            and not _dedup_gate(F, 60)  # panic_resonance
        ),
        buckets=("V型底区",),
        guards=("micro_th", "bid", "bid_boost", "market_distribution", "z_gate", "consecutive"),
        detail=lambda F: (
            f"极端恐慌(sent={F['sent']:.0f})+深度超跌(pct={F['pct']:.0f}%,Z={F['z']:.1f})"
            f"+短期反转(microTH={F['micro_th']})"
        ),
        sources=("panic_resonance_upgrade",),
        hypothesis="极端恐慌(sent≥75)+深度超跌(pct≤15%,Z≤-1.5)+短期反转(microTH≥60) → V 型底区反弹；回放 44 信号 win14 100%/avg14 +44.3",
        counterparty="恐慌抛售盘（割肉止损盘/追跌盘）",
        scenario="独立恐慌事件后的 V 型底区；大盘 21 日跌幅≤-18% 的极端环境（洗盘期最优定论）",
        failure_signal="恐慌后阴跌不反转（V 型失败）；44 信号=1 次事件簇（2026-05-22~27）——事件簇支撑，需独立事件复验",
    ),
    SignalFamily(
        key="deep_value",
        label="🟢 深值·大盘企稳·分批建仓",
        priority=50,
        limit=0.20,  # v2-T10（2026-08-15 O1 干净数据仓位网格）：0.15→0.20，cycle 186 组合 total +13.1pp / maxDD −12.63（改善）/ Calmar 23.0，前后半段一致
        trigger=lambda F: (
            F["pct"] is not None and F["pct"] <= 20
            and F["z"] is not None and F["z"] <= -0.5
            and F["th"] >= 35 and F["market_th"] >= 40
            # I-6 阴跌中继闸门 (2026-08-06 回放验证): 大盘 chg30 在 [-3,3) 横盘段期望 18-53% ，剔除；[-15,-3) 深跌修复段 85-93%
            # I-13 (2026-08-07 去量回测验证): 大盘 chg30>=3 上涨段深值失效（93信号14d 44%胜率/+2.2，跨10月40品，基线与去量版同款），仅保留 <=-3 企稳/修复环境
            and (F["mchg30"] is None or F["mchg30"] <= -3
                 or os.environ.get("CS_ENGINE_G2_UPSEG", "0") == "1")  # 审计②（2026-08-15）：G2 上涨段重开开关——干净数据 mchg30≥3 桶 +2.2% 反优于 ≤-3 桶 +0.92%
            and 40 <= F["sent"] <= 65 and F["drop21"] >= -5
            and not _dedup_gate(F, 50)  # deep_value
        ),
        buckets=("中性企稳", "弱市观望"),
        guards=("supply_expansion",),
        detail=lambda F: (
            f"深值低估(pct={F['pct']:.0f}%,Z={F['z']:.1f})"
            f"+大盘企稳(TH={F['market_th']},21日跌幅{F['drop21']:.1f}%)·"
            f"轻仓0.20·分批:首仓10%→跌10%加20%→跌15%加30%（单票敞口≤30%缩放）"
        ),
        sources=("deep_value_stable_market",),
        hypothesis="大盘企稳/修复环境(mchg30≤-3)下低分位(pct≤20%)+低估(Z≤-0.5)品均值回归；回放 56 信号 14d 75%/avg +14.9",
        counterparty="高位接盘/追涨盘（大盘上涨段深值失效：mchg30≥3 时 93 信号 14d 仅 44% 胜率/+2.2）",
        scenario="大盘深跌企稳段（mchg30 -15~-3，14d 85-93% 胜率）；中性企稳/弱市观望桶",
        failure_signal="大盘 mchg30∈[-3,3) 横盘段（期望 18-53% 已剔除）；mchg30≥3 上涨段（已剔除）；供给扩张>5%（禁买闸门）",
    ),
    SignalFamily(
        key="panic_easing",
        label="🟢 恐慌退潮·深跌止跌·分批建仓",
        priority=40,
        limit=0.10,
        trigger=lambda F: (
            F["pct"] is not None and F["pct"] <= 20
            and F["z"] is not None and F["z"] <= -1
            and 55 <= F["sent"] <= 80 and F["mchg30"] <= -15
            and F["stopped"]
            and not _dedup_gate(F, 40)  # panic_easing
        ),
        buckets=("V型底区", "阴跌中继区"),
        guards=(),
        detail=lambda F: (
            f"恐慌退潮(sent={F['sent']:.0f})+大盘30日跌幅{F['mchg30']:.1f}%(未企稳)"
            f"+深跌止跌(pct={F['pct']:.0f}%,Z={F['z']:.1f})·"
            f"轻仓0.10·分批:首仓10%→跌10%加20%→跌15%加30%（单票敞口≤30%缩放）"
        ),
        sources=("panic_easing_deep_bottom",),
        hypothesis="恐慌退潮(sent 55-80)+大盘深跌未企稳(mchg30≤-15)+深跌止跌(stopped) → 修复反弹；回放 14d +19.8",
        counterparty="恐慌期割肉盘（未企稳环境下的恐慌抛售）",
        scenario="恐慌事件后的退潮修复段（V 型底区/阴跌中继区）",
        failure_signal="退潮后二次探底（stopped 被证伪）；情绪反复/恐慌复发（sent 重新跌破 55）",
    ),
    SignalFamily(
        key="supply_accum",
        label="🟢 供给收缩·启动前吸筹·分批建仓",
        priority=30,
        limit=0.15,  # v2-T10（2026-08-15 O1 干净数据仓位网格）：0.10→0.15，cycle 186 组合 total +19.2pp / maxDD −14.64（改善）/ Calmar 20.26；旧 2026-08-10「降仓证伪」建立在伪零污染数据上，P2 证实 supply_accum 为稳族后重验通过
        trigger=lambda F: (
            len(F["supply_hist"]) >= 30 and len(F["prices"]) >= 8
            and not (F["survive"] > 0 and F["survive"] < 3000)
            and F["s30"] is not None and F["s30"] > 0
            and F["s7"] is not None and F["s7"] <= F["s30"] * 0.85
            and F["chg7"] is not None and abs(F["chg7"]) <= int(os.environ.get("CS_ENGINE_SUPPLY_ACCUM_CHG7_CAP", "3"))
            # T4（2026-08-10 第一性原理审计）：8 日动量门——「一周前拉涨、近7日横盘」的泵后横盘追高段禁买。
            # 实证：chg7<=3 但 chg8>3% 的 26 条信号 win14 42.3%/+4.14（2026-02 W2 反弹段集中 19 条）；
            # 只读全引擎模拟剔除后 wwin14 74.4->76.3%、wavg14 20.48->21.46、事件 14->15。
            # 已落地（2026-08-10 正式 A/B 通过）：默认开；env=0 可关闭做对照重放。
            and (os.environ.get("CS_ENGINE_SUPPLY_ACCUM_CHG8_CAP", "1") == "0"
                 or F["chg8"] is None or F["chg8"] <= 3)
            and not (F["sent"] < 40 and F["market_th"] < 45)
            and not _dedup_gate(F, 30)  # supply_accum
        ),
        buckets=("中性企稳", "弱市观望"),
        guards=(),
        detail=lambda F: (
            f"在售量收缩(7日均{F['s7']:.0f}≤30日均{F['s30']:.0f}×0.85)+价格平稳(7日{F['chg7']:+.1f}%)·"
            f"启动前吸筹·轻仓0.15·"
            f"分批:首仓10%→跌10%加20%→跌15%加30%（单票敞口≤30%缩放）"
        ),
        sources=("supply_contraction_accumulation",),
        hypothesis="在售量收缩(s7≤s30×0.85)+价格平稳(|chg7|≤3) = 启动前吸筹 → 拉升；回放 14d +11.2/30d +27.2，强牛段 30d +46.3",
        counterparty="派发盘/高位出货盘（供给扩张方）",
        scenario="供给收缩期（中性企稳/弱市观望桶）；强牛段(sent<40+大盘TH≥60)增强",
        failure_signal="假挂单/对倒虚缩（在售量口径失真，CS 庄家操纵）；泵后横盘追高段（chg8>3% 26 信号 42.3% 胜率已剔除）；开箱/赛事事件供给突变",
    ),
    SignalFamily(
        key="rise_accum",
        label="🟢 吸筹型上涨·强势买涨·分批建仓",
        # v3 实验（2026-08-16）：CS_ENGINE_RISE_PRIO 可提权（如 60=后置族首位），
        # 检验「腿本身好但被现存族抢先覆盖」假设；默认 28（supply_accum 30 之下）
        priority=int(os.environ.get("CS_ENGINE_RISE_PRIO", "28")),
        # v2-T12（2026-08-16 方案 I 落地）：limit 0.05（网格最优）+ 默认开（CS_ENGINE_RISE_ACCUM=0 关闭）
        limit=float(os.environ.get("CS_ENGINE_RISE_LIMIT", "0.05")),
        trigger=lambda F: (
            os.environ.get("CS_ENGINE_RISE_ACCUM", "1") == "1"
            and len(F["supply_hist"]) >= 60 and len(F["prices"]) >= 8
            and not (F["survive"] > 0 and F["survive"] < 3000)
            and F["s30"] is not None and F["s30"] > 0
            and F["s7"] is not None and F["s7"] <= F["s30"] * 0.85
            and F["chg7"] is not None and F["chg7"] > 3
            # v2（2026-08-16）：chg7 上限（默认 15）——v1 无上限致 2025-11 泵拉簇全灭
            # （德拉戈米尔 chg7 46/−27.97、闪回 37/−19.85、异星世界 29/−29.42 等）；≤0 关上限
            and (_rise_chg7_cap() <= 0 or F["chg7"] <= _rise_chg7_cap())
            # v2-T12：TH≥55 趋势段环境门（审计④ 正常市唯一正期望格；CS_ENGINE_RISE_TH_MIN=0 关）
            and (float(os.environ.get("CS_ENGINE_RISE_TH_MIN", "55")) <= 0
                 or F["market_th"] is not None and F["market_th"] >= float(os.environ.get("CS_ENGINE_RISE_TH_MIN", "55")))
            and F["supply_change_30d"] is not None and F["supply_change_30d"] > 5
            and not _dedup_gate(F, 28)  # rise_accum
        ),
        buckets=("中性企稳", "弱市观望"),
        guards=(),
        detail=lambda F: (
            f"吸筹型上涨(7日涨{F['chg7']:+.1f}%+供缩s7≤0.85s30+30日扩张{F['supply_change_30d']:+.0f}%+大盘TH≥55趋势段)·"
            f"轻仓0.05·持有21日或自高点回撤5%跟踪止盈离场（CS快涨快崩，方案I口径）"
        ),
        sources=("rise_accumulation",),
        hypothesis="价涨(chg7>3%)+供缩(s7≤0.85s30)+30日供给扩张(sc30>5%)=强势品吸筹型上涨（抽象派1337/合纵类）；买涨腿 A2 验证段去簇 155 win14 51.6%/avg14 +13.09 vs 价涨基线 45.3%/+4.86，置换 p_avg=0.002",
        counterparty="追涨盘/散户获利了结（上涨中供缩=买盘吸收挂单，接续上涨）",
        scenario="牛市中强势品的吸筹型上涨段；引擎唯一「买涨」腿（补齐 pct 高位强势品无覆盖的架构缺陷）",
        failure_signal="上涨中供缩为假吸筹（陷阱指纹 Δspread>8.9pp 待接入）；放量滞涨；供给扩张转派发",
    ),
    SignalFamily(
        key="rise_contract",
        label="🟢 深收缩慢涨·合纵型·分批建仓",
        # v6c（2026-08-16，用户决策「合纵收益最高」）：阈值 −10→−5 + 长持口径。
        # 数据：C1（sc30≤-5）池级 fit/val 随持有期单调上升——14d +1.19/+18.98、30d +4.93/+38.99、
        # 60d +13.08/+49.96、90d +21.85/+99.73、180d +49.33(win71%)/+140.41(win85%)；
        # 合纵 2025-02 入场 14d −2% 而 180d +105%。合纵型收益只在长持视野存在。
        priority=27,
        limit=0.05,
        trigger=lambda F: (
            os.environ.get("CS_ENGINE_RISE_CONTRACT", "0") == "1"
            and len(F["supply_hist"]) >= 60 and len(F["prices"]) >= 8
            and not (F["survive"] > 0 and F["survive"] < 3000)
            and F["s30"] is not None and F["s30"] > 0
            and F["s7"] is not None and F["s7"] <= F["s30"] * 0.85
            and F["chg7"] is not None and 3 < F["chg7"] <= 15
            and F["supply_change_30d"] is not None and F["supply_change_30d"] <= -5
            and F["market_th"] is not None and F["market_th"] >= 55
            and F["pct"] is not None and F["pct"] > 40
            and not _dedup_gate(F, 27)  # rise_contract
        ),
        buckets=("中性企稳",),
        guards=(),
        detail=lambda F: (
            f"深收缩慢涨(30日供给{F['supply_change_30d']:+.0f}%+7日续缩+温和上涨{F['chg7']:+.1f}%+TH≥55+分位{F['pct']:.0f}%)·"
            f"合纵型长持·轻仓0.05·持有180日（慢牛结构，短线14-30日无边际；供给收缩反转 sc30 回升>-5 离场）"
        ),
        sources=("rise_contract_accumulation",),
        hypothesis="30日供给深收缩(sc30≤-5)+7日续缩+温和上涨(3<chg7≤15)+TH≥55+分位>40 = 合纵型慢牛指纹；收益随持有期单调上升（池级 180d fit +49.33/win71%、val +140.41/win85%）——长持结构非摆动结构",
        counterparty="供给枯竭下的踏空盘/追涨盘（在售量持续收缩=持有人惜售+新供给不足）",
        scenario="TH≥55 趋势段的深供给收缩慢涨品（合纵 2025 型）；分位>40 强势域；长持 180 日口径",
        failure_signal="供给收缩反转（sc30 回升>-5）；开箱/新供给冲击；上涨转派发（s7/s30 回升）",
    ),
    SignalFamily(
        key="rs_accum",
        label="🟢 相对强度·独立强势·长持建仓",
        # 落地(2)（2026-08-17，P4 探针升格，预注册默认关 CS_ENGINE_RS_ACCUM=1 开）：
        # RS30=单品30d−大盘30d>10：fwd60 +39.8/win58.1%、fwd180 +117.6/win70.6%（n=16273），
        # 排除 rise_contract 指纹的互补子集 60d 仍 +41.3 → 独立增量。长持结构（hold 180）。
        # 落地判据=发射口径三关（组合级+前后半段+置换）+ 独特性护栏。
        priority=32,
        limit=0.05,
        trigger=lambda F: (
            os.environ.get("CS_ENGINE_RS_ACCUM", "0") == "1"
            and len(F["prices"]) >= 31
            and F["chg30"] is not None and F["mchg30"] is not None
            and F["chg30"] - F["mchg30"] > 10
            and F["pct"] is not None and F["pct"] > 40
            and not (F["survive"] > 0 and F["survive"] < 3000)
            and F["supply_change_30d"] is not None and F["supply_change_30d"] <= 5
            and not _dedup_gate(F, 32)  # rs_accum
            # 2026-08-17 补漏战役：族级 30 天重发冷却（D 族证伪根因=无时间窗约束；预注册）
            and not _cooldown_hit(F["recent_buy_dates"], F["signal_date"], 32, 30)
        ),
        buckets=("中性企稳", "弱市观望"),
        guards=(),
        detail=lambda F: (
            f"相对强度(单品30d{F['chg30']:+.1f}%−大盘{F['mchg30']:+.1f}%>10pp)+分位{F['pct']:.0f}%+供给未扩张)·"
            f"独立强势长持·轻仓0.05·参考持有180日（P4：60d +39.8/180d +117.6）"
        ),
        sources=("rs_accum_strength",),
        hypothesis="RS30>10（单品30d跑赢大盘10pp+）的强势品延续强势（P4：60d +39.8/180d +117.6，互补子集独立成立）——长持结构，与 rise_contract 互补",
        counterparty="卖出强势品换弱势品的轮动盘",
        scenario="任意时期的独立强势品（大盘涨跌无关的自身动量）",
        failure_signal="RS 转负（单品跑输大盘）；供给扩张>5%；动量崩坏（单日-8%）",
    ),
    SignalFamily(
        key="ct_accum",
        label="🟢 逆市走强·独立行情·长持建仓",
        # 落地(2)（2026-08-17，P11-Fa/P13-F1 升格，预注册默认关 CS_ENGINE_CT_ACCUM=1 开）：
        # 大盘 chg30<0 且单品 chg30>+5：14d +6.78/30d +23.82/60d +60.42（win69%）/180d +92.09（n=5205）。
        # 警示：P13 F1 事件占比 50.8%——事件依赖待发射口径拆解；落地判据同 rs_accum。
        priority=31,
        limit=0.05,
        trigger=lambda F: (
            os.environ.get("CS_ENGINE_CT_ACCUM", "0") == "1"
            and len(F["prices"]) >= 31
            and F["mchg30"] is not None and F["mchg30"] < 0
            and F["chg30"] is not None and F["chg30"] > 5
            and F["pct"] is not None and F["pct"] > 40
            and not (F["survive"] > 0 and F["survive"] < 3000)
            and F["supply_change_30d"] is not None and F["supply_change_30d"] <= 5
            and not _dedup_gate(F, 31)  # ct_accum
            # 2026-08-17 补漏战役：族级 30 天重发冷却（预注册）
            and not _cooldown_hit(F["recent_buy_dates"], F["signal_date"], 31, 30)
        ),
        buckets=("中性企稳", "弱市观望"),
        guards=(),
        detail=lambda F: (
            f"逆市走强(大盘30d{F['mchg30']:+.1f}%<0 而单品30d{F['chg30']:+.1f}%)+分位{F['pct']:.0f}%+供给未扩张)·"
            f"独立行情长持·轻仓0.05·参考持有180日（P11-Fa：60d +60.4/180d +92.1）"
        ),
        sources=("ct_accum_strength",),
        hypothesis="大盘走弱期单品逆市走强（mchg30<0 且 chg30>+5）= 资金独立运作指纹，长持延续（P11-Fa 180d +92.1）",
        counterparty="趁大盘弱市抛压的跟风盘",
        scenario="大盘 S3/S4 走弱期的逆市强势品（独特性发声通道）",
        failure_signal="补跌（大盘企稳后强势品反而回落）；供给扩张>5%；事件窗内单簇依赖",
    ),
    SignalFamily(
        key="volatile_accum",
        label="🟢 震荡吸筹·启动前·分批建仓",
        # D 族（2026-08-16 落地批次探针；默认关，重放证据见 decision-log U）：
        # 探针3 高波×慢涨×供缩（60d +28.7~32.1），但引擎发射口径 620 信号组合 −28.6pp/mdd −28.45
        # → 触发口径过宽，候选默认关（CS_ENGINE_D_ACCUM=1 开启 pilot）。
        # vol 阈值 0.03 = 全池 7 日波动率三分位上界（描述性常数，登记为假设）。
        priority=26,
        limit=0.05,
        trigger=lambda F: (
            os.environ.get("CS_ENGINE_D_ACCUM", "0") == "1"
            and len(F["supply_hist"]) >= 60 and len(F["prices"]) >= 8
            and not (F["survive"] > 0 and F["survive"] < 3000)
            and F["s30"] is not None and F["s30"] > 0
            and F["chg7"] is not None and 0 < F["chg7"] <= 5
            and F["supply_change_30d"] is not None and F["supply_change_30d"] <= -5
            and F["vol7"] is not None and F["vol7"] >= 0.03
            and F["pct"] is not None and F["pct"] > 40
            and not _dedup_gate(F, 26)  # volatile_accum
        ),
        buckets=("中性企稳",),
        guards=(),
        detail=lambda F: (
            f"震荡吸筹(高波动{F['vol7']:.2f}+慢涨{F['chg7']:+.1f}%+30日供缩{F['supply_change_30d']:+.0f}%+分位{F['pct']:.0f}%)·"
            f"启动前洗盘结构·轻仓0.05·族特征卡参考退出节奏（live pilot 口径）"
        ),
        sources=("volatile_accumulation",),
        hypothesis="高波动(vol7≥0.03)+慢涨(0<chg7≤5)+30日供给收缩(sc30≤-5)+分位>40 = 庄家震荡洗盘吸筹；探针3 池级 14d win45-46%/+5.6~6.9、60d win55-64%/+28.7~32.1（live-pilot 假设，C 通道监测）",
        counterparty="震荡中被洗出的散户（高波洗盘 + 供给收缩 = 筹码向庄家集中）",
        scenario="供给收缩期的震荡慢涨结构；分位>40 强势域（低位蓄势亚型未落地）",
        failure_signal="波动率转低且价格停滞（洗盘结束无拉升）；供给收缩反转；放量急拉脱离慢涨域（转 rise 域）",
    ),
    SignalFamily(
        key="second_wave",
        label="🟢 二波回调·强势承接·分批建仓",
        # C 族落地（2026-08-16 落地批次，默认关待重放验证 CS_ENGINE_C_WAVE=1 开启）：
        # 探针1 拐点——牛周期(mkt180>0)+高位(pct≥70)+回调带(-40~-5)+
        # 浅回调(-5~-10)1-5d 快进 / 深回调(≤-20)6d+ 等止跌且承接(bid抗跌≥0) / 中带任意龄。
        priority=24,
        limit=0.05,
        trigger=lambda F: (
            os.environ.get("CS_ENGINE_C_WAVE", "0") == "1"
            and F["mkt180"] is not None and F["mkt180"] > 0
            and F["pct"] is not None and F["pct"] >= 70
            and F["dd20"] is not None and -40 <= F["dd20"] <= -5
            and F["dd20_age"] is not None
            and (
                (F["dd20"] >= -10 and F["dd20_age"] <= 5)
                or (-20 < F["dd20"] < -10)
                or (F["dd20"] <= -20 and F["dd20_age"] >= 6
                    and F["bid_now"] is not None and F["bid_peak"] is not None
                    and F["bid_peak"] > 0
                    and (F["bid_now"] / F["bid_peak"] - 1) * 100 - F["dd20"] >= 0)
            )
            and len(F["supply_hist"]) >= 30 and len(F["prices"]) >= 8
            and not (F["survive"] > 0 and F["survive"] < 3000)
            and not _dedup_gate(F, 24)  # second_wave
        ),
        buckets=("中性企稳",),
        guards=(),
        detail=lambda F: (
            f"二波回调(牛周期+分位{F['pct']:.0f}%+20日回撤{F['dd20']:+.0f}%+回调龄{F['dd20_age']}d"
            f"{'+承接' if F['dd20'] <= -20 else ''})·"
            f"轻仓0.05·浅回调快进/深回调等止跌（探针1 拐点口径）"
        ),
        sources=("second_wave_pullback",),
        hypothesis="牛周期(mkt180>0)+高位(pct≥70)+真实回调(-5~-40)+回调龄匹配深度（浅快进/深等止跌+承接）= 二波；探针1 深回调6-10d+承接 14d win55%/+17.3、60d 71%/+68.9",
        counterparty="回调中恐慌离场的短线盘（强势品洗盘换手）",
        scenario="牛市大周期中的强势品回调段；C/A 边界=坑深-30~-40 与恐慌情绪叠加处归 A",
        failure_signal="回调转阴跌（dd20 破-40 且无承接）；大盘转熊（mkt180 转负）；求购崩塌",
    ),
    SignalFamily(
        key="xishou_mid",
        label="🟢 惜售中段·超跌反弹·分批建仓",
        priority=25,
        limit=0.10,
        trigger=lambda F: (
            os.environ.get("CS_ENGINE_XISHOU_MID", "0") == "1"
            and len(F["supply_hist"]) >= 30 and len(F["prices"]) >= 8
            and not (F["survive"] > 0 and F["survive"] < 3000)
            and F["s30"] is not None and F["s30"] > 0
            and F["s7"] is not None and F["s7"] <= F["s30"] * 0.85
            and F["chg5"] is not None and F["chg5"] < -3
            and F["pct"] is not None and 20 < F["pct"] <= 60
            and not (F["sent"] < 40 and F["market_th"] < 45)
            and not _dedup_gate(F, 25)  # xishou_mid
        ),
        buckets=("中性企稳", "弱市观望"),
        guards=("supply_expansion",),
        detail=lambda F: (
            f"惜售中段(供缩s7≤0.85s30+5日跌{F['chg5']:+.1f}%+分位{F['pct']:.0f}%)·"
            f"A2验证14d超额win+20.5pp/avg+9.36pp(置换p=0.018/0.034)·轻仓0.10"
        ),
        sources=("xishou_mid_oversold",),
        hypothesis="供缩(s7≤0.85s30)+价跌(5日<-3%)+中段分位(pct20~60)=下跌惜售/超跌反弹；O3 A2 验证段去簇 27 win14 59.3%/avg14 +10.77 vs 中段无条件基线 38.8%/+1.41，置换 p=0.018/0.034",
        counterparty="恐慌性抛售/止损盘（中段分位非深跌，卖方惜售遇反弹）",
        scenario="供缩+价跌的中段回调（pct 20~60 为引擎当前无覆盖带）；拟合/验证段方向一致",
        failure_signal="供缩+价跌后继续阴跌（惜售转恐慌）；地板以下无深度；供给扩张>5%",
    ),
)

SIGNAL_FAMILY_BY_KEY = {fam.key: fam for fam in SIGNAL_FAMILIES}
# 后置升级族（守卫链之后评估）：深值企稳 > 恐慌退潮 > 供给收缩（固定优先级，与现链路代码顺序一致）
_POST_FAMILIES = tuple(sorted(
    (fam for fam in SIGNAL_FAMILIES if fam.key != "panic_resonance"),
    key=lambda f: -f.priority,
))


# ---- 大盘时期路由（2026-08-16 预注册 → v2-T13 默认开；CS_ENGINE_PERIOD_ROUTE=0 关闭）----
# 证据 = references/probe_period_family_hq.py → data/_exp_period_family_hq.json
# （HQ 官方回放 233 信号 × 五时期 × 族，net 已扣 2%）：
#   rise_accum  S1 n=29 win14 31%/+0.65（差，追高腿在慢牛上行段不成立）；
#   deep_value  S3 n=6 0%/-5.67（弱市阴跌里深值接刀全亏）；
#   supply_accum S3 n=6 16.7%/-8.88@14d、S4 n=4 0%/-9.08（阴跌/反抽里吸筹语义错配）；
#   对照：S2 回调买全族正（deep_value 30d +76.6 全场最强）；base 基础族在 S3 仍 77.8%/+27.4（不设禁）。
# 发射口径重放三关（probe_period_route_compare.py → _exp_period_route_compare.json）：
#   组合级 total +367.67→+397.02（+29.35pp）maxDD −19.99→−14.09（改善 5.90pp）；
#   前后半段（切点 2026-03-02）front +9.77pp / back +4.44pp 双正；
#   置换检验 200 次随机移除同规模：dTotal 中位 −41.40（p=0.000）/ dMaxDD p90 +4.75（p=0.035）→ 选择性闸门成立。
# 落地默认开（v2-T13）；C 通道月度胜率/期望监测照常覆盖（P1 后验保险丝）。
PERIOD_ROUTE_BAN = {
    "rise_accum": ("S1牛市上行",),
    "deep_value": ("S3弱市阴跌",),
    "supply_accum": ("S3弱市阴跌", "S4弱市反弹"),
}


def _period_route_ok(fam_key, period):
    """时期路由放行：默认开（v2-T13）；CS_ENGINE_PERIOD_ROUTE=0 关闭对照。"""
    if os.environ.get("CS_ENGINE_PERIOD_ROUTE", "1") != "1":
        return True
    return period not in PERIOD_ROUTE_BAN.get(fam_key, ())


def _cooldown_hit(recent_buy_dates, signal_date, prio, days=30):
    """族级重发冷却（2026-08-17 预注册战役：长持族 30 天冷却）：
    同族（同去重优先级）在 days 天内已发射过 → 拦截（返回命中日期）。
    无 prio 标签的历史条目保守跳过（生产旧行）；与 7 天通用去重独立。"""
    if not recent_buy_dates or signal_date is None:
        return None
    from datetime import datetime as _dt, timedelta as _td
    try:
        sd = _dt.strptime(str(signal_date)[:10], "%Y-%m-%d")
    except ValueError:
        return None
    for d0 in recent_buy_dates:
        tag, p = str(d0), None
        if "|" in str(d0):
            tag, _, ps = str(d0).partition("|")
            try:
                p = int(ps)
            except ValueError:
                p = None
        if p is None or p != prio:
            continue
        try:
            if (sd - _dt.strptime(tag[:10], "%Y-%m-%d")).days < days:
                return tag[:10]
        except ValueError:
            continue
    return None


def _period_route_note(fd, fam_key):
    """路由拦截留痕（展示层）：族触发但被时期路由禁发。"""
    _src = "period_route:%s" % fam_key
    if _src not in fd.deduction_sources:
        fd.deduction_sources.append(_src)


# ---- 闸门实现：返回 (label, detail, source) 或 None（不命中）----
def _g_market_weak(fd, F):
    if fd.action != "buy":
        return None
    # 实验/对照开关：CS_ENGINE_NO_MARKET_WEAK=1 豁免大盘走弱拦截（重放验证用，默认行为不变）
    if os.environ.get("CS_ENGINE_NO_MARKET_WEAK") == "1":
        return None
    if F["market_th"] < 45 and F["mchg30"] < 0:
        return ("🟡 大盘走弱·观望",
                f"大盘TH={F['market_th']}且30日跌幅{F['mchg30']:.1f}%，弱势环境禁止新开仓",
                "market_weak_filter")
    if F["sent"] <= 30:
        return ("🟡 情绪贪婪·禁止追买",
                f"市场情绪贪婪(sent={F['sent']:.0f})，追买期望为负",
                "greedy_no_buy")
    return None


def _g_survive(fd, F):
    if fd.action != "buy" or not (0 < F["survive"] < 3000):
        return None
    return ("🟡 存世量过低·不建仓",
            f"存世量仅 {F['survive']} 件（<3000），流动性差，价格易失真",
            "survive_too_low")


def _g_halfway(fd, F):
    if fd.action != "buy" or F["pct"] is None or not (25 <= F["pct"] <= 40) or F["sent"] >= 85:
        return None
    return ("🟡 半山腰·观望",
            f"pct={F['pct']:.0f}%处于半山腰且无恐慌共振",
            "halfway_downgrade")


def _g_dedup(fd, F):
    if fd.action != "buy":
        return None
    hit = _dedup_gate(F, 0)  # 基础族优先级 0：被任何历史 buy（含各族）拦
    if not hit:
        return None
    return ("🟡 已在买点区·等待回调",
            f"7日内({hit})已触发买入信号，避免重复建仓",
            "buy_cluster_dedup")


def _g_falling_knife(fd, F):
    if fd.action != "buy" or F["z"] is None or F["z"] >= -2 or len(F["prices"]) < 4:
        return None
    low3 = min(F["prices"][-3:])
    if F["current"] <= low3 and F["chg3d"] is not None and F["chg3d"] <= 0:
        return ("🟡 飞刀未止跌·观望",
                f"Z={F['z']:.1f}深度超跌但仍在创新低且3日续跌{F['chg3d']:.1f}%，等待止跌确认",
                "falling_knife_filter")
    return None


def _g_micro_th(fd, F):
    if fd.action != "buy" or F["micro_th"] >= 45:
        return None
    return ("🟡 短期动能弱·观望",
            f"14日微型TH={F['micro_th']}，短期动能不足，等待反转确认",
            "micro_th_weak")


def _g_bid(fd, F):
    if fd.action != "buy" or F["bid_score"] > 25:
        return None
    return ("🟡 求购承接弱·观望",
            f"求购承接弱(score={F['bid_score']})，买盘意愿不足，暂缓建仓",
            "bid_support_weak")


def _g_bid_boost(fd, F):
    """求购承接增强注解（仅 watch 状态；与现链路 G7 的 elif 分支位置一致）。"""
    if fd.action == "watch" and F["bid_score"] >= 75 and F["pct"] is not None and F["pct"] <= 30:
        fd.action_label = "🟡 底部观察·承接增强"
        fd.action_detail = "低位且求购承接增强，纳入观察；不直接建仓，等待承接持续确认"
    return None


def _g_market_distribution(fd, F):
    if F["market_cycle"] != "distribution" or fd.action not in ("buy", "hold"):
        return None
    return ("🟡 大盘出货期·观望",
            fd.action_detail + "（大盘处于出货期，建仓/持有信号降级为观望）",
            "market_distribution_filter")


def _g_z_gate(fd, F):
    if fd.action != "buy" or F["z"] is None:
        return None
    gates = {"accumulation": -0.5, "consolidation": -1.0, "distribution": -1.5, "markup": 0, "unknown": -1.0}
    thr = gates.get(F["cycle_phase"], -1.0)
    if F["z"] > thr:
        return ("🟡 Z偏高·等待更优入场",
                f"Z={F['z']} 要求≤{thr}，估值未达极端低位",
                "item_z_gate")
    return None


def _g_consecutive(fd, F):
    if fd.action != "buy" or len(F["prices"]) < 7 or F["pct"] is None or F["pct"] <= 5:
        return None
    if F["chg3d"] is not None and abs(F["chg3d"]) < 1.5:
        return ("🟡 已在买入区·等待回调",
                f"3日价格变动{F['chg3d']:+.1f}%，无需重复触发买入",
                "consecutive_buy")
    return None


def _g_supply_expansion(fd, F):
    if fd.action not in ("buy", "oversold_buy"):
        return None
    chg = F["supply_change_30d"]
    if chg and chg > 5 and "deep_dip_exemption" not in fd.deduction_sources:
        # 审计③（2026-08-15）：吸筹型上涨豁免开关——30 日扩张 + 7 日收缩 = 强势品吸筹
        # （avg14 +6.78/avg30 +12.77 全场最强结构，旧「5/5 负期望」是小样本误判）
        if (os.environ.get("CS_ENGINE_G3_ACCUM", "0") == "1"
                and F["s30"] is not None and F["s30"] > 0
                and F["s7"] is not None and F["s7"] <= F["s30"] * 0.85):
            return None
        return ("🟡 供给扩张·观望",
                f"在售量30日扩张{round(chg, 1)}%，抛压堆积，结构性派发风险",
                "supply_expansion_filter")
    return None


_GUARDS = {
    "market_weak": _g_market_weak,
    "survive": _g_survive,
    "halfway": _g_halfway,
    "dedup7": _g_dedup,
    "falling_knife": _g_falling_knife,
    "micro_th": _g_micro_th,
    "bid": _g_bid,
    "bid_boost": _g_bid_boost,
    "market_distribution": _g_market_distribution,
    "z_gate": _g_z_gate,
    "consecutive": _g_consecutive,
    "supply_expansion": _g_supply_expansion,
}

# 基础族闸门集（守卫1 在恐慌升级前；守卫2 在升级/变换后，buy/hold/watch 均评估）
_GUARD1 = ("market_weak", "survive", "halfway", "dedup7", "falling_knife")
_GUARD2 = ("micro_th", "bid", "bid_boost", "market_distribution", "z_gate", "consecutive")


def _apply_guards(fd, F, keys):
    """按序执行闸门，首个命中即降级为 watch（与现串行链一致，后续闸门跳过）。"""
    for k in keys:
        veto = _GUARDS[k](fd, F)
        if veto is None:
            continue
        label, detail, src = veto
        fd.action = "watch"
        fd.action_label = label
        fd.action_detail = detail
        fd.deduction_sources.append(src)
        fd.position_limit = 0.0
        return k
    return None


def _apply_buy(fd, fam, F):
    fd.action = "buy"
    fd.action_label = fam.label
    fd.action_detail = fam.detail(F) if fam.detail else fam.label
    fd.deduction_sources.append(fam.sources[0] if fam.sources else fam.key)
    if fam.limit is not None:
        fd.position_limit = fam.limit


def _deep_dip_transform(fd, F):
    """P0-7b：周期吸筹 buy 需大盘深跌共振；D方案深度回调低吸例外。"""
    if not (fd.action == "buy" and "吸筹" in fd.action_label and F["drop21"] > -18):
        return False
    if getattr(fd, "liquidity_filtered", False):
        return False
    if F["dd30"] <= -22 and F["chg14"] <= -6:
        fd.action_label = "🟢 深度回调低吸·分批建仓"
        fd.action_detail = ("周期吸筹但大盘未深跌，单品深度回调"
                            f"(dd30={F['dd30']:.0f}%,chg14={F['chg14']:.0f}%)二次探底")
        fd.deduction_sources.append("deep_dip_exemption")
    else:
        fd.action = "watch"
        fd.action_label = "🟡 周期吸筹需大盘共振·观望"
        fd.action_detail = "周期吸筹但大盘20日跌幅" + str(round(F["drop21"], 1)) + "%~18%，等大盘深跌共振再建仓"
        fd.deduction_sources.append("cycle_accumulation_needs_market_drop")
        fd.position_limit = 0.0
    return True


# ============================================================
#  买点接近度（纯展示层，2026-08-07）
# ============================================================
#  买点接近度（纯展示层，2026-08-07）
# ============================================================
# 决策条只给定性标签（筑底/回调/震荡…），看不出离 buy 族还差多远。
# 本函数对每个 buy 信号族算「条件达标度 0~100%」（几何平均，任一硬条件
# 不达标即归零），取最接近一族展示，并列出最近的缺口。
# 只供报告展示，不参与任何决策；参数冻结不受影响。

_FAM_PRIORITY = {"base": 0, "panic": 5, "deep": 4, "easing": 3, "supply": 2, "oversold": 1}


def _prog_high(x, ok, zero):
    """x >= ok → 1.0；x <= zero → 0.0；之间线性过渡。"""
    if x is None:
        return None
    if x >= ok:
        return 1.0
    if x <= zero:
        return 0.0
    return (x - zero) / (ok - zero)


def _prog_low(x, ok, zero):
    """x <= ok → 1.0；x >= zero → 0.0；之间线性过渡。"""
    if x is None:
        return None
    if x <= ok:
        return 1.0
    if x >= zero:
        return 0.0
    return (zero - x) / (zero - ok)


def _prog_abs(x, ok, zero):
    """|x| <= ok → 1.0；|x| >= zero → 0.0；之间线性过渡。"""
    if x is None:
        return None
    a = abs(x)
    if a <= ok:
        return 1.0
    if a >= zero:
        return 0.0
    return (zero - a) / (zero - ok)


def _prog_range(x, lo_ok, hi_ok, lo_zero, hi_zero):
    """x ∈ [lo_ok, hi_ok] → 1.0；向两侧线性衰减至 0。"""
    if x is None:
        return None
    if lo_ok <= x <= hi_ok:
        return 1.0
    if x < lo_ok:
        return 0.0 if x <= lo_zero else (x - lo_zero) / (lo_ok - lo_zero)
    return 0.0 if x >= hi_zero else (hi_zero - x) / (hi_zero - hi_ok)


def _prog_window(x, lo, hi, lo_zero, hi_zero):
    """x ∈ [lo, hi] → 1.0（触发窗口）；向两侧线性衰减至 0。"""
    if x is None:
        return None
    if lo <= x <= hi:
        return 1.0
    if x < lo:
        return 0.0 if x <= lo_zero else (x - lo_zero) / (lo - lo_zero)
    return 0.0 if x >= hi_zero else (hi_zero - x) / (hi_zero - hi)


def compute_buy_proximity(F):
    """距最近 buy 信号族的达标度(0~100) + 缺口提示。纯展示，不参与决策。

    返回 {"score": int, "nearest": str, "gaps": [str, ...], "zero_reason": str}；
    缺数据的条件按不达标计 0（不产生缺口提示）；数据不足半数的族不参与评估；
    score==0 时 zero_reason 说明清零原因（数据不足 / 各路径均有硬缺口）。
    """
    def _note(v, label, fmt, need, hint=""):
        """缺口文案：{label}：{当前值}（需 {need}）{hint}；数据缺失返回 None。"""
        if v is None:
            return None
        text = "{}：{}（需 {}）".format(label, fmt.format(v), need)
        return text + hint if hint else text

    def _fam(key, label, conds):
        vals = [p for _, p, _n in conds if p is not None]
        if len(vals) < (len(conds) + 1) // 2:
            return None
        prod = 1.0
        for v in vals:
            prod *= v
        return {"key": key, "label": label, "score": prod ** (1.0 / len(vals)), "conds": conds}

    pct, z = F.get("pct"), F.get("z")
    th = F.get("th")
    sent, mth = F.get("sent"), F.get("market_th")
    mchg30, drop21 = F.get("mchg30"), F.get("drop21")
    prices = F.get("prices") or []
    current = F.get("current")
    supply_hist = F.get("supply_hist") or []
    s7, s30 = F.get("s7"), F.get("s30")
    chg7, chg3d = F.get("chg7"), F.get("chg3d")
    chg8 = F.get("chg8")
    _dedup_hit_flag = _dedup_hit(F.get("recent_buy_dates"), F.get("signal_date"))
    dedup = 1.0 if not _dedup_hit_flag else 0.0

    # 基础族：低估区 buy（pct<=30 + 趋势确认(th>=55=TH_STRONG) + Z 闸门）——对齐 compute_fusion_decision。
    # 2026-08-18 修正（E 类「拿历史均值当引擎买点」）：原「深跌确认 _prog_low(th,35,55)」把 th≤35 当
    # 「黄金坑=100% ready」，源自 369 信号「th<35 win 94%/+36%」的研究结论；但该结论是 P 期事件选择偏差
    # （全宇宙「pct≤30 & th<35」fwd14 按时期拆：P +26.1% / S1 +5.2% / S2 +1.8% / S3 −4.78% / S4 +8.3%），
    # 而引擎 compute_fusion_decision 低估区只在 th≥55(TH_STRONG) 才 buy、th<35 是 avoid/下跌中继。
    # → proximity 度量的是引擎不会发射的买点，已把方向画反（重放 15836 条「距买点100%但不买」96% 归因于此）。
    # 修正：th≥55 → ready（_prog_high），与 TH_STRONG 触发同源。纯展示层，不参与决策。
    z_gate = {"bear": 0, "consolidation": 0, "accumulation": 0.5, "markup": 1.0, "distribution": -0.5}.get(F.get("market_cycle"), 0)
    base = _fam("base", "低估区建仓", [
        ("低估分位", _prog_low(pct, 30, 45), _note(pct, "位置分位", "{:.0f}%", "≤30%", "，越低越便宜")),
        ("趋势确认", _prog_high(th, 55, 35), _note(th, "趋势分", "{:.0f}", "≥55 趋势确认", "（35-54 摩擦带，<35 下跌中继）")),
        ("Z闸门", _prog_low(z, z_gate, z_gate + 1.0), _note(z, "估值Z", "{:.2f}", "≤{:.1f}".format(z_gate))),
    ])

    # 恐慌共振
    panic = _fam("panic", "恐慌共振", [
        ("微型TH", _prog_high(F.get("micro_th"), 60, 45), _note(F.get("micro_th"), "恐慌度(微型TH)", "{:.0f}", "≥60")),
        ("恐慌情绪", _prog_high(sent, 75, 55), _note(sent, "市场情绪", "{:.0f}", "≥75")),
        ("价格下限", _prog_high(current, 15, 10), None),
        ("超跌Z窗口", _prog_window(z, -2.2, -1.5, -3.0, -0.5), _note(z, "估值Z", "{:.2f}", "需-2.2~-1.5")),
        ("21日深跌", _prog_low(drop21, -18, -8), _note(drop21, "大盘21日", "{:.1f}%", "≤-18%")),
        ("90日分位", _prog_low(pct, 15, 30), _note(pct, "位置分位", "{:.0f}%", "≤15%")),
        ("7日去重", dedup, None),
    ])

    # 深值·大盘企稳
    deep = _fam("deep", "深值企稳", [
        ("深值分位", _prog_low(pct, 20, 35), _note(pct, "位置分位", "{:.0f}%", "≤20%")),
        ("深值Z", _prog_low(z, -0.5, 0.5), _note(z, "估值Z", "{:.2f}", "≤-0.5")),
        ("单品TH", _prog_high(th, 35, 20), _note(th, "单品趋势分", "{:.0f}", "≥35")),
        ("大盘TH", _prog_high(mth, 40, 30), _note(mth, "大盘趋势分", "{:.0f}", "≥40")),
        ("大盘30日", 1.0 if mchg30 is None else _prog_low(mchg30, -3, 3),
         None if mchg30 is None else _note(mchg30, "大盘30日", "{:.1f}%", "≤-3%")),
        ("情绪区间", _prog_range(sent, 40, 65, 25, 80), _note(sent, "市场情绪", "{:.0f}", "40~65")),
        ("21日企稳", _prog_high(drop21, -5, -15), _note(drop21, "大盘21日", "{:.1f}%", "≥-5%")),
        ("7日去重", dedup, None),
    ])

    # 恐慌退潮
    easing = _fam("easing", "恐慌退潮", [
        ("深值分位", _prog_low(pct, 20, 35), _note(pct, "位置分位", "{:.0f}%", "≤20%")),
        ("深值Z", _prog_low(z, -1, 0), _note(z, "估值Z", "{:.2f}", "≤-1")),
        ("退潮情绪", _prog_range(sent, 55, 80, 35, 100), _note(sent, "市场情绪", "{:.0f}", "55~80")),
        ("大盘深跌", _prog_low(mchg30, -15, -5), _note(mchg30, "大盘30日", "{:.1f}%", "≤-15%")),
        ("止跌确认", 1.0 if F.get("stopped") else 0.0, None),
        ("7日去重", dedup, None),
    ])

    # 供给收缩吸筹（高位剔除：pct>70 的供给收缩按庄家「锁仓诱多」口径，不作买点路径）
    ratio = (s7 / s30) if (s7 and s30) else None
    if pct is not None and pct > 70:
        supply = None
    else:
        supply = _fam("supply", "供给收缩吸筹", [
            ("数据长度", 1.0 if (len(supply_hist) >= 30 and len(prices) >= 8) else 0.0, None),
            ("存世量", 1.0 if not (0 < F.get("survive", 0) < 3000) else 0.0, None),
            ("30日供给", 1.0 if (s30 is not None and s30 > 0) else 0.0, None),
            ("供给收缩", _prog_low(ratio, 0.85, 1.0),
             None if ratio is None else "供给收缩：7日/30日在售量 {:.2f}（需 ≤0.85，收缩15%+才达标）".format(ratio)),
            ("价格平稳", _prog_abs(chg7, 3, 6), _note(chg7, "7日价变", "{:+.1f}%", "|≤3%|", "，需价格平稳")),
            # T4（2026-08-10）8 日动量门：chg8>3% = 泵后横盘追高段禁买（proximity 补漏，对齐 supply_accum trigger）
            ("8日动量", 1.0 if (chg8 is None or chg8 <= 3) else _prog_low(chg8, 3, 8),
             None if chg8 is None else _note(chg8, "8日动量", "{:+.1f}%", "≤3%", "，泵后横盘追高禁买")),
            ("大盘共振", 1.0 if not (sent is not None and sent < 40 and mth is not None and mth < 45) else 0.0, None),
            ("7日去重", dedup, None),
        ])

    # 超跌反弹例外
    low2 = min(prices[-2:]) if len(prices) >= 2 else None
    low3 = min(prices[-3:]) if len(prices) >= 3 else None
    no_new_low = 1.0 if (low2 is not None and low3 is not None and low2 > low3) else 0.0
    oversold = _fam("oversold", "超跌反弹", [
        ("超跌分位", _prog_low(pct, 15, 30), _note(pct, "位置分位", "{:.0f}%", "≤15%")),
        ("超跌Z", _prog_low(z, -2.0, -1.0), _note(z, "估值Z", "{:.2f}", "≤-2.0")),
        ("不再创新低", no_new_low, None),
        ("3日转涨", _prog_high(chg3d, 0, -3), _note(chg3d, "3日价变", "{:+.1f}%", ">0", "，需转涨")),
    ])

    fams = [f for f in (base, panic, deep, easing, supply, oversold) if f]
    if not fams:
        return {"score": 0, "nearest": "—", "gaps": [], "zero_reason": "数据不足，无法评估买点路径",
                "dedup_hit": _dedup_hit_flag, "recent_buy_dates": F.get("recent_buy_dates") or []}
    best = max(fams, key=lambda f: (f["score"], -_FAM_PRIORITY[f["key"]]))
    if best["score"] <= 0:
        _ZERO_HINT = {"7日去重": "7日内已买过", "止跌确认": "仍未见止跌",
                      "不再创新低": "仍在创新低", "价格下限": "价格未达下限",
                      "存世量": "存世量过低"}
        _cnt = {}
        for _f in fams:
            for _desc, _p, _n in _f["conds"]:
                if _p == 0:
                    _cnt[_desc] = _cnt.get(_desc, 0) + 1
        _top = sorted(_cnt.items(), key=lambda kv: -kv[1])[:2]
        _parts = [d + ("（" + _ZERO_HINT.get(d, "") + "）" if _ZERO_HINT.get(d) else "") for d, _c in _top]
        return {"score": 0, "nearest": "—", "gaps": [],
                "zero_reason": "各买点路径均有硬缺口：" + "、".join(_parts) + "；暂无接近路径",
                "dedup_hit": _dedup_hit_flag, "recent_buy_dates": F.get("recent_buy_dates") or []}
    gaps = []
    for _desc, p, note in sorted(best["conds"], key=lambda c: (c[1] if c[1] is not None else 1.0)):
        if p is not None and 0 < p < 1 and note:
            gaps.append(note)
        if len(gaps) >= 2:
            break
    return {"score": int(round(best["score"] * 100)), "nearest": best["label"], "gaps": gaps, "zero_reason": "",
            "dedup_hit": _dedup_hit_flag, "recent_buy_dates": F.get("recent_buy_dates") or []}

def decide_fusion_signal(
    fd, *, position, cycle, th, value, prices, current, n, name,
    survive_count, sentiment_score, market_th_score, market_30d_change,
    market_drop21, market_cycle, supply, supply_hist, bid_support, micro_th,
    recent_buy_dates, signal_date, market_180d_change=0.0, bid_history=None,
):
    """统一决策核心：基础融合决策 + 信号族注册制升级 + 族级闸门。

    语义与阶段2 前串行链保真（engine-unified.md §4.2：阶段3 只做架构统一，不做期望分档）。
    返回 (fd, state_bucket)。
    """
    F = {
        "name": name, "current": current, "prices": prices, "n": n,
        "pct": position.percentile_90d, "z": position.zscore_90d,
        "th": th.score if hasattr(th, "score") else 50,
        "micro_th": micro_th,
        "sent": sentiment_score, "market_th": market_th_score,
        "mchg30": market_30d_change, "drop21": market_drop21,
        "market_cycle": market_cycle,
        "cycle_phase": cycle.phase if hasattr(cycle, "phase") else "unknown",
        "survive": survive_count, "supply_hist": supply_hist,
        "s7": sum(supply_hist[-7:]) / 7 if len(supply_hist) >= 7 else None,
        "s30": sum(supply_hist[-30:]) / 30 if len(supply_hist) >= 30 else None,
        "chg7": (current / prices[-8] - 1) * 100 if len(prices) >= 8 else None,
        "chg5": (current / prices[-6] - 1) * 100 if len(prices) >= 6 else None,
        # 落地(2)（2026-08-17）：单品 30 日动量（相对强度 rs30 = chg30 − mchg30 用）
        "chg30": (current / prices[-31] - 1) * 100 if len(prices) >= 31 else None,
        # T4（2026-08-10）：8 日动量（current vs 8 个交易日前），供吸筹族泵后横盘门使用
        "chg8": (current / prices[-9] - 1) * 100 if len(prices) >= 9 else None,
        "dd30": (current / max(prices[-30:]) - 1) * 100 if len(prices) >= 30 else 0.0,
        "chg14": (current / prices[-15] - 1) * 100 if len(prices) >= 15 else 0.0,
        "chg3d": (current - prices[-4]) / prices[-4] * 100 if len(prices) >= 4 else None,
        "stopped": len(prices) >= 3 and current >= prices[-2] and current >= prices[-3],
        "recent_buy_dates": recent_buy_dates, "signal_date": signal_date,
        "bid_score": bid_support.get("score", 50) if isinstance(bid_support, dict) else 50,
        "supply_change_30d": getattr(supply, "supply_change_30d", None),
        # D 族（2026-08-16 落地批次）：7 日波动率（日收益 std，震荡吸筹指纹）
        "vol7": _vol7_of(prices),
        # C 族（2026-08-16 落地批次）：二波回调量（回撤/龄/承接）
        "mkt180": market_180d_change,
        "dd20": _dd20_of(prices),
        "dd20_age": _dd20_age_of(prices),
        "bid_now": _bid_near(bid_history, signal_date),
        "bid_peak": _bid_near(bid_history, _peak_date_of(signal_date, _dd20_age_of(prices))),
    }
    bucket = _state_bucket(market_180d_change, market_30d_change)

    # ---- 基础族：守卫1（市场弱/存世量/半山腰/7天去重/飞刀确认）----
    _apply_guards(fd, F, _GUARD1)

    # ---- 升级族1：恐慌共振（守卫1 之后评估；跳过守卫1，保留守卫2+供给）----
    # F-3.5（2026-08-08）：流动性闸门禁升级——liquidity_filtered 的品（在售量过低）任何升级族都不得恢复 buy
    panic_fam = SIGNAL_FAMILY_BY_KEY["panic_resonance"]
    if fd.action in ("watch", "avoid") and not fd.liquidity_filtered and panic_fam.trigger(F):
        _apply_buy(fd, panic_fam, F)
    elif fd.action == "buy":
        # ---- P0-7b：周期吸筹需大盘深跌共振；D方案深度回调低吸例外 ----
        _deep_dip_transform(fd, F)
    # ---- 守卫2（微型TH/求购/Z门/大盘出货/连买抑制；buy/hold/watch 均评估）----
    _apply_guards(fd, F, _GUARD2)

    # ---- 分级仓位（基础族：价值分 + 情绪修正；后置族固定仓位覆盖）----
    # 2026-08-10：panic_resonance 升级族跳过分级（保持 fam.limit=0.30）——修复分级仓位覆盖
    # 族级参数的问题：panic 低 TH 使 th_boost 负值把分级 value 推高，旧分档下恰好顶格、
    # 换档即被错配降仓，而回放 369/365d 均显示 panic 14d 最强（win14 93.6%/+30.1），
    # 仓位应由族级参数决定（反事实：panic 0.30→0.20 使 wavg14 19.03→21.71 即 -2.68）。
    if fd.action in ("buy", "hold") and "panic_resonance_upgrade" not in fd.deduction_sources:
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
    elif fd.action not in ("buy", "hold"):
        fd.position_limit = 0.0

    # ---- 供给扩张过滤（基础/恐慌/深跌低吸；D方案豁免）----
    _apply_guards(fd, F, ("supply_expansion",))

    # ---- 买涨腿升级（v4 实验，v2-T12 默认开，CS_ENGINE_RISE_ACCUM=0 关闭）：审计③架构缺口——
    # 强势品在基础决策 hold/reduce 段被结构性排除（融合决策对 pct>40 拉升输出持有/减仓 →
    # 后置族循环不评估），这正是引擎错过抽象派1337/合纵类单调爬升品的根因。
    # 允许买涨族（rise_accum 默认开 / rise_contract v6 候选默认关）从 hold/reduce 升级 buy（族内自含环境门）。
    if fd.action in ("hold", "reduce") and not fd.liquidity_filtered:
        for _fam_key in ("rise_accum", "rise_contract", "volatile_accum", "rs_accum", "ct_accum"):
            _fam = SIGNAL_FAMILY_BY_KEY.get(_fam_key)
            if _fam is None or not _fam.trigger(F):
                continue
            if not _period_route_ok(_fam_key, bucket):
                _period_route_note(fd, _fam_key)
                continue
            _apply_buy(fd, _fam, F)
            break

    # ---- 升级族2：后置族（深值企稳 > 恐慌退潮 > 供给收缩，固定优先级）----
    # K-2（2026-08-06，预研 k2_guard_prestudy.json）：deep_value 叠加 supply_expansion 闸门，
    # 剔除供给扩张 91 信号后 14d +3.50→+5.58 / 30d +12.21→+16.68，前后半段一致；
    # supply_accum/panic_easing 不叠加（结构与通用守卫冲突/期望反降）。
    if fd.action in ("watch", "avoid") and not fd.liquidity_filtered:
        for fam in _POST_FAMILIES:
            if fam.trigger(F):
                if not _period_route_ok(fam.key, bucket):
                    _period_route_note(fd, fam.key)
                    continue
                _apply_buy(fd, fam, F)
                if fam.guards:
                    _apply_guards(fd, F, fam.guards)
                break

    # ---- 贴纸观察桶守卫（2026-08-12）：印花（贴纸）A2 验证前不进 buy 决策 ----
    # 贴纸为赛事事件驱动高波动品类，周期/供给吸筹语义错配（first-principles-stickers.md 2.1）；
    # 观察桶原则：仅 watch 积累 14/30d 追踪分桶，三件套 + A2 验证通过后才放开 buy。
    if name.startswith("印花 |") and fd.action == "buy":
        fd.action = "watch"
        fd.action_label = "👀 贴纸观察（A2 验证前不进 buy）"
        if "sticker_observation" not in fd.deduction_sources:
            fd.deduction_sources.append("sticker_observation")

    # ---- 信息层：买点接近度（不参与 action 决策；被监控 near_buy 与自选排序读取） ----
    fd.proximity = compute_buy_proximity(F)

    return fd, bucket


def _research_supply_three_state(prices, supply_hist):
    """#5（2026-08-14）供给收缩三态分解：只读展示指标，不改变引擎决策。

    口径与 references/probe_supply_three_state.py 保持一致：
    - 价格三态：chg7 > 3% 为 up；chg7 < -3% 为 down；否则 flat
    - 供给收缩：s30 > 0 且 s7 > 0 且 s7/s30 <= 0.85
    """
    if not prices or not supply_hist:
        return {}
    s7 = sum(supply_hist[-7:]) / 7 if len(supply_hist) >= 7 else None
    s30 = sum(supply_hist[-30:]) / 30 if len(supply_hist) >= 30 else None
    ratio = None
    if s7 is not None and s30 not in (None, 0):
        ratio = s7 / s30
    chg7 = None
    if len(prices) >= 8 and prices[-8] > 0 and prices[-1] > 0:
        chg7 = (prices[-1] / prices[-8] - 1) * 100
    price_state = None
    if chg7 is not None:
        if chg7 > 3:
            price_state = "up"
        elif chg7 < -3:
            price_state = "down"
        else:
            price_state = "flat"
    supply_contract = bool(
        s30 and s30 > 0 and s7 and s7 > 0 and ratio is not None and ratio <= 0.85
    )
    return {
        "s7": round(s7, 2) if s7 is not None else None,
        "s30": round(s30, 2) if s30 is not None else None,
        "chg7": round(chg7, 2) if chg7 is not None else None,
        "ratio": round(ratio, 4) if ratio is not None else None,
        "supply_contract": supply_contract,
        "price_state": price_state,
    }


def run_item_analysis(
    name: str,
    prices: list,
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
    survive_count: int = 0,
    supply_depth_missing: bool = False,
    market_180d_change: float = 0,
    bid_history: list = None,
):
    """
    Complete single-item analysis pipeline.

    Args:
        name: item display name
        prices: daily close prices, oldest-first (90-day)
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
    risk_level = "C"

    current = prices[-1]
    vol_total = supply_hist[-1] if supply_hist else 0

    # ---- Data Quality ----
    dq = "good" if n >= 60 else ("medium" if n >= 20 else "low")

    # ---- Auxiliary Factors ----
    aux = AuxFactors()
    window_90 = prices[-min(90, n):]
    aux.mean_price_90d = round(statistics.mean(window_90), 2)
    if n >= 30:
        ma30 = sum(prices[-30:]) / 30
        aux.ma_deviation = round((current / ma30 - 1) * 100, 2) if ma30 > 0 else 0

    # ---- Core Analyses ----
    position = _analyze_position(prices)
    cycle = _analyze_cycle(prices, sentiment_factor=compute_sentiment_factor(), supply=supply_hist)
    liquidity = score_liquidity(prices, vol_total)

    # ---- Trend Health (with category params + cycle/whale/lock/liquidity corrections) ----
    th = compute_trend_health(
        prices, supply=supply_hist,
        cycle_phase=cycle.phase,
        whale_prob=None,
        position_lock_score=0,
        liquidity_score=liquidity.score,
        item_meta=item_meta,
        zscore_90d=position.zscore_90d,
    )
    th_dict = trend_health_summary(th)

    # ---- Whale Detection ----
    whale = analyze_whale(prices, supply=supply_hist)

    # Re-run trend health with whale info for better detection
    if whale.probability > 0:
        th2 = compute_trend_health(
            prices, supply=supply_hist,
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
        supply_depth=vol_total,
        supply_depth_floor=liquidity_supply_floor(current),
        supply_depth_missing=supply_depth_missing,
    )

    # ==================== 统一大脑阶段3：统一决策核心 ====================
    # 信号族注册制 + 大盘五时期状态桶（2026-08-16 起，旧六态退役）+ 固定优先级 + 族级闸门
    # 见 references/engine-unified.md §3：阶段3 聚焦架构统一，不做期望分档；
    # 语义与阶段2 前串行链保真，新族只需注册到 SIGNAL_FAMILIES。
    micro_th = compute_micro_th(prices)
    bid_support = compute_bid_support(order_book)
    supply = analyze_supply(prices, supply_hist, vol_total, item_meta)
    fd, state_bucket = decide_fusion_signal(
        fd,
        position=position, cycle=cycle, th=th, value=value,
        prices=prices, current=current, n=n, name=name,
        survive_count=survive_count,
        sentiment_score=sentiment_score,
        market_th_score=market_th_score,
        market_30d_change=market_30d_change,
        market_drop21=market_drop21,
        market_cycle=market_cycle,
        supply=supply, supply_hist=supply_hist,
        bid_support=bid_support, micro_th=micro_th,
        recent_buy_dates=recent_buy_dates, signal_date=signal_date,
        market_180d_change=market_180d_change, bid_history=bid_history,
    )
    fd_dict = fusion_decision_summary(fd)
    fd_dict["state_bucket"] = state_bucket
    supply_dict = supply_summary(supply)

    # ---- Valuation Grid (3x4) ----
    # Signal conflict detection
    conflicts, decision_certainty = detect_signal_conflicts(position, cycle, th.score, whale.probability)
    vg = compute_valuation_grid(position.percentile_90d, th, whale.probability)
    vg_dict = valuation_grid_summary(vg)
    # ==================== 决策核心结束 ====================

    # ---- Risk level label (A/B/C/D) ----
    risk_score = 0
    risk_score += 3 if th.score >= 55 else (2 if th.score >= 40 else 1)
    if position.zscore_90d is not None:
        risk_score += 3 if position.zscore_90d <= -1.5 else (2 if position.zscore_90d <= -0.5 else 1)
    risk_score += 3 if liquidity.score >= 50 else (2 if liquidity.score >= 30 else 1)
    risk_score += 3 if whale.level in ("none", "accumulation") else 1
    if risk_score >= 12:
        risk_level = "A"
    elif risk_score >= 9:
        risk_level = "B"
    elif risk_score >= 6:
        risk_level = "C"
    else:
        risk_level = "D"


    # ---- Apply fusion decision to value score ----
    if fd.action == "buy":
        value.score = min(10, value.score + 1.5)
    elif fd.action in ("sell", "avoid"):
        value.score = max(0, value.score - 2.0)
    elif fd.action == "reduce":
        value.score = max(0, value.score - 1.0)

    # TH 偏移 2026-08-12 移除（原 th_boost = (TH-50)/50*2.0，TH 高加分）：与 M-5 反向定论矛盾
    # （TH 与 net14 负相关 spearman -0.344，TH<35 win14 80.8% vs TH>55 60.8%），且与 composite_score
    # 的反向 th_bonus 对冲；移除后 TH 在展示层仅由 composite_score th_bonus 反向单计（探针
    # data/_exp_th_boost_grade.json：Q5 win14 73.4→76.6%、spearman +0.087→+0.142、前后半段一致）。
    # 纯展示层（评级/position_advice）：分级仓位读 decide_fusion_signal 传入的基础 value.score，不受影响。

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
            logger.warning("build_market_context fallback failed for %r", name, exc_info=True)

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
                # 展示层 (2026-08-05 策略研究): 回测最优持有期 panic 14d / 其他 21d；
                # 固定百分比止盈截断反弹利润，改以时间退出为主（2026-08-07 去量解冻：参数定稿，不再等待成交量）
                _hold = 14 if sentiment_score >= 75 else 21
                strat.append("\u5efa\u8bae\u6301\u4ed3\u7ea6" + str(_hold) + "\u5929\u9000\u51fa(\u56de\u6d4b\u6700\u4f18\uff1b\u56fa\u5b9a\u6b62\u76c8\u4f1a\u622a\u65ad\u53cd\u5f39\u5229\u6da6)")

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
            supply=supply_dict,
        ) or {}
    except Exception:
        logger.warning("compute_buy_distance fallback failed for %r", name, exc_info=True)
        buy_distance = {}

    return ItemAnalysisResult(
        name=name,
        price_rmb=current,
        conflicts=conflicts,
        decision_certainty=decision_certainty,
        volume_day=0,
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
        research_metrics=_research_supply_three_state(prices, supply_hist),
    )
