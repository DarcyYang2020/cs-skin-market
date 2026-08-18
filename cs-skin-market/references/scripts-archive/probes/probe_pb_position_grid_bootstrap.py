#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P-B bootstrap: deep_value 0.10 -> 0.15 (block-free iid resample, 200 draws).

Research-only. Does not overwrite the official replay.
"""
import json
import random
import sys
from datetime import date
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = spec_from_file_location("pb", str(ROOT / "references" / "probe_pb_position_grid.py"))
pb = module_from_spec(_spec)
_spec.loader.exec_module(pb)

OUT = ROOT / "data" / "_exp_position_grid_bootstrap.json"


def pct_quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def main():
    sigs, args = pb.load_aligned_signals()
    rng = random.Random(20260814)
    n = len(sigs)
    draws = 200
    rows = []
    for b in range(draws):
        sample = [rng.choice(sigs) for _ in range(n)]
        base = pb.run_variant(sample, "bootstrap_base", cap=0.8,
                              wstart=args.get("start"), wend=args.get("end"))
        dv = pb.run_variant(pb.with_limits(sample, deep_value=0.15), "bootstrap_dv15", cap=0.8,
                            wstart=args.get("start"), wend=args.get("end"))
        rows.append({
            "total_diff_pp": round(dv.get("total_return_pct", 0.0) - base.get("total_return_pct", 0.0), 3),
            "calmar_diff": round((dv.get("calmar") or 0.0) - (base.get("calmar") or 0.0), 3),
            "maxdd_diff_pp": round(dv.get("max_drawdown_pct", 0.0) - base.get("max_drawdown_pct", 0.0), 3),
        })
    total = [r["total_diff_pp"] for r in rows]
    calmar = [r["calmar_diff"] for r in rows]
    maxdd = [r["maxdd_diff_pp"] for r in rows]
    out = {
        "generated": date.today().isoformat(),
        "method": "iid resample with replacement of aligned signals (n=%d, draws=%d)" % (n, draws),
        "baseline_n": n,
        "seed": 20260814,
        "total_diff_pp": {
            "mean": round(sum(total) / len(total), 3),
            "p_gt_0": round(sum(1 for x in total if x > 0) / len(total), 3),
            "p_lt_0": round(sum(1 for x in total if x < 0) / len(total), 3),
            "q05": round(pct_quantile(total, 0.05), 3),
            "q50": round(pct_quantile(total, 0.50), 3),
            "q95": round(pct_quantile(total, 0.95), 3),
        },
        "calmar_diff": {
            "mean": round(sum(calmar) / len(calmar), 3),
            "p_gt_0": round(sum(1 for x in calmar if x > 0) / len(calmar), 3),
            "p_lt_0": round(sum(1 for x in calmar if x < 0) / len(calmar), 3),
            "q05": round(pct_quantile(calmar, 0.05), 3),
            "q50": round(pct_quantile(calmar, 0.50), 3),
            "q95": round(pct_quantile(calmar, 0.95), 3),
        },
        "maxdd_diff_pp": {
            "mean": round(sum(maxdd) / len(maxdd), 3),
            "p_gt_0": round(sum(1 for x in maxdd if x > 0) / len(maxdd), 3),
            "p_lt_0": round(sum(1 for x in maxdd if x < 0) / len(maxdd), 3),
            "q05": round(pct_quantile(maxdd, 0.05), 3),
            "q50": round(pct_quantile(maxdd, 0.50), 3),
            "q95": round(pct_quantile(maxdd, 0.95), 3),
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
