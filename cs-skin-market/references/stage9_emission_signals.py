# -*- coding: utf-8 -*-
"""阶段9：发射侧逐信号明细（2026-08-18，回应③审计复审路径①②）。

审计：三份产物均无 signals[] 数组，a2_emission 复算 added_total=0。本脚本输出
「族开 vs 基线」的逐信号明细——每个 item-day 的期望值（机制开 vs 时期先验基线）+ 实际 fwd，
供审计独立复算排序能力。fit 段（<SPLIT）拟合机制，val 段（>=SPLIT）用 fit 参数输出逐信号。
输出 data/_exp_stage9_emission_signals.json（signals 数组 = val 段逐信号明细）。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage9_emission_signals.json"
K = 20
SPLIT = "2025-08-10"


def period_code(c180, c30):
    if c30 <= -15:
        return 0
    if c180 > 0:
        return 1 if c30 > 0 else 2
    return 3 if c30 <= 0 else 4


def load_and_fix():
    d = json.load(open(SRC, encoding="utf-8"))
    rows = d["rows"]
    clean = [r for r in rows if r[3] != 0.0]
    by_date = {}
    for r in clean:
        by_date.setdefault(r[0], (r[2], r[3]))
    run_map = {}
    prev = None
    run = 0
    for dt in sorted(by_date):
        c30, c180 = by_date[dt]
        b = period_code(c180, c30)
        run = run + 1 if b == prev else 1
        prev = b
        run_map[dt] = (b, run)
    return clean, run_map


def median(v):
    v = sorted(v)
    return v[len(v) // 2]


def zparams(vals):
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
    return m, (sd if sd > 0 else 1.0)


def main():
    rows, run_map = load_and_fix()
    # (date, item_id, period, day, z, th, supply30, chg7, chg3, fwd14)
    S = []
    for r in rows:
        p, day = run_map[r[0]]
        S.append((r[0], r[1], p, day, r[7], r[8], r[10], r[11], r[14], r[20]))

    train = [s for s in S if s[0] < SPLIT and s[9] is not None]
    test = [s for s in S if s[0] >= SPLIT and s[9] is not None]

    gm = median([s[9] for s in train])
    pm = {}
    for p in range(5):
        v = [s[9] for s in train if s[2] == p]
        if v:
            lam = len(v) / (len(v) + K)
            pm[p] = lam * median(v) + (1 - lam) * gm
    zp = {}
    for p in range(5):
        sub = [s for s in train if s[2] == p]
        if len(sub) < 30:
            sub = train
        zp[p] = {}
        for key, col in [("z", 4), ("th", 5), ("s30", 6), ("c7", 7), ("c3", 8)]:
            vals = [s[col] for s in sub if s[col] is not None]
            if vals:
                zp[p][key] = zparams(vals)

    def score(p, s):
        def z(x, key):
            if x is None:
                return 0.0
            m, sd = zp[p][key]
            return (x - m) / sd
        if p == 0:
            return -(z(s[7], "c7") + z(s[8], "c3") + z(s[4], "z")) / 3
        if p in (1, 2):
            return -z(s[6], "s30")
        if p == 3:
            return z(s[5], "th") - z(s[6], "s30")
        return -z(s[6], "s30")

    trait_buckets = {}
    for p in range(5):
        sub = [s for s in train if s[2] == p and s[4] is not None and s[6] is not None and s[7] is not None and s[8] is not None]
        if len(sub) < 30:
            continue
        sc = [score(p, s) for s in sub]
        ssc = sorted(sc)
        thr1, thr2 = ssc[len(sc) // 3], ssc[2 * len(sc) // 3]
        buckets = defaultdict(list)
        for i, s in enumerate(sub):
            b = 0 if sc[i] > thr2 else (1 if sc[i] > thr1 else 2)
            buckets[b].append(s[9])
        p_med = median([s[9] for s in sub])
        trait_buckets[p] = {"thr1": thr1, "thr2": thr2, "med": {}}
        for b, v in buckets.items():
            lam = len(v) / (len(v) + K)
            trait_buckets[p]["med"][b] = lam * median(v) + (1 - lam) * p_med

    def pred_on(s):
        base = pm.get(s[2], gm)
        if s[2] not in trait_buckets or s[4] is None or s[6] is None or s[7] is None or s[8] is None:
            return base
        tb = trait_buckets[s[2]]
        sc = score(s[2], s)
        b = 0 if sc > tb["thr2"] else (1 if sc > tb["thr1"] else 2)
        return tb["med"].get(b, base)

    signals = []
    for s in test:
        signals.append({
            "date": s[0], "item_id": s[1], "period": s[2], "period_days": s[3],
            "trait_score": round(score(s[2], s), 4),
            "pred_base": round(pm.get(s[2], gm), 2),
            "pred_on": round(pred_on(s), 2),
            "fwd14_actual": round(s[9], 2),
        })

    out = {"probe": "阶段9 发射侧逐信号明细", "split": SPLIT, "shrink_k": K,
           "n_signals": len(signals), "signals": signals}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("saved", OUT, "n_signals=", len(signals))


if __name__ == "__main__":
    main()
