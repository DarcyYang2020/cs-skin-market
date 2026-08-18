# -*- coding: utf-8 -*-
"""阶段18 P2-B A 模型（逻辑回归）（2026-08-18，预注册）。

P2-B 假说：A 模型（逻辑回归）捕捉「特征交互」，在 walk-forward 样本外超过「时期单因素」B 模型。
目标 = P(fwd14>+10%)（大涨，AS 已证区分度高）；特征 = 时期 one-hot + 市场(mchg30/sent) + 单品(pct/z/th/supply30/chg7/chg3/rs30/no_new_low2/spread_chg5/decay3/volreg)。
模型 = 逻辑回归 L2（批量梯度下降，预注册：lr=0.1, epochs=200, l2=0.001）。
验证 = SPLIT 切分 walk-forward，train 拟合标准化参数 + 权重，test 算 AUC。
预注册判据：A 模型 test AUC ≥ 基线（period 单因素）+0.02。
输出 data/_exp_stage18_p2b.json。
"""
import json
import math
from collections import defaultdict
from pathlib import Path

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage18_p2b.json"
SPLIT = "2025-08-10"
LR, EPOCHS, L2 = 0.1, 200, 0.001
THRESH = 10.0


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


def roc_auc(scores, labels):
    n = len(scores)
    pos = [i for i in range(n) if labels[i] == 1]
    neg = [i for i in range(n) if labels[i] == 0]
    np_, nn = len(pos), len(neg)
    if np_ == 0 or nn == 0:
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
    rs = sum(ranks[i] for i in pos)
    return (rs - np_ * (np_ + 1) / 2.0) / (np_ * nn)


def sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def main():
    rows, run_map = load_and_fix()
    # 特征：date, period, 连续特征 list, fwd14
    # 连续特征列：mchg30(2) sent(5) pct(6) z(7) th(8) supply30(10) chg7(11) chg30(12) rs30(13) chg3(14) no_new_low2(15) decay3(16) spread_chg5(17) volreg(18)
    cont_cols = [2, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18]
    S = []
    for r in rows:
        if r[20] is None:
            continue
        p = run_map[r[0]][0]
        feats = [r[c] if r[c] is not None else 0.0 for c in cont_cols]
        S.append((r[0], p, feats, 1.0 if r[20] > THRESH else 0.0))

    train = [s for s in S if s[0] < SPLIT]
    test = [s for s in S if s[0] >= SPLIT]

    # 标准化参数（train 拟合）
    means = []
    stds = []
    for j in range(len(cont_cols)):
        vals = [s[2][j] for s in train]
        m = sum(vals) / len(vals)
        sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
        means.append(m)
        stds.append(sd if sd > 0 else 1.0)

    def to_x(s):
        onehot = [1.0 if s[1] == p else 0.0 for p in range(5)]
        cont = [(s[2][j] - means[j]) / stds[j] for j in range(len(cont_cols))]
        return onehot + cont

    Xtr = [to_x(s) for s in train]
    ytr = [s[3] for s in train]
    Xte = [to_x(s) for s in test]
    yte = [s[3] for s in test]
    nfeat = len(Xtr[0])

    # 逻辑回归 L2 梯度下降
    w = [0.0] * nfeat
    b = 0.0
    n = len(Xtr)
    for _ in range(EPOCHS):
        gw = [0.0] * nfeat
        gb = 0.0
        for i in range(n):
            z = b + sum(w[j] * Xtr[i][j] for j in range(nfeat))
            err = sigmoid(z) - ytr[i]
            gb += err
            for j in range(nfeat):
                gw[j] += err * Xtr[i][j]
        for j in range(nfeat):
            w[j] -= LR * (gw[j] / n + L2 * w[j])
        b -= LR * (gb / n)

    pred = [sigmoid(b + sum(w[j] * Xte[i][j] for j in range(nfeat))) for i in range(len(Xte))]
    auc_full = roc_auc(pred, yte)

    # 基线：period 单因素（B 模型，条件匹配 + 收缩）
    pcell = defaultdict(list)
    for s in train:
        pcell[s[1]].append(s[3])
    pw = {p: sum(v) / len(v) for p, v in pcell.items()}
    base_pred = [pw.get(s[1], 0.5) for s in test]
    auc_base = roc_auc(base_pred, yte)

    out = {"probe": "阶段18 P2-B A模型逻辑回归", "split": SPLIT, "target": f"fwd14>+{THRESH}%",
           "model": {"lr": LR, "epochs": EPOCHS, "l2": L2, "n_feat": nfeat},
           "auc_base_period": round(auc_base, 4) if auc_base else None,
           "auc_a_model": round(auc_full, 4) if auc_full else None,
           "n_train": len(Xtr), "n_test": len(Xte)}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(f"目标 P(fwd14>+{THRESH}%)，SPLIT={SPLIT}")
    print(f"基线（period 单因素 B 模型）AUC = {out['auc_base_period']}")
    print(f"A 模型（逻辑回归全特征）AUC = {out['auc_a_model']}")
    if auc_full is not None and auc_base is not None:
        d = auc_full - auc_base
        print(f"增量 = {d:+.4f}  -> {'达标(>=+0.02)' if d >= 0.02 else '未达标'}")


if __name__ == "__main__":
    main()
