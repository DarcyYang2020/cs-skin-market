#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical Calmar/maxDD standard for strategy-level reports.

Standard: b1_risk_backtest_v2.simulate + portfolio_backtest.risk_metrics,
window = replay args start/end, cap=0.8, hold21, 2% cost, priority admission.
This is the single ruler for benchmark_compare and P-B position-grid reports.
Exit-rule A2 keeps its own longer horizon but uses the same portfolio engine fixes.
"""
import io
import json
import sys
from datetime import date
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = spec_from_file_location("b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
b1v2 = module_from_spec(_spec)
_spec.loader.exec_module(b1v2)

_spec2 = spec_from_file_location("pfb", str(ROOT / "references" / "portfolio_backtest.py"))
pfb = module_from_spec(_spec2)
_spec2.loader.exec_module(pfb)

OFFICIAL = ROOT / "data" / "item_backtest_full_2025.json"
COVERAGE = ROOT / "data" / "_exp_guard_coverage.json"
OUT = ROOT / "data" / "_exp_calmar_standard.json"


def official_signals():
    d = json.load(io.open(OFFICIAL, encoding="utf-8"))
    sigs = []
    for s in d.get("signals", []):
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = b1v2.classify(s.get("action_label"))
        sigs.append({
            "date": date.fromisoformat(s["date"]), "item": s["name"],
            "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
            "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1),
        })
    return sigs, d.get("args", {})


def aligned_signals():
    official, args = official_signals()
    cov = json.load(io.open(COVERAGE, encoding="utf-8"))
    keep = {(s["name"], s["date"]) for s in cov.get("signals", []) if s.get("aligned_action") in ("buy", "oversold_buy")}
    sigs = [s for s in official if (s["item"], s["date"].isoformat()) in keep]
    return sigs, args


def metrics(sigs, args):
    sim = b1v2.simulate(sigs, cap=0.8)
    curve = sim["curve"]
    wstart = args.get("start")
    wend = args.get("end")
    if wstart:
        curve = [c for c in curve if wstart <= c[0] <= (wend or "9999-12-31")]
    m = pfb.risk_metrics(curve)
    closed = sim.get("closed") or []
    m.update({
        "n_signals": len(sigs),
        "n_trades": len(closed),
        "portfolio_win_rate_pct": round(100.0 * sum(1 for x in closed if x > 0) / len(closed), 1) if closed else None,
    })
    return m


def main():
    off, args = official_signals()
    al, _ = aligned_signals()
    deep = [dict(s, limit=0.15) if s["st"] == "deep_value" else s for s in al]
    out = {
        "generated": date.today().isoformat(),
        "standard": "b1_risk_backtest_v2.simulate + portfolio_backtest.risk_metrics; cap=0.8, hold21, cost=2%, priority admission; window=replay args.start~end",
        "variants": {
            "official_317_v2T4": metrics(off, args),
            "aligned_290_v2T4": metrics(al, args),
            "aligned_290_deep_value_0.15": metrics(deep, args),
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
