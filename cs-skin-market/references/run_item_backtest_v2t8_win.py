# -*- coding: utf-8 -*-
"""True v2-T8 engine replay against data/replay_v2t6_win.db.

Read-only with respect to the official product: writes to
data/_exp_v2t8_win_replay.json, never touches data/item_backtest_full_2025.json.
"""
import os, sys, json
from pathlib import Path
from datetime import datetime
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = os.environ.get("CS_MODEL_DB") or str(ROOT / "data" / "replay_v2t6_win.db")

sys.path.insert(0, str(ROOT))
import importlib.util

_ARCHIVED_RUNNER = ROOT / "references" / "scripts-archive" / "run_item_backtest.py"
spec = importlib.util.spec_from_file_location("rib", str(_ARCHIVED_RUNNER))
rib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rib)

from pipeline.backtest_common import build_market_context
from pipeline import db

def pool_a_items():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT i.id, i.name, MIN(p.date) first_date
           FROM items i JOIN price_history p ON p.item_id = i.id
           GROUP BY i.id HAVING first_date <= '2025-08-10'""").fetchall()
    conn.close()
    return {r["id"]: r["name"] for r in rows if r["name"] not in rib.EXCLUDED_ITEMS}

def main():
    START, END, WARMUP = "2025-08-10", "2026-08-05", 30
    rib.patch_sentiment(50.0)
    market_ctx = build_market_context(START, end=END)
    print("market ctx dates:", len(market_ctx), flush=True)
    items = pool_a_items()
    print("pool A items:", len(items), flush=True)
    results = []
    t0 = datetime.now()
    for n_i, (iid, iname) in enumerate(sorted(items.items()), 1):
        r = rib.backtest_item(iid, iname, START, END, WARMUP, market_ctx, cost=0.02)
        results.append(r)
        sigs = [s for s in r.get("signals", []) if s.get("fwd14") is not None]
        if n_i % 10 == 0 or sigs:
            print(f"[{n_i}/{len(items)}] {iname[:28]:30s} days={r.get('days')} sig={len(sigs)} "
                  f"elapsed={str(datetime.now()-t0)[:8]}", flush=True)
    sigs_out = [s for r in results for s in r.get("signals", []) if s.get("fwd14") is not None]
    rows, agg = rib.summarize(results)
    out = {"args": {"start": START, "end": END, "warmup": WARMUP,
                    "pool": "A(98\u8001\u54c1,365\u5929\u7a97\u53e3)", "db": os.environ["CS_MODEL_DB"],
                    "engine": "v2-T8 (DECISION-6 missing/zero + DECISION-7 below_floor + accumulation liquidity_filtered)"},
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "aggregate": agg, "per_item": rows, "signals": sigs_out}
    with open(ROOT / "data" / os.environ.get("V2T8_OUT", "_exp_v2t8_win_replay.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("signals:", len(sigs_out), "| saved", os.environ.get("V2T7_OUT", "data/_exp_v2t8_win_replay.json"), flush=True)
    print("by signal_type:", dict(Counter(s.get("signal_type") for s in sigs_out)), flush=True)

if __name__ == "__main__":
    main()