import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "data" / "item_backtest_full_2025.json"
OUT = BASE / "data" / "_exp_signal_family_matrix.json"

FAMILY_LABELS = {
    "accumulate": "周期吸筹",
    "panic": "恐慌共振",
    "base": "低位低估",
}


def median_or_none(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 3) if vals else None


def mean_or_none(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.mean(vals), 3) if vals else None


def win_or_none(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else None


def forward_stats(rows):
    out = {"n": len(rows)}
    if not rows:
        return out
    for field in ("fwd14", "net14", "fwd30", "net30"):
        out[f"win_{field}"] = win_or_none([r.get(field) for r in rows])
        out[f"mean_{field}"] = mean_or_none([r.get(field) for r in rows])
        out[f"median_{field}"] = median_or_none([r.get(field) for r in rows])
    return out


def days_between(a, b):
    return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days


def pair_key(a, b):
    return tuple(sorted((a, b)))


def main():
    replay = json.load(open(REPLAY, encoding="utf-8"))
    sigs = replay.get("signals", [])

    by_item = defaultdict(list)
    for s in sigs:
        by_item[s["name"]].append(s)

    family_counts = {}
    for fam in FAMILY_LABELS:
        rows = [s for s in sigs if s["signal_type"] == fam]
        items = {s["name"] for s in rows}
        family_counts[fam] = {
            "label": FAMILY_LABELS[fam],
            "n_signals": len(rows),
            "n_unique_items": len(items),
        }

    item_fams = {name: set(s["signal_type"] for s in ss) for name, ss in by_item.items()}
    same_item_pairs = Counter()
    date_pairs = Counter()
    by_date = defaultdict(set)
    for name, fams in item_fams.items():
        fams = sorted(fams)
        for i in range(len(fams)):
            for j in range(i + 1, len(fams)):
                same_item_pairs[pair_key(fams[i], fams[j])] += 1
    for s in sigs:
        by_date[s["date"]].add(s["signal_type"])
    for fams in by_date.values():
        fams = sorted(fams)
        for i in range(len(fams)):
            for j in range(i + 1, len(fams)):
                date_pairs[pair_key(fams[i], fams[j])] += 1

    temporal_pairs = {14: Counter(), 30: Counter()}
    for name, ss in by_item.items():
        ss = sorted(ss, key=lambda x: x["date"])
        for i in range(len(ss)):
            for j in range(i + 1, len(ss)):
                gap = days_between(ss[i]["date"], ss[j]["date"])
                if ss[i]["signal_type"] == ss[j]["signal_type"]:
                    continue
                if gap <= 14:
                    temporal_pairs[14][pair_key(ss[i]["signal_type"], ss[j]["signal_type"])] += 1
                if gap <= 30:
                    temporal_pairs[30][pair_key(ss[i]["signal_type"], ss[j]["signal_type"])] += 1

    single_vs_multi = {}
    for fam in FAMILY_LABELS:
        single = [s for s in sigs if s["signal_type"] == fam and len(item_fams[s["name"]]) == 1]
        multi = [s for s in sigs if s["signal_type"] == fam and len(item_fams[s["name"]]) > 1]
        single_vs_multi[fam] = {
            "label": FAMILY_LABELS[fam],
            "single_family_item": forward_stats(single),
            "multi_family_item": forward_stats(multi),
        }

    item_multi_share = {
        "n_items_with_signals": len(by_item),
        "n_single_family_items": sum(1 for f in item_fams.values() if len(f) == 1),
        "n_multi_family_items": sum(1 for f in item_fams.values() if len(f) > 1),
    }

    out = {
        "probe": "signal_family_matrix",
        "stage": "stage0",
        "generated": "2026-08-14",
        "caveats": [
            "read-only probe: no engine parameters/thresholds changed",
            "replay stores only the final family after fixed-priority selection; true same-day multi-family triggers are not observable in this artifact",
            "same-item consecutive signals are >=8 days apart because of the 7-day dedup, so the 14-day window is the closest feasible same-item proxy",
            "forward-return splits are in-sample on the single 2025-11..2026-07 replay window and are not walk-forward evidence",
        ],
        "family_counts": family_counts,
        "item_multi_share": item_multi_share,
        "same_item_family_pairs": {f"{FAMILY_LABELS[k[0]]}×{FAMILY_LABELS[k[1]]}": v for k, v in same_item_pairs.items()},
        "same_date_family_pairs": {f"{FAMILY_LABELS[k[0]]}×{FAMILY_LABELS[k[1]]}": v for k, v in date_pairs.items()},
        "same_item_temporal_pairs_14d": {f"{FAMILY_LABELS[k[0]]}×{FAMILY_LABELS[k[1]]}": v for k, v in temporal_pairs[14].items()},
        "same_item_temporal_pairs_30d": {f"{FAMILY_LABELS[k[0]]}×{FAMILY_LABELS[k[1]]}": v for k, v in temporal_pairs[30].items()},
        "single_vs_multi_family_forward": single_vs_multi,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
