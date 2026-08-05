# -*- coding: utf-8 -*-
"""Market macro data collector + signal computer.

Sources (csQAQ /api/v1/current_data?type=volume):
  - rate_data: market breadth (items up/down/flat over multiple timeframes)
  - greedy: greed/fear index (60-day history)
  - online_chart: daily online player count (978 days)
  - online_number: current/today/month peak online
  - card_price: recharge card price history (179 days)

All data cached for 10 minutes to avoid rate limiting.
"""

import time as _time
from dataclasses import dataclass

_cache_ts = 0
_cache_data = None


def _fetch_macro():
    """Fetch macro data from csQAQ, cached for 10 min.
    Uses collector._api_get for built-in rate limiting and retry."""
    global _cache_ts, _cache_data
    now = _time.time()
    if _cache_data is not None and (now - _cache_ts) < 600:
        return _cache_data
    from .collector import _api_get
    resp = _api_get("/current_data?type=volume")
    _cache_data = resp.get("data", {})
    _cache_ts = now
    _persist_macro(_cache_data)
    return _cache_data


def _persist_macro(d: dict):
    """Write-through: backfill the FULL greedy/card_price history.

    csQAQ returns ~60d of greedy and ~180d of card_price, each point carrying its
    own date. Persist every point (not just the latest) so backtests can use real
    historical sentiment instead of the price-action proxy.
    """
    try:
        greedy = d.get("greedy", [])
        card = d.get("card_price", [])
        rows_by_date = {}
        for pt in greedy:
            if isinstance(pt, list) and len(pt) > 1 and pt[0]:
                try:
                    date = str(pt[0])[:10]
                    rows_by_date[date] = [date, float(pt[1]), None]
                except (TypeError, ValueError):
                    continue
        for pt in card:
            if isinstance(pt, dict) and pt.get("created_at"):
                date = str(pt["created_at"])[:10]
                entry = rows_by_date.setdefault(date, [date, None, None])
                try:
                    entry[2] = float(pt.get("card_price"))
                except (TypeError, ValueError):
                    continue
        if not rows_by_date:
            return
        from .db import get_conn, save_macro_snapshots
        conn = get_conn()
        try:
            save_macro_snapshots(conn, rows_by_date.values())
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # persistence is best-effort, never break live analysis


# ============================================================
#  Market Breadth Score (0-100)
# ============================================================

def compute_breadth_score(days: int = 7) -> float:
    """Compute market breadth health 0-100 from rate_data.

    Higher = more items rising than falling (bullish breadth).
    Lower = more items falling (bearish breadth / panic).
    """
    d = _fetch_macro()
    rd = d.get("rate_data", {})
    pos = rd.get(f"count_positive_{days}", 0)
    neg = rd.get(f"count_negative_{days}", 0)
    zero = rd.get(f"count_zero_{days}", 0)
    total = pos + neg + zero
    if total == 0:
        return 50.0
    ratio = pos / max(neg, 1)
    if ratio >= 2.0:
        return 90.0
    elif ratio >= 1.5:
        return 75.0
    elif ratio >= 1.2:
        return 65.0
    elif ratio >= 1.0:
        return 55.0
    elif ratio >= 0.8:
        return 50.0
    elif ratio >= 0.6:
        return 40.0
    elif ratio >= 0.4:
        return 25.0
    elif ratio >= 0.25:
        return 15.0
    else:
        return 5.0


def breadth_label(score: float) -> str:
    if score >= 80: return "极度强势"
    elif score >= 65: return "偏多"
    elif score >= 45: return "中性"
    elif score >= 25: return "偏空"
    elif score >= 10: return "恐慌"
    else: return "极度恐慌"


# ============================================================
#  Greed/Fear Sentiment Score (0-100, contrarian)
# ============================================================

def greedy_to_sentiment(current: float) -> float:
    """Map raw greedy index -> contrarian sentiment 0-100.

    0 = extreme greed (danger, contrarian sell).
    100 = extreme fear (opportunity, contrarian buy).
    """
    if current >= 150:
        return 5.0
    elif current >= 130:
        return 10.0
    elif current >= 120:
        return 20.0
    elif current >= 110:
        return 35.0
    elif current >= 100:
        return 50.0
    elif current >= 90:
        return 60.0
    elif current >= 80:
        return 70.0
    elif current >= 70:
        return 80.0
    elif current >= 60:
        return 90.0
    else:
        return 95.0


def compute_sentiment_score() -> float:
    """Current contrarian sentiment 0-100 from greedy index (live fetch, 10min cache)."""
    d = _fetch_macro()
    greedy = d.get("greedy", [])
    if not greedy:
        return 50.0
    current = float(greedy[-1][1]) if isinstance(greedy[-1], list) and len(greedy[-1]) > 1 else 100.0
    return greedy_to_sentiment(current)


