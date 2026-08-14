import json
import statistics
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "data" / "item_backtest_full_2025.json"
OUT = BASE / "data" / "_exp_cost_shadow_3pct.json"

DISPLAY_KEYS = ("panic", "deep_value", "accumulate")
LABELS = {"panic": "恐慌族", "deep_value": "深值企稳", "accumulate": "吸筹族"}


def display_key(action_label):
    label = action_label or ""
    if "恐慌" in label:
        return "panic"
    if "深值" in label:
        return "deep_value"
    return "accumulate"


def stats_for(rows, field):
    vals = [r[field] for r in rows if r.get(field) is not None]
    if not vals:
        return {"n": len(rows), "win": None, "avg": None, "median": None}
    return {
        "n": len(vals),
        "win": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
        "avg": round(statistics.mean(vals), 2),
        "median": round(statistics.median(vals), 2),
    }


def main():
    replay = json.load(open(REPLAY, encoding="utf-8"))
    signals = replay.get("signals", [])
    families = {}
    total_shadow = []
    for key in DISPLAY_KEYS:
        sigs = [s for s in signals if display_key(s.get("action_label")) == key]
        net14_3 = [(s.get("fwd14") - 3.0) if s.get("fwd14") is not None else None for s in sigs]
        net30_3 = [(s.get("fwd30") - 3.0) if s.get("fwd30") is not None else None for s in sigs]
        shadow_rows = [dict(s, net14=net14_3[i], net30=net30_3[i]) for i, s in enumerate(sigs)]
        families[key] = {
            "label": LABELS[key],
            "n": len(sigs),
            "win14_3pct": stats_for(shadow_rows, "net14")["win"],
            "avg14_3pct": stats_for(shadow_rows, "net14")["avg"],
            "median14_3pct": stats_for(shadow_rows, "net14")["median"],
            "win30_3pct": stats_for(shadow_rows, "net30")["win"],
            "avg30_3pct": stats_for(shadow_rows, "net30")["avg"],
            "median30_3pct": stats_for(shadow_rows, "net30")["median"],
        }
        total_shadow.extend(shadow_rows)

    overall14 = stats_for(total_shadow, "net14")
    overall30 = stats_for(total_shadow, "net30")
    out = {
        "probe": "cost_shadow_3pct",
        "generated": "2026-08-14",
        "cost_base_pct": 2.0,
        "cost_shadow_pct": 3.0,
        "method": "net14 = fwd14 - 3.0%; net30 = fwd30 - 3.0%; display-only shadow, production 2% cost unchanged",
        "overall": {
            "n": len(total_shadow),
            "win14_3pct": overall14["win"],
            "avg14_3pct": overall14["avg"],
            "median14_3pct": overall14["median"],
            "win30_3pct": overall30["win"],
            "avg30_3pct": overall30["avg"],
            "median30_3pct": overall30["median"],
        },
        "families": families,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
