# -*- coding: utf-8 -*-
"""阶段1b：目标重定义（P(fwd14>阈值)）+ 单品特征重跑（2026-08-18，预注册）。

B1 假说（P3）：预测「显著反弹」比「微涨」更有区分度，因为 P(fwd14>0) 的 baseline 51% 接近随机。
先扫描目标阈值（只报告趋势，不据此选阈值），再在预注册主目标 fwd14>+10% 下重跑单品特征 H2-H5，
并做置换检验防「阈值扫描/加维度细分」过拟合。
输出 data/_exp_stage1b_target_redefinition.json。
"""
import json
import random
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage1b_target_redefinition.json"
K = 20
CUTS = ["2025-04-01", "2025-10-01", "2026-03-01"]


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
        run_map[dt] = b
    return clean, run_map


def _bucket(x, ths):
    if x is None:
        return -1
    for i, t in enumerate(ths):
        if x <= t:
            return i
    return len(ths)


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


def fit_predict(train, test, feat_names):
    p_agg = defaultdict(list)
    for s in train:
        p_agg[s[1]].append(s[3])
    gw = sum(s[3] for s in train) / len(train)
    p_win = {}
    for p, v in p_agg.items():
        lam = len(v) / (len(v) + K)
        p_win[p] = lam * (sum(v) / len(v)) + (1 - lam) * gw
    f_agg = defaultdict(list)
    for s in train:
        f_agg[(s[1],) + tuple(s[2][f] for f in feat_names)].append(s[3])
    f_win = {}
    for key, v in f_agg.items():
        lam = len(v) / (len(v) + K)
        f_win[key] = lam * (sum(v) / len(v)) + (1 - lam) * p_win[key[0]]

    def pred(s):
        key = (s[1],) + tuple(s[2][f] for f in feat_names)
        return f_win.get(key, p_win.get(s[1], gw))
    return [pred(s) for s in test], [s[3] for s in test]


def main():
    rows, run_map = load_and_fix()
    # 预构建样本（fwd14 原始值）
    base = []
    for r in rows:
        if r[20] is None:
            continue
        feat = {name: fn(r[col]) for name, (col, fn) in FEATURES.items()}
        base.append((r[0], run_map[r[0]], feat, r[20]))

    # ---- 1. 目标阈值扫描（period 单因素 AUC，只报告趋势）----
    threshold_scan = []
    for th in [5, 10, 15, 20]:
        samples = [(s[0], s[1], 1.0 if s[3] > th else 0.0) for s in base]
        aucs = []
        for cut in CUTS:
            train = [s for s in samples if s[0] < cut]
            test = [s for s in samples if s[0] >= cut]
            agg = defaultdict(list)
            for s in train:
                agg[s[1]].append(s[2])
            gw = sum(s[2] for s in train) / len(train)
            cw = {}
            for p, v in agg.items():
                lam = len(v) / (len(v) + K)
                cw[p] = lam * (sum(v) / len(v)) + (1 - lam) * gw
            pred = [cw.get(s[1], gw) for s in test]
            lab = [s[2] for s in test]
            aucs.append(round(roc_auc(pred, lab), 4))
        threshold_scan.append({"threshold": th, "period_auc": aucs})

    # ---- 2. 主目标 fwd14>+10% 下重跑单品特征 H1-H5 ----
    T = 10
    samples = [(s[0], s[1], s[2], 1.0 if s[3] > T else 0.0) for s in base]
    scheme_results = []
    for scheme_name, feat_names in SCHEMES:
        per_cut = []
        for cut in CUTS:
            train = [s for s in samples if s[0] < cut]
            test = [s for s in samples if s[0] >= cut]
            pred, lab = fit_predict(train, test, feat_names)
            per_cut.append({"cut": cut, "auc": round(roc_auc(pred, lab), 4)})
        scheme_results.append({"scheme": scheme_name, "cuts": per_cut})

    # ---- 3. 置换检验：+10% 目标下 H3（反转）cut2 ----
    cut = "2025-10-01"
    train = [s for s in samples if s[0] < cut]
    test = [s for s in samples if s[0] >= cut]
    feat_names = ["chg3", "no_new_low2", "decay3"]
    pred, lab = fit_predict(train, test, feat_names)
    real_auc = roc_auc(pred, lab)
    random.seed(42)
    perm_aucs = []
    for _ in range(200):
        cols = {f: [s[2][f] for s in test] for f in feat_names}
        for f in feat_names:
            random.shuffle(cols[f])
        test2 = [(s[0], s[1], {f: cols[f][i] for f in feat_names}, s[3]) for i, s in enumerate(test)]
        p2, l2 = fit_predict(train, test2, feat_names)
        a = roc_auc(p2, l2)
        if a is not None:
            perm_aucs.append(a)
    p_val = sum(1 for a in perm_aucs if a >= real_auc) / len(perm_aucs)

    out = {
        "probe": "阶段1b 目标重定义", "shrink_k": K, "cuts": CUTS,
        "threshold_scan": threshold_scan,
        "main_target": T, "schemes": scheme_results,
        "permutation": {"scheme": "H3_reversal", "cut": cut,
                        "real_auc": round(real_auc, 4),
                        "perm_median": round(sorted(perm_aucs)[len(perm_aucs) // 2], 4),
                        "p": round(p_val, 4)},
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print("\n=== 目标阈值扫描（period 单因素 AUC）===")
    for t in threshold_scan:
        print(f"  fwd14>+{t['threshold']:2d}% : AUC = {t['period_auc']}")
    print(f"\n=== 主目标 fwd14>+{T}% 下单品特征 AUC ===")
    for s in scheme_results:
        print(f"  {s['scheme']:20s} : {[c['auc'] for c in s['cuts']]}")
    print(f"\n=== 置换检验（+{T}% H3 cut2）=== real={round(real_auc,4)} "
          f"perm_median={round(sorted(perm_aucs)[len(perm_aucs)//2],4)} p={round(p_val,4)}")


if __name__ == "__main__":
    main()
