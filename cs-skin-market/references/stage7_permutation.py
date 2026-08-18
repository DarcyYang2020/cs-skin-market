# -*- coding: utf-8 -*-
"""阶段7：最终机制置换检验（2026-08-18，回应③审计驳回）。

审计指出：数据层 Top-Bottom 差仅作初筛，P期2事件贯穿、S3/S4 各仅2独立切点，
须补「最终机制置换」——打乱单品特性标签（保持时期+fwd14），看真实 Top-Bottom 差
是否显著高于随机特性，排除「靠2事件/切点巧合」。
对每个时期：真实特性分数 Top20% vs Bottom20% 中位数差 D_real，打乱特性 500 次得 D_perm 分布，
p = P(D_perm >= D_real)。
输出 data/_exp_stage7_permutation.json。
"""
import json
import random
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage7_permutation.json"
PNAME = {0: "P恐慌", 1: "S1牛市", 2: "S2回调", 3: "S3阴跌", 4: "S4反弹"}


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


def zscore(vals):
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
    return [(x - m) / sd if sd > 0 else 0.0 for x in vals]


def item_score(p, r):
    if p == 0:
        return -(r["c7"] + r["c3"] + r["z"]) / 3
    if p in (1, 2):
        return -r["s30"]
    if p == 3:
        return r["th"] - r["s30"]
    return -r["s30"]


def top_bot_diff(recs, scores):
    order = sorted(range(len(recs)), key=lambda i: scores[i], reverse=True)
    k = max(1, len(order) // 5)
    top = [recs[i]["fwd14"] for i in order[:k]]
    bot = [recs[i]["fwd14"] for i in order[-k:]]
    return median(top) - median(bot)


def main():
    rows, run_map = load_and_fix()
    # 构建每时期的记录 + 标准化特征
    periods = defaultdict(list)
    for r in rows:
        p = run_map[r[0]][0]
        periods[p].append(r)
    out = {"probe": "阶段7 置换检验", "n_perm": 500, "seed": 42, "seed_scheme": "42+p(时期码)",
           "p_method": "p = P(D_perm >= D_real) = hits/n_perm（打乱特性标签，保持时期+fwd14；非地板值时取 hits/n_perm）",
           "periods": {}}
    for p in range(5):
        sub = [r for r in periods[p] if r[7] is not None and r[8] is not None
               and r[10] is not None and r[11] is not None and r[14] is not None and r[20] is not None]
        if len(sub) < 100:
            continue
        c7 = zscore([r[11] for r in sub]); c3 = zscore([r[14] for r in sub]); zz = zscore([r[7] for r in sub])
        s30 = zscore([r[10] for r in sub]); th = zscore([r[8] for r in sub])
        recs = [{"fwd14": r[20], "c7": c7[i], "c3": c3[i], "z": zz[i], "s30": s30[i], "th": th[i]}
                for i, r in enumerate(sub)]
        real_scores = [item_score(p, rec) for rec in recs]
        D_real = top_bot_diff(recs, real_scores)
        random.seed(42 + p)
        D_perm = []
        for _ in range(500):
            shuffled = real_scores[:]
            random.shuffle(shuffled)
            D_perm.append(top_bot_diff(recs, shuffled))
        pval = sum(1 for d in D_perm if d >= D_real) / len(D_perm)
        out["periods"][PNAME[p]] = {
            "n": len(recs), "D_real": round(D_real, 2),
            "D_perm_median": round(median(D_perm), 2),
            "D_perm_p90": round(sorted(D_perm)[450], 2),
            "p": round(pval, 4),
        }
        print(f"{PNAME[p]:10s} n={len(recs)} D_real={D_real:+.2f} D_perm_median={median(D_perm):+.2f} p={pval:.4f}")

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)


if __name__ == "__main__":
    main()
