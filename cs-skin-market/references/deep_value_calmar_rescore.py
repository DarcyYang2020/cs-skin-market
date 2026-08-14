# -*- coding: utf-8 -*-
"""Deep-value position-limit Calmar re-score (2026-08-14, read-only).

Reads existing _exp_family_cap_sensitivity.json and re-scores the deep_value scaling
grid under the new north-star metric (expectancy + Calmar/maxDD) instead of raw return.
Pre-registers a formal A2 gate: deep_value family needs >=30 closed trades before a
position-limit change can be considered for production.
Writes data/_exp_deep_value_calmar_rescore.json. No engine/param changes.
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "data" / "_exp_family_cap_sensitivity.json"
OUT = BASE / "data" / "_exp_deep_value_calmar_rescore.json"

KEYS = ["baseline_x1.0", "deep_x0.5", "deep_x1.5", "deep_x2.0"]


def annualized(total_pct, days):
    if days <= 0:
        return None
    growth = 1.0 + total_pct / 100.0
    if growth <= 0:
        return None
    return round((growth ** (365.0 / days) - 1.0) * 100.0, 2)


def score(row):
    total = row.get("total_return_pct")
    dd = row.get("max_drawdown_pct")
    days = row.get("days")
    if total is None or dd is None or dd == 0:
        return None
    ann = annualized(total, days)
    return {
        "total_return_pct": total,
        "max_drawdown_pct": dd,
        "annualized_pct": ann,
        "calmar_rd": round(total / abs(dd), 2),
        "calmar_ann": round(ann / abs(dd), 2) if ann is not None else None,
        "n_trades": row.get("n_trades"),
        "deep_value_closed_n": (row.get("by_family") or {}).get("deep_value", {}).get("n"),
    }


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    grid = data.get("grid") or {}
    rows = {}
    for key in KEYS:
        if key in grid:
            rows[key] = score(grid[key])
    base = rows.get("baseline_x1.0") or {}
    best = None
    for key in ("deep_x0.5", "deep_x1.5", "deep_x2.0"):
        r = rows.get(key)
        if not r or not r.get("calmar_ann"):
            continue
        if best is None or r["calmar_ann"] > best["calmar_ann"]:
            best = {"key": key, **r}
    out = {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
        "note": "New north-star re-score of deep_value position-limit scaling. Calmar_rd=return/drawdown; Calmar_ann=annualized/drawdown. Pre-registered production gate: deep_value closed trades >=30 before any limit change.",
        "baseline": base,
        "grid": rows,
        "best_calmar_variant": best,
        "pre_registered_gate": {
            "metric": "deep_value closed trades >=30",
            "current_closed_n": base.get("deep_value_closed_n"),
            "status": "not_ready" if (base.get("deep_value_closed_n") or 0) < 30 else "ready",
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("written:", OUT)


if __name__ == "__main__":
    main()