import json
import math
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from pipeline.backtest_common import approx_sentiment
from pipeline.market_macro import greedy_to_sentiment

DB = BASE / "data" / "market.db"
OUT = BASE / "data" / "_exp_sentiment_calibration_stage0.json"


def pearson(xs, ys):
    if not xs or len(xs) != len(ys):
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def spearman(xs, ys):
    if not xs or len(xs) != len(ys):
        return None

    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    return pearson(ranks(xs), ranks(ys))


def threshold_table(real, approx, cut):
    t = {"real_pos": 0, "real_neg": 0, "approx_pos": 0, "approx_neg": 0, "agree": 0, "n": len(real)}
    for r, p in zip(real, approx):
        rp = r >= cut
        pp = p >= cut
        t["real_pos"] += rp
        t["real_neg"] += not rp
        t["approx_pos"] += pp
        t["approx_neg"] += not pp
        t["agree"] += (rp == pp)
    t["agree_pct"] = round(t["agree"] / t["n"] * 100, 1) if t["n"] else None
    return t


def main():
    con = sqlite3.connect(DB)
    macro = con.execute("SELECT date, greedy_index FROM macro_history WHERE greedy_index IS NOT NULL ORDER BY date").fetchall()
    market = con.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    con.close()

    dates = [r[0] for r in market]
    values = [r[1] for r in market]
    idx_by_date = {d: i for i, d in enumerate(dates)}

    real_raw = {d: float(v) for d, v in macro}
    real_sent = {d: greedy_to_sentiment(float(v)) for d, v in macro}

    overlap_dates = []
    real_sent_list = []
    real_raw_list = []
    approx_list = []
    for d in sorted(real_raw):
        idx = idx_by_date.get(d)
        if idx is None or idx < 14:
            continue
        overlap_dates.append(d)
        real_sent_list.append(real_sent[d])
        real_raw_list.append(real_raw[d])
        approx_list.append(approx_sentiment(values, idx))

    out = {
        "probe": "sentiment_calibration_stage0",
        "stage": "stage0",
        "generated": "2026-08-14",
        "caveats": [
            "read-only probe: no engine parameters/thresholds changed",
            "real greedy history starts 2026-02-03; replay panic signals before 2026-05 have no real sentiment overlap",
            "approx_sentiment is the price-action proxy used by offline replay, not a production trigger",
            "threshold agreement is descriptive only and does not change the production panic gate",
        ],
        "real_sentiment": {
            "n_days": len(real_raw),
            "date_range": [min(real_raw), max(real_raw)],
            "sentiment_values": dict(Counter(real_sent.values())),
            "sent_ge75_days": sum(1 for v in real_sent.values() if v >= 75),
            "sent_ge70_days": sum(1 for v in real_sent.values() if v >= 70),
        },
        "overlap": {
            "n_days": len(overlap_dates),
            "date_range": [overlap_dates[0], overlap_dates[-1]] if overlap_dates else None,
            "pearson_sent_vs_approx": round(pearson(real_sent_list, approx_list), 3) if real_sent_list else None,
            "spearman_sent_vs_approx": round(spearman(real_sent_list, approx_list), 3) if real_sent_list else None,
            "pearson_raw_vs_approx": round(pearson(real_raw_list, approx_list), 3) if real_raw_list else None,
            "spearman_raw_vs_approx": round(spearman(real_raw_list, approx_list), 3) if real_raw_list else None,
            "mae_sent_vs_approx": round(statistics.mean([abs(r - p) for r, p in zip(real_sent_list, approx_list)]), 2) if real_sent_list else None,
            "bias_real_minus_approx": round(statistics.mean([r - p for r, p in zip(real_sent_list, approx_list)]), 2) if real_sent_list else None,
            "threshold_50": threshold_table(real_sent_list, approx_list, 50),
            "threshold_70": threshold_table(real_sent_list, approx_list, 70),
            "threshold_75": threshold_table(real_sent_list, approx_list, 75),
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
