# -*- coding: utf-8 -*-
"""阶段16 P3 深跌 S3 单品特性置换（2026-08-18，回应③审计#3「P3 产物未交付」）。

落盘 P3 证据：深跌 S3（chg30<=-5）内部，超跌深度 + 供给收缩 的 Top20%-Bottom20% fwd14 中位数差 + 置换检验。
输出 data/_exp_stage16_p3.json。
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stage2_selection import load_and_fix

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage16_p3.json"
N_PERM = 500
SEED = 42


def median(v):
    v = sorted(v)
    return v[len(v) // 2]


def zscore(vals):
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
    return [(x - m) / sd if sd > 0 else 0.0 for x in vals]


def topbot(fwd, sc):
    order = sorted(range(len(fwd)), key=lambda i: sc[i], reverse=True)
    k = max(1, len(order) // 5)
    top = [fwd[i] for i in order[:k]]
    bot = [fwd[i] for i in order[-k:]]
    return median(top) - median(bot)


def main():
    rows, run_map = load_and_fix()
    sub = [r for r in rows if r[20] is not None and run_map[r[0]] == 3 and r[2] <= -5
           and r[11] is not None and r[14] is not None and r[7] is not None and r[10] is not None]
    c7 = zscore([r[11] for r in sub]); c3 = zscore([r[14] for r in sub]); zz = zscore([r[7] for r in sub])
    s30 = zscore([r[10] for r in sub])
    oversold = [-(c7[i] + c3[i] + zz[i]) / 3 for i in range(len(sub))]
    supply = [-x for x in s30]
    fwd = [r[20] for r in sub]

    out = {"probe": "阶段16 P3 深跌S3单品特性", "n": len(sub), "n_perm": N_PERM, "seed": SEED, "signals": {}}
    rng = random.Random(SEED)
    for name, sc in [("超跌深度", oversold), ("供给收缩", supply)]:
        d_real = topbot(fwd, sc)
        perms = []
        for _ in range(N_PERM):
            sh = sc[:]
            rng.shuffle(sh)
            perms.append(topbot(fwd, sh))
        p = sum(1 for x in perms if x >= d_real) / N_PERM
        out["signals"][name] = {
            "topbot_real": round(d_real, 2),
            "topbot_perm_median": round(median(perms), 2),
            "topbot_perm_p90": round(sorted(perms)[int(N_PERM * 0.9)], 2),
            "p": round(p, 4),
        }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