def sentiment_label(score: float) -> str:
    if score >= 85: return "极度恐惧"
    elif score >= 70: return "恐惧"
    elif score >= 50: return "中性"
    elif score >= 30: return "贪婪"
    elif score >= 15: return "高度贪婪"
    else: return "极度贪婪"




def compute_sentiment_factor() -> float:
    """Map 0-100 sentiment score to -1.0 ~ +1.0 uniform correction factor.
    +1.0 = extreme fear (contrarian buy), -1.0 = extreme greed (contrarian sell).
    Used across probability, bottom, fusion decision layers.
    """
    s = compute_sentiment_score()
    if s >= 85:  return 0.6
    if s >= 70:  return 0.3
    if s >= 50:  return 0.0
    if s >= 30:  return -0.3
    return -0.6

def get_greedy_current() -> float:
    d = _fetch_macro()
    greedy = d.get("greedy", [])
    if greedy:
        g = greedy[-1]
        return float(g[1]) if isinstance(g, list) and len(g) > 1 else 100.0
    return 100.0


# ============================================================
#  Online Player Trend Score (0-100)
# ============================================================

def compute_online_trend_score() -> float:
    """Compute playerbase health 0-100 from online_chart.

    Rising playerbase = healthy market demand.
    Falling playerbase = shrinking demand, bearish.
    """
    d = _fetch_macro()
    oc = d.get("online_chart", [])
    if len(oc) < 30:
        return 50.0
    recent = [float(r["m"]) for r in oc[-30:] if r.get("m")]
    if len(recent) < 10:
        return 50.0
    first_10 = sum(recent[:10]) / 10
    last_10 = sum(recent[-10:]) / 10
    chg = (last_10 - first_10) / max(first_10, 1) * 100
    if chg > 5:
        return 85.0
    elif chg > 2:
        return 70.0
    elif chg > 0:
        return 55.0
    elif chg > -3:
        return 45.0
    elif chg > -5:
        return 30.0
    elif chg > -10:
        return 15.0
    else:
        return 5.0


def online_label(score: float) -> str:
    if score >= 75: return "强劲增长"
    elif score >= 60: return "温和增长"
    elif score >= 45: return "平稳"
    elif score >= 30: return "缓慢下降"
    elif score >= 15: return "持续流失"
    else: return "加速流失"


def get_online_current() -> int:
    d = _fetch_macro()
    on = d.get("online_number", {})
    return on.get("current_number", 0)


# ============================================================
#  Card Price Trend Score (0-100)
# ============================================================

def compute_card_trend_score() -> float:
    """Compute capital flow health 0-100 from card_price.

    Rising card price = more demand for RMB recharge = capital inflow.
    Falling card price = less demand = capital outflow.
    """
    d = _fetch_macro()
    cp = d.get("card_price", [])
    if len(cp) < 30:
        return 50.0
    recent = [float(r["card_price"]) for r in cp[-30:] if r.get("card_price")]
    if len(recent) < 10:
        return 50.0
    first_10 = sum(recent[:10]) / 10
    last_10 = sum(recent[-10:]) / 10
    chg = (last_10 - first_10) / max(first_10, 1) * 100
    if chg > 3:
        return 80.0
    elif chg > 1:
        return 65.0
    elif chg > -1:
        return 50.0
    elif chg > -3:
        return 35.0
    elif chg > -5:
        return 20.0
    else:
        return 10.0


def card_label(score: float) -> str:
    if score >= 70: return "资金流入"
    elif score >= 55: return "温和流入"
    elif score >= 45: return "平稳"
    elif score >= 30: return "缓慢流出"
    else: return "加速流出"


# ============================================================
#  Bottom-Fishing Readiness Score (0-100)
# ============================================================

@dataclass
class BottomSignal:
    score: int = 0
    level: str = "neutral"
    level_label: str = ""
    action: str = ""
    percentile_contrib: int = 0
    zscore_contrib: int = 0
    breadth_contrib: int = 0
    sentiment_contrib: int = 0
    deceleration_contrib: int = 0
    cycle_contrib: int = 0


