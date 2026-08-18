# -*- coding: utf-8 -*-
"""阶段1：单品领先特征 × 时期交互验证（2026-08-18，预注册）。

消费 data/_exp_universe_panel_v2.json。
方法见 item-shortterm-expectancy-design.md：
  - 层次收缩（正确交互结构）：period 层收缩向全局，单品特征层收缩向 period 层（k=20）
  - 多切点 walk-forward + AUC/Brier（决策指标）
  - 预注册配方 H1-H5；H1(period) 为基线，H2-H5 为单品特征交互
输出 data/_exp_stage1_feature_interaction.json。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage1_feature_interaction.json"
K = 20
CUTS = ["2025-04-01", "2025-10-01", "2026-03-01"]

# v2 schema 列索引
# [date, item_id, mchg30, mchg180, mth, sent, pct, z, th, cycle, supply30,
#  chg7, chg30, rs30, chg3, no_new_low2, decay3, spread_chg5, volreg, fwd7, fwd14, fwd30]
FWD14 = 20


def period_code(c180, c30):
    if c30 <= -15:
        return 0
    if c180 > 0:
        return 1 if c30 > 0 else 2
    return 3 if c30 <= 0 else 4


def load_and_fix():
    d = json.load(open(SRC, encoding="utf-8"))
    rows = d["rows"]
    clean = [r for r in rows if r[3] != 0.0]  # 过滤 chg180 哨兵日
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
        run_map[dt] = b
    return clean, run_map


def _bucket(x, ths):
    if x is None:
        return -1
    for i, t in enumerate(ths):
        if x <= t:
            return i
    return len(ths)


# 单品特征分桶（预注册；None → -1 单独桶）
FEATURES = {
    "pct": (6, lambda v: _bucket(v, [15, 30, 70])),
    "z": (7, lambda v: _bucket(v, [-2, -0.5, 0.5])),
    "supply30": (10, lambda v: _bucket(v, [-5, 5])),
    "rs30": (13, lambda v: _bucket(v, [-5, 5, 10])),
    "chg3": (14, lambda v: _bucket(v, [-3, 0, 3])),
    "no_new_low2": (15, lambda v: -1 if v is None else (1 if v > 0 else 0)),
    "decay3": (16, lambda v: _bucket(v, [-1, 1])),
    "spread_chg5": (17, lambda v: _bucket(v, [-2, 0, 2])),
}

# 预注册配方
SCHEMES = [
    ("H1_period", []),
    ("H2_position", ["pct", "z"]),
    ("H3_reversal", ["chg3", "no_new_low2", "decay3"]),
    ("H4_supply_bid", ["supply30", "spread_chg5"]),
    ("H5_relstrength", ["rs30"]),
]


def roc_auc(scores, labels):
    n = len(scores)
    pos = [i for i in range(n) if labels[i] == 1]
    neg = [i for i in range(n) if labels[i] == 0]
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        return None
    order = sorted(range(n), key=lambda i: scores[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and scores[order[j]] == scores[order[i]]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[order[k]] = avg
        i = j
    rank_sum_pos = sum(ranks[i] for i in pos)
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def brier(scores, labels):
    return sum((s - l) ** 2 for s, l in zip(scores, labels)) / len(labels)


def main():
    rows, run_map = load_and_fix()

    # 预计算每条样本的 (date, period, feat_dict, lab14, fwd14)
    samples = []
    for r in rows:
        if r[FWD14] is None:
            continue
        feat = {}
        ok = True
        for name, (col, fn) in FEATURES.items():
            v = r[col]
            feat[name] = fn(v)
        samples.append((r[0], run_map[r[0]], feat, 1.0 if r[FWD14] > 0 else 0.0, r[FWD14]))

    results = []
    for scheme_name, feat_names in SCHEMES:
        per_cut = []
        for cut in CUTS:
            train = [s for s in samples if s[0] < cut]
            test = [s for s in samples if s[0] >= cut]
            # 第一层：period 收缩向全局
            p_agg = defaultdict(list)
            for s in train:
                p_agg[s[1]].append(s[3])
            global_win = sum(s[3] for s in train) / len(train)
            p_win = {}
            for p, v in p_agg.items():
                lam = len(v) / (len(v) + K)
                p_win[p] = lam * (sum(v) / len(v)) + (1 - lam) * global_win
            # 第二层：(period, feat) 收缩向 period
            f_agg = defaultdict(list)
            for s in train:
                key = (s[1],) + tuple(s[2][f] for f in feat_names)
                f_agg[key].append(s[3])
            f_win = {}
            for key, v in f_agg.items():
                lam = len(v) / (len(v) + K)
                p = key[0]
                f_win[key] = lam * (sum(v) / len(v)) + (1 - lam) * p_win[p]

            def predict(s):
                key = (s[1],) + tuple(s[2][f] for f in feat_names)
                return f_win.get(key, p_win.get(s[1], global_win))

            pred = [predict(s) for s in test]
            lab = [s[3] for s in test]
            auc = roc_auc(pred, lab)
            br = brier(pred, lab)
            # 覆盖度：test 中 feat key 命中（非回退到 period）的比例
            hit = sum(1 for s in test if (s[1],) + tuple(s[2][f] for f in feat_names) in f_win)
            per_cut.append({
                "cut": cut, "n_train": len(train), "n_test": len(test),
                "auc14": round(auc, 4) if auc is not None else None,
                "brier": round(br, 4),
                "feat_hit_pct": round(hit / len(test) * 100, 1) if test else None,
            })
        results.append({"scheme": scheme_name, "feats": feat_names, "cuts": per_cut})

    out = {"probe": "阶段1 单品特征×时期交互", "shrink_k": K, "cuts": CUTS,
           "n_samples": len(samples), "schemes": results}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(f"\n{'scheme':20s} | " + " | ".join(f"cut={c[5:10]}" for c in CUTS))
    for s in results:
        line = f"{s['scheme']:20s} | " + " | ".join(f"AUC={c['auc14']}" for c in s["cuts"])
        print(line)
    # 打印 AUC 提升（相对 H1）
    h1 = results[0]["cuts"]
    for s in results[1:]:
        diffs = []
        for c_h1, c_s in zip(h1, s["cuts"]):
            if c_h1["auc14"] is not None and c_s["auc14"] is not None:
                diffs.append(round(c_s["auc14"] - c_h1["auc14"], 4))
        print(f"{s['scheme']:20s}  ΔAUC vs H1 = {diffs}")


if __name__ == "__main__":
    main()
