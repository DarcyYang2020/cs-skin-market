"""Sentiment x valuation 9-grid backtest for item buy signals.

Slices buy signals by sentiment bucket (<50 / 50-75 / >=75) and price-percentile
bucket (<10 / 10-25 / >=25), then reports 14d/30d win-rate, avg return, expectancy
per cell. Goal: verify the "fake bottom" (low valuation + greedy) cell has negative
expectancy, so the engine can add a targeted downgrade rule if the data supports it.

Usage:
  python run_item_9grid_backtest.py                 # default signals: data/item_backtest_full_2025.json
  python run_item_9grid_backtest.py --signals path
"""
import sys, json, argparse
from pathlib import Path
sys.path.insert(0, ".")

SENT_BUCKETS = [(0, 50, "贪婪带<50"), (50, 75, "中性带50-75"), (75, 200, "恐惧带>=75")]
PCT_BUCKETS = [(0, 10, "深低估pct<10"), (10, 25, "低估pct10-25"), (25, 200, "高估pct>=25")]


def bucket_of(v, buckets):
    for lo, hi, label in buckets:
        if lo <= v < hi:
            return label
    return "未知"


def stats(rows, key14="fwd14", key30="fwd30"):
    def one(key, horizon):
        vals = [r[key] for r in rows if r.get(key) is not None]
        if not vals:
            return {"n": 0}
        wins = sum(1 for v in vals if v > 0)
        return {"n": len(vals), "win_pct": round(100.0 * wins / len(vals), 1),
                "avg": round(sum(vals) / len(vals), 2), "expectancy": round(sum(vals) / len(vals), 2)}
    return {"14d": one(key14, 14), "30d": one(key30, 30)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--signals", default="data/item_backtest_full_2025.json")  # 去量 v2 标准回放（旧 88 基准已删）
    args = p.parse_args()
    data = json.loads(Path(args.signals).read_text(encoding="utf-8"))
    signals = data["signals"]

    grid = {"meta": {"n_signals": len(signals), "source": args.signals}, "cells": {}}
    overall = stats(signals)
    grid["overall"] = overall

    for slo, shi, slabel in SENT_BUCKETS:
        for plo, phi, plabel in PCT_BUCKETS:
            cell_rows = [s for s in signals
                         if slo <= s["sentiment"] < shi and plo <= s["pct"] < phi]
            key = f"{slabel} | {plabel}"
            grid["cells"][key] = {"n": len(cell_rows), "stats": stats(cell_rows)}

    out = Path("data/item_9grid_backtest_latest.json")
    out.write_text(json.dumps(grid, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"signals={len(signals)}  overall 14d {overall['14d']}  30d {overall['30d']}")
    for k, v in grid["cells"].items():
        s14, s30 = v["stats"]["14d"], v["stats"]["30d"]
        if v["n"] == 0:
            print(f"  {k:28s} n=0")
        else:
            print(f"  {k:28s} n={v['n']:3d}  14d win={s14['win_pct']:5.1f}% avg={s14['avg']:7.2f}  30d win={s30['win_pct']:5.1f}% avg={s30['avg']:7.2f}")


if __name__ == "__main__":
    main()
