"""Factor decay monitor: compare buy-signal performance across backtest snapshots."""
import json
from pathlib import Path
from datetime import datetime, timedelta

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "backtest_snapshots"
THRESHOLDS = {"14d_win_rate": 0.70, "30d_win_rate": 0.55}

def _buy_only(signals):
    """Filter to buy/oversold signals only."""
    return [s for s in signals if "\u5efa\u4ed3" in str(s.get("action_label", ""))]

def stats(signals):
    f14 = [s["fwd14"] for s in signals if s.get("fwd14") is not None]
    f30 = [s["fwd30"] for s in signals if s.get("fwd30") is not None]
    if not f14:
        return {"14d_win_rate": 1.0, "14d_avg": 0, "30d_win_rate": 1.0, "30d_avg": 0, "count": 0}
    return {
        "14d_win_rate": sum(1 for v in f14 if v > 0) / len(f14),
        "14d_avg": sum(f14) / len(f14),
        "30d_win_rate": sum(1 for v in f30 if v > 0) / len(f30) if f30 else 1.0,
        "30d_avg": sum(f30) / len(f30) if f30 else 0,
        "count": len(f14),
    }

def check_decay(series="backtest_"):
    """series: "backtest_" (market) or "item_backtest_" (single-item)."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = sorted(SNAPSHOT_DIR.glob(series + "*.json"))
    if len(snapshots) < 2:
        print("Not enough snapshots (need >= 2)")
        return

    latest = snapshots[-1]
    previous = snapshots[-2]

    with open(latest, encoding="utf-8") as f:
        new_data = json.load(f)
    with open(previous, encoding="utf-8") as f:
        old_data = json.load(f)

    old_buys = _buy_only(old_data.get("signals", []))
    new_buys = _buy_only(new_data.get("signals", []))

    old_st = stats(old_buys)
    new_st = stats(new_buys)

    print(f"Previous ({previous.stem}): {old_st['count']} buy signals, 14d={old_st['14d_win_rate']:.0%}, 30d={old_st['30d_win_rate']:.0%}")
    print(f"Latest   ({latest.stem}): {new_st['count']} buy signals, 14d={new_st['14d_win_rate']:.0%}, 30d={new_st['30d_win_rate']:.0%}")

    alerts = []
    for metric, threshold in THRESHOLDS.items():
        old_v = old_st[metric]
        new_v = new_st[metric]
        if new_v < threshold and old_v < threshold:
            alerts.append(f"DECAY: {metric}={new_v:.0%} (below {threshold:.0%} x2 snapshots)")
        elif new_v < threshold:
            alerts.append(f"WATCH: {metric}={new_v:.0%} (below {threshold:.0%}, 1st occurrence)")

    if alerts:
        print("\n=== ALERTS ===")
        for a in alerts:
            print(a)
    else:
        print("\nNo decay detected")

    # Show trend
    if old_st["count"] > 0 and new_st["count"] > 0:
        delta = new_st["14d_win_rate"] - old_st["14d_win_rate"]
        print(f"\nTrend: 14d win rate {'+' if delta>=0 else ''}{delta:.0%}")

if __name__ == "__main__":
    import sys
    series = sys.argv[1] if len(sys.argv) > 1 else "backtest_"
    if series not in ("backtest_", "item_backtest_"):
        print("usage: python pipeline/factor_monitor.py [backtest_|item_backtest_]")
        sys.exit(1)
    check_decay(series)
