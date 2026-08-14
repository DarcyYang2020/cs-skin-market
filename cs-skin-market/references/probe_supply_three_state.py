import bisect
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date as date_cls, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "market.db"
REPLAY = BASE / "data" / "item_backtest_full_2025.json"
OUT = BASE / "data" / "_exp_supply_three_state.json"

STATE_LABELS = {
    "up": "价涨量缩·真吸筹",
    "flat": "价平量缩·挂单撤走（现引擎判定为吸筹）",
    "down": "价跌量缩·下跌惜售",
}


def median_or_none(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 3) if vals else None


def mean_or_none(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.mean(vals), 3) if vals else None


def p90_or_none(vals):
    vals = sorted(v for v in vals if v is not None)
    return round(vals[int(len(vals) * 0.9) - 1], 3) if len(vals) >= 10 else None


def win_or_none(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else None


def share_gt(vals, threshold):
    vals = [v for v in vals if v is not None]
    if len(vals) < 5:
        return None
    return round(sum(1 for v in vals if v > threshold) / len(vals) * 100, 1)


def supply_metrics(rows, as_of):
    prior = [r for r in rows if r[0] <= as_of]
    if not prior:
        return None
    last30 = prior[-30:]
    last7 = prior[-7:]
    vals30 = [r[2] for r in last30 if r[2] is not None]
    vals7 = [r[2] for r in last7 if r[2] is not None]
    if len(vals30) < 20:
        return None
    s30 = sum(vals30) / len(vals30)
    s7 = sum(vals7) / len(vals7) if vals7 else 0.0
    ratio = (s7 / s30) if s30 > 0 else None
    prices = [r[1] for r in prior if r[1] is not None]
    chg7 = None
    chg14 = None
    if len(prices) >= 8 and prices[-1] > 0 and prices[-8] > 0:
        chg7 = (prices[-1] / prices[-8] - 1) * 100
    if len(prices) >= 15 and prices[-1] > 0 and prices[-15] > 0:
        chg14 = (prices[-1] / prices[-15] - 1) * 100
    price_state = None
    if chg7 is not None:
        if chg7 > 3.0:
            price_state = "up"
        elif chg7 < -3.0:
            price_state = "down"
        else:
            price_state = "flat"
    supply_contract = bool(s30 > 0 and s7 > 0 and ratio is not None and ratio <= 0.85)
    return {
        "s7": round(s7, 2),
        "s30": round(s30, 2),
        "ratio": round(ratio, 4) if ratio is not None else None,
        "ins_valid30": len(vals30),
        "ins_null30": 30 - len(vals30),
        "ins_zero30": sum(1 for v in vals30 if v == 0),
        "chg7": round(chg7, 2) if chg7 is not None else None,
        "chg14": round(chg14, 2) if chg14 is not None else None,
        "price_state": price_state,
        "supply_contract": supply_contract,
    }


def forward_return(rows, as_of, horizon):
    idx = bisect.bisect_right([r[0] for r in rows], as_of) - 1
    if idx < 0:
        return None
    entry = rows[idx][1]
    target_idx = idx + horizon
    if target_idx >= len(rows):
        return None
    target = rows[target_idx][1]
    if entry is None or target is None or entry <= 0:
        return None
    return (target / entry - 1) * 100


def forward_stats(rows):
    out = {"n": len(rows)}
    if not rows:
        return out
    for field in ("fwd14", "net14", "fwd30", "net30"):
        out[f"win_{field}"] = win_or_none([r.get(field) for r in rows])
        out[f"mean_{field}"] = mean_or_none([r.get(field) for r in rows])
        out[f"median_{field}"] = median_or_none([r.get(field) for r in rows])
    return out


def load_price_rows(con):
    rows = defaultdict(list)
    for item_id, dt, price, ins in con.execute(
        "SELECT item_id, date, price_rmb, in_sale_count FROM price_history ORDER BY date"
    ):
        rows[item_id].append((dt, price, ins))
    return rows


def load_bid_rows(con):
    rows = defaultdict(list)
    for item_id, dt, bp, bn, bm in con.execute(
        "SELECT item_id, date, buy_price_last, buy_num_last, buy_price_mean FROM bid_history ORDER BY date"
    ):
        rows[item_id].append((dt, bp, bn, bm))
    return rows


def load_snapshot_rows(con):
    rows = defaultdict(list)
    for item_id, dt, spread, spread_avg, bid7, bid30, bid_highest in con.execute(
        "SELECT item_id, date, spread_pct, spread_avg, bid_7d_chg, bid_30d_chg, bid_highest FROM snapshots ORDER BY date"
    ):
        rows[item_id].append((dt[:10], spread, spread_avg, bid7, bid30, bid_highest))
    return rows


def add_days(day, delta):
    y, m, d = (int(x) for x in day.split("-"))
    return (date_cls(y, m, d) + timedelta(days=delta)).isoformat()


def bid_delta(rows, as_of, field_idx, delta):
    current = None
    base = None
    cutoff = add_days(as_of, delta)
    for r in rows:
        if r[0] > as_of:
            break
        if r[0] <= cutoff:
            base = r[field_idx]
        current = r[field_idx]
    if current is None or base is None or base <= 0:
        return None
    return (current / base - 1) * 100


def replay_segment(replay, price_rows, bid_rows):
    sigs = [s for s in replay.get("signals", []) if s.get("signal_type") == "accumulate"]
    con = sqlite3.connect(DB)
    names = {}
    for item_id, name in con.execute("SELECT id, name FROM items"):
        names[name] = item_id
    con.close()

    records = []
    for s in sigs:
        item_id = names.get(s.get("name"))
        metrics = supply_metrics(price_rows.get(item_id, []), s["date"]) if item_id else None
        state = None
        if metrics and metrics["supply_contract"]:
            state = metrics["price_state"]
        elif metrics:
            state = "not_contract"
        records.append(
            {
                "date": s["date"],
                "name": s.get("name"),
                "state": state,
                "metrics": metrics,
                "engine_supply_change_30d": s.get("supply_change_30d"),
                "fwd14": s.get("fwd14"),
                "net14": s.get("net14"),
                "fwd30": s.get("fwd30"),
                "net30": s.get("net30"),
                "bid_before_date": bool(item_id and any(r[0] <= s["date"] for r in bid_rows.get(item_id, []))),
            }
        )

    states = {"up": [], "flat": [], "down": [], "not_contract": []}
    for r in records:
        if r["state"] in states:
            states[r["state"]].append(r)
    monthly = defaultdict(Counter)
    for r in records:
        if r["state"] in ("up", "flat", "down"):
            monthly[r["date"][:7]][STATE_LABELS[r["state"]]] += 1
    contract_by_engine = Counter(
        "engine_contract" if (r.get("engine_supply_change_30d") or 0) < 0 else "engine_not_contract"
        for r in records
    )
    return {
        "n_accumulate_signals": len(records),
        "n_unmapped_items": sum(1 for r in records if r["metrics"] is None),
        "n_with_computed_contract": sum(1 for r in records if r["state"] in ("up", "flat", "down")),
        "n_with_bid_before_date": sum(1 for r in records if r["bid_before_date"]),
        "engine_supply_direction": dict(contract_by_engine),
        "note": "supply_accum family trigger is s7<=s30*0.85 AND |chg7|<=3, so by construction the replay family is the flat state; DB in_sale_count zero-padding in 2026-02/03 collapses s7 to 0 for most records",
        "by_state": {k: forward_stats(v) for k, v in states.items()},
        "monthly_contract_states": {k: dict(v) for k, v in sorted(monthly.items())},
        "sample_records": records[:10],
    }


def bid_evidence_segment(price_rows, bid_rows, snap_rows):
    latest_spread = {}
    for item_id, snaps in snap_rows.items():
        for r in reversed(snaps):
            if r[1] is not None:
                latest_spread[item_id] = r[1]
                break

    records = []
    for item_id, item_bids in bid_rows.items():
        item_price = price_rows.get(item_id, [])
        item_snaps = snap_rows.get(item_id, [])
        snap_dates = [r[0] for r in item_snaps]
        for bid in item_bids:
            as_of, bp, bn, bm = bid
            metrics = supply_metrics(item_price, as_of)
            if not metrics or not metrics["supply_contract"]:
                continue
            state = metrics["price_state"]
            if state is None:
                continue
            pos = bisect.bisect_right(snap_dates, as_of) - 1
            snap = item_snaps[pos] if pos >= 0 else None
            fwd14 = forward_return(item_price, as_of, 14)
            fwd30 = forward_return(item_price, as_of, 30)
            records.append(
                {
                    "item_id": item_id,
                    "date": as_of,
                    "state": state,
                    "buy_price_last": bp,
                    "buy_num_last": bn,
                    "buy_price_mean": bm,
                    "buy_price_chg7": bid_delta(item_bids, as_of, 1, -7),
                    "buy_num_chg7": bid_delta(item_bids, as_of, 2, -7),
                    "spread_pct": snap[1] if snap else None,
                    "spread_avg": snap[2] if snap else None,
                    "bid_7d_chg": snap[3] if snap else None,
                    "bid_30d_chg": snap[4] if snap else None,
                    "bid_highest": snap[5] if snap else None,
                    "latest_spread_pct": latest_spread.get(item_id),
                    "fwd14": fwd14,
                    "net14": (fwd14 - 2.0) if fwd14 is not None else None,
                    "fwd30": fwd30,
                    "net30": (fwd30 - 2.0) if fwd30 is not None else None,
                }
            )

    states = {k: [r for r in records if r["state"] == k] for k in STATE_LABELS}
    summary = {}
    for state, rows in states.items():
        summary[state] = {
            "label": STATE_LABELS[state],
            "n": len(rows),
            "n_unique_items": len({r["item_id"] for r in rows}),
            "n_buy_price_chg7_nonnull": sum(1 for r in rows if r["buy_price_chg7"] is not None),
            "n_buy_num_chg7_nonnull": sum(1 for r in rows if r["buy_num_chg7"] is not None),
            "n_spread_date_aligned_nonnull": sum(1 for r in rows if r["spread_pct"] is not None),
            "n_latest_spread_nonnull": sum(1 for r in rows if r["latest_spread_pct"] is not None),
            "median_buy_price_chg7": median_or_none([r["buy_price_chg7"] for r in rows]),
            "median_buy_num_chg7": median_or_none([r["buy_num_chg7"] for r in rows]),
            "median_spread_pct": median_or_none([r["spread_pct"] for r in rows]),
            "median_bid_7d_chg": median_or_none([r["bid_7d_chg"] for r in rows]),
            "median_bid_30d_chg": median_or_none([r["bid_30d_chg"] for r in rows]),
            "median_bid_highest": median_or_none([r["bid_highest"] for r in rows]),
            "median_latest_spread_pct": median_or_none([r["latest_spread_pct"] for r in rows]),
            "share_latest_spread_gt2": share_gt([r["latest_spread_pct"] for r in rows], 2.0),
            "forward": forward_stats(rows),
        }
    monthly = defaultdict(Counter)
    for r in records:
        monthly[r["date"][:7]][STATE_LABELS[r["state"]]] += 1

    all_spreads = [r[1] for snaps in snap_rows.values() for r in snaps if r[1] is not None]
    global_spread = {
        "n": len(all_spreads),
        "median": median_or_none(all_spreads),
        "mean": mean_or_none(all_spreads),
        "p90": p90_or_none(all_spreads),
        "share_gt2": share_gt(all_spreads, 2.0),
    }
    return {
        "window": ["2026-05-15", "2026-08-13"],
        "n_contract_bid_days": len(records),
        "n_unique_items": len({r["item_id"] for r in records}),
        "global_spread_distribution": global_spread,
        "by_state": summary,
        "monthly_contract_states": {k: dict(v) for k, v in sorted(monthly.items())},
    }


def main():
    replay = json.load(open(REPLAY, encoding="utf-8"))
    con = sqlite3.connect(DB)
    price_rows = load_price_rows(con)
    bid_rows = load_bid_rows(con)
    snap_rows = load_snapshot_rows(con)
    con.close()

    replay_part = replay_segment(replay, price_rows, bid_rows)
    bid_part = bid_evidence_segment(price_rows, bid_rows, snap_rows)
    out = {
        "probe": "supply_three_state",
        "stage": "stage0",
        "generated": "2026-08-14",
        "caveats": [
            "read-only probe: no engine parameters/thresholds changed",
            "replay accumulation signals are concentrated in 2026-02/03; bid_history starts 2026-05, so replay bid evidence is only n=3",
            "supply_accum family is by construction price-flat (|chg7|<=3); the three-state contrast therefore lives in the 2026-05+ bid evidence segment",
            "bid evidence segment is observational, overlapping windows, not walk-forward; forward returns are unverified small samples and not a production gate",
            "spread_pct is sparse (425 non-null snapshots), so per-state date-aligned spread is mostly missing; latest item-level spread is a static liquidity proxy",
            "supply_contract uses s7/s30<=0.85 consistent with the engine family trigger",
        ],
        "replay_accumulate": replay_part,
        "bid_evidence": bid_part,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
