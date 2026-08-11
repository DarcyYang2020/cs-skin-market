# -*- coding: utf-8 -*-
"""P-2 分桶回放（2026-08-11）：高价(>=1000)品按信号日在售量分桶，输出三件套。

用法: cd cs-skin-market && python references/p2_bucket_backtest.py --window all --out data/_exp_p2_bucket_all.json
窗口: all = 价>=1000 品全量（58 品 − 2 品 runner EXCLUDED_ITEMS = 56）；365d = 仅 days>=350 品（34）。
分桶（信号日动态口径）: entry_price>=1000 且 in_sale_count ∈[100,200]=p2 / >200=ctrl / <100=deep_low。
只读回放，不动引擎/库；产物归档 data/_exp_p2_bucket_*.json。
"""
import sys, json, argparse
from datetime import datetime
from pathlib import Path
from collections import Counter

sys.path.insert(0, ".")
import importlib.util

_ARCHIVED_RUNNER = Path(__file__).resolve().parent / "scripts-archive" / "run_item_backtest.py"
spec = importlib.util.spec_from_file_location("rib", str(_ARCHIVED_RUNNER))
rib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rib)

from pipeline.backtest_common import build_market_context
from pipeline import db

START, END, WARMUP = "2025-08-10", "2026-08-05", 30
COST = 0.02
EXCLUDED = rib.EXCLUDED_ITEMS


def bucket_pool():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT i.id, i.name,
               (SELECT ph.price_rmb FROM price_history ph WHERE ph.item_id=i.id
                ORDER BY ph.date DESC LIMIT 1) AS price,
               (SELECT COUNT(DISTINCT ph.date) FROM price_history ph WHERE ph.item_id=i.id) AS days
           FROM items i
           WHERE (SELECT ph.price_rmb FROM price_history ph WHERE ph.item_id=i.id
                  ORDER BY ph.date DESC LIMIT 1) >= 1000
             """).fetchall()
    conn.close()
    return [r for r in rows if r["name"] not in EXCLUDED]


def sale_map(item_id):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT date, in_sale_count FROM price_history WHERE item_id=?", (item_id,)).fetchall()
    conn.close()
    return {r["date"]: r["in_sale_count"] or 0 for r in rows}


def bucket_stats(sigs):
    n = len(sigs)
    if not n:
        return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
    r14 = [s["net14"] for s in sigs if s.get("net14") is not None]
    r30 = [s["net30"] for s in sigs if s.get("net30") is not None]
    return {
        "n": n,
        "win14": round(sum(1 for x in r14 if x > 0) / len(r14) * 100, 1) if r14 else None,
        "avg14": round(sum(r14) / len(r14), 2) if r14 else None,
        "win30": round(sum(1 for x in r30 if x > 0) / len(r30) * 100, 1) if r30 else None,
        "avg30": round(sum(r30) / len(r30), 2) if r30 else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="all", choices=["all", "365d"])
    ap.add_argument("--out", default="data/_exp_p2_bucket_all.json")
    args = ap.parse_args()

    rib.patch_sentiment(50.0)
    market_ctx = build_market_context(START, end=END)
    pool = bucket_pool()
    if args.window == "365d":
        pool = [r for r in pool if r["days"] >= 350]
    print(f"P-2 池: {len(pool)} 品 (window={args.window})", flush=True)

    results, signals = [], []
    t0 = datetime.now()
    for n_i, r in enumerate(pool, 1):
        iid, iname = r["id"], r["name"]
        br = rib.backtest_item(iid, iname, START, END, WARMUP, market_ctx, cost=COST)
        smap = sale_map(iid)
        got = [s for s in br.get("signals", []) if s.get("fwd14") is not None]
        for s in got:
            s["in_sale_count"] = smap.get(s["date"])
            s["item_days"] = r["days"]
        results.append(br)
        signals.extend(got)
        if n_i % 10 == 0 or got:
            print(f"[{n_i}/{len(pool)}] {iname[:26]:28s} days={br.get('days')} sig={len(got)} "
                  f"elapsed={str(datetime.now()-t0)[:8]}", flush=True)

    buckets = {"p2": [], "ctrl": [], "deep_low": [], "no_sale": []}
    for s in signals:
        if s["entry_price"] < 1000:
            continue
        sc = s.get("in_sale_count")
        if sc is None:
            buckets["no_sale"].append(s)
        elif 100 <= sc <= 200:
            buckets["p2"].append(s)
        elif sc > 200:
            buckets["ctrl"].append(s)
        else:
            buckets["deep_low"].append(s)

    out = {
        "args": {"window": args.window, "start": START, "end": END, "warmup": WARMUP,
                 "cost": COST, "pool": f"价>=1000 {len(pool)}品"},
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signals_total": len(signals),
        "buckets": {k: bucket_stats(v) for k, v in buckets.items()},
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "by_type": dict(Counter(s.get("signal_type") for s in signals)),
        "signals": signals,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("signals:", len(signals), "| 分桶:", out["bucket_counts"], flush=True)
    print("三件套 p2:", out["buckets"]["p2"], flush=True)
    print("三件套 ctrl:", out["buckets"]["ctrl"], flush=True)
    print("saved", args.out, flush=True)


if __name__ == "__main__":
    main()
