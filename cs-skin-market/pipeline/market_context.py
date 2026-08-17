# Market Context Anchor -- solves the 30-day item data limitation.
import logging
import statistics, math

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from .index_analysis import _momentum, _percentile  # reuse instead of redefining

@dataclass
class MarketContext:
    correlation: float = 0.0
    beta: float = 1.0
    r_squared: float = 0.0
    correlation_strength: str = "none"
    market_pct_90d: float = 50.0
    market_pct_30d: float = 50.0
    item_pct_30d: float = 50.0
    anchored_pct_90d: float = 50.0
    market_trend_7d: float = 0.0
    market_trend_30d: float = 0.0
    market_cycle: str = "unknown"
    market_zscore: float = 0.0
    context_label: str = ""
    context_action: str = ""
    confidence_penalty: float = 0.0
    data_quality: str = "low"
    valuation_override: str = ""
    valuation_reason: str = ""

def _pearson_r(xs, ys):
    n = len(xs)
    if n < 5 or n != len(ys): return 0.0
    mx = statistics.mean(xs); my = statistics.mean(ys)
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs))
    dy = math.sqrt(sum((y-my)**2 for y in ys))
    if dx==0 or dy==0: return 0.0
    return num/(dx*dy)

def _returns(prices):
    return [math.log(prices[i]/prices[i-1]) for i in range(1,len(prices)) if prices[i-1]>0 and prices[i]>0]


def _market_values(market_history):
    """Normalize market_history to numeric values.

    Accepts either [(date_str, value), ...] (replay/production DB path) or [value, ...]
    (legacy item-analysis test/replay path). This is the single source of the 2026-08-14
    #10 dual-track fix: one function, one accepted contract.
    """
    out = []
    for x in market_history or []:
        if isinstance(x, (tuple, list)) and len(x) >= 2:
            v = x[1]
        else:
            v = x
        if isinstance(v, (int, float)) and v > 0:
            out.append(float(v))
    return out

def build_market_context(item_prices, market_history, market_cycle="unknown", market_zscore=0.0):
    """Build market-anchored context for a single item.
    item_prices: daily close prices (oldest->newest), typically ~30 pts
    market_history: [(date_str, value), ...] from csQAQ, 90+ pts
    """
    ctx = MarketContext()
    ctx.market_cycle = market_cycle
    ctx.market_zscore = market_zscore
    n_item = len(item_prices)
    if n_item < 5:
        ctx.context_label = "data_insufficient"; ctx.confidence_penalty = 0.5; return ctx
    if n_item >= 90: ctx.data_quality = "high"; ctx.confidence_penalty = 0.0
    elif n_item >= 30: ctx.data_quality = "medium"; ctx.confidence_penalty = 0.15
    else: ctx.data_quality = "low"; ctx.confidence_penalty = 0.35

    market_values = _market_values(market_history)
    if len(market_values) < 5: ctx.context_label = "market_data_insufficient"; ctx.confidence_penalty = 0.5; return ctx

    mkt_90d = market_values[-90:] if len(market_values) >= 90 else market_values
    ctx.market_pct_90d = _percentile(mkt_90d, mkt_90d[-1])
    mkt_30d = market_values[-30:] if len(market_values) >= 30 else market_values
    ctx.market_pct_30d = _percentile(mkt_30d, mkt_30d[-1])
    item_30d = item_prices[-30:] if n_item >= 30 else item_prices
    ctx.item_pct_30d = _percentile(item_30d, item_prices[-1])

    overlap = min(n_item, len(market_values), 30)
    if overlap >= 5:
        item_ret = _returns(item_prices[-overlap:])
        mkt_ret = _returns(market_values[-overlap:])
        ml = min(len(item_ret), len(mkt_ret))
        item_ret = item_ret[-ml:]; mkt_ret = mkt_ret[-ml:]
        if len(item_ret) >= 5:
            ctx.correlation = round(_pearson_r(item_ret, mkt_ret), 3)
            try:
                var_mkt = statistics.variance(mkt_ret) if len(mkt_ret) >= 2 else 0
                if var_mkt and var_mkt != 0:
                    cov = sum((ir-statistics.mean(item_ret))*(mr-statistics.mean(mkt_ret)) for ir,mr in zip(item_ret,mkt_ret))/(len(mkt_ret)-1)
                    ctx.beta = round(cov/var_mkt, 2)
            except (statistics.StatisticsError, ValueError, ZeroDivisionError): ctx.beta = 1.0

    ctx.r_squared = round(ctx.correlation**2, 3)
    ar = abs(ctx.correlation)
    if ar >= 0.7: ctx.correlation_strength = "strong"
    elif ar >= 0.4: ctx.correlation_strength = "moderate"
    elif ar >= 0.2: ctx.correlation_strength = "weak"
    else: ctx.correlation_strength = "none"

    ctx.market_trend_7d = _momentum(market_values, 7)
    ctx.market_trend_30d = _momentum(market_values, 30)

    if ctx.correlation_strength in ("strong", "moderate"):
        divergence = ctx.item_pct_30d - ctx.market_pct_30d
        anchor = ctx.market_pct_90d + divergence * ctx.r_squared
        anchor = anchor * ctx.r_squared + ctx.item_pct_30d * (1 - ctx.r_squared)
        ctx.anchored_pct_90d = round(max(0, min(100, anchor)), 1)
    else:
        ctx.anchored_pct_90d = ctx.item_pct_30d

    ctx.context_label, ctx.context_action, ctx.valuation_override, ctx.valuation_reason = _derive_context(ctx)
    return ctx


