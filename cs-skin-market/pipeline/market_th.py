# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
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
    key_level_score: int = 50
    ma_structure: str = ""
    ma_cross_type: str = ""
    steepness_signal: str = ""
    volume_signal: str = ""
    has_anomaly: bool = False
    anomaly_count: int = 0
    anomaly_type: str = "none"
    key_level_signal: str = ""
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
    if th.score >= 70:
        level = "\u5f3a\u52bf"; level_label = "\U0001f7e2 \u5f3a\u52bf"
    elif th.score >= 50:
        level = "\u4e2d\u6027\u504f\u5f3a"; level_label = "\U0001f7e1 \u4e2d\u6027\u504f\u5f3a"
    elif th.score >= 35:
        level = "\u4e2d\u6027\u65e0\u5e8f"; level_label = "\U0001f7e1 \u4e2d\u6027"
    else:
        level = "\u5f31\u52bf"; level_label = "\U0001f534 \u5f31\u52bf"
    return MarketTrendHealth(
        raw_score=raw, score=th.score, level=level, level_label=level_label,
        direction=th.direction, persistence_score=th.persistence_score,
        steepness_score=th.steepness_score, structure_score=th.structure_score,
        volume_score=th.volume_score, anomaly_score=th.anomaly_score,
        key_level_score=th.key_level_score, ma_structure=th.ma_structure,
        ma_cross_type=th.ma_cross_type, steepness_signal=th.steepness_signal,
        volume_signal=th.volume_signal, has_anomaly=th.has_anomaly,
        anomaly_count=th.anomaly_count, anomaly_type=th.anomaly_type,
        key_level_signal=th.key_level_signal, deduction_sources=deductions,
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
                key_level_score=mth.key_level_score,
                ma_structure=mth.ma_structure,
                ma_cross_type=mth.ma_cross_type,
                steepness_signal=mth.steepness_signal,
                volume_signal=mth.volume_signal,
                has_anomaly=mth.has_anomaly,
                anomaly_count=mth.anomaly_count,
                anomaly_type=mth.anomaly_type,
                key_level_signal=mth.key_level_signal,
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


def compute_market_fusion_decision(percentile_90d, th, zscore_90d=0.0):
    fd = MarketFusionDecision(percentile_90d=percentile_90d,
        raw_th_score=th.raw_score, corrected_th_score=th.score,
        deduction_sources=th.deduction_sources)
    score = th.score
    if percentile_90d <= 30:
        fd.zone = "undervalued"; fd.zone_label = "\u4f4e\u4f30\u533a\u95f4"
        if score >= 60:
            fd.action = "buy"; fd.action_label = "\U0001f7e2 \u5efa\u4ed3\u533a\u57df"
            fd.action_detail = "\u5927\u76d8\u4f4e\u4f30+\u8d8b\u52bf\u5065\u5eb7\uff0c\u9002\u5408\u5206\u6279\u5efa\u4ed3"
            fd.global_position_limit = 0.30
        elif score >= 40:
            fd.action = "watch"; fd.action_label = "\U0001f7e1 \u7b51\u5e95\u89c2\u5bdf"
            fd.action_detail = "\u5927\u76d8\u4f4e\u4f30\u4f46\u8d8b\u52bf\u504f\u5f31\uff0c\u7b49\u5f85\u8d8b\u52bf\u786e\u8ba4"
            fd.global_position_limit = 0.15
        else:
            fd.action = "avoid"; fd.action_label = "\U0001f534 \u4e0b\u8dcc\u4e2d\u7ee7"
            fd.action_detail = "\u5927\u76d8\u4f4e\u4f30\u4f46\u8d8b\u52bf\u6781\u5f31\uff0c\u6682\u4e0d\u53c2\u4e0e"
            fd.global_position_limit = 0.05
    elif percentile_90d <= 70:
        fd.zone = "fair"; fd.zone_label = "\u5408\u7406\u533a\u95f4"
        if score >= 70:
            fd.action = "hold"; fd.action_label = "\U0001f7e2 \u5065\u5eb7\u6301\u6709"
            fd.action_detail = "\u5927\u76d8\u8d8b\u52bf\u5065\u5eb7\uff0c\u6301\u4ed3\u4e0d\u52a8"
            fd.global_position_limit = 0.25
        elif score >= 50:
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
        elif score >= 70:
            fd.action = "reduce"; fd.action_label = "\U0001f7e0 \u62b1\u56e2\u884c\u60c5\u00b7\u5206\u6279\u6b62\u76c8"
            fd.action_detail = "\u5927\u76d8\u9ad8\u4f30\u4f46\u8d8b\u52bf\u4ecd\u5f3a\uff0c\u53ea\u51fa\u4e0d\u8fdb"
            fd.global_position_limit = 0.10
        elif score >= 40:
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
                global_position_limit=fd.global_position_limit)

