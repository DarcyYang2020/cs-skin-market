#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P-A: supply_depth latest vs 7-day median floor sensitivity (read-only).

Uses the DECISION-4 aligned audit rows and re-reads price_history to compute
a robust 7-day median. It does not change the production floor or replay
product.
"""
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db


COVERAGE = ROOT / "data" / "_exp_guard_coverage.json"
OUT = ROOT / "data" / "_exp_supply_depth_sensitivity.json"


def item_name_to_id():
    conn = db.get_conn()
    rows = conn.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    conn.close()
    return {r["name"]: r["id"] for r in rows}


def load_series(item_id):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT date, price_rmb, in_sale_count
           FROM price_history
           WHERE item_id=? AND id IN (
             SELECT MAX(id) FROM price_history WHERE item_id=? GROUP BY date
           )
           ORDER BY date""",
        (item_id, item_id),
    ).fetchall()
    conn.close()
    return [r["date"] for r in rows], [r["price_rmb"] for r in rows], [r["in_sale_count"] or 0 for r in rows]


def median7_nonzero(supply, idx):
    window = supply[max(0, idx - 6):idx + 1]
    vals = [v for v in window if v and v > 0]
    if len(vals) >= 3:
        return statistics.median(vals)
    if vals:
        return statistics.median(vals)
    return None


def win_stats(rows):
    with_fwd = [r for r in rows if r.get("fwd14") is not None]
    wins = [r for r in with_fwd if (r.get("fwd14") or 0) > 0]
    return {
        "n": len(with_fwd),
        "win14_pct": round(100.0 * len(wins) / len(with_fwd), 2) if with_fwd else None,
        "avg14_pct": round(sum(r["fwd14"] for r in with_fwd) / len(with_fwd), 3) if with_fwd else None,
    }


def main():
    audit = json.loads(COVERAGE.read_text(encoding="utf-8"))
    rows_in = audit.get("signals", [])
    name_to_id = item_name_to_id()
    cache = {}
    rows = []
    for sig in rows_in:
        item_id = name_to_id.get(sig["name"])
        if item_id is None:
            continue
        if item_id not in cache:
            cache[item_id] = load_series(item_id)
        dates, prices, supply = cache[item_id]
        idx = dates.index(sig["date"]) if sig["date"] in dates else None
        if idx is None:
            continue
        latest = supply[idx] if idx < len(supply) else None
        median = median7_nonzero(supply, idx)
        floor = sig.get("supply_depth_floor")
        if floor is None:
            floor = 0
        latest_hit = bool(0 < (latest or 0) < (floor or 0))
        median_hit = bool(median is not None and 0 < median < floor)
        flip = "median_unavailable"
        if median is not None:
            if latest_hit == median_hit:
                flip = "same_fail" if latest_hit else "same_pass"
            elif latest_hit and not median_hit:
                flip = "latest_fail_median_pass"
            else:
                flip = "latest_pass_median_fail"
        rows.append({
            "name": sig["name"],
            "date": sig["date"],
            "aligned_action": sig.get("aligned_action"),
            "original_action": sig.get("original_action"),
            "price": prices[idx] if idx < len(prices) else None,
            "latest": latest,
            "median7_nonzero": median,
            "floor": floor,
            "latest_hit": latest_hit,
            "median_hit": median_hit,
            "flip": flip,
            "fwd14": sig.get("fwd14"),
            "fwd30": sig.get("fwd30"),
            "net14": sig.get("net14"),
        })
    aligned = [r for r in rows if r.get("aligned_action") in ("buy", "oversold_buy")]
    latest_pass = [r for r in aligned if not r["latest_hit"]]
    latest_fail = [r for r in aligned if r["latest_hit"]]
    median_pass = [r for r in aligned if not r["median_hit"]]
    median_fail = [r for r in aligned if r["median_hit"]]
    would_downgrade = [r for r in aligned if r["flip"] == "latest_pass_median_fail"]
    would_upgrade = [r for r in aligned if r["flip"] == "latest_fail_median_pass"]
    agg = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": len(rows),
        "flip_counts": dict(Counter(r["flip"] for r in rows)),
        "aligned_flip_counts": dict(Counter(r["flip"] for r in aligned)),
        "aligned": {
            "n": len(aligned),
            "latest_pass": win_stats(latest_pass),
            "latest_fail": win_stats(latest_fail),
            "median_pass": win_stats(median_pass),
            "median_fail": win_stats(median_fail),
            "would_downgrade_median": win_stats(would_downgrade),
            "would_upgrade_median": win_stats(would_upgrade),
        },
    }
    OUT.write_text(json.dumps({"aggregate": agg, "signals": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()