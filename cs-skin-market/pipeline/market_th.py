# -*- coding: utf-8 -*-

from dataclasses import dataclass, field

from .config import THRESHOLDS as T
from .trend_health import compute_trend_health



@dataclass

class MarketTrendHealth:

    raw_score: int = 50

    score: int = 50

    level: str = ""

    level_label: str = ""

    direction: str = "flat"

    persistence_score: int = 50

    steepness_score: int = 50

    structure_score: int = 50

    volume_score: int = 50

    anomaly_score: int = 50

    ma_structure: str = ""

    ma_cross_type: str = ""

    steepness_signal: str = ""

    volume_signal: str = ""

    has_anomaly: bool = False

    anomaly_count: int = 0

    anomaly_type: str = "none"


    deduction_sources: list = field(default_factory=list)

    volume_divergence: bool = False

    volume_divergence_label: str = ""

    bubble_breadth: float = 0.0

    bubble_breadth_label: str = ""
    drop_from_peak_pct: float = 0.0
    pct_30d_ago: float = 50.0


def derive_market_cycle(values, i):
    """Classify market cycle label at index i (same rules as webapp._market_snapshot).

    Single source of truth so backtest (build_market_context) and live analysis
    produce identical market_cycle values. values: full ascending close prices.
    """
    cur = values[i]
    m7 = values[i - 7] if i >= 7 else values[0]
    m30 = values[i - 30] if i >= 30 else values[0]
    chg7 = (cur - m7) / m7 * 100 if m7 > 0 else 0.0
    chg30 = (cur - m30) / m30 * 100 if m30 > 0 else 0.0
    mean_m = sum(values) / len(values) if values else 1.0
    vol7 = 0.0
    if mean_m > 0:
        recent = values[max(0, i - 6):i + 1]
        vol7 = (sum((v - mean_m) ** 2 for v in recent) / len(recent)) ** 0.5 / mean_m * 100
    if chg30 > 5 and chg7 > 1:
        return "bull"
    if chg30 < -5 and chg7 < -1:
        return "bear"
    if vol7 > 3:
        return "volatile"
    if abs(chg30) <= 3 and abs(chg7) <= 1:
        return "sideways"
    if chg30 < -2:
        return "distribution" if chg7 < 0 else "accumulation"
    return "sideways"

def compute_market_trend_health(prices, volumes=None, cycle_phase="unknown",

                                 event_risk_discount=1.0,

                                 volume_divergence_discount=1.0, bubble_breadth_discount=1.0, pct_30d_ago=50.0,
                                 zscore_90d=None, percentile_90d=None):

