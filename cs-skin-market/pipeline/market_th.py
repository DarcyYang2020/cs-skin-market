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





def compute_market_trend_health(prices, volumes=None, cycle_phase="unknown",

                                 event_risk_discount=1.0,

                                 volume_divergence_discount=1.0, bubble_breadth_discount=1.0):

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

    if th.raw_direction == "down":

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

    rebound_late: bool = False

    hysteresis_applied: bool = False

    maturing_detail: str = ""





def compute_market_fusion_decision(percentile_90d, th, zscore_90d=0.0, cycle_phase="unknown", event_risk_discount=1.0, percentile_trend="flat"):

    fd = MarketFusionDecision(percentile_90d=percentile_90d,

        raw_th_score=th.raw_score, corrected_th_score=th.score,

        deduction_sources=th.deduction_sources)

    fd.percentile_trend = percentile_trend

    score = th.score

    # --- Hysteresis: debounce threshold boundaries ---

    effective_pct = percentile_90d

    hysteresis_applied = False

    # Boundary 28-35 (undervalued -> fair): require clear trend to switch

    if 28 < percentile_90d <= 35 and percentile_trend == "falling":

        effective_pct = 28  # keep in undervalued zone

        hysteresis_applied = True

    # Boundary 25-32 (fair -> undervalued): require falling to cross down

    if 25 <= percentile_90d <= 32 and percentile_trend == "rising":

        effective_pct = 72  # keep in fair zone

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

    if effective_pct <= 30:

        fd.zone = "undervalued"; fd.zone_label = "\u4f4e\u4f30\u533a\u95f4"

        if score >= T["TH_STRONG"]:

            if rebound_late:

                fd.action = "watch"; fd.action_label = "\U0001f7e1 \u53cd\u5f39\u672b\u671f\u00b7\u8f7b\u4ed3\u8bd5\u63a2"

                fd.action_detail = "\u4f4e\u4f30+\u8d8b\u52bf\u5065\u5eb7\u4f46\u5904\u4e8e\u53cd\u5f39\u540e\u534a\u6bb5\uff0c\u8f7b\u4ed3\u8bd5\u63a2\uff0c\u4e25\u683c\u6b62\u635f"

                fd.global_position_limit = 0.15

            else:

                fd.action = "buy"; fd.action_label = "\U0001f7e2 \u5efa\u4ed3\u533a\u57df"

                fd.action_detail = "\u5927\u76d8\u4f4e\u4f30+\u8d8b\u52bf\u5065\u5eb7\uff0c\u9002\u5408\u5206\u6279\u5efa\u4ed3"

                fd.global_position_limit = 0.30

        elif score >= T["TH_NEUTRAL"]:

            if rebound_late:

                fd.action = "watch"; fd.action_label = "\U0001f7e1 \u53cd\u5f39\u5c3e\u58f0\u00b7\u89c2\u671b"

                fd.action_detail = "\u4f4e\u4f30\u4f46\u53cd\u5f39\u5df2\u8fd1\u5c3e\u58f0\uff0c\u4e0d\u8ffd\u6da8\uff0c\u7b49\u5f85\u56de\u8c03\u673a\u4f1a"

                fd.global_position_limit = 0.10

            else:

                fd.action = "watch"; fd.action_label = "\U0001f7e1 \u7b51\u5e95\u89c2\u5bdf"

                fd.action_detail = "\u5927\u76d8\u4f4e\u4f30\u4f46\u8d8b\u52bf\u504f\u5f31\uff0c\u7b49\u5f85\u8d8b\u52bf\u786e\u8ba4"

            fd.global_position_limit = 0.15

        else:
            if cycle_phase == "accumulation":
                fd.action = "watch"; fd.action_label = "🟡 筑底观察"
                fd.action_detail = "大盘低估+吸筹期，趋势弱但底部特征明显，可轻仓参与，分批建仓"
                fd.global_position_limit = 0.15
            else:
                fd.action = "avoid"; fd.action_label = "🔴 下跌中继"
                fd.action_detail = "大盘低估但趋势极弱，暂不参与"
                fd.global_position_limit = 0.05

    elif effective_pct <= 70:

        fd.zone = "fair"; fd.zone_label = "\u5408\u7406\u533a\u95f4"

        if score >= T["TH_STRONG"]:

            fd.action = "hold"; fd.action_label = "\U0001f7e2 \u5065\u5eb7\u6301\u6709"

            fd.action_detail = "\u5927\u76d8\u8d8b\u52bf\u5065\u5eb7\uff0c\u6301\u4ed3\u4e0d\u52a8"

            fd.global_position_limit = 0.25

        elif score >= T["TH_NEUTRAL"]:

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

    return fd





def market_fd_summary(fd):

    return dict(percentile_90d=fd.percentile_90d, raw_th_score=fd.raw_th_score,

                corrected_th_score=fd.corrected_th_score, zone=fd.zone,

                zone_label=fd.zone_label, action=fd.action,

                action_label=fd.action_label, action_detail=fd.action_detail,

                deduction_sources=fd.deduction_sources,

                global_position_limit=fd.global_position_limit,

                percentile_trend=fd.percentile_trend,

                rebound_late=fd.rebound_late,

                hysteresis_applied=fd.hysteresis_applied,

                maturing_detail=fd.maturing_detail)



