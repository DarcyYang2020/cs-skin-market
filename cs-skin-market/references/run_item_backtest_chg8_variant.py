# -*- coding: utf-8 -*-
"""P-1（T4）变体回放：CS_ENGINE_SUPPLY_ACCUM_CHG8_CAP=1 的 chg8 门控全窗口回放。

与 references/run_item_backtest_full.py 同构（同池/同窗口/同 warmup），
仅输出到 data/_exp_supply_chg8_cap_ab.json，不覆盖标准产物。
基线对比：data/item_backtest_full_2025.json（同数据回放，本脚本启动前已备份）。
"""
import os
os.environ["CS_ENGINE_SUPPLY_ACCUM_CHG8_CAP"] = "1"
import sys, json
from datetime import datetime
from pathlib import Path
sys.path.insert(0, ".")
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

OUT = "data/_exp_supply_chg8_cap_ab.json"

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
        if n_i % 20 == 0 or sigs:
            print(f"[{n_i}/{len(items)}] {iname[:28]:30s} days={r.get('days')} sig={len(sigs)} "
                  f"elapsed={str(datetime.now()-t0)[:8]}", flush=True)
    sigs_out = [s for r in results for s in r.get("signals", []) if s.get("fwd14") is not None]
    rows, agg = rib.summarize(results)
    out = {"args": {"start": START, "end": END, "warmup": WARMUP, "pool": "A(98老品,365天窗口)",
                    "engine_switch": "CS_ENGINE_SUPPLY_ACCUM_CHG8_CAP=1"},
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "aggregate": agg, "per_item": rows, "signals": sigs_out}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("signals:", len(sigs_out), "| saved", OUT, flush=True)
    from collections import Counter
    c = Counter(s.get("signal_type") for s in sigs_out)
    print("by signal_type:", dict(c), flush=True)

if __name__ == "__main__":
    main()