def _derive_context(ctx):
    """Derive context label, action, valuation override."""
    pct = ctx.anchored_pct_90d
    cs = ctx.correlation_strength
    cycle = ctx.market_cycle
    mkt_pct = ctx.market_pct_90d

    if cs in ("strong", "moderate") and pct <= 25 and mkt_pct <= 30:
        if cycle == "accumulation":
            return ("跟随大盘同步触底，处于吸筹区间", "buy_zone", "undervalued", "强相关品种，大盘90日低位同步确认，是真实底部区间")
        return ("跟随大盘下跌，但大盘尚未确认底部", "caution", "", "强相关品种跟随大盘走弱，等待大盘确认底部后再介入")

    if cs in ("strong", "moderate") and pct >= 75 and mkt_pct >= 70:
        return ("跟随大盘同步高位，注意止盈", "avoid", "overvalued", "强相关品种，大盘90日高位同步确认，是真实顶部区间")

    if cs in ("strong", "moderate") and ctx.item_pct_30d <= 20 and mkt_pct >= 60:
        return (f"散户抄底陷阱！大盘{mkt_pct}%高位但单品独跌至{ctx.item_pct_30d}%分位——品种自身弱势", "avoid", "overvalued", f"大盘90日分位{mkt_pct}%高位，但单品独跌——非大盘拖累，是品种自身弱势，抄底风险极高")

    if cs in ("strong", "moderate") and ctx.item_pct_30d >= 70 and mkt_pct <= 35:
        return ("独立强势品种，逆市上涨——有资金独立运作", "hold", "", "大盘低位但单品逆市走强，可能有大资金控盘或独立催化剂")

    if cs in ("weak", "none"):
        if pct <= 20:
            return ("低相关性品种，30日低位——需结合基本面判断", "caution", "", f"与大盘相关性低({abs(ctx.correlation):.0%})，30日分位参考价值有限")
        if pct >= 80:
            return ("低相关性品种，30日高位——独立行情", "caution", "", "与大盘相关性低，独立走势")
        return ("低相关性品种，独立行情——大盘参照意义有限", "hold", "", f"与大盘相关性低({abs(ctx.correlation):.0%})")

    if cycle == "accumulation":
        return ("大盘吸筹期，可关注回调机会", "buy_zone", "", "大盘处于吸筹周期，回调品种可考虑分批建仓")
    if cycle == "distribution":
        return ("大盘出货期，建议观望", "avoid", "", "大盘处于出货周期，整体风险偏高")
    return ("跟随大盘震荡，等待方向选择", "hold", "", "大盘方向不明，保持现有仓位等待信号")


def context_summary(ctx):
    """Return dict suitable for report rendering."""
    return {
        "correlation": ctx.correlation, "correlation_strength": ctx.correlation_strength,
        "beta": ctx.beta, "market_pct_90d": ctx.market_pct_90d,
        "market_pct_30d": ctx.market_pct_30d, "item_pct_30d": ctx.item_pct_30d,
        "anchored_pct_90d": ctx.anchored_pct_90d,
        "market_cycle": ctx.market_cycle, "market_trend_7d": ctx.market_trend_7d,
        "market_trend_30d": ctx.market_trend_30d, "context_label": ctx.context_label,
        "context_action": ctx.context_action, "valuation_override": ctx.valuation_override,
        "valuation_reason": ctx.valuation_reason, "confidence_penalty": ctx.confidence_penalty,
        "data_quality": ctx.data_quality,
    }

