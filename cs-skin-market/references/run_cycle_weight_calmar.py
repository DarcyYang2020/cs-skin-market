# -*- coding: utf-8 -*-
"""Cycle-weight Calmar re-score (2026-08-14, read-only).

Re-scores the current cycle ordering under the new north-star metric using the standard
317-signal replay. For each cycle phase it reports net14/net30 expectancy and a cap0.8/hold21
portfolio Calmar. This is not a full counterfactual rerun of the pre-2026-08-10 mapping:
pool-A history needed for a clean rerun has been pruned by the 365-day retention policy.

Writes only data/_exp_cycle_weight_calmar.json. No engine/param changes.
"""
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "references"))
import exit_1_a2 as e1

REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
OUT = ROOT / "data" / "_exp_cycle_weight_calmar.json"


def stats(vals):
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "win_pct": round(100.0 * sum(1 for v in vals if v > 0) / len(vals), 1),
        "avg_pct": round(sum(vals) / len(vals), 2),
        "median_pct": round(statistics.median(vals), 2),
    }


def main():
    data = json.loads(REPLAY.read_text(encoding="utf-8"))
    sigs = [s for s in data.get("signals") or [] if s.get("fwd_series")]
    by_cycle = defaultdict(list)
    for s in sigs:
        by_cycle[s.get("cycle")].append(s)

    rows = {}
    for cyc, arr in sorted(by_cycle.items(), key=lambda x: -len(x[1])):
        net14 = [s["net14"] for s in arr if s.get("net14") is not None]
        net30 = [s["net30"] for s in arr if s.get("net30") is not None]
        rows[cyc] = {
            "n_signals": len(arr),
            "net14": stats(net14),
            "net30": stats(net30),
            "portfolio": e1._portfolio(arr, "hold21"),
        }

    current_order = ["consolidation", "accumulation", "markup", "distribution"]
    order_check = {}
    available = [c for c in current_order if c in rows and rows[c]["portfolio"]]
    for i in range(len(available) - 1):
        a, b = available[i], available[i + 1]
        ca = rows[a]["portfolio"]["calmar"]
        cb = rows[b]["portfolio"]["calmar"]
        order_check[a + ">=" + b] = bool(ca >= cb)

    out = {
        "generated": datetime.now().isoformat(timespec="minutes"),
        "note": "Cycle-weight re-score under expectancy + Calmar/maxDD on the current 317-signal replay. Not a clean counterfactual rerun of old cycle weights: pool-A history was pruned by 365d retention. Current production order: consolidation 2.5 > accumulation 2.0 > markup 1.2 > distribution 0.5.",
        "signals": len(sigs),
        "by_cycle": rows,
        "calmar_order_check": order_check,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("written:", OUT)


if __name__ == "__main__":
    main()