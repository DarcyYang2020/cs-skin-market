#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P-D: LIQ-RATIO-1 forward-only cross-sectional validation (read-only).

Scope: only aligned buy signals where both survive_history and bid_history are
available (bid history starts 2026-05-15). This is a forward/production sample,
NOT a historical replay factor.
"""
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db


COVERAGE = ROOT / "data" / "_exp_guard_coverage.json"
OUT = ROOT / "data" / "_exp_liq_ratio_forward.json"


def load_bid_map():
    conn = db.get_conn()
    rows = conn.execute("SELECT item_id, date, buy_num_last, buy_num_mean FROM bid_history ORDER BY item_id, date").fetchall()
    conn.close()
    out = defaultdict(dict)
    for r in rows:
        out[r["item_id"]][r["date"]] = r
    return out


def item_name_to_id():
    conn = db.get_conn()
    rows = conn.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    conn.close()
    return {r["name"]: r["id"] for r in rows}


def fnum(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def win(rows):
    n = len(rows)
    wins = sum(1 for r in rows if (r.get("fwd14") or 0) > 0)
    return {
        "n": n,
        "win14_pct": round(100.0 * wins / n, 2) if n else None,
        "avg14_pct": round(sum(r["fwd14"] for r in rows) / n, 3) if n else None,
        "avg_net14_pct": round(sum(r["net14"] for r in rows) / n, 3) if n else None,
    }


def bucket_stats(rows, key):
    buckets = [("0-0.5%", 0, 0.005), ("0.5-1%", 0.005, 0.01), ("1-2%", 0.01, 0.02),
               ("2-3%", 0.02, 0.03), ("3-5%", 0.03, 0.05), ("5%+", 0.05, float("inf"))]
    out = {}
    for label, lo, hi in buckets:
        subset = [r for r in rows if r.get(key) is not None and lo <= r[key] < hi]
        out[label] = win(subset)
    return out


def main():
    audit = json.loads(COVERAGE.read_text(encoding="utf-8"))
    name_to_id = item_name_to_id()
    bid_map = load_bid_map()
    rows = []
    for sig in audit["signals"]:
        if not (sig.get("survive_available") and sig.get("bid_available")):
            continue
        if sig.get("aligned_action") not in ("buy", "oversold_buy"):
            continue
        if sig.get("fwd14") is None:
            continue
        item_id = name_to_id.get(sig["name"])
        if item_id is None:
            continue
        bid_row = bid_map.get(item_id, {}).get(sig["date"])
        if bid_row is None:
            continue
        supply_depth = sig.get("supply_depth")
        survive = sig.get("survive_count")
        bid_num = fnum(bid_row["buy_num_last"]) or fnum(bid_row["buy_num_mean"])
        if not supply_depth or not survive or bid_num is None:
            continue
        listed_ratio = supply_depth / survive
        bid_sell_ratio = bid_num / supply_depth if supply_depth > 0 else None
        rows.append({
            "name": sig["name"],
            "date": sig["date"],
            "supply_depth": supply_depth,
            "survive_count": survive,
            "bid_num": bid_num,
            "listed_ratio": round(listed_ratio, 6),
            "bid_sell_ratio": round(bid_sell_ratio, 6) if bid_sell_ratio is not None else None,
            "bid_score": sig.get("bid_score"),
            "fwd14": sig.get("fwd14"),
            "net14": sig.get("net14"),
            "fwd30": sig.get("fwd30"),
        })
    sorted_lr = sorted(r["listed_ratio"] for r in rows)
    quantiles = {}
    for p in (0.1, 0.25, 0.5, 0.75, 0.9):
        if sorted_lr:
            idx = min(len(sorted_lr) - 1, int(len(sorted_lr) * p))
            quantiles[f"p{int(p*100)}"] = round(sorted_lr[idx], 6)
    agg = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "aligned buys with both survive and bid history available",
        "n": len(rows),
        "listed_ratio_quantiles": quantiles,
        "listed_ratio_buckets": bucket_stats(rows, "listed_ratio"),
        "bid_sell_ratio_buckets": bucket_stats(rows, "bid_sell_ratio"),
        "overall": win(rows),
    }
    OUT.write_text(json.dumps({"aggregate": agg, "signals": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()