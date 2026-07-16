
"""
Strategy backtesting engine for CS skin investments.
"""

from dataclasses import dataclass, field
import math
from datetime import datetime, timedelta


@dataclass
class BacktestResult:
    strategy: str = ""
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 0.0
    final_value: float = 0.0
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)


def run_backtest(prices, strategy="three_factor", entry_threshold="A",
                 commission_pct=0.0, initial_capital=10000.0):
    from .config import TAKE_PROFIT_STEPS, STOP_LOSS_STEPS

    if not prices or len(prices) < 2:
        return BacktestResult(strategy=strategy)

    capital = initial_capital
    position = 0.0
    entry_price = 0.0
    peak_capital = capital
    max_dd = 0.0
    equity = []
    trades = []
    daily_returns = []

    for i, day in enumerate(prices):
        price = day.get("price", 0)
        grade = day.get("grade", "C")
        if price <= 0:
            equity.append(capital + position)
            continue

        current_equity = capital + position
        equity.append(current_equity)
        if current_equity > peak_capital:
            peak_capital = current_equity
        dd = (peak_capital - current_equity) / peak_capital * 100 if peak_capital > 0 else 0
        if dd > max_dd:
            max_dd = dd
        if i > 0 and equity[-2] > 0:
            daily_returns.append((current_equity - equity[-2]) / equity[-2])

        if position == 0:
            grades_ok = (entry_threshold == "A" and grade in ("S", "A")) or                         (entry_threshold == "S" and grade == "S")
            if grades_ok and price > 0:
                entry_price = price
                shares = capital / price
                position = shares * price
                capital *= (1 - commission_pct / 100)
                trades.append({"type": "buy", "date": day["date"], "price": price, "grade": grade})
        else:
            pnl_pct = (price / entry_price - 1) * 100
            for sl_pct, sl_action in STOP_LOSS_STEPS:
                if pnl_pct <= sl_pct and sl_action > 0:
                    sell_pct = sl_action
                    sell_value = position * sell_pct
                    capital += sell_value * (1 - commission_pct / 100)
                    position -= sell_value
                    trades.append({"type": "sell_sl", "date": day["date"], "price": price,
                                   "pnl_pct": round(pnl_pct, 1), "portion": sell_pct})
                    if position <= 1:
                        position = 0
                    break
            if position > 0:
                for tp_pct, tp_action in TAKE_PROFIT_STEPS:
                    if pnl_pct >= tp_pct * 100 and tp_action > 0:
                        sell_pct = tp_action
                        sell_value = position * sell_pct
                        capital += sell_value * (1 - commission_pct / 100)
                        position -= sell_value
                        trades.append({"type": "sell_tp", "date": day["date"], "price": price,
                                       "pnl_pct": round(pnl_pct, 1), "portion": sell_pct})
                        if position <= 1:
                            position = 0
                        break

    if position > 0 and prices:
        last_price = prices[-1]["price"]
        capital += position * (1 - commission_pct / 100)
        trades.append({"type": "close", "date": prices[-1]["date"], "price": last_price, "portion": 1.0})
        position = 0

    final_value = capital
    total_return = (final_value / initial_capital - 1) * 100
    days = max(len(prices), 1)
    if days >= 30 and final_value > 0:
        annualized = ((final_value / initial_capital) ** (365 / days) - 1) * 100
        annualized = max(-100, min(1000, annualized))  # cap extreme values
    else:
        annualized = 0  # insufficient data, suppress misleading number

    if len(daily_returns) > 1:
        import statistics
        avg_r = statistics.mean(daily_returns)
        std_r = statistics.stdev(daily_returns)
        sharpe = (avg_r / std_r) * math.sqrt(252) if std_r > 0 else 0
    else:
        sharpe = 0

    selling = sum(1 for t in trades if t["type"].startswith("sell"))
    winning = sum(1 for t in trades if t["type"].startswith("sell") and t.get("pnl_pct", -999) > 0)
    win_rate = (winning / selling * 100) if selling > 0 else 0

    return BacktestResult(
        strategy=strategy,
        start_date=prices[0]["date"],
        end_date=prices[-1]["date"],
        initial_capital=initial_capital,
        final_value=round(final_value, 2),
        total_return_pct=round(total_return, 2),
        annualized_return_pct=round(annualized, 2),
        max_drawdown_pct=round(max_dd, 2),
        sharpe_ratio=round(sharpe, 2),
        win_rate_pct=round(win_rate, 1),
        total_trades=len(trades),
        winning_trades=winning,
        equity_curve=equity,
        trades=trades,
    )


def generate_backtest_report(result, item_name=""):
    perf = "positive" if result.total_return_pct > 20 else ("flat" if result.total_return_pct > 0 else "negative")
    lines = [
        "# Backtest: " + (item_name or result.strategy),
        "",
        "| Metric | Value |",
        "|---|---|",
        "| Strategy | " + result.strategy + " |",
        "| Period | " + result.start_date + " ~ " + result.end_date + " |",
        "| Initial Capital | CNY " + f"{result.initial_capital:,.0f}" + " |",
        "| Final Value | CNY " + f"{result.final_value:,.2f}" + " |",
        "| Total Return | **" + f"{result.total_return_pct:+.2f}%" + "** |",
        "| Annualized Return | " + f"{result.annualized_return_pct:+.2f}%" + " |",
        "| Max Drawdown | " + f"{result.max_drawdown_pct:.2f}%" + " |",
        "| Sharpe Ratio | " + str(result.sharpe_ratio) + " |",
        "| Win Rate | " + f"{result.win_rate_pct:.1f}%" + " |",
        "| Total Trades | " + str(result.total_trades) + " |",
        "",
        "### Performance: " + perf,
        "",
    ]
    if result.trades:
        lines.append("## Recent Trades")
        lines.append("")
        lines.append("| Date | Type | Price | PnL |")
        lines.append("|---|---|---|---|")
        for t in result.trades[-20:]:
            pnl = f"{t.get('pnl_pct', 0):+.1f}%" if "pnl_pct" in t else "-"
            lines.append("| " + t["date"] + " | " + t["type"] + " | CNY " + f"{t['price']:,.2f}" + " | " + pnl + " |")
    return "\n".join(lines)
