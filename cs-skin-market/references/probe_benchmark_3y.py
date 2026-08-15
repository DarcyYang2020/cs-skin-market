# -*- coding: utf-8 -*-
"""3 年基准对照（只读）：回放源换 cycle 186，三腿三数 + 年度 maxDD 拆解。

口径唯一变量 = 回放源 cycle 186（DB 指针 replay_cycle_win.db 3 年日线）。
"""
import os
import sys
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark_compare as bc  # noqa: E402

CYCLE = ROOT / "data" / "_exp_cycle_replay_2026.json"
OUT = ROOT / "data" / "_exp_benchmark_3y.json"


def annual_maxdd(curve):
    years = defaultdict(list)
    for d, v in curve:
        years[d[:4]].append((d, v))
    out = {}
    for y, pts in sorted(years.items()):
        if len(pts) < 2:
            continue
        peak = pts[0][1]
        mdd = 0.0
        for _, v in pts:
            peak = max(peak, v)
            mdd = min(mdd, (v / peak - 1) * 100 if peak else 0.0)
        out[y] = round(mdd, 2)
    return out


def main():
    sigs, args = bc.load_signals(CYCLE)
    sim = bc.b1v2.simulate(sigs, cap=0.8)
    strat_curve = [(c[0], c[2]) for c in sim["curve"]]
    names = sorted({s["item"] for s in sigs})
    idmap = bc.id_by_name(names)
    prices = bc.price_series(list(idmap.keys()))
    mkt = bc.market_series()
    full_start = date.fromisoformat(args.get("start", "2023-11-17"))
    full_end = date.fromisoformat(args.get("end", "2026-08-05"))

    strat_m = bc.metrics(strat_curve)
    pool_curve = bc.buy_hold(prices, full_start, full_end)
    pool_m = bc.metrics(pool_curve)
    mkt_curve = bc.ffill_curve(mkt, full_start, full_end)
    mkt_m = bc.metrics(mkt_curve)

    ann = {"strategy": annual_maxdd(strat_curve),
           "pool_buy_hold": annual_maxdd(pool_curve),
           "market_index": annual_maxdd(mkt_curve)}

    out = {"baseline": "CYCLE-3Y", "signals": len(sigs),
           "window": [full_start.isoformat(), full_end.isoformat()],
           "legs": {"strategy": strat_m, "pool_buy_hold": pool_m, "market_index": mkt_m},
           "annual_maxdd": ann}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== CYCLE-3Y 三腿三数（%s ~ %s）===" % (full_start, full_end))
    for leg, m in out["legs"].items():
        print(f"  {leg:16s} total={m['total_return_pct']:>9.2f}%  maxDD={m['max_drawdown_pct']:>8.2f}%  ann={m['annualized_pct']}")
    print("=== 年度 maxDD 拆解 ===")
    for leg, a in ann.items():
        print(f"  {leg:16s} {json.dumps(a, ensure_ascii=False)}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
