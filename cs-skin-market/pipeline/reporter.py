"""
Markdown report generator for CS skin investment analysis (v2).
"""

from .scorer import ScoreResult, calc_take_profit_steps, calc_stop_loss_steps
from .trend_health import compute_trend_health, trend_health_summary
from .valuation import compute_valuation_grid
from .trends import TrendSignals, trend_signals_to_dict
from .supply import SupplySignals, supply_signals_to_dict
from .config import WEIGHT_SCARCITY, WEIGHT_VOLUME, WEIGHT_LIQUIDITY, WEIGHT_MARKET


def generate_item_report(
    name: str,
    weapon: str,
    skin: str,
    wear: str,
    score: ScoreResult,
    price_rmb: float,
    volume_day: int,
    volume_total: int,
    trend: str,
    rarity: str,
    source: str,
    is_discontinued: bool,
    discontinued_years: float,
    index_value: float,
    index_change_7d: float,
    index_mood: str,
    trend_health_dict: dict = None,
    valuation_grid_dict: dict = None,
) -> str:
    entry_price = price_rmb
    tp_steps = calc_take_profit_steps(entry_price, score.liquidity)
    sl_steps = calc_stop_loss_steps(entry_price)
    rec = _recommendation_text(score)

    # Trend emoji
    trend_emoji = {"up": "\U0001f4c8", "down": "\U0001f4c9", "sideways": "\U0001f4ca"}.get(trend, "\u2796")

    # Source label
    source_label = _source_label(source, is_discontinued, discontinued_years)
    rarity_label = rarity.upper() if rarity else "N/A"

    report = f"""# \u3010{name}\u3011

## \u5927\u76d8\u6e29\u5ea6

| \u6307\u6807 | \u6570\u503c |
|---|---|
| 大盘指数 | {index_value:,.2f} |
| 7\u65e5\u6da8\u8dcc | {index_change_7d:+.2f}% |
| \u5e02\u573a\u60c5\u7eea | {index_mood} |

## \u5b9e\u65f6\u6570\u636e

| \u6307\u6807 | \u6570\u503c |
|---|---|
| \u5f53\u524d\u4ef7\u683c | \u00a5{price_rmb:,.2f} |
| \u65e5\u6210\u4ea4\u91cf | {volume_day} \u4ef6 |
| \u5728\u552e\u603b\u6570 | {volume_total} \u4ef6 |
| \u8d8b\u52bf\u5224\u65ad | {trend_emoji} {trend} |
"""

    # ---- Trend Health & Valuation Grid (NEW v3) ----
    if trend_health_dict:
        th = trend_health_dict
        th_score = th.get("score", 50)
        th_dir = th.get("direction", "flat")
        th_dir_label = {"up": "📈 向上", "flat": "➖ 走平", "down": "📉 向下"}.get(th_dir, th_dir)
        report += f"""
## 📊 趋势健康度

| 指标 | 数值 |
|---|---|
| 健康度得分 | **{th_score}/100** {th.get("level_label", "")} |
| 趋势方向 | {th_dir_label} (置信度: {th.get("direction_confidence", 0):.0%}) |
| 持续性 | {th.get("persistence_score", 0)}/100 |
| 均线结构 | {th.get("ma_structure", "-")} ({th.get("ma_cross_type", "-")}) |
| 趋势陡度 | {th.get("steepness_signal", "-")} |
| 量价配合 | {th.get("volume_signal", "-")} |
| 异常缺口 | {"⚠️ 有" if th.get("has_anomaly") else "✅ 无"} |
"""

    if valuation_grid_dict:
        vg = valuation_grid_dict
        grid_map = {
            ("undervalued", "up"): "🟢 低估+趋势向上  → 反弹确认·建仓",
            ("undervalued", "flat"): "🟡 低估+趋势走平  → 筑底中·观察",
            ("undervalued", "down"): "🔴 低估+趋势向下  → 持续下跌·等待",
            ("fair", "up"): "🟢 合理+趋势向上  → 健康上涨·持有",
            ("fair", "flat"): "🟡 合理+趋势走平  → 震荡·观望",
            ("fair", "down"): "🟡 合理+趋势向下  → 回调中·关注",
            ("overvalued", "up"): "🟡 高估+趋势向上  → 强势拉升·持有",
            ("overvalued", "flat"): "🔴 高估+趋势走平  → 高位横盘·减仓",
            ("overvalued", "down"): "🔴 高估+趋势向下  → 趋势反转·卖出",
        }
        key = (vg.get("grid_row", "fair"), vg.get("grid_col", "flat"))
        grid_str = grid_map.get(key, str(key))
        report += f"""
## 🎯 估值宫格判断

> {grid_str}

| 指标 | 数值 |
|---|---|
| 90日百分位 | **{vg.get("percentile", 50):.1f}%** |
| 综合判定 | {vg.get("grid_emoji", "")} {vg.get("grid_label", "")} |
| 操作建议 | **{vg.get("grid_action", "")}** |
| 总结 | {vg.get("advice", "")} |
"""


    # Liquidity section (NEW)
    if score.liquidity > 0:
        liq_status = "\u5065\u5eb7" if score.liquidity >= 1.0 else ("\u4e00\u822c" if score.liquidity >= 0.7 else "\u5371\u9669")
        report += f"""
## \u6d41\u52a8\u6027\u5206\u6790

| \u6307\u6807 | \u6570\u503c |
|---|---|
| \u6d41\u52a8\u6027\u5f97\u5206 | **{score.liquidity}** |
| \u5065\u5eb7\u5ea6 | {liq_status} |
"""

    # Sector section (NEW)
    if score.sector_name and score.sector_name != "unknown":
        sector_arrow = "\u2197" if score.sector_mod > 0 else ("\u2198" if score.sector_mod < 0 else "\u2192")
        report += f"""
## \u677f\u5757\u70ed\u5ea6

| \u6307\u6807 | \u6570\u503c |
|---|---|
| \u6240\u5c5e\u677f\u5757 | {score.sector_name} |
| \u677f\u5757\u6392\u540d | {score.sector_rank} |
| \u677f\u5757\u4fee\u6b63 | {score.sector_mod:+.2f} {sector_arrow} |
"""


    # Trend section (NEW)
    if score.trend_signals and score.trend_signals.confidence != "low":
        ts = score.trend_signals
        ma_emoji = "\U0001f4c8" if ts.ma_crossover == "golden_cross" else ("\U0001f4c9" if ts.ma_crossover == "death_cross" else "\u2796")
        report += f"""
## \u8d8b\u52bf\u5206\u6790

| \u6307\u6807 | \u6570\u503c |
|---|---|
| 7\u65e5\u52a8\u91cf | {ts.momentum_7d:+.1f}% |
| 30\u65e5\u52a8\u91cf | {ts.momentum_30d:+.1f}% |
| \u52a8\u91cf\u4e00\u81f4\u6027 | {ts.momentum_alignment} |
| MA7 | {ts.ma7:,.2f} |
| MA30 | {ts.ma30:,.2f} |
| MA\u4ea4\u53c9 | {ma_emoji} {ts.ma_crossover} |
| 7\u65e5\u6ce2\u52a8\u7387 | {ts.volatility_7d:.1f}% |
| \u6210\u4ea4\u91cf\u8d8b\u52bf | {ts.volume_trend} |
| \u91cf\u4ef7\u4fe1\u53f7 | {ts.volume_price_signal} |
| \u8d8b\u52bf\u5f97\u5206 | **{ts.trend_score:+.2f}** |
| \u4fe1\u5fc3\u5ea6 | {ts.confidence} |
"""
    elif score.trend_mod != 0:
        report += f"""
## \u8d8b\u52bf\u5206\u6790

- \u8d8b\u52bf\u4fee\u6b63: {score.trend_mod:+.2f}
"""

    # Supply section (NEW)
    if score.supply_signals and score.supply_signals.signal != "none":
        ss = score.supply_signals
        sig_emoji = "\U0001f4e6" if ss.signal == "accumulation" else "\U0001f4a8"
        report += f"""
## \u4f9b\u7ed9\u5206\u6790

| \u6307\u6807 | \u6570\u503c |
|---|---|
| \u5f53\u524d\u5728\u552e | {ss.current_supply} \u4ef6 |
| 7\u65e5\u4f9b\u7ed9\u53d8\u5316 | {ss.supply_change_7d:+.1f}% |
| 30\u65e5\u4f9b\u7ed9\u53d8\u5316 | {ss.supply_change_30d:+.1f}% |
| \u4f9b\u7ed9\u8d8b\u52bf | {ss.supply_trend} ({ss.trend_strength}) |
| \u4fe1\u53f7 | {sig_emoji} {ss.signal} |
| \u4fe1\u53f7\u4fe1\u5fc3\u5ea6 | {ss.signal_confidence} |
| \u4f9b\u7ed9\u5f97\u5206 | **{ss.supply_score:+.2f}** |
"""
    elif score.supply_mod != 0:
        report += f"""
## \u4f9b\u7ed9\u5206\u6790

- \u4f9b\u7ed9\u4fee\u6b63: {score.supply_mod:+.2f}
"""

    # Four-factor score table
    report += f"""
## \u56db\u56e0\u5b50\u8bc4\u5206

| \u56e0\u5b50 | \u6743\u91cd | \u5f97\u5206 | \u8bf4\u660e |
|---|---|---|---|
| \u7a00\u7f3a\u5ea6 | {WEIGHT_SCARCITY*100:.0f}% | **{score.scarcity}** | {rarity_label} \u00b7 {source_label} |
| \u6210\u4ea4\u91cf | {WEIGHT_VOLUME*100:.0f}% | **{score.volume}** | \u65e5\u6210\u4ea4 {volume_day} \u4ef6 |
| \u6d41\u52a8\u6027 | {WEIGHT_LIQUIDITY*100:.0f}% | **{score.liquidity}** | \u4ef7\u5dee+\u6c42\u8d2d\u6df1\u5ea6 |
| \u5927\u76d8 | {WEIGHT_MARKET*100:.0f}% | **{score.market}** | 7\u65e5 {index_change_7d:+.2f}% |
"""

    # Modifiers (NEW)
    mod_lines = []
    if abs(score.sector_mod) > 0.01:
        mod_lines.append(f"\u677f\u5757\u70ed\u5ea6: {score.sector_mod:+.2f}")
    if abs(score.momentum_mod) > 0.01:
        mod_lines.append(f"\u52a8\u91cf\u4fe1\u53f7 (\u653e\u91cf {score.volume_spike_ratio:.1f}x): {score.momentum_mod:+.2f}")
    if abs(score.event_mod) > 0.01:
        mod_lines.append(f"\u4e8b\u4ef6\u5f71\u54cd: {score.event_mod:+.2f} ({', '.join(score.active_events)})")
    if score.volume_spike_ratio > 3:
        mod_lines.append("\u26a0\ufe0f \u68c0\u6d4b\u5230\u5f02\u5e38\u653e\u91cf\uff0c\u53ef\u80fd\u6709\u5e84\u5bb6\u64cd\u76d8")

    modifier_str = "\n".join(f"- {m}" for m in mod_lines) if mod_lines else "- \u65e0"
    report += f"""
### \u4fee\u6b63\u56e0\u5b50

{modifier_str}

### \u7efc\u5408\u8bc4\u5206: **{score.total}** ({score.grade}\u7ea7)
"""

    # Scarcity breakdown
    discontinued_label = "\u5df2\u7edd\u7248" if is_discontinued else "\u5728\u552e"
    report += f"""
## \u7a00\u7f3a\u5ea6\u5206\u6790

- \u7a00\u6709\u5ea6\u7b49\u7ea7: {rarity_label}
- \u6765\u6e90: {source_label}
- \u7edd\u7248\u72b6\u6001: {discontinued_label}
"""
    if is_discontinued and discontinued_years > 0:
        report += f"- \u7edd\u7248\u65f6\u957f: {discontinued_years} \u5e74\n"
    report += f"- \u7a00\u7f3a\u5ea6\u5f97\u5206: {score.scarcity}\n"

    # Recommendation
    report += f"""\n## \u64cd\u4f5c\u5efa\u8bae

**{rec}**

### \u6b62\u76c8\u8868
| \u76ee\u6807\u4ef7 (RMB) | \u6da8\u5e45 | \u5356\u51fa\u6bd4\u4f8b | \u7d2f\u8ba1\u5356\u51fa |
|---|---|---|---|
"""

    for s in tp_steps:
        report += f"| {s['target_price']} | {s['gain_pct']} | {s['sell_pct']} | {s['cumulative_sell']} |\n"

    report += f"""
### \u6b62\u635f\u8868
| \u89e6\u53d1\u4ef7 (RMB) | \u8dcc\u5e45 | \u64cd\u4f5c |
|---|---|---|
"""
    for s in sl_steps:
        report += f"| {s['trigger_price']} | {s['loss_pct']} | {s['action']} |\n"

    # Position advice
    position_pct = _position_advice(score)
    report += f"""
### \u5efa\u8bae\u4ed3\u4f4d
- {position_pct}
- \u6838\u5fc3\u903b\u8f91: {_logic_text(score)}
"""

    # Risks
    report += f"""
### \u4e3b\u8981\u98ce\u9669
{_risk_text(source, is_discontinued, volume_day, score.liquidity, score.volume_spike_ratio)}

> \u26a0\ufe0f \u8bf7\u4ee5\u60a0\u60a0\u6709\u54c1/Buff163 \u5b9e\u65f6\u6302\u5355\u4ef7\u786e\u8ba4\u540e\u64cd\u4f5c \u00b7 \u975e\u6295\u8d44\u5efa\u8bae
"""

    return report


