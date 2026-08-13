# -*- coding: utf-8 -*-
"""chg7 门槛变体回放（研究 1：吸筹族「价格平稳」前提复核，2026-08-12）。

env: CS_ENGINE_SUPPLY_ACCUM_CHG7_CAP=<cap>，abs(chg7)<=cap。
与 references/run_item_backtest_full.py 同构（同池/同窗口/同 warmup），
仅输出到 data/_exp_supply_chg7_cap_<cap>.json，不覆盖标准产物。
基线对照：data/item_backtest_full_2025.json（cap=3，317 信号）。
"""
import os, sys, json
from datetime import datetime
from pathlib import Path
sys.path.insert(0, ".")

CAP = os.environ.get("CS_ENGINE_SUPPLY_ACCUM_CHG7_CAP", "3")
os.environ["CS_ENGINE_SUPPLY_ACCUM_CHG7_CAP"] = CAP

import importlib.util
_ARCHIVED_RUNNER = Path(__file__).resolve().parent / "scripts-archive" / "run_item_backtest.py"
_RUNNER_CANDIDATES = [_ARCHIVED_RUNNER, Path("run_item_backtest.py")]
_RUNNER = next((p for p in _RUNNER_CANDIDATES if p.exists()), None)
if _RUNNER is None:
    raise FileNotFoundError("run_item_backtest.py not found")
spec = importlib.util.spec_from_file_location("rib", str(_RUNNER))
rib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rib)

from pipeline.backtest_common import build_market_context
from pipeline import db

OUT = f"data/_exp_supply_chg7_cap_{CAP}.json"

def pool_a_items():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT i.id, i.name, MIN(p.date) first_date "
        "FROM items i JOIN price_history p ON p.item_id = i.id "
        "GROUP BY i.id HAVING first_date <= ?", (os.environ.get("CS_BT_START", "2025-08-12"),)).fetchall()
    conn.close()
    return {r["id"]: r["name"] for r in rows if r["name"] not in rib.EXCLUDED_ITEMS}

def main():
    START = os.environ.get("CS_BT_START", "2025-08-12")
    END = os.environ.get("CS_BT_END", "2026-08-11")
    WARMUP = int(os.environ.get("CS_BT_WARMUP", "30"))
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
        if n_i % 20 == 0 or sigs:
            print(f"[{n_i}/{len(items)}] {iname[:28]:30s} days={r.get('days')} sig={len(sigs)} "
                  f"elapsed={str(datetime.now()-t0)[:8]}", flush=True)
    sigs_out = [s for r in results for s in r.get("signals", []) if s.get("fwd14") is not None]
    rows, agg = rib.summarize(results)
    out = {"args": {"start": START, "end": END, "warmup": WARMUP, "pool": "A(98老品,365天窗口)",
                    "engine_switch": f"CS_ENGINE_SUPPLY_ACCUM_CHG7_CAP={CAP}"},
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "aggregate": agg, "per_item": rows, "signals": sigs_out}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("signals:", len(sigs_out), "| saved", OUT, flush=True)
    from collections import Counter
    c = Counter(s.get("signal_type") for s in sigs_out)
    print("by signal_type:", dict(c), flush=True)
    acc = [s for s in sigs_out if s.get("signal_type") == "supply_accum"]
    if acc:
        n = len(acc); wins = sum(1 for s in acc if s["net14"] > 0)
        avg = sum(s["net14"] for s in acc) / n
        print(f"supply_accum: n={n} win14={wins/n*100:.1f}% avg14={avg:+.2f}", flush=True)

if __name__ == "__main__":
    main()
