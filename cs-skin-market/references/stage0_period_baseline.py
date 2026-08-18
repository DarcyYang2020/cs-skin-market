# -*- coding: utf-8 -*-
"""阶段 0：period / period+period_days 单因素 AUC 基线（2026-08-18，预注册）。

消费 data/_exp_universe_panel_v2.json（build_universe_panel_v2.py 产物）。
方法见 item-shortterm-expectancy-design.md 第六节：
  - target 主 = P(fwd14>0)，辅 = P(fwd7>0)
  - 模型 B 条件匹配 + 收缩（k=20），阶段 0 只跑 H1 单因素（period / period+period_days）
  - 多切点 walk-forward（4 切点）+ 决策指标（AUC/Brier/净收益），不用 RMSE
输出 data/_exp_stage0_period_baseline.json。
"""
import json
import math
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage0_period_baseline.json"
K = 20

# 多切点 walk-forward（train 须覆盖多时期；chg180 自 2024-05 起可算，
# 故切点不早于 2025-04，确保每段 train ≥ 11 个月、覆盖 ≥3 时期）
CUTS = ["2025-04-01", "2025-10-01", "2026-03-01"]

# v2 schema 列索引
# [date, item_id, mchg30, mchg180, mth, sent, pct, z, th, cycle, supply30,
#  chg7, chg30, rs30, chg3, no_new_low2, decay3, spread_chg5, volreg, fwd7, fwd14, fwd30]
FWD7, FWD14 = 19, 20


def period_code(c180, c30):
    """state_bucket → 0-4（P/S1/S2/S3/S4），与 market_context.state_bucket 同源。"""
    if c30 <= -15:
        return 0
    if c180 > 0:
        return 1 if c30 > 0 else 2
    return 3 if c30 <= 0 else 4


def load_and_fix():
    d = json.load(open(SRC, encoding="utf-8"))
    rows = d["rows"]
    # 过滤 chg180 哨兵退化日（mchg180==0.0）
    clean = [r for r in rows if r[3] != 0.0]
    # 重算 period/period_days（date -> (period, run)）
    by_date = {}
    for r in clean:
        by_date.setdefault(r[0], (r[2], r[3]))  # (mchg30, mchg180)
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


def period_days_bucket(pd):
    return 0 if pd <= 7 else (1 if pd <= 14 else (2 if pd <= 30 else 3))


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
    results = []

    # 两个基线方案
    # period: 只用 period 桶；period_days: period × period_days 桶
    schemes = [
        ("period", lambda r, pd: (pd[0],)),
        ("period+period_days", lambda r, pd: (pd[0], period_days_bucket(pd[1]))),
    ]

    for scheme_name, keyfn in schemes:
        per_cut = []
        for cut in CUTS:
            # 每条样本附 (date, period, period_days, fwd14, fwd7)
            train = []
            test = []
            for r in rows:
                if r[FWD14] is None:
                    continue
                pd = run_map[r[0]]
                lab14 = 1.0 if r[FWD14] > 0 else 0.0
                if r[0] < cut:
                    train.append((keyfn(r, pd), r[FWD14], lab14, r[FWD7]))
                else:
                    test.append((keyfn(r, pd), r[FWD14], lab14, r[FWD7]))
            if not train or not test:
                per_cut.append({"cut": cut, "error": "empty split"})
                continue
            # 拟合：train 上每个 cell 的 win rate（收缩向全局）
            agg = defaultdict(list)
            for key, fwd14, lab14, _ in train:
                agg[key].append(lab14)
            global_win = sum(lab for _, _, lab, _ in train) / len(train)
            cell_win = {}
            for k, v in agg.items():
                lam = len(v) / (len(v) + K)
                cell_win[k] = lam * (sum(v) / len(v)) + (1 - lam) * global_win

            def predict(key):
                return cell_win.get(key, global_win)

            pred = [predict(t[0]) for t in test]
            lab = [t[2] for t in test]
            auc = roc_auc(pred, lab)
            br = brier(pred, lab)
            # 净收益：P>0.5 子集 fwd14 均值 vs 全 test 均值
            sub = [t[1] for t, p in zip(test, pred) if p > 0.5]
            all_fwd = [t[1] for t in test]
            sub_mean = sum(sub) / len(sub) if sub else None
            all_mean = sum(all_fwd) / len(all_fwd)
            # P(fwd7>0) 作为辅指标：同法算 AUC
            test7 = [t for t in test if t[3] is not None]
            if test7:
                lab7 = [1.0 if t[3] > 0 else 0.0 for t in test7]
                pred7 = [predict(t[0]) for t in test7]
                auc7 = roc_auc(pred7, lab7)
            else:
                auc7 = None
            per_cut.append({
                "cut": cut, "n_train": len(train), "n_test": len(test),
                "auc14": round(auc, 4) if auc is not None else None,
                "auc7": round(auc7, 4) if auc7 is not None else None,
                "brier": round(br, 4),
                "sub_p05_mean14": round(sub_mean, 2) if sub_mean is not None else None,
                "sub_p05_n": len(sub),
                "all_mean14": round(all_mean, 2),
                "global_win": round(global_win, 3),
            })
        results.append({"scheme": scheme_name, "cuts": per_cut})

    out = {"probe": "阶段0 period 单因素 AUC 基线", "shrink_k": K,
           "target": "P(fwd14>0) 主 / P(fwd7>0) 辅", "cuts": CUTS,
           "n_clean_rows": len(rows), "schemes": results}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    for s in results:
        print(f"\n=== {s['scheme']} ===")
        for c in s["cuts"]:
            print(f"  cut={c['cut']} n_test={c['n_test']} "
                  f"auc14={c['auc14']} auc7={c['auc7']} brier={c['brier']} "
                  f"sub_mean14={c['sub_p05_mean14']} (n={c['sub_p05_n']}) all_mean14={c['all_mean14']}")


if __name__ == "__main__":
    main()
