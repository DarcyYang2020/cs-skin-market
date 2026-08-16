# -*- coding: utf-8 -*-
"""v69 历史扩窗口重放：对 replay_cycle_win.db 跑 v2-T9 引擎全窗口（2023-11-17~2026-08-05）。

只读，输出 data/_exp_cycle_replay_2026.json。args.engine 标 v2-T9（数据修正同 v2-T9）。
窗口：START=2023-11-17（market_index 起点），END=2026-08-05（与生产回放同终点）。
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = os.environ.get("CS_MODEL_DB") or str(ROOT / "data" / "replay_cycle_win.db")

sys.path.insert(0, str(ROOT))
import importlib.util

_ARCHIVED_RUNNER = ROOT / "references" / "scripts-archive" / "run_item_backtest.py"
spec = importlib.util.spec_from_file_location("rib", str(_ARCHIVED_RUNNER))
rib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rib)

from pipeline.backtest_common import build_market_context  # noqa: E402
from pipeline import db  # noqa: E402

OUT = ROOT / "data" / os.environ.get("CS_ENGINE_REPLAY_OUT", "_exp_cycle_replay_2026.json")


def pool_a_items():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT i.id, i.name, MIN(p.date) first_date
           FROM items i JOIN price_history p ON p.item_id = i.id
           GROUP BY i.id HAVING first_date <= '2025-08-10'""").fetchall()
    conn.close()
    return {r["id"]: r["name"] for r in rows if r["name"] not in rib.EXCLUDED_ITEMS}


def main():
    START, END, WARMUP = "2023-11-17", "2026-08-05", 30
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
            print(f"[{n_i}/{len(items)}] {iname[:26]:28s} days={r.get('days')} sig={len(sigs)} "
                  f"elapsed={str(datetime.now()-t0)[:8]}", flush=True)

    sigs_out = [s for r in results for s in r.get("signals", []) if s.get("fwd14") is not None]
    rows, agg = rib.summarize(results)
    agg["signals"] = len(sigs_out)
    switches = ",".join("%s=1" % k for k in sorted(os.environ)
                        if k.startswith("CS_ENGINE_") and os.environ[k] == "1")
    out = {"args": {"start": START, "end": END, "warmup": WARMUP,
                    "pool": "A(96\u8001\u54c1,3\u5e74\u7a97\u53e3)", "db": os.environ["CS_MODEL_DB"],
                    "engine": "v2-T10 (DECISION-6/7 + liquidity_filtered + csQAQ period=1095 NULL+0gap backfill + O1 仓位网格 supply_accum0.15/deep_value0.20 + cycle window)",
                    "env_switches": switches or None},
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "aggregate": agg, "per_item": rows, "signals": sigs_out}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("signals:", len(sigs_out), "| saved", OUT, flush=True)
    print("by signal_type:", dict(Counter(s.get("signal_type") for s in sigs_out)), flush=True)


if __name__ == "__main__":
    main()
