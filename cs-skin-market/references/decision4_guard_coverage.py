#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DECISION-4: guard coverage audit + current-production aligned replay (read-only).

Inputs:
  data/item_backtest_full_2025.json
  data/market.db

Outputs:
  data/_exp_guard_coverage.json
  data/_exp_aligned_replay_v2T4.json

This script does not modify the production engine, does not overwrite the
official backtest product, and does not overturn the 2026-08-10 audit.
"""
import bisect
import io
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db
from pipeline import item_analysis as ia
from pipeline.backtest_common import build_market_context, patch_sentiment
from pipeline.trend_health import liquidity_supply_floor


START = "2025-08-10"
END = "2026-08-05"
WARMUP = 30
COST = 0.02
JSON_PATH = ROOT / "data" / "item_backtest_full_2025.json"
if os.environ.get("DECISION6_OUT") == "1":
    GUARD_OUT = ROOT / "data" / "_exp_guard_coverage_decision6.json"
    REPLAY_OUT = ROOT / "data" / "_exp_aligned_replay_decision6.json"
else:
    GUARD_OUT = ROOT / "data" / "_exp_guard_coverage.json"
    REPLAY_OUT = ROOT / "data" / "_exp_aligned_replay_v2T4.json"


def load_official_signals():
    with io.open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("signals", [])


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
    dates = [r["date"] for r in rows]
    prices = [r["price_rmb"] for r in rows]
    supply = [r["in_sale_count"] or 0 for r in rows]
    raw_supply = [r["in_sale_count"] for r in rows]
    return dates, prices, supply, raw_supply


def load_survive(item_id):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT date, statistic FROM survive_history WHERE item_id=? AND statistic IS NOT NULL AND statistic>0 ORDER BY date",
        (item_id,),
    ).fetchall()
    conn.close()
    return [r["date"] for r in rows], [r["statistic"] for r in rows]


def load_bid(item_id):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT date, buy_price_last, buy_price_mean, buy_num_last, buy_num_mean
           FROM bid_history WHERE item_id=? ORDER BY date""",
        (item_id,),
    ).fetchall()
    conn.close()
    return rows


def _as_float(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def bid_proxy_at(rows, index, price):
    if not rows or price is None or price <= 0:
        return None
    row = rows[index]
    bid_price = _as_float(row["buy_price_last"]) or _as_float(row["buy_price_mean"])
    if bid_price is None or bid_price <= 0:
        return None
    spread_pct = (price - bid_price) / price * 100.0
    if spread_pct < 0:
        spread_pct = 0.0
    lo = max(0, index - 29)
    spreads = []
    for r in rows[lo:index + 1]:
        bp = _as_float(r["buy_price_last"]) or _as_float(r["buy_price_mean"])
        # price for older spread is unavailable here; use current price only for width,
        # which keeps the proxy conservative and avoids a second join by date.
        if bp and price > 0:
            spreads.append(max(0.0, (price - bp) / price * 100.0))
    spread_avg = (sum(spreads) / len(spreads)) if spreads else spread_pct
    base_idx7 = index - 7
    base_idx30 = index - 30
    cur = bid_price
    prev7 = _as_float(rows[base_idx7]["buy_price_last"] or rows[base_idx7]["buy_price_mean"]) if base_idx7 >= 0 else None
    prev30 = _as_float(rows[base_idx30]["buy_price_last"] or rows[base_idx30]["buy_price_mean"]) if base_idx30 >= 0 else None
    bid7 = ((cur / prev7 - 1) * 100.0) if prev7 else None
    bid30 = ((cur / prev30 - 1) * 100.0) if prev30 else None
    return {
        "spread_pct": round(spread_pct, 3),
        "spread_avg": round(spread_avg, 3),
        "bid_7d_chg": round(bid7, 3) if bid7 is not None else None,
        "bid_30d_chg": round(bid30, 3) if bid30 is not None else None,
        "_source": "bid_history_proxy",
    }


def nearest_survive(dates, values, target):
    if not dates or target < dates[0]:
        return None, False
    idx = bisect.bisect_right(dates, target) - 1
    return values[idx], True


def run_one(item_id, name, series, idx, market_ctx, survive, bid_rows, recent_buys):
    dates, prices, supply, raw_supply = series
    supply_depth_missing = db.supply_depth_missing(raw_supply[idx], dates[idx]) if idx < len(raw_supply) else True
    d = dates[idx]
    mc = market_ctx.get(d)
    if mc is None:
        return None, "market_ctx_missing"
    patch_sentiment(mc["sentiment"])
    survive_count = 0
    survive_available = False
    if survive is not None:
        survive_count, survive_available = nearest_survive(survive[0], survive[1], d)
        survive_count = int(survive_count) if survive_count else 0
    bid_index = None
    if bid_rows:
        bdates = [r["date"] for r in bid_rows]
        bi = bisect.bisect_right(bdates, d) - 1
        if bi >= 0:
            bid_index = bi
    order_book = bid_proxy_at(bid_rows, bid_index, prices[idx]) if bid_index is not None else None
    try:
        res = ia.run_item_analysis(
            name=name,
            prices=prices[:idx + 1],
            supply_hist=supply[:idx + 1],
            supply_depth_missing=supply_depth_missing,
            market_history=None,
            market_pct_90d=mc["pct"],
            market_cycle=mc["cycle"],
            market_zscore=mc["z"],
            market_th_score=mc["th"],
            market_30d_change=mc.get("chg30", 0),
            market_drop21=mc.get("drop21", 0),
            recent_buy_dates=recent_buys,
            signal_date=d,
            survive_count=survive_count,
            order_book=order_book,
        )
    except Exception as exc:
        return None, f"engine_error:{type(exc).__name__}:{exc}"
    fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
    return {
        "fd": fd,
        "liquidity_score": getattr(res.liquidity, "score", None),
        "liquidity_breakdown": getattr(res.liquidity, "breakdown", {}),
        "value_score": getattr(res.value, "score", None),
        "supply_depth": supply[idx] if idx < len(supply) else None,
        "supply_depth_missing": supply_depth_missing,
        "supply_depth_floor": liquidity_supply_floor(prices[idx]) if idx < len(prices) else None,
        "liquidity_depth_gate_hit": bool(0 < (supply[idx] if idx < len(supply) else 0) < (liquidity_supply_floor(prices[idx]) if idx < len(prices) else 0)),
        "liquidity_score_gate_hit": bool((getattr(res.liquidity, "score", 50) or 50) < 30),
        "survive_count": survive_count,
        "survive_available": survive_available,
        "bid_score": res.bid_support.get("score") if isinstance(res.bid_support, dict) else None,
        "bid_available": bool(order_book),
        "bid_source": order_book.get("_source") if order_book else None,
        "signal_type": None,
    }, None


def summarize(rows):
    def agg(subset):
        with_fwd = [r for r in subset if r.get("fwd14") is not None]
        wins = [r for r in with_fwd if (r["fwd14"] or 0) > 0]
        return {
            "n": len(with_fwd),
            "win14_pct": round(100.0 * len(wins) / len(with_fwd), 2) if with_fwd else None,
            "avg14_pct": round(sum(r["fwd14"] for r in with_fwd) / len(with_fwd), 3) if with_fwd else None,
            "avg_net14_pct": round(sum(r["net14"] for r in with_fwd) / len(with_fwd), 3) if with_fwd else None,
        }
    aligned_buys = [r for r in rows if r.get("aligned_action") in ("buy", "oversold_buy")]
    strict_buys = [r for r in rows if r.get("strict_action") in ("buy", "oversold_buy")]
    original_buys = [r for r in rows]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "official_n": len(rows),
        "official": agg(original_buys),
        "aligned": agg(aligned_buys),
        "strict": agg(strict_buys),
        "action_distribution": {
            "official": dict(Counter(r.get("original_action") for r in rows)),
            "aligned": dict(Counter(r.get("aligned_action") for r in rows)),
            "strict": dict(Counter(r.get("strict_action") for r in rows)),
        },
        "coverage": {
            "survive_available": sum(1 for r in rows if r.get("survive_available")),
            "bid_available": sum(1 for r in rows if r.get("bid_available")),
            "liquidity_score_present": sum(1 for r in rows if r.get("liquidity_score") is not None),
        },
        "flips": {
            "official_to_aligned": dict(Counter(f"{r.get('original_action')}->{r.get('aligned_action')}" for r in rows)),
        },
    }