# Compute 21-day peak drop before trend health (uses original prices)
    drop_from_peak_pct = 0.0
    if len(prices) >= 21:
        peak_21d = max(prices[-21:])
        if peak_21d > 0:
            drop_from_peak_pct = round((prices[-1] / peak_21d - 1) * 100, 1)

    th = compute_trend_health(prices=prices, volumes=volumes, cycle_phase=cycle_phase,

                               whale_prob=0.0, position_lock_score=0, liquidity_score=100)

    raw = th.score

    deductions = []

    if event_risk_discount < 1.0:

        th.score = round(th.score * event_risk_discount)

        deductions.append("事件风险折价 x{:.1f}".format(event_risk_discount))

    if volume_divergence_discount < 1.0:

        th.score = round(th.score * volume_divergence_discount)

        deductions.append("量价背离折价 x{:.1f}".format(volume_divergence_discount))

    if bubble_breadth_discount < 1.0:

        th.score = round(th.score * bubble_breadth_discount)

        deductions.append("泡沫广度折价 x{:.1f}".format(bubble_breadth_discount))

    th.z_floor_applied = False
    if th.raw_direction == "down":
        # Oversold TH floor: when Z is extreme and percentile rock-bottom,
        # TH should not collapse completely - extreme value IS the signal
        if zscore_90d is not None and zscore_90d <= -2.0 and percentile_90d is not None and percentile_90d <= 20:
            z_floor = 15 + abs(zscore_90d + 2.0) * 15  # z=-2.0->15, z=-2.5->22, z=-3.0->30
            th.z_floor_applied = th.score < z_floor
            th.score = max(th.score, min(round(z_floor), 35))

        th.score = min(th.score, 45)

    elif th.raw_direction == "flat":

        th.score = min(th.score, 65)

    th.score = max(0, min(100, th.score))


    if th.score >= T["TH_STRONG"]:

        level = "\u5f3a\u52bf"; level_label = "\U0001f7e2 \u5f3a\u52bf"

    elif th.score >= T["TH_NEUTRAL"]:

        level = "\u4e2d\u6027\u504f\u5f3a"; level_label = "\U0001f7e1 \u4e2d\u6027\u504f\u5f3a"

    elif th.score >= T["TH_WEAK"]:

        level = "\u4e2d\u6027\u65e0\u5e8f"; level_label = "\U0001f7e1 \u4e2d\u6027"

    else:

        level = "\u5f31\u52bf"; level_label = "\U0001f534 \u5f31\u52bf"

    return MarketTrendHealth(

        raw_score=raw, score=th.score, level=level, level_label=level_label,

        direction=th.direction, persistence_score=th.persistence_score,

        steepness_score=th.steepness_score, structure_score=th.structure_score,

        volume_score=th.volume_score, anomaly_score=th.anomaly_score,


        ma_cross_type=th.ma_cross_type, steepness_signal=th.steepness_signal,

        volume_signal=th.volume_signal, has_anomaly=th.has_anomaly,

        anomaly_count=th.anomaly_count, anomaly_type=th.anomaly_type,


        volume_divergence=(volume_divergence_discount < 1.0),

        volume_divergence_label="\u65e0\u91cf\u62c9\u5347" if volume_divergence_discount < 1.0 else "",

        drop_from_peak_pct=drop_from_peak_pct,
        pct_30d_ago=pct_30d_ago,

    )





def market_th_summary(mth):

    return dict(raw_score=mth.raw_score, score=mth.score, level=mth.level,

                level_label=mth.level_label, direction=mth.direction,

                persistence_score=mth.persistence_score,

                steepness_score=mth.steepness_score,

                structure_score=mth.structure_score,

                volume_score=mth.volume_score,

                anomaly_score=mth.anomaly_score,


                ma_structure=mth.ma_structure,

                ma_cross_type=mth.ma_cross_type,

                steepness_signal=mth.steepness_signal,

                volume_signal=mth.volume_signal,

                drop_from_peak_pct=mth.drop_from_peak_pct,
                pct_30d_ago=mth.pct_30d_ago,

                has_anomaly=mth.has_anomaly,

                anomaly_count=mth.anomaly_count,

                anomaly_type=mth.anomaly_type,


                deduction_sources=mth.deduction_sources,

                volume_divergence=mth.volume_divergence,

                volume_divergence_label=mth.volume_divergence_label,

                bubble_breadth=mth.bubble_breadth,

                bubble_breadth_label=mth.bubble_breadth_label)





@dataclass

class MarketFusionDecision:

    percentile_90d: float = 50.0

    raw_th_score: int = 50

    corrected_th_score: int = 50

    zone: str = "neutral"

    zone_label: str = ""

    action: str = "watch"

    action_label: str = ""

    action_detail: str = ""

    deduction_sources: list = field(default_factory=list)

    global_position_limit: float = 1.0

    percentile_trend: str = "flat"
    drop_from_peak_pct: float = 0.0
    pct_30d_ago: float = 50.0
    micro_th_score: int = 50
    is_bear: bool = False
    cap_triggered: bool = False
    rally_decay: bool = False
    market_regime: str = "sideways"
    selling_pressure_score: int = 50
    volatility_regime: str = "normal"


    rebound_late: bool = False

    hysteresis_applied: bool = False

    maturing_detail: str = ""





