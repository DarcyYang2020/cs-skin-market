#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POOL-2: supply_depth latest vs 7-day-median floor sensitivity on CLEAN-CUR.

Read-only probe. It re-reads price_history for each CLEAN-CUR signal (the
BASELINE_LEDGER CLEAN-CUR replay source) and compares the current production
"latest in_sale_count" floor against a "7-day nonzero median" alternative.
It does NOT change the floor, engine, or replay product.

Input : data/_exp_v2t7_win_replay.json (CLEAN-CUR baseline, 150 signals)
Output: data/_exp_pool2_supply_depth_clean.json
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
from pipeline.trend_health import liquidity_supply_floor
from pipeline.config import SIGNAL_FAMILY_TAXONOMY, display_key_for_label

REPLAY = ROOT / "data" / "_exp_v2t7_win_replay.json"
OUT = ROOT / "data" / "_exp_pool2_supply_depth_clean.json"


def item_name_to_id():
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
        return {r["name"]: r["id"] for r in rows}
    finally:
        conn.close()


def load_series(item_id):
    conn = db.get_conn()
    try:
        rows = conn.execute(
            """SELECT date, price_rmb, in_sale_count
               FROM price_history
               WHERE item_id=? AND id IN (
                 SELECT MAX(id) FROM price_history WHERE item_id=? GROUP BY date
               )
               ORDER BY date""",
            (item_id, item_id),
        ).fetchall()
        return ([r["date"] for r in rows],
                [r["price_rmb"] for r in rows],
                [r["in_sale_count"] or 0 for r in rows])
    finally:
        conn.close()


def median7_nonzero(supply, idx):
    window = supply[max(0, idx - 6):idx + 1]
    vals = [v for v in window if v and v > 0]
    if not vals:
        return None
    return statistics.median(vals)


def win_stats(rows):
    with_fwd = [r for r in rows if r.get("fwd14") is not None]
    wins = [r for r in with_fwd if (r.get("fwd14") or 0) > 0]
    return {
        "n": len(with_fwd),
        "win14_pct": round(100.0 * len(wins) / len(with_fwd), 2) if with_fwd else None,
        "avg14_pct": round(sum(r["fwd14"] for r in with_fwd) / len(with_fwd), 3) if with_fwd else None,
    }


def main():
    data = json.loads(REPLAY.read_text(encoding="utf-8"))
    rows_in = data.get("signals", [])
    name_to_id = item_name_to_id()
    cache = {}
    rows = []
    for sig in rows_in:
        item_id = name_to_id.get(sig.get("name"))
        if item_id is None:
            rows.append({"name": sig.get("name"), "date": sig.get("date"), "skip": "no_item"})
            continue
        if item_id not in cache:
            cache[item_id] = load_series(item_id)
        dates, prices, supply = cache[item_id]
        idx = dates.index(sig["date"]) if sig["date"] in dates else None
        if idx is None:
            rows.append({"name": sig.get("name"), "date": sig.get("date"), "skip": "no_date"})
            continue
        latest = supply[idx] if idx < len(supply) else None
        median = median7_nonzero(supply, idx)
        floor = liquidity_supply_floor(sig.get("entry_price"))
        latest_hit = bool(floor and 0 < (latest or 0) < floor)
        median_hit = bool(floor and median is not None and 0 < median < floor)
        if median is None:
            flip = "median_unavailable"
        elif latest_hit == median_hit:
            flip = "same_fail" if latest_hit else "same_pass"
        elif latest_hit and not median_hit:
            flip = "latest_fail_median_pass"
        else:
            flip = "latest_pass_median_fail"
        rows.append({
            "name": sig.get("name"),
            "date": sig.get("date"),
            "action_label": sig.get("action_label"),
            "display_key": display_key_for_label(sig.get("action_label") or ""),
            "entry_price": sig.get("entry_price"),
            "latest": latest,
            "median7_nonzero": median,
            "floor": floor,
            "latest_hit": latest_hit,
            "median_hit": median_hit,
            "flip": flip,
            "fwd14": sig.get("fwd14"),
            "net14": sig.get("net14"),
        })

    aligned = [r for r in rows if r.get("flip") is not None]
    would_downgrade = [r for r in aligned if r["flip"] == "latest_pass_median_fail"]
    would_upgrade = [r for r in aligned if r["flip"] == "latest_fail_median_pass"]
    by_key = {}
    for key in SIGNAL_FAMILY_TAXONOMY["display_keys"]:
        sub = [r for r in aligned if r.get("display_key") == key]
        by_key[key] = {
            "n": len(sub),
            "flip_counts": dict(Counter(r["flip"] for r in sub)),
            "would_downgrade_median": win_stats([r for r in sub if r["flip"] == "latest_pass_median_fail"]),
            "would_upgrade_median": win_stats([r for r in sub if r["flip"] == "latest_fail_median_pass"]),
        }
    agg = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "replay": str(REPLAY),
        "rows": len(rows),
        "matched": len(aligned),
        "skip_counts": dict(Counter(r.get("skip") for r in rows if r.get("skip"))),
        "flip_counts": dict(Counter(r["flip"] for r in aligned)),
        "would_downgrade_median": win_stats(would_downgrade),
        "would_upgrade_median": win_stats(would_upgrade),
        "by_display_key": by_key,
    }
    OUT.write_text(json.dumps({"aggregate": agg, "signals": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()