# ============================================================
# 统一状态桶（统一大脑阶段3/4：单一口径来源，禁止各处自行定义）
# ============================================================
# 2026-08-16 定稿：旧六态（贪婪禁入/V型底区/阴跌中继区/恐慌浅跌/中性企稳/弱市观望）
# 整体退役，替换为大盘五时期（用户裁定：切点验证通过，旧口径不保留）。
# 路由数据挖掘自 probe_market_periods.py（3 年 813 天状态窗，边界时间稳定性全部 ≤6.5pp），
# 定稿见 references/market-bucket-alignment.md v2。


def state_bucket(market_180d_change, market_30d_change):
    """大盘五时期状态桶（引擎口径）→ label。

    路由（market-bucket-alignment.md v2 定稿）：
      P 恐慌深跌: chg30 <= -15
      S1 牛市上行: chg180 > 0 且 chg30 > 0
      S2 牛市回调: chg180 > 0 且 chg30 <= 0
      S3 弱市阴跌: chg180 <= 0 且 chg30 <= 0
      S4 弱市反弹: chg180 <= 0 且 chg30 > 0
    贪婪禁入（sent<=30）为正交覆盖层（非时期，任何时期生效），不在此函数内：
    展示层见 batch_scan.market_regime，引擎层见单品情绪闸门（item_analysis）。
    """
    c180 = float(market_180d_change) if market_180d_change is not None else 0.0
    c30 = float(market_30d_change) if market_30d_change is not None else 0.0
    if c30 <= -15:
        return "P恐慌深跌"
    if c180 > 0:
        return "S1牛市上行" if c30 > 0 else "S2牛市回调"
    return "S3弱市阴跌" if c30 <= 0 else "S4弱市反弹"


# ============================================================
# 大盘指数统计（单一事实源 2026-08-08）
# 两处复用：analysis_service.market_snapshot（引擎路径，情绪在线口径）
#           pipeline.monitor._market_ctx_from_db（监控路径，情绪纯 DB 口径）
# 指数分位/Z/周期/TH/涨跌幅 必须统一走本函数，禁止各处自行计算。
# ============================================================
def market_index_stats(market_history):
    """大盘指数统计（纯计算）：90日分位/Z/周期/TH/7-30-21日涨跌幅。

    market_history: [(date_str, value), ...]（oldest -> newest）。
    """
    values = _market_values(market_history)
    pct, z = 50.0, 0.0
    cycle, th = "unknown", 50.0
    chg7 = chg30 = drop21 = chg180 = 0.0
    if len(values) >= 30:
        from .index_analysis import analyze_index
        _ires = analyze_index(market_history[-90:])
        _ipos = _ires.get("position", {}) if isinstance(_ires, dict) else {}
        pct = _ipos.get("percentile_90d", 50)
        z = _ipos.get("zscore_90d", 0)
        cur = values[-1]
        m7 = values[-7] if len(values) >= 7 else values[0]
        m30 = values[-30]
        m21 = values[-21] if len(values) >= 21 else values[0]
        chg7 = round((cur - m7) / m7 * 100, 1) if m7 > 0 else 0
        chg30 = round((cur - m30) / m30 * 100, 1) if m30 > 0 else 0
        drop21 = round((cur - m21) / m21 * 100, 1) if m21 > 0 else 0
        chg180 = round((cur - values[-180]) / values[-180] * 100, 1) if len(values) >= 180 and values[-180] > 0 else 0
        from .market_th import derive_market_cycle, compute_market_trend_health
        cycle = derive_market_cycle(values, len(values) - 1)
        try:
            _mth = compute_market_trend_health(values[-90:])
            th = _mth.corrected_score if hasattr(_mth, "corrected_score") else _mth.score
        except Exception:
            logger.warning("compute_market_trend_health fallback failed", exc_info=True)
            th = max(0, min(100, 50 + chg30 * 3))
    return {"pct": pct, "z": z, "cycle": cycle, "th": th,
            "chg7": chg7, "chg30": chg30, "drop21": drop21, "chg180": chg180}
