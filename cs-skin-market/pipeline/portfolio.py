
"""Portfolio management: position tracking, P&L, rebalancing."""

from dataclasses import dataclass, field


@dataclass
class PortfolioSummary:
    total_cost: float = 0.0
    total_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    position_count: int = 0
    positions: list[dict] = field(default_factory=list)
    max_single_pct: float = 0.0
    concentration_risk: str = "low"


def get_portfolio_summary(conn, positions_data):
    if not positions_data:
        return PortfolioSummary()
    total_cost = sum(p["cost"] for p in positions_data)
    total_value = sum(p["value"] for p in positions_data)
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0
    max_single = max(p["value"] / total_value * 100 for p in positions_data) if total_value > 0 else 0
    risk = "high" if max_single > 40 else ("medium" if max_single > 20 else "low")
    return PortfolioSummary(
        total_cost=round(total_cost, 2), total_value=round(total_value, 2),
        total_pnl=round(total_pnl, 2), total_pnl_pct=round(total_pnl_pct, 2),
        position_count=len(positions_data), positions=positions_data,
        max_single_pct=round(max_single, 1), concentration_risk=risk,
    )


def get_rebalance_suggestions(summary):
    s = []
    if summary.concentration_risk == "high":
        s.append("WARN: single position >" + str(int(summary.max_single_pct)) + "% concentration, suggest diversify")
    for p in summary.positions:
        if p["pnl_pct"] > 50:
            s.append("SELL: " + p["name"] + " +" + f"{p['pnl_pct']:.0f}%" + ", take 50% profit")
        elif p["pnl_pct"] < -20:
            s.append("CUT: " + p["name"] + " " + f"{p['pnl_pct']:.0f}%" + ", stop loss")
    if not s:
        s.append("OK: portfolio healthy, no action needed")
    return s