def _recommendation_text(score: ScoreResult) -> str:
    g, t = score.grade, ""

    # Liquidity override
    if score.liquidity < 0.5:
        return "\u274c \u6d41\u52a8\u6027\u6781\u4f4e\uff0c\u5efa\u8bae\u56de\u907f"

    # Momentum boost
    if score.momentum_mod > 0.1 and g in ("S", "A"):
        return "\U0001f525 \u653e\u91cf\u7a81\u7834\uff0c\u77ed\u7ebf\u8ddf\u8fdb"

    recs = {
        "S": "\U0001f525 \u6838\u5fc3\u6807\u7684\uff0c\u95ed\u773c\u957f\u6301",
        "A": "\u2705 \u4f18\u8d28\u6807\u7684\uff0c\u9022\u4f4e\u53ef\u5165",
        "B": "\u2796 \u4e2d\u6027\u6807\u7684\uff0c\u9009\u62e9\u6027\u914d\u7f6e",
        "C": "\u274c \u56de\u907f\u6216\u8d85\u77ed\u535a\u5f08",
    }
    return recs.get(g, "\u89c2\u671b")


def _source_label(source: str, is_discontinued: bool, years: float) -> str:
    if is_discontinued:
        if years >= 5:
            return "\u7edd\u7248\u6536\u85cf\u54c1 (5\u5e74+)"
        return "\u7edd\u7248\u7bb1 (\u5df2\u505c\u4ea7)"
    return {
        "collection": "\u6536\u85cf\u54c1",
        "case": "\u6b66\u5668\u7bb1",
        "current_case": "\u5f53\u524d\u6389\u843d\u7bb1",
    }.get(source, source or "\u672a\u77e5")


