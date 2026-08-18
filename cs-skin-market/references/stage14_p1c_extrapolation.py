# -*- coding: utf-8 -*-
"""阶段14 P1-C chg30 幅度外推规则（2026-08-18，预注册）。

核心洞察（阶段13 根因）：坏 S3（chg30 深跌 ≤-5）是 SPLIT 前 3 年历史**从未出现的新 regime**，
train 里 S3 深跌样本 = 0，任何「从 train 学」的方法都学不到「深跌→负期望」。
零滞后的「算准」只能靠**外推规则**（领域知识）：chg30 深跌 → 负期望、浅跌 → 企稳。

本探针验证「chg30 幅度」区分好坏 S3 的**方向能力**（样本内验证，非样本外泛化——
坏 S3 是新 regime，样本外泛化只能靠领域知识外推 + B 通道/live pilot，不靠数据拟合）。
预测 = median[fwd | 时期, chg30幅度桶]（全样本建表，作为外推表）。
预注册判据：S3 期「深跌桶」fwd 中位数显著负于「浅跌桶」（差 ≥5pp），方向对。
输出 data/_exp_stage14_p1c_extrapolation.json。
"""
import json
from collections import defaultdict
from pathlib import Path

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage14_p1c_extrapolation.json"
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
    """chg30 幅度分桶（预注册，第一性原理：-15 是 P 期下限，-5 是 S3 深/浅跌自然分界，与供给扩张阈值 5% 对齐）。"""
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

    # 全样本建「时期 × chg30 幅度」外推表
    cell = defaultdict(list)
    for _, p, c30, f in S:
        cell[(p, chg30_bucket(c30))].append(f)
    cell_med = {k: median(v) for k, v in cell.items()}
    cell_win = {k: round(sum(1 for x in v if x > 0) / len(v) * 100, 1) for k, v in cell.items()}

    out = {"probe": "阶段14 P1-C chg30外推规则", "note":
           "样本内验证方向能力；坏S3是新regime，样本外泛化靠领域知识外推+B通道，不靠拟合",
           "buckets": {}}
    print("时期 × chg30幅度 外推表（fwd14 中位数 / 翻正率）")
    for p in range(5):
        for b in range(4):
            k = (p, b)
            if k in cell_med:
                blabel = ["<=-15", "-15~-5", "-5~0", ">0"][b]
                out["buckets"][f"{PNAME[p]}-{blabel}"] = {
                    "n": len(cell[k]), "fwd14_med": round(cell_med[k], 2), "win": cell_win[k]}
                print(f"  {PNAME[p]:8s} chg30 {blabel:7s} n={len(cell[k]):5d} fwd14_med={cell_med[k]:+.2f}% 翻正={cell_win[k]}%")

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)


if __name__ == "__main__":
    main()