def compute_bottom_signal(pct_90d: float, zscore_90d: float, prices: list, accumulation_prob: float = 0.0) -> BottomSignal:
    """Compute bottom-fishing readiness 0-100.

    This signal fires BEFORE trend confirmation - it's a leading indicator.
    Does NOT require TH>=60 or MA crossover.
    """
    bs = BottomSignal()

    # 1. Price extreme (0-25)
    if pct_90d <= 5:
        bs.percentile_contrib = 25
    elif pct_90d <= 10:
        bs.percentile_contrib = 20
    elif pct_90d <= 15:
        bs.percentile_contrib = 15
    elif pct_90d <= 20:
        bs.percentile_contrib = 10
    elif pct_90d <= 30:
        bs.percentile_contrib = 5

    # 2. Z-score extreme (0-20)
    if zscore_90d <= -2.5:
        bs.zscore_contrib = 20
    elif zscore_90d <= -2.0:
        bs.zscore_contrib = 16
    elif zscore_90d <= -1.5:
        bs.zscore_contrib = 12
    elif zscore_90d <= -1.0:
        bs.zscore_contrib = 8
    elif zscore_90d <= -0.5:
        bs.zscore_contrib = 4

    # 3. Breadth panic (0-20)
    breadth = compute_breadth_score(7)
    if breadth <= 5:
        bs.breadth_contrib = 20
    elif breadth <= 15:
        bs.breadth_contrib = 16
    elif breadth <= 25:
        bs.breadth_contrib = 12
    elif breadth <= 40:
        bs.breadth_contrib = 8
    elif breadth <= 50:
        bs.breadth_contrib = 4

    # 4. Sentiment fear (0-20)
    sentiment = compute_sentiment_score()
    if sentiment >= 90:
        bs.sentiment_contrib = 20
    elif sentiment >= 80:
        bs.sentiment_contrib = 16
    elif sentiment >= 70:
        bs.sentiment_contrib = 12
    elif sentiment >= 60:
        bs.sentiment_contrib = 8
    elif sentiment >= 50:
        bs.sentiment_contrib = 4

    # 5. Price deceleration (0-15)
    # The decline rate is slowing = selling exhaustion
    if prices and len(prices) >= 14:
        week1 = (prices[-1] - prices[-7]) / max(prices[-7], 1) * 100 if prices[-7] > 0 else 0
        week2 = (prices[-8] - prices[-14]) / max(prices[-14], 1) * 100 if prices[-14] > 0 else 0
        if week2 < 0 and week1 > week2:
            improvement = week1 - week2
            if improvement > 5:
                bs.deceleration_contrib = 15
            elif improvement > 3:
                bs.deceleration_contrib = 12
            elif improvement > 2:
                bs.deceleration_contrib = 8
            elif improvement > 1:
                bs.deceleration_contrib = 5
            elif improvement > 0:
                bs.deceleration_contrib = 3

    # 6. Cycle phase alignment bonus (0-20)
    if accumulation_prob >= 80:
        bs.cycle_contrib = 20
    elif accumulation_prob >= 70:
        bs.cycle_contrib = 15
    elif accumulation_prob >= 60:
        bs.cycle_contrib = 10
    elif accumulation_prob >= 50:
        bs.cycle_contrib = 5
    else:
        bs.cycle_contrib = 0

    bs.score = (bs.percentile_contrib + bs.zscore_contrib +
                bs.breadth_contrib + bs.sentiment_contrib +
                bs.deceleration_contrib + bs.cycle_contrib)

    # Event risk discount
    evt = event_risk_coefficient()
    if evt < 1.0:
        bs.score = round(bs.score * evt)

    if bs.score >= 80:
        bs.level = "strong_bottom"
        bs.level_label = "强烈抄底信号"
        bs.action = "多维共振极端底部，可分批建仓"
    elif bs.score >= 60:
        bs.level = "watch_bottom"
        bs.level_label = "关注抄底"
        bs.action = "底部区域，等待确认信号后入场"
    elif bs.score >= 40:
        bs.level = "neutral"
        bs.level_label = "中性偏底"
        bs.action = "具备部分底部特征，可结合周期阶段轻仓参与"
    elif bs.score >= 20:
        bs.level = "no_bottom"
        bs.level_label = "底部未确认"
        bs.action = "未触发极端底部信号。若吸筹期概率较高，可按仓位上限轻仓分批试探"
    else:
        bs.level = "strong_market"
        bs.level_label = "强势行情"
        bs.action = "价格偏强，无底部可言"

    return bs


def bottom_signal_summary(bs):
    return dict(
        score=bs.score, level=bs.level, level_label=bs.level_label,
        action=bs.action,
        percentile_contrib=bs.percentile_contrib,
        zscore_contrib=bs.zscore_contrib,
        breadth_contrib=bs.breadth_contrib,
        sentiment_contrib=bs.sentiment_contrib,
        deceleration_contrib=bs.deceleration_contrib,
        cycle_contrib=bs.cycle_contrib,
    )


def event_risk_coefficient() -> float:
    """Return event risk discount (1.0 = no risk, 0.7 = major risk).
    Checks for known V社 events via settings table.
    """
    import json
    try:
        from . import db
        conn = db.get_conn()
        try:
            evt = db.get_setting(conn, "event_active", "")
            if evt:
                data = json.loads(evt) if isinstance(evt, str) else evt
                if isinstance(data, dict):
                    coeff = data.get("coefficient", 1.0)
                    return max(0.5, min(1.0, float(coeff)))
            return 1.0
        finally:
            conn.close()
    except Exception:
        return 1.0


def get_greedy_history(start=None):
    """Persisted greedy index [(date, value)] ascending for backtests; empty until daily collection."""
    from .db import get_conn, get_greedy_history as _db_greedy
    conn = get_conn()
    try:
        return _db_greedy(conn, start=start)
    finally:
        conn.close()
