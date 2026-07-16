#!/usr/bin/env python3
"""
CS 饰品价格分析工具
注意: 分析结果基于输入数据，国内定价以悠悠有品 RMB 为准
用法: python analyze.py <prices.json> [--output report.md]
"""

import argparse
import json
import statistics
import sys
from pathlib import Path


def load_prices(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data.get("prices", [])
    except Exception as e:
        print(f"[ERROR] Failed to read file: {e}", file=sys.stderr)
        sys.exit(1)


def calc_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return None

    price_vals = [p["price"] for p in prices]

    ema_fast = [price_vals[0]]
    k_fast = 2 / (fast + 1)
    for p in price_vals[1:]:
        ema_fast.append(p * k_fast + ema_fast[-1] * (1 - k_fast))

    ema_slow = [price_vals[0]]
    k_slow = 2 / (slow + 1)
    for p in price_vals[1:]:
        ema_slow.append(p * k_slow + ema_slow[-1] * (1 - k_slow))

    dif = [ema_fast[i] - ema_slow[i] for i in range(len(price_vals))]

    dea = [dif[0]]
    k_sig = 2 / (signal + 1)
    for d in dif[1:]:
        dea.append(d * k_sig + dea[-1] * (1 - k_sig))

    macd_bar = [(dif[i] - dea[i]) * 2 for i in range(len(price_vals))]

    prev_cross = dif[-2] - dea[-2]
    curr_cross = dif[-1] - dea[-1]

    if curr_cross > 0 and prev_cross <= 0:
        sig = "Golden Cross (Bullish)"
    elif curr_cross < 0 and prev_cross >= 0:
        sig = "Death Cross (Bearish)"
    else:
        sig = "No Signal"

    return {
        "dif": round(dif[-1], 4),
        "dea": round(dea[-1], 4),
        "macd": round(macd_bar[-1], 4),
        "signal": sig
    }


def calc_volatility(prices):
    price_vals = [p["price"] for p in prices]
    if len(price_vals) < 2:
        return None
    mean = statistics.mean(price_vals)
    stdev = statistics.stdev(price_vals)
    return round((stdev / mean) * 100, 2)


def analyze(prices):
    price_vals = [p["price"] for p in prices]

    result = {
        "data_points": len(prices),
        "date_range": prices[0]["date"] + " ~ " + prices[-1]["date"],
        "latest_price": prices[-1]["price"],
        "avg_price": round(statistics.mean(price_vals), 2),
        "median_price": round(statistics.median(price_vals), 2),
        "min_price": min(price_vals),
        "max_price": max(price_vals),
        "volatility_pct": calc_volatility(prices),
    }

    if len(price_vals) >= 7:
        result["ma7"] = round(statistics.mean(price_vals[-7:]), 2)
    else:
        result["ma7"] = None

    if len(price_vals) >= 30:
        result["ma30"] = round(statistics.mean(price_vals[-30:]), 2)
    else:
        result["ma30"] = None

    result["macd"] = calc_macd(prices) if len(prices) >= 35 else None

    if result["ma7"] and result["ma30"]:
        if result["ma7"] > result["ma30"]:
            trend = "Uptrend (MA7 above MA30)"
        elif result["ma7"] < result["ma30"]:
            trend = "Downtrend (MA7 below MA30)"
        else:
            trend = "Sideways"
    else:
        trend = "Insufficient data"

    result["trend"] = trend

    price_range = result["max_price"] - result["min_price"]
    if price_range > 0:
        position = (result["latest_price"] - result["min_price"]) / price_range * 100
        result["price_position_pct"] = round(position, 1)
    else:
        result["price_position_pct"] = 50.0

    return result


def generate_report(prices, metrics, item_name):
    ma7_str = "%.2f" % metrics["ma7"] if metrics["ma7"] else "N/A"
    ma30_str = "%.2f" % metrics["ma30"] if metrics["ma30"] else "N/A"

    lines = [
        "# CS Item Market Analysis Report",
        "",
        "**Item**: " + item_name,
        "**Date Range**: " + metrics["date_range"] + " (" + str(metrics["data_points"]) + " data points)",
        "",
        "## Key Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        "| Latest Price | " + str(metrics["latest_price"]) + " |",
        "| Average Price | " + str(metrics["avg_price"]) + " |",
        "| Median Price | " + str(metrics["median_price"]) + " |",
        "| Min Price | " + str(metrics["min_price"]) + " |",
        "| Max Price | " + str(metrics["max_price"]) + " |",
        "| Volatility | " + str(metrics["volatility_pct"]) + "% |",
        "| MA7 | " + ma7_str + " |",
        "| MA30 | " + ma30_str + " |",
        "| Price Position | " + str(metrics["price_position_pct"]) + "% (from min) |",
        "",
        "## Trend",
        "",
        "**" + metrics["trend"] + "**",
    ]

    if metrics["macd"]:
        macd = metrics["macd"]
        lines += [
            "",
            "**MACD Signal**: " + macd["signal"],
            "- DIF: " + str(macd["dif"]),
            "- DEA: " + str(macd["dea"]),
            "- MACD Bar: " + str(macd["macd"]),
        ]

    lines += [
        "",
        "## Recommendation",
        "",
        "Based on current technical indicators, consult references/trading-strategies.md for specific actions.",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="CS item price analysis")
    parser.add_argument("prices_json", help="Price JSON file from fetch_prices.py")
    parser.add_argument("--output", default=None, help="Output Markdown report path")
    args = parser.parse_args()

    prices = load_prices(args.prices_json)

    if not prices:
        print("[ERROR] Price data is empty", file=sys.stderr)
        sys.exit(1)

    item_name = json.loads(Path(args.prices_json).read_text(encoding="utf-8")).get("item", "Unknown")
    metrics = analyze(prices)
    report = generate_report(prices, metrics, item_name)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print("Report saved to: " + args.output)

    print(report)


if __name__ == "__main__":
    main()