def main():
    official = load_official_signals()
    name_to_id = item_name_to_id()
    market_ctx = build_market_context(START, end=END)
    by_item = defaultdict(list)
    for sig in official:
        by_item[sig.get("name")].append(sig)
    rows = []
    errors = []
    for name, sigs in sorted(by_item.items()):
        item_id = name_to_id.get(name)
        if item_id is None:
            errors.append({"name": name, "error": "item_id_missing"})
            continue
        series = load_series(item_id)
        if len(series[0]) < WARMUP + 1:
            errors.append({"name": name, "error": "not_enough_history"})
            continue
        date_to_idx = {d: i for i, d in enumerate(series[0])}
        survive = load_survive(item_id)
        bid_rows = load_bid(item_id)
        recent_buys = []
        for sig in sorted(sigs, key=lambda s: s["date"]):
            idx = date_to_idx.get(sig["date"])
            if idx is None:
                errors.append({"name": name, "date": sig["date"], "error": "date_not_in_series"})
                continue
            result, err = run_one(item_id, name, series, idx, market_ctx, survive, bid_rows, recent_buys)
            if result is None:
                errors.append({"name": name, "date": sig["date"], "error": err})
                continue
            fd = result["fd"]
            action = fd.get("action", "")
            result.update({
                "name": name,
                "date": sig["date"],
                "entry_price": sig.get("entry_price"),
                "original_action": sig.get("action"),
                "original_signal_type": sig.get("signal_type"),
                "fwd14": sig.get("fwd14"),
                "fwd30": sig.get("fwd30"),
                "net14": sig.get("net14"),
                "net30": sig.get("net30"),
                "max_dd": sig.get("max_dd"),
                "aligned_action": action,
                "deduction_sources": fd.get("deduction_sources", []),
                "liquidity_filtered": fd.get("liquidity_filtered"),
                "position_limit": fd.get("position_limit"),
            })
            # Strict missing-guard sensitivity: treat missing survive/bid as a veto for buy.
            strict_block = []
            if action in ("buy", "oversold_buy") and not result["survive_available"]:
                strict_block.append("missing_survive")
            if action in ("buy", "oversold_buy") and not result["bid_available"]:
                strict_block.append("missing_bid")
            result["strict_blocked_by"] = strict_block
            result["strict_action"] = "watch" if strict_block else action
            rows.append(result)
            if action in ("buy", "oversold_buy"):
                recent_buys.append(sig["date"])
    agg = summarize(rows)
    GUARD_OUT.write_text(json.dumps({"aggregate": agg, "signals": rows, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    replay = [r for r in rows if r.get("aligned_action") in ("buy", "oversold_buy")]
    REPLAY_OUT.write_text(json.dumps({"aggregate": agg, "signals": replay, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False, indent=2))
    print("rows", len(rows), "errors", len(errors))
    print("wrote", GUARD_OUT)
    print("wrote", REPLAY_OUT)


if __name__ == "__main__":
    main()