def compute_market_fusion_decision(percentile_90d, th, zscore_90d=0.0, cycle_phase="unknown", event_risk_discount=1.0, percentile_trend="flat", micro_th_score=None, is_bear=False, cap_triggered=False, rally_decay=False, sentiment_score=50, market_regime="sideways", selling_pressure_score=50, volatility_regime="normal", prices=None):

    fd = MarketFusionDecision(percentile_90d=percentile_90d,

        raw_th_score=th.raw_score, corrected_th_score=th.score,

        deduction_sources=th.deduction_sources)

    fd.percentile_trend = percentile_trend
    fd.drop_from_peak_pct = th.drop_from_peak_pct
    fd.pct_30d_ago = th.pct_30d_ago
    fd.micro_th_score = micro_th_score if micro_th_score is not None else 50
    fd.is_bear = is_bear
    fd.cap_triggered = cap_triggered
    fd.rally_decay = rally_decay
    fd.market_regime = market_regime
    fd.selling_pressure_score = selling_pressure_score
    fd.volatility_regime = volatility_regime

    score = th.score
    # P1-2 牛熊动态 TH 阈值 (2026-08-02 数据验证: 2025 牛市段回调日 13/13 100% 胜率)
    th_neutral_eff = T["TH_NEUTRAL"]
    if market_regime in ("bull", "sideways"):
        th_neutral_eff = max(30, th_neutral_eff - 5)  # 35->30: 牛市/震荡回调买点提前触发

    # --- Hysteresis: debounce threshold boundaries ---

    effective_pct = percentile_90d

    hysteresis_applied = False

    # Boundary 28-35 (undervalued -> fair): require clear trend to switch

    if 28 < percentile_90d <= 35 and percentile_trend == "falling":

        effective_pct = 28  # keep in undervalued zone

        hysteresis_applied = True

    # Boundary 25-32 (fair -> undervalued): require falling to cross down

    if 25 <= percentile_90d <= 32 and percentile_trend == "rising":

        effective_pct = 28  # keep in undervalued zone (hysteresis: delay fair transition when rising)

        hysteresis_applied = True

    # Boundary 65-72 (fair -> overvalued): require rising to cross up

    if 65 <= percentile_90d <= 72 and percentile_trend == "rising":

        effective_pct = 72  # enter overvalued early

        hysteresis_applied = True

    # Boundary 65-75 (overvalued -> fair): require falling to cross down

    if 68 <= percentile_90d <= 75 and percentile_trend == "falling":

        effective_pct = 68  # keep in fair zone

        hysteresis_applied = True

    fd.hysteresis_applied = hysteresis_applied

    # Rebound maturing detection (方向B)

    rebound_late = False

    maturing_detail = ""

    if percentile_90d <= 30 and percentile_trend in ("rising",) and zscore_90d > -1.2 and zscore_90d < 0.0:

        # Percentile still undervalued but recovering — possible late rebound

        rebound_late = True

        if 20 <= percentile_90d <= 30:

            maturing_detail = "估值低位反弹后半段，继续上行空间有限"

        else:

            maturing_detail = "深跌后快速反弹，注意回落风险"

    fd.rebound_late = rebound_late

    fd.maturing_detail = maturing_detail

    # ---- Sentiment resonance/conflict/bubble rules (P0) ----
    sent_boost = 0
    sentiment_conflict = False
    bubble_resonance = False
    sent_detail = ""

    # Resonance: extreme fear + deep undervalue
    if sentiment_score >= 85 and percentile_90d <= 20:
        sent_boost = 3
        sent_detail = "极度恐惧+深度低估共振, TH+3"
    # Conflict: undervalue + mild greed
    if percentile_90d <= 25 and sentiment_score <= 35:
        sent_boost = -2
        sentiment_conflict = True
        sent_detail = "低估+轻度贪婪冲突, TH-2"
    # Bubble hard cap: extreme greed + bubble
    if percentile_90d >= 90 and sentiment_score <= 20:
        bubble_resonance = True

    if sent_boost != 0:
        score = score + sent_boost
        fd.deduction_sources = list(fd.deduction_sources or [])
        fd.deduction_sources.append(sent_detail)

    if effective_pct <= 45:

        fd.zone = "undervalued"; fd.zone_label = "低估区间"

        # S25-45: context-aware buy (p≤45 + TH≥35 + Z≤0.5 + 30天前市场健康)
        if score >= T["TH_NEUTRAL"] + 5 and zscore_90d <= 0.5 and fd.pct_30d_ago > 50:
            fd.action = "buy"; fd.action_label = "🟢 低估区间·分批建仓"
            fd.action_detail = "大盘低估+趋势中性偏强，近期市场环境健康，分批建仓"
            fd.global_position_limit = 0.30

        # Original: deep undervalue + strong trend (p≤30 + TH≥55 + Z≤0)
        elif effective_pct <= 30 and score >= T["TH_STRONG"] and zscore_90d <= 0:
            if rebound_late:
                fd.action = "watch"; fd.action_label = "🟡 反弹末期·轻仓试探"
                fd.action_detail = "低估+趋势健康但处于反弹后半段，轻仓试探，严格止损"
                fd.global_position_limit = 0.15
            else:
                # V5 fake-bottom gate (2026-07 数据验证): 建仓区域需 30日深跌 OR 14日急跌
                if prices is None:
                    deep_ok = True
                else:
                    chg30 = (prices[-1] / prices[-31] - 1) * 100 if len(prices) >= 31 else None
                    chg14 = (prices[-1] / prices[-15] - 1) * 100 if len(prices) >= 15 else None
                    chg21 = (prices[-1] / prices[-22] - 1) * 100 if len(prices) >= 22 else None
                    # V5.1 (2026-08 数据验证): 深跌确认 OR 低位温和反弹(21日涨幅0~8%)放行
                    # 拦截 6/15(+20.1% 追高)/6/18(+9.8%)/6/30(-8.1% 中继), 放行 2月小牛六连发(14d全胜)
                    deep_ok = ((chg30 is not None and chg30 <= -20)
                               or (chg14 is not None and chg14 <= -10)
                               or (chg21 is not None and 0 <= chg21 <= 8))
                if not deep_ok:
                    fd.action = "watch"; fd.action_label = "🟡 假底部·观望"
                    fd.action_detail = "低估+趋势健康但 30日未深跌/近期无急跌，疑似反弹末端或假底部，观望"
                    fd.global_position_limit = 0.10
                else:
                    fd.action = "buy"; fd.action_label = "🟢 建仓区域"
                    fd.action_detail = "大盘低估+趋势健康，适合分批建仓"
                    fd.global_position_limit = 0.30

        # P1-2 牛市深度回调买点: 非熊市 + 深度回调(drop21<=−12%) + TH>=30 + z<=0.5
        elif (market_regime == "bull" and score >= 30
              and zscore_90d <= 0.5 and th.drop_from_peak_pct <= -12):
            fd.action = "buy"
            fd.action_label = "🟢 牛市深调·分批介入"
            fd.action_detail = "牛市深度回调确认，估值低位，可分批介入"
            fd.global_position_limit = 0.20

        # TH≥35 at p≤30: watch/bottom watch
        elif effective_pct <= 30 and score >= T["TH_NEUTRAL"] + 10:
            if rebound_late:
                fd.action = "watch"; fd.action_label = "🟡 反弹尾声·观望"
                fd.action_detail = "低估但反弹已近尾声，不追涨，等待回调机会"
                fd.global_position_limit = 0.10
            else:
                fd.action = "watch"; fd.action_label = "🟡 筑底观察"
                fd.action_detail = "大盘低估但趋势偏弱，等待趋势确认"
                fd.global_position_limit = 0.15

        # TH<35 at p≤30: avoid unless accumulation
        elif effective_pct <= 30:
            if cycle_phase == "accumulation":
                fd.action = "watch"; fd.action_label = "🟡 筑底观察"
                fd.action_detail = "大盘低估+吸筹期，趋势弱但底部特征明显，可轻仓参与，分批建仓"
                fd.global_position_limit = 0.15
            else:
                fd.action = "avoid"; fd.action_label = "🔴 下跌中继"
                fd.action_detail = "大盘低估但趋势极弱，暂不参与"
                fd.global_position_limit = 0.05

        # p30-45 + S25-45 not met: based on trend
        else:
            if score >= T["TH_STRONG"]:
                fd.action = "hold"; fd.action_label = "🟢 健康持有"
                fd.action_detail = "大盘趋势健康，持仓不动"
                fd.global_position_limit = 0.25
            elif score >= th_neutral_eff:
                fd.action = "watch"; fd.action_label = "🟡 震荡观望"
                fd.action_detail = "大盘合理区间但趋势中性"
                fd.global_position_limit = 0.15
            else:
                fd.action = "reduce"; fd.action_label = "🟡 回调关注"
                fd.action_detail = "大盘趋势转弱，注意回调"
                fd.global_position_limit = 0.10

    elif effective_pct <= 70:

        fd.zone = "fair"; fd.zone_label = "\u5408\u7406\u533a\u95f4"

        if score >= T["TH_STRONG"]:

            fd.action = "hold"; fd.action_label = "\U0001f7e2 \u5065\u5eb7\u6301\u6709"

            fd.action_detail = "\u5927\u76d8\u8d8b\u52bf\u5065\u5eb7\uff0c\u6301\u4ed3\u4e0d\u52a8"

            fd.global_position_limit = 0.25

        elif score >= T["TH_NEUTRAL"]:

            # Drop-triggered buy: catches bull market pullbacks before full recovery
            if th.drop_from_peak_pct <= -12 and zscore_90d <= 0.5:
                fd.action = "buy"; fd.action_label = "\U0001f7e2 \u56de\u8c03\u786e\u8ba4\u00b7\u5206\u6279\u4ecb\u5165"
                fd.action_detail = f"\u5927\u76d8\u4ece\u8fd121\u65e5\u9ad8\u70b9\u56de\u843d{th.drop_from_peak_pct:.0f}%\uff0c\u8d8b\u52bf\u5df2\u7a33\u5b9a\u5c5e\u56de\u8c03\u786e\u8ba4\u4e70\u70b9\uff0c\u5206\u6279\u4ecb\u5165"
                fd.global_position_limit = 0.20
            else:
                fd.action = "watch"; fd.action_label = "\U0001f7e1 \u9707\u8361\u89c2\u671b"

                fd.action_detail = "\u5927\u76d8\u5408\u7406\u533a\u95f4\u4f46\u8d8b\u52bf\u4e2d\u6027"

                fd.global_position_limit = 0.15

        else:

            fd.action = "reduce"; fd.action_label = "\U0001f7e1 \u56de\u8c03\u5173\u6ce8"

            fd.action_detail = "\u5927\u76d8\u8d8b\u52bf\u8f6c\u5f31\uff0c\u6ce8\u610f\u56de\u8c03"

            fd.global_position_limit = 0.10

    else:

        fd.zone = "overvalued"; fd.zone_label = "\u9ad8\u4f30\u533a\u95f4"

        if percentile_90d >= 95 and zscore_90d >= 2.5:

            fd.action = "sell"; fd.action_label = "\U0001f534 \u6781\u7aef\u6ce1\u6cab\u00b7\u6e05\u4ed3"

            fd.action_detail = "\u5927\u76d8\u6781\u5ea6\u6ce1\u6cab\uff0c\u5f3a\u5236\u6e05\u4ed3"

            fd.global_position_limit = 0.0

        elif score >= T["TH_STRONG"]:

            fd.action = "reduce"; fd.action_label = "\U0001f7e0 \u62b1\u56e2\u884c\u60c5\u00b7\u5206\u6279\u6b62\u76c8"

            fd.action_detail = "\u5927\u76d8\u9ad8\u4f30\u4f46\u8d8b\u52bf\u4ecd\u5f3a\uff0c\u53ea\u51fa\u4e0d\u8fdb"

            fd.global_position_limit = 0.10

        elif score >= T["TH_NEUTRAL"]:

            fd.action = "reduce"; fd.action_label = "\U0001f7e0 \u9ad8\u4f4d\u6a2a\u76d8\u00b7\u51cf\u4ed3"

            fd.action_detail = "\u5927\u76d8\u9ad8\u4f4d\u8d8b\u52bf\u8d70\u5f31\uff0c\u5927\u5e45\u51cf\u4ed3"

            fd.global_position_limit = 0.05

        else:

            fd.action = "sell"; fd.action_label = "\U0001f534 \u8d8b\u52bf\u53cd\u8f6c\u00b7\u6e05\u4ed3"

            fd.action_detail = "\u5927\u76d8\u9ad8\u4f4d\u8d8b\u52bf\u5d29\u584c\uff0c\u65e0\u6761\u4ef6\u79bb\u573a"

            fd.global_position_limit = 0.0
    # ---- Micro TH override: catch small cycles within big trend ----
    if micro_th_score is not None and micro_th_score > 0:
        micro_up = {"low_volatile": 45, "high_volatile": 55}.get(volatility_regime, 50)
        micro_strong = {"low_volatile": 60, "high_volatile": 70}.get(volatility_regime, 65)
        micro_down = {"low_volatile": 30, "high_volatile": 40}.get(volatility_regime, 35)
        if fd.action in ("avoid",) and micro_th_score >= micro_up and fd.zone == "undervalued":
            fd.action = "watch"
            fd.action_label = "🟡 短期反转·观察"
            fd.action_detail = "大盘长期仍弱，但短期反转确认，可轻仓尝试"
            fd.global_position_limit = max(fd.global_position_limit, 0.12)
        if fd.action in ("watch",) and fd.zone == "undervalued" and micro_th_score >= micro_strong:
            if (is_bear and not cap_triggered) or fd.rally_decay:
                fd.action = "watch"
                fd.action_label = "🟡 短期反转·观察"
                fd.action_detail = "熊市反弹，动能衰减，暂缓建仓"
            else:
                fd.action = "buy"
                fd.action_label = "🟢 短期反转·分批建仓"
                fd.action_detail = "大盘短期反转强劲，可分批建仓"
                fd.global_position_limit = max(fd.global_position_limit, 0.20)
        if micro_th_score < micro_down and fd.action in ("hold", "buy") and fd.zone in ("fair", "undervalued"):
            fd.action = "reduce"
            fd.action_label = "🟡 短期衰减·减仓"
            fd.action_detail = "短期动能衰减，注意回调"
            fd.global_position_limit = min(fd.global_position_limit, 0.10)
    if fd.rally_decay:
        # Downgrade buy/watch signals when rally momentum is decaying.
        # Exception: fresh V-bottom where zscore is still deeply negative.
        if fd.action in ("watch", "buy") and fd.zone in ("fair", "undervalued"):
            is_fresh_vbottom = (fd.corrected_th_score >= T["TH_STRONG"]
                                and fd.zone == "undervalued"
                                and fd.percentile_90d <= 30
                                and zscore_90d <= -1.0)
            if is_fresh_vbottom:
                pass  # True V-bottom: zscore still deeply negative, rally just starting
            else:
                fd.action = "reduce"
                fd.action_label = "🟡 反弹衰竭·减仓"
                fd.action_detail = "反弹动能衰竭，注意回调风险"
                fd.global_position_limit = min(fd.global_position_limit, 0.10)

    # ---- Selling pressure exhaustion override (v4.6) ----
    if selling_pressure_score >= 70:
        if fd.action in ("avoid", "sell", "reduce") and percentile_90d <= 20:
            fd.action = "watch"
            fd.action_label = "🟡 抛压衰竭·底部观察"
            fd.action_detail = "卖方力量枯竭+止跌企稳，底部特征显现，轻仓观察"
            fd.global_position_limit = max(fd.global_position_limit, 0.10)
        if selling_pressure_score >= 85 and percentile_90d <= 15 and (micro_th_score or 0) >= 55:
            fd.action = "buy"
            fd.action_label = "🟢 抛压衰竭·分批建仓"
            fd.action_detail = "深度恐慌后卖方枯竭，短期企稳，可分批建仓"
            fd.global_position_limit = max(fd.global_position_limit, 0.15)

    # ---- Sentiment conflict cap: undervalue + mild greed -> 5% max ----
    if sentiment_conflict:
        if fd.global_position_limit > 0.05:
            fd.global_position_limit = 0.05


    # ---- Bubble resonance hard cap: override everything ----
    if bubble_resonance:
        fd.action = "avoid"
        fd.action_label = "🔴 泡沫共振·禁止开仓"
        fd.action_detail = "极度贪婪+估值泡沫，全局禁止新开多仓"
        fd.global_position_limit = 0.0
        return fd

    # ---- Extreme oversold override: V-bottom detection ----
    if fd.action == "avoid" and sentiment_score >= 85 and percentile_90d <= 5 and zscore_90d <= -2.0 and (th.z_floor_applied or score < 25):
        fd.action = "watch"
        fd.action_label = "🟡 极限超跌·底部观察"
        fd.action_detail = "极度恐惧+深度超卖，V型底部特征明显，轻仓观察"
        fd.global_position_limit = max(fd.global_position_limit, 0.10)

    # Bear market safety net: weak buy without capitulation + falling price -> hold
    if fd.action == "buy" and fd.is_bear and not fd.cap_triggered:
        if fd.corrected_th_score < 65 and fd.percentile_trend == "falling":
            fd.action = "hold"
            fd.action_label = "\U0001f7e1 \u718a\u5e02\u4e0d\u8ffd\u00b7\u6301\u4ed3\u89c2\u671b"
            fd.action_detail = "\u718a\u5e02\u4e2d\u6ca1\u6709\u66b4\u8dcc\u6b62\u8dcc\u4fe1\u53f7\uff0c\u6682\u4e0d\u5efa\u4ed3"

    return fd






