"""
Trend Health Score v3  --- 5-dimension quant engine.

Dimensions & Weights:
  1. Trend Persistence  (22%): MA7 streak + deviation expansion
  2. Trend Steepness    (22%): 7-day regression slope + 2nd-derivative
  3. MA Structure       (22%): MA7 / MA30 / MA90 triple alignment + key levels
  4. Supply-Price      (16%): supply-price coordination + in_sale trend (2026-08-07 去量)
  5. Extreme Gap Risk   (18%): MAD-based anomaly (pos -5 / neg -13 penalty)

Correction layers:
  - Direction cap: momentum-aware (not hard 45/65)
  - Cycle phase: distribution 0.5-0.8, consolidation 0.7-0.9
  - Whale pooling: prob > 60% discount 0.70
  - Position lock: lock_score > 15 discount 0.60

Fusion: percentile_90d + corrected trend health -> standardized action.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from .config import THRESHOLDS as T


# ============================================================
#  Data Classes
# ============================================================

@dataclass
class TrendHealth:
    """Raw + corrected trend health with deduction sources."""
    raw_score: int = 50
    score: int = 50
    level: str = "中性无序"
    level_label: str = ""
    direction: str = "flat"           # up / flat / down
    direction_confidence: float = 0.0

    # 5 dimension raw scores (0-100)
    persistence_score: int = 50
    steepness_score: int = 50
    structure_score: int = 50
    supply_score: int = 50
    anomaly_score: int = 50

    # Detailed metrics
    consecutive_above_ma: int = 0
    consecutive_below_ma: int = 0
    ma_structure: str = "中性无序"      # bullish / bearish / recovering / weakening / neutral
    ma_cross_type: str = "无交叉"        # golden_cross / death_cross / none
    steepness_signal: str = "匀速稳定"   # accelerating / exhaustion / panicking / bottoming / reversing_up / reversing_down / stable
    supply_signal: str = "中性无序"     # 供给×价格协调（替代原量价维度，2026-08-07 去量）
    has_anomaly: bool = False
    anomaly_count: int = 0
    anomaly_type: str = "无交叉"         # bubble / panic / mixed / none

    # Corrections
    deduction_sources: list = field(default_factory=list)
    raw_direction: str = "flat"

    def __post_init__(self):
        if self.score >= T["TH_STRONG"]:
            self.level = "healthy"; self.level_label = "\U0001f7e2 \u5065\u5eb7"
        elif self.score >= T["TH_NEUTRAL"]:
            self.level = "中性偏强"; self.level_label = "\U0001f7e1 \u4e2d\u6027"
        elif self.score >= T["TH_WEAK"]:
            self.level = "weak"; self.level_label = "\U0001f7e0 \u8870\u5f31"
        else:
            self.level = "critical"; self.level_label = "\U0001f534 \u5371\u9669"


@dataclass
class FusionDecision:
    """Percentile + trend health fusion -> standardized action."""
    percentile_90d: float = 50.0
    raw_th_score: int = 50
    corrected_th_score: int = 50
    zone: str = "中性无序"
    zone_label: str = ""
    action: str = "watch"
    action_label: str = ""
    action_detail: str = ""
    deduction_sources: list = field(default_factory=list)
    liquidity_filtered: bool = False
    market_relative_strength: bool = False
    position_limit: float = 1.0
    proximity: dict = None  # 纯展示层：买点接近度（不参与任何决策）


# ============================================================
#  Helpers
# ============================================================

def _ma(vals, w):
    if len(vals) < w or w <= 0:
        return 0.0
    return sum(vals[-w:]) / w


def _regression_slope(vals, w):
    """Normalized linear slope over last w points."""
    if len(vals) < w or w < 3:
        return 0.0
    ys = vals[-w:]
    mean_y = statistics.mean(ys)
    if mean_y == 0:
        return 0.0
    xs = list(range(w))
    mx = (w - 1) / 2.0
    num = sum((x - mx) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return (num / den) / mean_y if den else 0.0


def _mad(vals):
    if len(vals) < 2:
        return 0.0
    med = statistics.median(vals)
    return statistics.median([abs(v - med) for v in vals])


# ============================================================
#  Dim 1: Trend Persistence (24%)  --- MA7 streak + deviation delta
# ============================================================

def _dim_persistence(prices):
    """
    N=7: measure consecutive days above/below MA7 + deviation gradient.

    - 7+ days above MA7 with expanding deviation: high
    - 7+ days below MA7: low
    - Mixed: scored by net-ratio
    """
    n = len(prices)
    if n < 15:
        return 50, 0, 0, "stable"

    # --- compute MA7 series ---
    ma7_series = []
    for i in range(n):
        start = max(0, i - 6)
        ma7_series.append(sum(prices[start:i+1]) / (i - start + 1))

    lookback = min(20, n - 7)
    if lookback < 3:
        return 50, 0, 0, "stable"

    above_streak = 0; below_streak = 0
    max_above = 0; max_below = 0
    total_above = 0; total_below = 0

    # deviation deltas for gradient
    deviations = []

    for i in range(n - lookback, n):
        p = prices[i]; m = ma7_series[i]
        if m <= 0:
            continue
        ratio = p / m
        dev_pct = (ratio - 1.0) * 100

        if ratio > 1.005:
            above_streak += 1; below_streak = 0
            max_above = max(max_above, above_streak); total_above += 1
            deviations.append(dev_pct)
        elif ratio < 0.995:
            below_streak += 1; above_streak = 0
            max_below = max(max_below, below_streak); total_below += 1
            deviations.append(dev_pct)
        else:
            above_streak = below_streak = 0

    total_days = total_above + total_below
    if total_days == 0:
        return 50, 0, 0, "stable"

    net_ratio = (total_above - total_below) / total_days

    # Deviation gradient: is deviation expanding or contracting?
    dev_gradient = "匀速稳定"
    if len(deviations) >= 6:
        early = statistics.mean([abs(d) for d in deviations[:3]])
        late  = statistics.mean([abs(d) for d in deviations[-3:]])
        if early > 0:
            delta = (late - early) / early
            if delta > 0.3:
                dev_gradient = "乖离扩大"
            elif delta < -0.3:
                dev_gradient = "乖离收敛"
            else:
                dev_gradient = "匀速稳定"

    # Score
    if net_ratio > 0.3:
        persistence = min(max_above, 7)
        if persistence >= 7:
            base = 95 if dev_gradient == "乖离扩大" else 80
        elif persistence >= 5:
            base = 70
        elif persistence >= 3:
            base = 58
        else:
            base = 50 + int(net_ratio * 10)
    elif net_ratio < -0.3:
        persistence = min(max_below, 7)
        if persistence >= 7:
            base = 0 if dev_gradient == "乖离扩大" else 8
        elif persistence >= 5:
            base = 15
        elif persistence >= 3:
            base = 28
        else:
            base = 40 + int(net_ratio * 10)
    else:
        base = 50 + int(net_ratio * 15)

    return max(0, min(100, base)), max_above, max_below, dev_gradient


# ============================================================
#  Dim 2: Trend Steepness (24%)  --- 7-day slope + 2nd-derivative
# ============================================================

def _dim_steepness(prices):
    """
    7-day regression slope normalized; 2nd-derivative for accel/decel.
    """
    n = len(prices)
    if n < 15:
        return 50, "stable"

    slopes = []
    for i in range(7, n + 1):
        slopes.append(_regression_slope(prices[:i], 7))

    if len(slopes) < 3:
        return 50, "stable"

    recent_slope = slopes[-1]

    daily_pct = recent_slope * 100

    # Compute ratio-based exhaustion/acceleration
    # Compare current slope to average of previous 3 slope values
    if len(slopes) >= 4:
        prev_3_avg = statistics.mean(slopes[-4:-1])
        if abs(prev_3_avg) > 1e-10:
            slope_ratio = recent_slope / prev_3_avg
        else:
            slope_ratio = 1.0
    else:
        slope_ratio = 1.0

    # Signal with ratio-based quantification
    if daily_pct > 1.0:
        if slope_ratio > 1.30:
            signal = "加速上涨"
        elif slope_ratio < 0.70:
            signal = "上涨衰竭"
        else:
            signal = "匀速稳定"
    elif daily_pct < -1.0:
        if slope_ratio > 1.30:
            signal = "恐慌下跌"
        elif slope_ratio < 0.70:
            signal = "触底企稳"
        else:
            signal = "匀速稳定"
    else:
        if slope_ratio > 1.30:
            signal = "拐头向上"
        elif slope_ratio < 0.70:
            signal = "拐头向下"
        else:
            signal = "匀速稳定"

    abs_pct = abs(daily_pct)

    if daily_pct > 0.2:
        if abs_pct > 5:
            base = 90
        elif abs_pct > 2:
            base = 75
        elif abs_pct > 1:
            base = 65
        elif abs_pct > 0.5:
            base = 58
        else:
            base = 52
        if signal == "加速上涨":
            base = min(100, base + 8)
        elif signal == "上涨衰竭":
            base = max(10, base - 10)
    elif daily_pct < -0.2:
        if abs_pct > 5:
            base = 5
        elif abs_pct > 2:
            base = 15
        elif abs_pct > 1:
            base = 30
        elif abs_pct > 0.5:
            base = 42
        else:
            base = 48
        if signal == "恐慌下跌":
            base = max(0, base - 8)
        elif signal == "触底企稳":
            base = min(60, base + 12)
    else:
        base = 50

    return max(0, min(100, base)), signal


# ============================================================
#  Dim 3: MA Structure (19%)  --- MA7 / MA30 / MA90
# ============================================================

def _dim_structure(prices):
    """
    Triple MA alignment with MA90 anchor penalty.
    """
    n = len(prices)
    if n < 30:
        return 50, "量能中性", "none"

    ma7  = _ma(prices, 7)
    ma30 = _ma(prices, 30)
    ma90 = _ma(prices, min(90, n)) if n >= 90 else ma30
    current = prices[-1]

    prev_ma7  = _ma(prices[:-1], 7) if n > 7 else ma7
    prev_ma30 = _ma(prices[:-1], 30) if n > 30 else ma30
    cross = "无交叉"
    if prev_ma7 <= prev_ma30 and ma7 > ma30:
        cross = "金叉"
    elif prev_ma7 >= prev_ma30 and ma7 < ma30:
        cross = "死叉"

    if ma7 > ma30 > ma90:
        structure = "多头排列"
        score = 100 if current > ma90 else 50  # MA90 anchor penalty
    elif ma7 < ma30 < ma90:
        structure = "空头排列"
        score = 0 if current < ma90 else 25
    elif ma7 > ma30 and ma30 < ma90:
        structure = "修复反弹"
        score = 60
    elif ma7 < ma30 and ma30 > ma90:
        structure = "走弱转跌"
        score = 30
    else:
        structure = "中性无序"
        score = 50 if abs(ma7 - ma30) / max(ma30, 0.01) < 0.02 else 45

    return max(0, min(100, score)), structure, cross


# ============================================================
#  Dim 4: Supply-Price Coordination (16%)  (去量 2026-08-07)
# ============================================================

def _dim_supply_price(prices, supply):
    """Supply-price coordination (替代原量价维度，2026-08-07 去量).
    - Price up + supply down (contracting, 吸筹): high
    - Price up + supply up (expanding, 派发/对倒嫌疑): penalty
    - Price down + supply up (panic/dumping): penalty
    - Price down + supply down (illiquid, 无人接盘): medium-low
    - Sideways + stable supply: medium
    - Extended: 5d/20d supply trend
    """
    real_days = sum(1 for s in supply if s and s > 0) if supply else 0
    # 在售量 < 20 天：长窗口供给项置中性，避免采样干扰
    if not supply or len(supply) < 10 or real_days < 20 or len(prices) < 10:
        return 50, "中性无序"
    n = min(len(prices), len(supply))
    prices = prices[-n:]
    supply = supply[-n:]

    recent_p = statistics.mean(prices[-5:]) if n >= 5 else prices[-1]
    earlier_p = statistics.mean(prices[-10:-5]) if n >= 10 else recent_p
    p_chg = (recent_p / earlier_p - 1.0) * 100 if earlier_p > 0 else 0

    recent_s = statistics.mean(supply[-5:])
    earlier_s = statistics.mean(supply[-10:-5]) if n >= 10 else recent_s
    s_chg = (recent_s / earlier_s - 1.0) * 100 if earlier_s > 0 else 0
    s_20d = statistics.mean(supply[-20:]) if len(supply) >= 20 else recent_s
    s_5_vs_20 = (recent_s / s_20d - 1.0) * 100 if s_20d > 0 else 0

    score = 50
    if p_chg > 3:
        if s_chg < -8:
            score = 85
        elif s_chg > 8:
            score = 25
        else:
            score = 65
    elif p_chg < -3:
        if s_chg > 8:
            score = 20
        elif s_chg < -8:
            score = 35
        else:
            score = 45
    else:
        if abs(s_chg) < 5:
            score = 55
        elif s_chg > 8:
            score = 40
        else:
            score = 60
    # 5d vs 20d supply trend: expanding = penalty, contracting = healthy
    if s_5_vs_20 > 10:
        score -= 8
    elif s_5_vs_20 < -10:
        score += 6
    score = int(max(0, min(100, score)))
    if score >= 70:
        signal = "供给配合"
    elif score >= 45:
        signal = "中性无序"
    else:
        signal = "供给背离"
    return score, signal


def _dim_anomaly(prices, mad_scale=1.0):
    """
    MAD (Median Absolute Deviation) threshold = 1.8 * MAD.
    Gradient penalty: -13 per anomaly point.
    """
    n = len(prices)
    if n < 10:
        return 50, 0, "none"

    rets = []
    for i in range(1, n):
        if prices[i-1] > 0:
            rets.append((prices[i] / prices[i-1] - 1.0) * 100)

    if len(rets) < 8:
        return 50, 0, "none"

    mad_val = _mad(rets)
    if mad_val == 0:
        try:
            mad_val = statistics.stdev(rets) * 0.6745
        except:
            return 100, 0, "none"

    threshold = mad_val * 1.8 * mad_scale

    recent_n = min(15, len(rets))
    recent = rets[-recent_n:]

    up_anom = sum(1 for r in recent if r > threshold)
    dn_anom = sum(1 for r in recent if r < -threshold)
    total   = up_anom + dn_anom

    if total == 0:
        return 100, 0, "none"

    score = max(5, 100 - dn_anom * 13 - up_anom * 5)
    if   up_anom > dn_anom: atype = "情绪泡沫"
    elif dn_anom > up_anom: atype = "恐慌抛压"
    else:                    atype = "混合异常"

    return score, total, atype


# ============================================================
#  Main
# ============================================================

def compute_trend_health(prices, supply=None,
                         cycle_phase=None, whale_prob=None,
                         position_lock_score=0, liquidity_score=50,
                         item_meta=None, zscore_90d=None):
    """Compute 0-100 trend health with corrections.

    Args:
        prices: daily close prices (oldest->newest)
        cycle_phase: 'accumulation'/'consolidation'/'markup'/'distribution'
        whale_prob: whale manipulation probability 0-100
        position_lock_score: WhaleDetection position_lock_score (0-20)
        liquidity_score: 0-100 liquidity score
    """

    th = TrendHealth()
    n = len(prices)
    if n < 8:
        return th

    # --- 5 dimensions ---
    th.persistence_score, th.consecutive_above_ma, th.consecutive_below_ma, _ = _dim_persistence(prices)
    th.steepness_score,   th.steepness_signal   = _dim_steepness(prices)
    th.structure_score,   th.ma_structure, th.ma_cross_type = _dim_structure(prices)
    th.supply_score,      th.supply_signal      = _dim_supply_price(prices, supply)
    # Extract category-specific params
    mad_scale = 1.0
    if item_meta:
        type_name = item_meta.get('type_name', '')
        try:
            from .config import CATEGORY_PARAMS
            cat = CATEGORY_PARAMS.get(type_name, CATEGORY_PARAMS.get('_default', {}))
            mad_scale = cat.get('mad_scale', 1.0)
        except Exception:
            pass

    anom, anom_count, anom_type = _dim_anomaly(prices, mad_scale)
    th.anomaly_score  = anom
    th.anomaly_count  = anom_count
    th.anomaly_type   = anom_type
    th.has_anomaly    = anom_count > 0

    # --- raw weighted ---
    raw = (
        th.persistence_score * 0.22 +
        th.steepness_score   * 0.22 +
        th.structure_score   * 0.22 +
        th.supply_score      * 0.16 +
        th.anomaly_score     * 0.18
    )
    th.raw_score = int(round(raw))

    # --- direction ---
    up_v = 0.0; dn_v = 0.0

    if   th.persistence_score >= 65: up_v += 2
    elif th.persistence_score <= 35: dn_v += 2

    if   th.ma_structure in ("多头排列","修复反弹"): up_v += 1.5
    elif th.ma_structure in ("空头排列","走弱转跌"):  dn_v += 1.5

    if   th.steepness_signal in ("加速上涨","拐头向上"): up_v += 1
    elif th.steepness_signal in ("恐慌下跌","上涨衰竭","拐头向下"): dn_v += 1
    elif th.steepness_signal == "触底企稳": up_v += 0.5

    if   th.supply_signal == "供给配合" and th.steepness_signal in ("加速上涨","匀速稳定"): up_v += 0.5
    elif th.supply_signal == "供给背离": dn_v += 1

    tot = up_v + dn_v
    net = (up_v - dn_v) / tot if tot > 0 else 0

    if   net >= 0.3:  th.direction = "up"
    elif net <= -0.3: th.direction = "down"
    else:             th.direction = "flat"
    th.direction_confidence = round(abs(net), 2)
    th.raw_direction = th.direction

    # --- direction cap (momentum-aware, not hard cutoff) ---
    if th.direction == "down":
        oversold_rebound = False
        if n >= 10 and zscore_90d is not None and abs(zscore_90d) > 0.1:
            if zscore_90d < -2.2:
                ma7_now = _ma(prices, 7)
                ma7_prev = _ma(prices[:-3], 7) if n >= 10 else ma7_now
                if ma7_now > ma7_prev:
                    oversold_rebound = True
        elif n >= 10:
            prices_window = prices[-min(90, n):]
            if len(prices_window) >= 10:
                mean_p = sum(prices_window) / len(prices_window)
                std_p = (sum((p - mean_p) ** 2 for p in prices_window) / len(prices_window)) ** 0.5
                if std_p > 0:
                    z_approx = (prices[-1] - mean_p) / std_p
                    if z_approx < -2.2:
                        ma7_now = _ma(prices, 7)
                        ma7_prev = _ma(prices[:-3], 7) if n >= 10 else ma7_now
                        if ma7_now > ma7_prev:
                            oversold_rebound = True
        if oversold_rebound:
            th.score = min(th.raw_score, 60)
            th.deduction_sources.append("oversold_rebound_cap")
        elif th.steepness_signal == '触底企稳':
            th.score = min(th.raw_score, 55)
            th.deduction_sources.append("steepness_bottom_cap")
        elif th.persistence_score >= 60 and th.steepness_signal == '拐头向上':
            th.score = min(th.raw_score, 50)
            th.deduction_sources.append("steepness_reversal_cap")
        else:
            th.score = min(th.raw_score, 45)
    elif th.direction == "flat":
        if th.persistence_score >= 65 or th.ma_structure in ('多头排列', '修复反弹'):
            th.score = min(th.raw_score, 75)
            th.deduction_sources.append("flat_strong_cap")
        elif th.steepness_signal == '拐头向上':
            th.score = min(th.raw_score, 70)
            th.deduction_sources.append("flat_improving_cap")
        else:
            th.score = min(th.raw_score, 65)
    else:
        th.score = th.raw_score

    # --- collect all corrections (anti-chain: max discount + 30% of others) ---
    multipliers = []  # each entry: (multiplier, source_label)

    if cycle_phase == "distribution":
        if th.direction == "up":
            multipliers.append((0.80, "distribution_cycle"))
        elif th.direction == "flat":
            multipliers.append((0.65, "distribution_cycle"))
        else:
            multipliers.append((0.50, "distribution_cycle"))
    elif cycle_phase == "consolidation":
        ma90 = _ma(prices, min(90, n)) if n >= 90 else _ma(prices, n)
        if ma90 > 0 and prices[-1] / ma90 > 1.20:
            multipliers.append((0.70, "high_consolidation"))
        else:
            multipliers.append((0.90, "consolidation_phase"))

    if whale_prob is not None and whale_prob > 60:
        multipliers.append((0.70, "whale_pooling"))

    if position_lock_score > 15:
        multipliers.append((0.60, "position_locked"))

    if multipliers:
        # Convert multipliers to discounts: discount = 1 - multiplier
        discounts = [(1.0 - m, label) for m, label in multipliers]
        discounts.sort(key=lambda x: x[0], reverse=True)  # largest discount first

        max_discount = discounts[0][0]
        other_discounts = [d for d, _ in discounts[1:]]
        total_discount = max_discount + 0.3 * sum(other_discounts)
        total_discount = min(0.90, total_discount)  # cap at 90% discount (floor at 10%)

        th.score = int(th.score * (1.0 - total_discount))
        th.deduction_sources.extend([label for _, label in discounts])

    # clamp
    th.score = max(0, min(100, th.score))
    th.__post_init__()
    return th


def trend_health_summary(th):
    return {
        "raw_score": th.raw_score,
        "score": th.score,
        "level": th.level,
        "level_label": th.level_label,
        "direction": th.direction,
        "direction_confidence": th.direction_confidence,
        "raw_direction": th.raw_direction,
        "persistence_score": th.persistence_score,
        "steepness_score": th.steepness_score,
        "structure_score": th.structure_score,
        "supply_score": th.supply_score,
        "anomaly_score": th.anomaly_score,
        "consecutive_above_ma": th.consecutive_above_ma,
        "consecutive_below_ma": th.consecutive_below_ma,
        "ma_structure": th.ma_structure,
        "ma_cross_type": th.ma_cross_type,
        "steepness_signal": th.steepness_signal,
        "supply_signal": th.supply_signal,
        "has_anomaly": th.has_anomaly,
        "anomaly_count": th.anomaly_count,
        "anomaly_type": th.anomaly_type,
        "deduction_sources": th.deduction_sources,
    }


# ============================================================
#  Fusion Decision Engine
# ============================================================

def compute_fusion_decision(percentile_90d, th, liquidity_score=50, zscore_90d=0.0, cycle_phase="unknown", market_cycle="unknown", market_30d_change=0.0, item_7d_change=0.0, event_risk_discount=1.0, prices=None, sentiment_score=50.0):
    """Combine percentile + corrected trend health -> action.

    When market is weak (bear/distribution) but item shows independent strength
    (item_7d_change outperforms market_30d_change by 5%+), buy thresholds are lowered.

    Liquidity filter: if liquidity < 30, any 'buy' downgrades to 'watch'.
    """
    fd = FusionDecision()
    fd.percentile_90d = percentile_90d
    fd.raw_th_score = th.raw_score
    fd.corrected_th_score = th.score
    fd.deduction_sources = th.deduction_sources

    pct = percentile_90d
    ts  = th.score

    # Extreme valuation protection: percentile>95% + Z>2.5 = forced sell
    if pct > 95 and zscore_90d > 2.5:  # could use config.Z_EXTREME_EXIT
        fd.action = "sell"
        fd.action_label = "\U0001f4a5 极端泡沫·强制清仓"
        fd.action_detail = "百分位>95%且Z-score>2.5，处于统计极端区域，无论趋势如何都建议立即清仓"
        fd.zone = "overvalued"
        fd.zone_label = "\U0001f4a5 极端泡沫区"
        fd.percentile_90d = pct
        fd.raw_th_score = th.raw_score
        fd.corrected_th_score = th.score
        fd.deduction_sources = th.deduction_sources
        return fd

    # Sentiment-adjusted trend health: fear→small boost, greed→small dampen
    sentiment_adjustment = (sentiment_score - 50) / 50 * 3
    ts = min(100, max(0, ts + sentiment_adjustment))

    if   pct <= 30: fd.zone = "undervalued"; fd.zone_label = "🟢 低估区 (0-30%)"
    elif pct <= 70: fd.zone = "中性无序";      fd.zone_label = "🟡 中性区 (30-70%)"
    else:           fd.zone = "overvalued";   fd.zone_label = "🔴 高估泡沫区 (70-100%)"

    # Decision matrix
    if fd.zone == "undervalued":
        # Dynamic Z-gate: bear/consolidation=strict(≤0), accumulation=mild(≤0.5), markup=loose(≤1.0), distribution=strictest(≤-0.5)
        cycle_z_gates = {"bear": 0, "consolidation": 0, "accumulation": 0.5, "markup": 1.0, "distribution": -0.5}
        z_threshold = cycle_z_gates.get(market_cycle, 0)
        if ts >= T["TH_STRONG"] and zscore_90d <= z_threshold:
            fd.action = "buy"
            fd.action_label = "\U0001f7e2 \u5206\u6279\u5efa\u4ed3"
            fd.action_detail = "\u4f4e\u4f4d\u4f4e\u4f30 + \u8d8b\u52bf\u5065\u5eb7\uff0c\u5b89\u5168\u8fb9\u9645\u6700\u9ad8\uff0c\u5efa\u8bae\u5206\u6279\u4ecb\u5165"
        elif ts >= T["TH_NEUTRAL"]:
            fd.action = "watch"
            fd.action_label = "\U0001f7e1 \u7b51\u5e95\u4e2d\u00b7\u89c2\u5bdf"
            fd.action_detail = "\u4f4e\u4f4d\u4f46\u8d8b\u52bf\u4e0d\u786e\u5b9a\uff0c\u7b49\u5f85\u8d8b\u52bf\u786e\u8ba4\u540e\u518d\u4ecb\u5165"
        else:
            fd.action = "avoid"
            fd.action_label = "\U0001f534 \u4e0b\u8dcc\u4e2d\u7ee7\u00b7\u89c2\u671b"
            fd.action_detail = "\u4f4e\u4f4d\u4f46\u8d8b\u52bf\u8870\u5f31\uff0c\u53ef\u80fd\u662f\u4e0b\u8dcc\u4e2d\u7ee7\uff0c\u4e0d\u6284\u5e95"
    elif fd.zone == "中性无序":
        if ts >= 70:
            fd.action = "hold"
            fd.action_label = "\U0001f7e2 \u77ed\u7ebf\u6301\u6709\u00b7\u6b62\u76c8\u6536\u7d27"
            fd.action_detail = "\u4ef7\u683c\u5408\u7406 + \u8d8b\u52bf\u5f3a\u52b2\uff0c\u7ee7\u7eed\u6301\u6709\u4f46\u6ce8\u610f\u6b62\u76c8\u4f4d"
        elif ts >= 50:
            fd.action = "watch"
            fd.action_label = "\U0001f7e1 \u9707\u8361\u00b7\u89c2\u671b"
            fd.action_detail = "\u4ef7\u683c\u5408\u7406\u4f46\u8d8b\u52bf\u4e0d\u5f3a\uff0c\u7b49\u5f85\u65b9\u5411\u786e\u8ba4"
        else:
            fd.action = "watch"
            fd.action_label = "\U0001f7e1 \u56de\u8c03\u4e2d\u00b7\u5173\u6ce8"
        fd.action_detail = "\u4ef7\u683c\u5408\u7406\u4f46\u8d8b\u52bf\u8f6c\u5f31\uff0c\u53ef\u80fd\u5728\u56de\u8c03\uff0c\u4fdd\u6301\u5173\u6ce8"
        # ---- Cycle-aware downgrade for neutral zone ----
        # When price is neutral but cycle signals distribution, downgrade action
        if cycle_phase == "distribution" and fd.action in ("hold", "buy"):
            fd.action = "reduce"
            fd.action_label = "🟠 周期出货·减仓"
            fd.action_detail = fd.action_detail + "（周期判定出货期，百分位中性区间先行减仓防范）"
            fd.deduction_sources.append("cycle_distribution_downgrade")
        elif cycle_phase == "accumulation" and fd.action == "avoid":
            fd.action = "watch"
            fd.action_label = "🟡 周期吸筹·关注"
            fd.action_detail = fd.action_detail + "（周期判定吸筹期，虽百分位中性但可关注）"
            fd.deduction_sources.append("cycle_accumulation_upgrade")

    else:  # overvalued
        if ts >= T["TH_STRONG"]:
            # Split by supply-price health (去量 2026-08-07)
            if th.supply_signal == "供给配合":
                fd.action = "hold"
                fd.action_label = "\U0001f7e2 强势趋势·持有（设移动止盈）"
                fd.action_detail = "高位 + 趋势强劲 + 供给配合健康，继续持有但设置移动止盈保护利润"
            else:
                fd.action = "reduce"
                fd.action_label = "\U0001f534 抱团风险·分批止盈"
                fd.action_detail = "高位泡沫 + 趋势强劲但供给背离，可能是抱团拉升，禁止新开仓，分批止盈"
        elif ts >= T["TH_NEUTRAL"]:
            # Moderate TH at high percentile - direction-aware
            if th.direction == "up":
                fd.action = "hold"
                fd.action_label = "\U0001f7e2 强势整理·持有观察"
                fd.action_detail = "高位但趋势仍向上，可能是健康回调换手，持仓观察，不急于清仓"
            elif th.direction == "flat":
                fd.action = "reduce"
                fd.action_label = "\U0001f7e0 高位横盘·减仓"
                fd.action_detail = "高位且趋势走平，建议分批减仓锁定利润"
            else:
                fd.action = "reduce"
                fd.action_label = "\U0001f7e0 回调风险·减仓观望"
                fd.action_detail = "高位且趋势转弱，可能是回调信号，建议减仓观望"
        else:
            # TH < 40 at high percentile
            if th.direction == "down":
                fd.action = "sell"
                fd.action_label = "\U0001f534 趋势反转·清仓"
                fd.action_detail = "高位 + 趋势衰弱 + 方向向下，趋势反转信号确认，建议清仓离场"
            elif th.direction == "up":
                fd.action = "reduce"
                fd.action_label = "\U0001f7e0 高位震荡·减仓"
                fd.action_detail = "高位但方向仍向上，可能是震荡洗盘，建议先减仓观察，不急于全清"
            else:
                fd.action = "reduce"
                fd.action_label = "\U0001f7e0 高位震荡·减仓"
                fd.action_detail = "高位且趋势偏弱，建议分批减仓观察"


    # ---- Market-Relative Strength (弱市独立走强) ----
    # When market is weak but item shows anti-fragility, upgrade signals
    market_is_weak = market_cycle in ("bear", "distribution")
    market_relative_outperformance = (item_7d_change - market_30d_change) if market_30d_change < 0 else 0
    
    if market_is_weak and market_relative_outperformance > 5:
        # Item is outperforming weak market by 5%+, may have independent strength
        fd.market_relative_strength = True
        if fd.zone == "undervalued" and fd.action == "avoid":
            # Upgrade from avoid to watch - item is cheap AND holding up better than market
            if ts >= 40:
                fd.action = "watch"
                fd.action_label = "\U0001f7e1 \u5f31\u5e02\u6297\u8dcc\u00b7\u8f7b\u4ed3\u8bd5\u63a2"
                fd.action_detail = "\u5927\u76d8\u504f\u5f31\u4f46\u54c1\u79cd\u8868\u73b0\u660e\u663e\u6297\u8dcc(\u8dd1\u8d62\u5927\u76d8%.1f%%)+\u4f4e\u4f30\uff0c\u53ef\u8f7b\u4ed3\u8bd5\u63a2" % market_relative_outperformance
                fd.deduction_sources.append("market_relative_strength_upgrade")
        elif fd.zone == "undervalued" and fd.action == "watch":
            # Upgrade watch to buy if TH >= 50
            if ts >= 50:
                fd.action = "buy"
                fd.action_label = "\U0001f7e2 \u5f31\u5e02\u6297\u8dcc\u00b7\u5206\u6279\u4ecb\u5165"
                fd.action_detail = "\u5927\u76d8\u504f\u5f31\u4f46\u54c1\u79cd\u62d2\u7edd\u8ddf\u8dcc(\u8dd1\u8d62\u5927\u76d8%.1f%%)+\u4f4e\u4f30+\u8d8b\u52bf\u5065\u5eb7\uff0c\u53ef\u5206\u6279\u4ecb\u5165" % market_relative_outperformance
                fd.deduction_sources.append("market_relative_strength_upgrade")
    elif market_is_weak and fd.zone == "overvalued":
        # In a weak market, overvalued items with weak trend should be more aggressively sold
        if fd.action == "reduce":
            fd.action_label = "\U0001f534 \u5f31\u5e02\u00b7\u52a0\u901f\u51cf\u4ed3"
            fd.action_detail = fd.action_detail + "\uff08\u5f31\u5e02+\u9ad8\u4f30\uff0c\u5efa\u8bae\u52a0\u5feb\u51cf\u4ed3\u8282\u594f\uff09"

    # ==== Oversold buy exception (P0): pct≤15%, Z≤-2.0, 跌速衰减 ====
    # Allows buy signal at deeply oversold levels when decline is decelerating.
    # Rule: no_new_low2 (last 2 days > last 3 days low) + chg3d > 0%
    if prices is not None and len(prices) >= 7:
        if pct <= 15 and zscore_90d <= -2.0 and fd.action != "buy":
            low2 = min(prices[-2:])
            low3 = min(prices[-3:])
            chg3d = (prices[-1] - prices[-4]) / prices[-4] * 100
            no_new_low2 = low2 > low3
            if no_new_low2 and chg3d > 0:
                fd.action = "buy"
                fd.action_label = "\U0001f7e2 \u8d85\u8dcc\u53cd\u5f39\u00b7\u5206\u6279\u5efa\u4ed3"
                fd.action_detail = "\u6df1\u5ea6\u8d85\u8dcc\u533a\uff0c\u8dcc\u901f\u8870\u51cf\u4f01\u7a33\uff0c\u53ef\u5206\u6279\u5efa\u4ed3"
                fd.deduction_sources.append("oversold_buy_exception")

    # Liquidity filter
    if liquidity_score < 30 and fd.action == "buy":
        fd.action = "watch"
        fd.action_label = "\U0001f7e1 \u6d41\u52a8\u6027\u4e0d\u8db3\u00b7\u89c2\u671b"
        fd.action_detail = "\u4f4e\u4f30\u4f46\u6d41\u52a8\u6027\u6781\u5dee\uff0c\u51fa\u8d27\u56f0\u96be\uff0c\u5efa\u4ed3\u964d\u7ea7\u4e3a\u89c2\u671b"
        fd.liquidity_filtered = True

    # Event risk filter (P0)
    if event_risk_discount < 0.85 and fd.action in ("buy", "hold"):
        fd.action = "watch"
        fd.action_label = "🟡 事件风险·观望"
        fd.action_detail = fd.action_detail + "（重大事件风险活跃，暂缓新建仓）"
        fd.deduction_sources.append("event_risk_filter")

    # Cycle phase coordination: align fusion decision with cycle analysis
    if cycle_phase == "accumulation":
        if fd.action in ("sell", "avoid"):
            fd.action = "watch"
            fd.action_label = "🟡 周期吸筹·观察"
            fd.action_detail = fd.action_detail + "。但周期处于吸筹期，不宜清仓，先观察等待确认。"
            fd.deduction_sources.append("cycle_accumulation_boost")
        elif fd.action == "watch":
            fd.action = "buy"
            fd.action_label = "🟢 周期吸筹·分批建仓"
            fd.action_detail = "周期处于吸筹期，融合决策建议分批建仓。"
            fd.deduction_sources.append("cycle_accumulation_boost")

    elif cycle_phase == "markup":
        if fd.action in ("sell", "avoid"):
            fd.action = "watch"
            fd.action_label = "🟡 周期拉升·观察"
            fd.action_detail = fd.action_detail + "。但周期处于拉升期，不宜清仓，先观察。"
            fd.deduction_sources.append("cycle_markup_boost")
        elif fd.action == "reduce":
            fd.action = "hold"
            fd.action_label = "🟢 周期拉升·持有"
            fd.action_detail = fd.action_detail + "。但周期拉升期，可继续持有观察。"
            fd.deduction_sources.append("cycle_markup_boost")

    elif cycle_phase == "distribution":
        if fd.action == "buy":
            fd.action = "watch"
            fd.action_label = "🟡 周期出货·不建仓"
            fd.action_detail = fd.action_detail + "。但周期处于出货期，不宜新建仓，降级为观望。"
            fd.deduction_sources.append("cycle_distribution")
        elif fd.action == "hold":
            fd.action = "reduce"
            fd.action_label = "🟠 周期出货·分批止盈"
            fd.action_detail = fd.action_detail + "。但周期处于出货期，建议分批止盈离场。"
            fd.deduction_sources.append("cycle_distribution")
        elif fd.action == "watch":
            fd.action = "avoid"
            fd.action_label = "🔴 周期出货·观望"
            fd.action_detail = "周期处于出货期，建议保持观望，不急于操作。"
            fd.deduction_sources.append("cycle_distribution")
        elif fd.action == "reduce":
            fd.action = "sell"
            fd.action_label = "🔴 周期出货·清仓"
            fd.action_detail = "周期处于出货期，融合决策建议清仓离场。"
            fd.deduction_sources.append("cycle_distribution")

    elif cycle_phase == "consolidation":
        if fd.action == "buy":
            fd.action = "watch"
            fd.action_label = "🟡 周期洗盘·观望"
            fd.action_detail = "周期洗盘期方向不明，不宜追买，先观察等待突破。"
            fd.deduction_sources.append("cycle_consolidation")

    return fd


def fusion_decision_summary(fd):
    return {
        "percentile_90d": fd.percentile_90d,
        "raw_th_score": fd.raw_th_score,
        "corrected_th_score": fd.corrected_th_score,
        "zone": fd.zone,
        "zone_label": fd.zone_label,
        "action": fd.action,
        "action_label": fd.action_label,
        "action_detail": fd.action_detail,
        "deduction_sources": fd.deduction_sources,
        "liquidity_filtered": fd.liquidity_filtered,
        "position_limit": fd.position_limit,
        "proximity": getattr(fd, "proximity", None),
    }

# === Market Index Trend Health ===
# See pipeline/market_th.py for full implementation