def _position_advice(score: ScoreResult) -> str:
    if score.grade == "S":
        return "\u603b\u4ed3\u4f4d: 15-20%"
    elif score.grade == "A":
        return "\u603b\u4ed3\u4f4d: 10-15%"
    elif score.grade == "B":
        return "\u603b\u4ed3\u4f4d: 5-10%"
    else:
        return "\u603b\u4ed3\u4f4d: \u22645%"


def _logic_text(score: ScoreResult) -> str:
    parts = []
    if score.scarcity >= 4:
        parts.append("\u9ad8\u7a00\u7f3a")
    elif score.scarcity >= 2:
        parts.append("\u4e2d\u7b49\u7a00\u7f3a")
    if score.volume >= 1.1:
        parts.append("\u9ad8\u6d41\u52a8")
    elif score.volume >= 0.7:
        parts.append("\u4e2d\u7b49\u6d41\u52a8")
    if score.liquidity >= 1.0:
        parts.append("\u8ba2\u5355\u7c3f\u5065\u5eb7")
    elif score.liquidity < 0.6:
        parts.append("\u8ba2\u5355\u7c3f\u8584\u5f31")
    if score.sector_mod > 0.05:
        parts.append("\u677f\u5757\u987a\u98ce")
    elif score.sector_mod < -0.05:
        parts.append("\u677f\u5757\u9006\u98ce")
    if not parts:
        parts.append("\u591a\u7ef4\u5ea6\u4e2d\u6027")
    return " + ".join(parts)