def compute_market_regime(prices):
    """Determine market regime: bull / sideways / bear.
    Based on MA30 vs MA90 relationship + MA90 trend confirmation.
    Bull requires BOTH MA30>MA90 AND MA90 rising (filters bear market bounces).
    Returns: (regime: str, label: str, class: str, detail: str)
    """
    if len(prices) < 90:
        return ("sideways", "不足", "", "数据不足无法判断")
    ma30 = sum(prices[-30:]) / 30
    ma90 = sum(prices[-90:]) / 90
    ratio = ma30 / ma90 - 1
    # MA90 trend: is the 90d average rising?
    ma90_rising = sum(prices[-30:]) / 30 > sum(prices[-120:-90]) / 30 if len(prices) >= 120 else True
    if ratio < -0.03:
        return ("bear", "🐴 熊市", "bear", f"MA30较MA90低{abs(ratio)*100:.0f}%，下跌趋势")
    elif ratio > 0.03 and ma90_rising:
        return ("bull", "🐂 牛市", "bull", f"MA30较MA90高{ratio*100:.0f}%，上升趋势")
    else:
        return ("sideways", "📊 震荡", "sideways", f"MA30较MA90{ratio*100:+.1f}%，无明显方向")

def market_fd_summary(fd):

    return dict(percentile_90d=fd.percentile_90d, raw_th_score=fd.raw_th_score,

                corrected_th_score=fd.corrected_th_score, zone=fd.zone,

                zone_label=fd.zone_label, action=fd.action, drop_from_peak_pct=fd.drop_from_peak_pct,

                action_label=fd.action_label, action_detail=fd.action_detail,

                deduction_sources=fd.deduction_sources,

                global_position_limit=fd.global_position_limit,

                percentile_trend=fd.percentile_trend,

                rebound_late=fd.rebound_late,

                hysteresis_applied=fd.hysteresis_applied,

                maturing_detail=fd.maturing_detail,
                micro_th_score=fd.micro_th_score,
                is_bear=fd.is_bear,
                cap_triggered=fd.cap_triggered,
                rally_decay=fd.rally_decay,
                pct_30d_ago=fd.pct_30d_ago)



