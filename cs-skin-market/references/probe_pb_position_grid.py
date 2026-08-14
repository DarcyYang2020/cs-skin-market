#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P-B: family position-limit grid on the DECISION-4 aligned signal set.

Reuses b1_risk_backtest_v2.simulate and portfolio_backtest.risk_metrics.
This is a research variant; it does not overwrite the official replay.
"""
import io
import json
import sys
from datetime import date
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OFFICIAL = ROOT / "data" / "item_backtest_full_2025.json"
COVERAGE = ROOT / "data" / "_exp_guard_coverage.json"
OUT = ROOT / "data" / "_exp_position_grid_v2T4.json"

_spec = spec_from_file_location("b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
b1v2 = module_from_spec(_spec)
_spec.loader.exec_module(b1v2)

_spec2 = spec_from_file_location("pfb", str(ROOT / "references" / "portfolio_backtest.py"))
pfb = module_from_spec(_spec2)
_spec2.loader.exec_module(pfb)


def load_aligned_signals():
    official = json.load(io.open(OFFICIAL, encoding="utf-8"))
    cov = json.load(io.open(COVERAGE, encoding="utf-8"))
    aligned = {(s["name"], s["date"]) for s in cov["signals"] if s.get("aligned_action") in ("buy", "oversold_buy")}
    sigs = []
    for s in official.get("signals", []):
        if (s["name"], s["date"]) not in aligned:
            continue
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = b1v2.classify(s.get("action_label"))
        sigs.append({
            "date": date.fromisoformat(s["date"]),
            "item": s["name"],
            "entry": s["entry_price"],
            "limit": s.get("position_limit") or 0.0,
            "fwd": fwd,
            "st": st,
            "prio": b1v2.PRIORITY.get(st, 1),
        })
    return sigs, official.get("args", {})


def with_limits(sigs, panic=None, accumulate=None, deep_value=None):
    out = []
    for s in sigs:
        c = dict(s)
        if s["st"] == "panic" and panic is not None:
            c["limit"] = panic
        elif s["st"] == "accumulate" and accumulate is not None:
            c["limit"] = accumulate
        elif s["st"] == "deep_value" and deep_value is not None:
            c["limit"] = deep_value
        out.append(c)
    return out


def run_variant(sigs, label, cap=0.8, wstart=None, wend=None):
    sim = b1v2.simulate(sigs, cap=cap)
    curve = sim["curve"]
    if wstart is not None:
        curve = [c for c in curve if wstart <= c[0] <= (wend or "9999-12-31")]
    sim = dict(sim, curve=curve)
    m = pfb.risk_metrics(curve)
    closed = sim.get("closed") or []
    m.update({
        "n_signals": len(sigs),
        "n_trades": len(closed),
        "portfolio_win_rate_pct": round(100.0 * sum(1 for x in closed if x > 0) / len(closed), 1) if closed else None,
        "avg_trade_pct": round(sum(closed) / len(closed) * 100, 2) if closed else None,
        "max_position": round(sim["max_pos"], 3),
        "rejected_cap": sim["rejected_cap"],
        "label": label,
    })
    return m


def main():
    sigs, args = load_aligned_signals()
    wstart = args.get("start")
    wend = args.get("end")
    variants = {}
    variants["baseline"] = run_variant(sigs, "baseline", cap=0.8, wstart=wstart, wend=wend)
    for p in (0.25, 0.35):
        variants[f"panic_{p}"] = run_variant(with_limits(sigs, panic=p), f"panic={p}", cap=0.8, wstart=wstart, wend=wend)
    for a in (0.15, 0.20):
        variants[f"accumulate_{a}"] = run_variant(with_limits(sigs, accumulate=a), f"accumulate={a}", cap=0.8, wstart=wstart, wend=wend)
    variants["deep_value_0.15"] = run_variant(with_limits(sigs, deep_value=0.15), "deep_value=0.15", cap=0.8, wstart=wstart, wend=wend)
    out = {
        "generated": date.today().isoformat(),
        "baseline_n": len(sigs),
        "variants": variants,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in variants.items():
        print("%s total=%s ann=%s maxDD=%s calmar=%s win=%s n=%s maxPos=%s rejCap=%s" % (
            k, v.get("total_return_pct"), v.get("ann_return_pct"), v.get("max_drawdown_pct"),
            v.get("calmar"), v.get("portfolio_win_rate_pct"), v.get("n_trades"), v.get("max_position"), v.get("rejected_cap")))
    print("wrote", OUT)


if __name__ == "__main__":
    main()