def generate_portfolio_report(summary):
    mood = {"high": "WARNING", "medium": "NEUTRAL", "low": "HEALTHY"}
    lines = [
        "# Portfolio Report",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        "| Positions | " + str(summary.position_count) + " |",
        "| Total Cost | CNY " + f"{summary.total_cost:,.2f}" + " |",
        "| Total Value | CNY " + f"{summary.total_value:,.2f}" + " |",
        "| Total PnL | CNY " + f"{summary.total_pnl:+,.2f}" + " (" + f"{summary.total_pnl_pct:+.2f}%" + ") |",
        "| Max Single | " + f"{summary.max_single_pct:.1f}%" + " |",
        "| Concentration | " + mood.get(summary.concentration_risk, summary.concentration_risk) + " |",
        "",
        "## Holdings",
        "",
        "| Item | Buy | Now | Qty | Cost | Value | PnL | % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in summary.positions:
        emoji = "+" if p["pnl"] >= 0 else "-"
        lines.append(
            "| " + p["name"] + " | CNY " + f"{p['buy_price']:,.2f}" + " | CNY " + f"{p['current_price']:,.2f}" + " | "
            + str(p["quantity"]) + " | CNY " + f"{p['cost']:,.2f}" + " | CNY " + f"{p['value']:,.2f}" + " | "
            + emoji + " CNY " + f"{abs(p['pnl']):,.2f}" + " | " + f"{p['pnl_pct']:+.1f}%" + " |"
        )
    lines.append("")
    lines.append("## Suggestions")
    lines.append("")
    for sug in get_rebalance_suggestions(summary):
        lines.append("- " + sug)
    return "\n".join(lines)


# ============================================================
#  Portfolio Optimization (P1)
# ============================================================

def calc_correlation_matrix(conn):
    """Calculate daily-return correlation matrix between all watchlist items with >=5 price points."""
    import statistics

    items = conn.execute(
        "SELECT id, name FROM items WHERE in_watchlist=1 ORDER BY id"
    ).fetchall()

    # Gather price series
    series = {}
    for item in items:
        rows = conn.execute(
            "SELECT price_rmb FROM price_history WHERE item_id=? ORDER BY date ASC",
            (item["id"],)
        ).fetchall()
        prices = [float(r["price_rmb"]) for r in rows if r["price_rmb"] and float(r["price_rmb"]) > 0]
        if len(prices) >= 5:
            # Daily returns
            returns = [(prices[i] / prices[i-1] - 1) * 100 for i in range(1, len(prices))]
            series[item["name"]] = returns

    if len(series) < 2:
        return [], []

    names = list(series.keys())
    n = len(names)
    matrix = [[1.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(i+1, n):
            ret_i = series[names[i]]
            ret_j = series[names[j]]
            # Align to shorter length
            min_len = min(len(ret_i), len(ret_j))
            if min_len >= 3:
                ri = ret_i[-min_len:]
                rj = ret_j[-min_len:]
                mean_i = statistics.mean(ri)
                mean_j = statistics.mean(rj)
                num = sum((a - mean_i) * (b - mean_j) for a, b in zip(ri, rj))
                den_i = sum((a - mean_i) ** 2 for a in ri) ** 0.5
                den_j = sum((b - mean_j) ** 2 for b in rj) ** 0.5
                if den_i > 0 and den_j > 0:
                    corr = num / (den_i * den_j)
                    matrix[i][j] = round(corr, 3)
                    matrix[j][i] = round(corr, 3)

    return names, matrix


def calc_optimal_weights(conn, capital=10000):
    """Naive mean-variance optimization with equal-weight fallback.
    Returns suggested weights and expected portfolio metrics."""
    import statistics
    import math

    items = conn.execute(
        "SELECT id, name FROM items WHERE in_watchlist=1 ORDER BY id"
    ).fetchall()

    # Gather price series
    item_data = []
    for item in items:
        rows = conn.execute(
            "SELECT price_rmb FROM price_history WHERE item_id=? ORDER BY date ASC",
            (item["id"],)
        ).fetchall()
        prices = [float(r["price_rmb"]) for r in rows if r["price_rmb"] and float(r["price_rmb"]) > 0]
        if len(prices) >= 5:
            returns = [(prices[i] / prices[i-1] - 1) for i in range(1, len(prices))]
            mean_ret = statistics.mean(returns) if returns else 0
            std_ret = statistics.stdev(returns) if len(returns) > 1 else 0
            item_data.append({
                "name": item["name"],
                "price": prices[-1],
                "mean_daily_return": mean_ret,
                "volatility": std_ret,
                "sharpe": mean_ret / std_ret * math.sqrt(252) if std_ret > 0 else 0,
                "data_points": len(prices),
            })

    if not item_data:
        return [], {}

    n = len(item_data)

    # Simple allocation: weight by Sharpe ratio (capped), equal weight as floor
    sharpes = [d["sharpe"] for d in item_data]
    min_s = min(sharpes)
    max_s = max(sharpes)

    if max_s > min_s:
        # Normalize sharpe to 0.5-1.5 range, then normalize to sum=1
        raw = [(s - min_s) / (max_s - min_s) + 0.5 for s in sharpes]
    else:
        raw = [1.0] * n

    total = sum(raw)
    if total > 0:
        weights = [round(w / total, 3) for w in raw]
    else:
        weights = [round(1.0 / n, 3)] * n

    # Portfolio metrics
    portfolio_return = sum(item_data[i]["mean_daily_return"] * weights[i] for i in range(n))
    # Approximate portfolio vol (assumes 0 correlation for simplicity)
    portfolio_vol = math.sqrt(sum((item_data[i]["volatility"] * weights[i]) ** 2 for i in range(n)))
    portfolio_sharpe = portfolio_return / portfolio_vol * math.sqrt(252) if portfolio_vol > 0 else 0

    result = {
        "expected_daily_return": round(portfolio_return * 100, 4),
        "expected_annual_return": round(portfolio_return * 252 * 100, 1),
        "portfolio_volatility": round(portfolio_vol * 100, 2),
        "portfolio_sharpe": round(portfolio_sharpe, 2),
    }

    return weights, result


def generate_optimization_report(conn):
    """Generate a Markdown report with correlation matrix + suggested weights."""
    names, corr_matrix = calc_correlation_matrix(conn)
    weights, metrics = calc_optimal_weights(conn)

    lines = []
    lines.append("## \U0001f4ca \u6295\u8d44\u7ec4\u5408\u4f18\u5316")
    lines.append("")

    if len(names) < 2:
        lines.append("\u6570\u636e\u4e0d\u8db3\uff1a\u9700\u8981\u81f3\u5c11 2 \u4e2a\u7269\u54c1\u5404\u6709 5 \u5929\u4ee5\u4e0a\u4ef7\u683c\u5386\u53f2")
        lines.append("")
        return "\n".join(lines)

    # Correlation matrix
    lines.append("### \u76f8\u5173\u6027\u77e9\u9635")
    lines.append("")
    header = "| " + " | ".join([n[:12] for n in names]) + " |"
    sep = "|" + "|".join(["---" for _ in names]) + "|"
    lines.append(header)
    lines.append(sep)
    for i, name in enumerate(names):
        row = "| " + name[:12]
        for j in range(len(names)):
            v = corr_matrix[i][j]
            if v > 0.5:
                emoji = "\U0001f534"
            elif v > 0.2:
                emoji = "\U0001f7e1"
            elif v < -0.2:
                emoji = "\U0001f7e2"
            else:
                emoji = " "
            row += " | {}{:.2f}".format(emoji, v)
        row += " |"
        lines.append(row)
    lines.append("")
    lines.append("*\U0001f534 = \u9ad8\u6b63\u76f8\u5173 (>0.5)  |  \U0001f7e2 = \u8d1f\u76f8\u5173 (<-0.2)*")
    lines.append("")

    # Suggested weights
    if weights:
        lines.append("### \u5efa\u8bae\u6743\u91cd")
        lines.append("")
        lines.append("| \u7269\u54c1 | \u5efa\u8bae\u4ed3\u4f4d | \u4ef7\u683c | \u65e5\u5747\u6536\u76ca | \u6ce2\u52a8\u7387 |")
        lines.append("|---|---|---|---|---|")
        items = conn.execute("SELECT id, name FROM items WHERE in_watchlist=1 ORDER BY id").fetchall()
        for i, item in enumerate(items):
            if i < len(weights):
                rows_price = conn.execute(
                    "SELECT price_rmb FROM price_history WHERE item_id=? ORDER BY date DESC LIMIT 1",
                    (item["id"],)
                ).fetchone()
                price = rows_price["price_rmb"] if rows_price else 0
                w = weights[i]
                lines.append("| {} | **{:.0f}%** | \u00a5{:,.2f} | {}% | {}% |".format(
                    item["name"][:25],
                    w * 100,
                    float(price),
                    round(item_data[i]["mean_daily_return"] * 100, 4) if i < len(item_data) else "-",
                    round(item_data[i]["volatility"] * 100, 2) if i < len(item_data) else "-",
                ))
        lines.append("")

    if metrics:
        lines.append("### \u9884\u671f\u6536\u76ca")
        lines.append("")
        lines.append("| \u6307\u6807 | \u6570\u503c |")
        lines.append("|---|---|")
        lines.append("| \u9884\u671f\u5e74\u5316\u6536\u76ca | {}% |".format(metrics.get("expected_annual_return", 0)))
        lines.append("| \u7ec4\u5408\u6ce2\u52a8\u7387 | {}% |".format(metrics.get("portfolio_volatility", 0)))
        lines.append("| \u7ec4\u5408\u590f\u666e\u6bd4\u7387 | {} |".format(metrics.get("portfolio_sharpe", 0)))
        lines.append("")

    return "\n".join(lines)


def calc_correlation_from_prices(price_series):
    """Calculate correlation matrix from dict of {name: [prices]} (e.g. from K-line data)."""
    import statistics

    returns_map = {}
    for name, prices in price_series.items():
        if len(prices) >= 5:
            rets = [(prices[i] / prices[i-1] - 1) * 100 for i in range(1, len(prices))]
            returns_map[name] = rets

    if len(returns_map) < 2:
        return [], []

    names = list(returns_map.keys())
    n = len(names)
    matrix = [[1.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(i+1, n):
            ret_i = returns_map[names[i]]
            ret_j = returns_map[names[j]]
            min_len = min(len(ret_i), len(ret_j))
            if min_len >= 3:
                ri = ret_i[-min_len:]
                rj = ret_j[-min_len:]
                mean_i = statistics.mean(ri)
                mean_j = statistics.mean(rj)
                num = sum((a - mean_i) * (b - mean_j) for a, b in zip(ri, rj))
                den_i = sum((a - mean_i) ** 2 for a in ri) ** 0.5
                den_j = sum((b - mean_j) ** 2 for b in rj) ** 0.5
                if den_i > 0 and den_j > 0:
                    corr = num / (den_i * den_j)
                    matrix[i][j] = round(corr, 3)
                    matrix[j][i] = round(corr, 3)

    return names, matrix


def calc_weights_from_prices(price_series):
    """Calculate optimal weights from dict of {name: [prices]}."""
    import statistics, math

    item_data = []
    for name, prices in price_series.items():
        if len(prices) < 5:
            continue
        returns = [(prices[i] / prices[i-1] - 1) for i in range(1, len(prices))]
        mean_ret = statistics.mean(returns) if returns else 0
        std_ret = statistics.stdev(returns) if len(returns) > 1 else 0
        item_data.append({
            "name": name,
            "price": prices[-1],
            "mean_daily_return": mean_ret,
            "volatility": std_ret,
            "sharpe": mean_ret / std_ret * math.sqrt(252) if std_ret > 0 else 0,
        })

    if not item_data:
        return [], {}

    n = len(item_data)
    sharpes = [d["sharpe"] for d in item_data]
    min_s = min(sharpes)
    max_s = max(sharpes)

    if max_s > min_s:
        raw = [(s - min_s) / (max_s - min_s) + 0.5 for s in sharpes]
    else:
        raw = [1.0] * n

    total = sum(raw)
    weights = [round(w / total, 3) for w in raw] if total > 0 else [round(1.0/n, 3)] * n

    portfolio_return = sum(item_data[i]["mean_daily_return"] * weights[i] for i in range(n))
    portfolio_vol = math.sqrt(sum((item_data[i]["volatility"] * weights[i]) ** 2 for i in range(n)))
    portfolio_sharpe = portfolio_return / portfolio_vol * math.sqrt(252) if portfolio_vol > 0 else 0

    metrics = {
        "expected_annual_return": round(portfolio_return * 252 * 100, 1),
        "portfolio_volatility": round(portfolio_vol * 100, 2),
        "portfolio_sharpe": round(portfolio_sharpe, 2),
    }

    return weights, metrics, item_data
