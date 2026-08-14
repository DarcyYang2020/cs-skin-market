#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P-F: quantify post-family guard bypass impact (read-only).

Uses the DECISION-4 aligned audit rows plus the official 317-signal feature
fields to evaluate whether family upgrades would have been vetoed by guards
they currently bypass.
"""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COVERAGE = ROOT / "data" / "_exp_guard_coverage.json"
OFFICIAL = ROOT / "data" / "item_backtest_full_2025.json"
OUT = ROOT / "data" / "_exp_guard_bypass.json"


def family_of(sources):
    if "panic_resonance_upgrade" in sources:
        return "panic"
    if "deep_value_stable_market" in sources:
        return "deep_value"
    if "panic_easing_deep_bottom" in sources:
        return "panic_easing"
    if "supply_contraction_accumulation" in sources:
        return "supply_accum"
    if "oversold_buy_exception" in sources:
        return "oversold"
    return "base"


def win(rows):
    n = len(rows)
    wins = sum(1 for r in rows if (r.get("fwd14") or 0) > 0)
    return {
        "n": n,
        "win14_pct": round(100.0 * wins / n, 2) if n else None,
        "avg14_pct": round(sum(r["fwd14"] for r in rows) / n, 3) if n else None,
        "avg_net14_pct": round(sum(r["net14"] for r in rows) / n, 3) if n else None,
    }


def eval_guards(row, off):
    flags = {}
    # market_weak: bypassed by every family upgrade because it is GUARD1.
    flags["market_weak"] = bool((off.get("market_th") is not None and off["market_th"] < 45) and (off.get("mkt_chg30") is not None and off["mkt_chg30"] < 0))
    flags["halfway"] = bool(off.get("pct") is not None and 25 <= off["pct"] <= 40 and (off.get("sentiment") is None or off["sentiment"] < 85))
    # GUARD2 predicates.
    flags["micro_th"] = bool(off.get("micro_th") is not None and off["micro_th"] < 45)
    flags["bid"] = bool(row.get("bid_score") is not None and row["bid_score"] <= 25)
    flags["consecutive"] = bool(off.get("pct") is not None and off["pct"] > 5 and off.get("chg3d") is not None and abs(off["chg3d"]) < 1.5)
    z = off.get("z")
    cycle = off.get("cycle") or "unknown"
    gates = {"accumulation": -0.5, "consolidation": -1.0, "distribution": -1.5, "markup": 0, "unknown": -1.0}
    flags["z_gate"] = bool(z is not None and z > gates.get(cycle, -1.0))
    flags["supply_expansion"] = bool(off.get("supply_change_30d") is not None and off["supply_change_30d"] > 5)
    return flags


def main():
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    official = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    off_map = {(s["name"], s["date"]): s for s in official.get("signals", [])}
    rows = []
    for r in coverage["signals"]:
        if r.get("aligned_action") not in ("buy", "oversold_buy"):
            continue
        off = off_map.get((r["name"], r["date"]))
        if off is None:
            continue
        sources = r.get("deduction_sources") or []
        fam = family_of(sources)
        bypass1 = fam in ("panic", "deep_value", "panic_easing", "supply_accum")
        bypass2 = fam in ("deep_value", "panic_easing", "supply_accum")
        flags = eval_guards(r, off)
        rows.append({
            "name": r["name"],
            "date": r["date"],
            "family": fam,
            "bypass_guard1": bypass1,
            "bypass_guard2": bypass2,
            "guards_would_hit": {k: v for k, v in flags.items() if v},
            "fwd14": r.get("fwd14"),
            "net14": r.get("net14"),
        })
    by_family = {}
    for fam in ("base", "oversold", "panic", "deep_value", "panic_easing", "supply_accum"):
        subset = [r for r in rows if r["family"] == fam]
        by_family[fam] = {
            "all": win(subset),
            "guard1_bypass": win([r for r in subset if r["bypass_guard1"]]),
            "guard2_bypass": win([r for r in subset if r["bypass_guard2"]]),
        }
    hit_counts = Counter()
    hit_outcome = defaultdict(list)
    for r in rows:
        for g in r["guards_would_hit"]:
            hit_counts[g] += 1
            hit_outcome[g].append(r)
    guard_hit = {g: {"count": c, **win(hit_outcome[g])} for g, c in hit_counts.items()}
    agg = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "n": len(rows),
        "family": by_family,
        "guard_would_hit": guard_hit,
        "family_counts": dict(Counter(r["family"] for r in rows)),
    }
    OUT.write_text(json.dumps({"aggregate": agg, "signals": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(agg, ensure_ascii=False, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()