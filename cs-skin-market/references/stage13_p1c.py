# -*- coding: utf-8 -*-
"""阶段13 P1-C 市场特征条件化（chg30 幅度细桶，2026-08-18，预注册）。

P1 细化：时期漂移的根因 = 时期标签太粗（S3 内部好/坏不分）。chg30 是当前可观测的市场特征，
能零滞后区分「深跌(坏) vs 浅跌(好)」。本探针验证：时期先验用「时期 × chg30 幅度」细桶
替代「时期 × 时点」，是否全面提升 MAE（不仅 S3）。
预注册判据：S3 样本外 MAE 从基线 13.24 降 ≥10%，且其他时期不劣化。
输出 data/_exp_stage13_p1c.json。
"""
import json
from collections import defaultdict
from pathlib import Path

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage13_p1c.json"
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
    """chg30 幅度分桶（预注册）。"""
    if c30 <= -15:
        return 0
    if c30 <= -5:
        return 1
    if c30 <= 0:
        return 2
    return 3


def main():
    rows, run_map = load_and_fix()
    S = [(r[0], run_map[r[0]][0], r[2], r[20]) for r in rows if r[20] is not None]
    # S: (date, period, chg30, fwd14)

    out = {"probe": "阶段13 P1-C chg30幅度细桶", "split": SPLIT, "groups": {}}

    # 训练：SPLIT 前拟合「时期 × chg30 桶」中位数
    train = [s for s in S if s[0] < SPLIT]
    cell = defaultdict(list)
    for _, p, c30, f in train:
        cell[(p, chg30_bucket(c30))].append(f)
    cell_med = {k: median(v) for k, v in cell.items()}
    # 全局 + 时期中位数（收缩参照）
    gm = median([f for _, _, _, f in train])
    pmed = {}
    for p in range(5):
        v = [f for _, pp, _, f in train if pp == p]
        if v:
            pmed[p] = median(v)

    # 预测（SPLIT 后，样本外）：cell 命中用 cell，否则时期中位数
    def predict(p, c30):
        b = chg30_bucket(c30)
        if (p, b) in cell_med:
            return cell_med[(p, b)]
        return pmed.get(p, gm)

    for p in range(5):
        for seg in ["sample_in", "sample_out"]:
            sub = [s for s in S if s[1] == p and (s[0] < SPLIT if seg == "sample_in" else s[0] >= SPLIT)]
            if len(sub) < 30:
                continue
            preds = [predict(s[1], s[2]) for s in sub]
            acts = [s[3] for s in sub]
            mae = sum(abs(a - b) for a, b in zip(preds, acts)) / len(sub)
            key = f"{PNAME[p]}-{seg}"
            out["groups"][key] = {"n": len(sub), "mae": round(mae, 2),
                                  "pred_med": round(median(preds), 2), "actual_med": round(median(acts), 2)}

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(f"\n基线 S3 样本外 MAE = 13.24")
    for p in range(5):
        line = []
        for seg in ["sample_in", "sample_out"]:
            k = f"{PNAME[p]}-{seg}"
            if k in out["groups"]:
                line.append(f"{seg}={out['groups'][k]['mae']}")
        print(f"  {PNAME[p]:10s} {'  '.join(line)}")


if __name__ == "__main__":
    main()