def _risk_text(source: str, is_discontinued: bool, volume: int,
               liquidity: float, spike_ratio: float) -> str:
    risks = []
    if liquidity < 0.5:
        risks.append("\u6d41\u52a8\u6027\u6781\u4f4e\uff0c\u53d8\u73b0\u56f0\u96be")
    if volume < 5:
        risks.append("\u65e5\u6210\u4ea4\u91cf\u6781\u4f4e")
    if spike_ratio > 3:
        risks.append("\u5f02\u5e38\u653e\u91cf\uff0c\u8b66\u60d5\u5e84\u5bb6\u62c9\u9ad8\u51fa\u8d27")
    if not is_discontinued and source not in ("collection",):
        risks.append("\u4ecd\u5728\u6389\u843d\uff0c\u4f9b\u7ed9\u538b\u529b\u6301\u7eed")
    if not risks:
        risks.append("\u5e02\u573a\u6574\u4f53\u7cfb\u7edf\u6027\u98ce\u9669")
    return " \u00b7 ".join(risks)


def generate_watchlist_report(items: list[dict]) -> str:
    lines = [
        "# \u6301\u4ed3\u76d1\u63a7\u62a5\u544a",
        "",
        f"**\u66f4\u65b0\u65e5\u671f**: {_now_str()}",
        "",
        "| \u7269\u54c1 | \u78e8\u635f | \u5f53\u524d\u4ef7 | \u65e5\u6210\u4ea4 | \u6d41\u52a8\u6027 | \u677f\u5757 | \u8bc4\u5206 | \u8bc4\u7ea7 | \u5efa\u8bae |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(
            f"| {item.get('name', '')} | {item.get('wear', '')} | "
            f"\u00a5{item.get('price', 0):,.2f} | {item.get('volume', 0)} | "
            f"{item.get('liquidity', '-')} | {item.get('sector', '-')} | "
            f"{item.get('score', 0)} | {item.get('grade', '')} | "
            f"{item.get('rec', '')} |"
        )
    return "\n".join(lines)


def _now_str() -> str:
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M")
