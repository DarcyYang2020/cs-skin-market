# -*- coding: utf-8 -*-
"""阶段17 chg30 幅度 walk-forward 样本外验证（2026-08-18，回应③审计#3）。

只验证「可 walk-forward 部分」= train(SPLIT 前) 有样本的 (时期, chg30 幅度桶)。
train 拟合「时期 × chg30 幅度桶」中位数 + 翻正率；test 用 train 参数预测，算 MAE + 方向一致率。
深跌 S3 桶（train 无样本）标注「无样本外能力」，不参与判据。
预注册判据（chg30-prereg.md）：可验证部分 MAE 较「时期×时点」基线降 ≥10%，且方向一致。
输出 data/_exp_stage17_chg30_wf.json。
"""
import json
from collections import defaultdict
from pathlib import Path

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage17_chg30_wf.json"
SPLIT = "2025-08-10"
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


def chg30_bucket(c30):
    if c30 <= -15:
        return 0
    if c30 <= -5:
        return 1
    return 2


def main():
    rows, run_map = load_and_fix()
    S = [(r[0], run_map[r[0]][0], r[2], r[20]) for r in rows if r[20] is not None]
    train = [s for s in S if s[0] < SPLIT]
    test = [s for s in S if s[0] >= SPLIT]

    # 时期×时点基线（train 拟合时期中位数）
    pmed = {}
    for p in range(5):
        v = [s[3] for s in train if s[1] == p]
        if v:
            pmed[p] = median(v)
    gm = median([s[3] for s in train])

    # chg30 幅度桶（train 拟合）
    cell = defaultdict(list)
    for _, p, c30, f in train:
        cell[(p, chg30_bucket(c30))].append(f)
    cell_med = {k: median(v) for k, v in cell.items()}
    cell_win = {k: sum(1 for x in v if x > 0) / len(v) for k, v in cell.items()}

    # 深跌 S3 桶 = (3, 1)：train 有无样本？
    deep_s3_in_train = (3, 1) in cell_med

    out = {"probe": "阶段17 chg30 walk-forward", "split": SPLIT,
           "deep_s3_in_train": deep_s3_in_train, "groups": {}}

    def pred_chg30(p, c30):
        return cell_med.get((p, chg30_bucket(c30)), pmed.get(p, gm))

    # 可验证部分：test 里，train 有样本的桶
    errs_chg30 = []; errs_base = []
    correct_dir_chg30 = 0; correct_dir_base = 0; tot = 0
    for d, p, c30, f in test:
        b = chg30_bucket(c30)
        if (p, b) not in cell_med:
            continue  # train 无样本（如深跌 S3），不参与可验证判据
        pr_c = cell_med[(p, b)]
        pr_b = pmed.get(p, gm)
        errs_chg30.append(abs(pr_c - f))
        errs_base.append(abs(pr_b - f))
        tot += 1
        if (pr_c > 0) == (f > 0):
            correct_dir_chg30 += 1
        if (pr_b > 0) == (f > 0):
            correct_dir_base += 1
    out["verifiable"] = {
        "n_test": tot,
        "mae_chg30": round(sum(errs_chg30) / len(errs_chg30), 2) if errs_chg30 else None,
        "mae_base": round(sum(errs_base) / len(errs_base), 2) if errs_base else None,
        "dir_agree_chg30_pct": round(correct_dir_chg30 / tot * 100, 1) if tot else None,
        "dir_agree_base_pct": round(correct_dir_base / tot * 100, 1) if tot else None,
    }
    # 各时期可验证桶明细
    for p in range(5):
        for b in range(3):
            k = (p, b)
            if k not in cell_med:
                continue
            tsub = [s for s in test if s[1] == p and chg30_bucket(s[2]) == b]
            if len(tsub) < 30:
                continue
            pred_med = cell_med[k]
            act_med = median([s[3] for s in tsub])
            out["groups"][f"{PNAME[p]}-{['<=-15','-15~-5','>-5'][b]}"] = {
                "train_n": len(cell[k]), "test_n": len(tsub),
                "pred_med": round(pred_med, 2), "actual_med": round(act_med, 2),
                "dir_agree": round(sum(1 for s in tsub if (pred_med > 0) == (s[3] > 0)) / len(tsub) * 100, 1),
            }

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(f"深跌 S3 桶在 train 有无样本：{deep_s3_in_train}")
    v = out["verifiable"]
    print(f"可验证部分 test n={v['n_test']}：MAE chg30={v['mae_chg30']} vs 基线={v['mae_base']}")
    print(f"方向一致率：chg30={v['dir_agree_chg30_pct']}% vs 基线={v['dir_agree_base_pct']}%")


if __name__ == "__main__":
    main()
