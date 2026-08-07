# Market Context Anchor -- solves the 30-day item data limitation.
import statistics, math
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

    market_values = [v for _, v in market_history if v > 0]
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
            except: ctx.beta = 1.0

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
# 引擎口径：恐慌阈值 sent>=75（P0-7 恐慌共振引擎阈值，engine-unified.md §3.3）。
# 展示层此前用 80 分口径（I-1 遗留），阶段4 已对齐——item_analysis 与 batch_scan
# 都必须引用本函数，避免口径再次漂移。补仓引擎的 80 分恐慌阈值是回测参数，不在本函数内。

PANIC_SENT_THRESHOLD = 75


def state_bucket(sentiment_score, market_th_score, market_30d_change):
    """六态市场状态桶（引擎口径）→ label。

    - 贪婪禁入: sent<=30
    - V型底区(恐慌深跌): sent>=75 & chg30<=-15
    - 阴跌中继区(恐慌中跌): sent>=75 & -15<chg30<=-5
    - 恐慌浅跌: sent>=75 & chg30>-5
    - 中性企稳: sent<75 & TH>=45
    - 弱市观望: sent<75 & TH<45
    """
    s = float(sentiment_score) if sentiment_score is not None else 50.0
    t = float(market_th_score) if market_th_score is not None else 50.0
    c = float(market_30d_change) if market_30d_change is not None else 0.0
    if s <= 30:
        return "贪婪禁入"
    if s >= PANIC_SENT_THRESHOLD:
        if c <= -15:
            return "V型底区"
        if c <= -5:
            return "阴跌中继区"
        return "恐慌浅跌"
    if t >= 45:
        return "中性企稳"
    return "弱市观望"
