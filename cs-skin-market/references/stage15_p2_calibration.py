# -*- coding: utf-8 -*-
"""阶段15 P2 概率校准（2026-08-18，预注册）。

P2 目标：让「翻正率」真对应实际翻正率（预测 62% 时实际真 62%）。
对比「基线（时期×时点翻正率，train拟合）」vs「P1-C（chg30幅度桶翻正率，全样本外推）」的
  Brier score（越小越准）+ 校准曲线（预测翻正率 vs 实际翻正率，贴对角线=校准）。
预注册判据：P1-C 的 Brier 显著低于基线，且校准曲线更贴对角线。
输出 data/_exp_stage15_p2_calibration.json。
"""
import json
from collections import defaultdict
from pathlib import Path

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage15_p2_calibration.json"
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


def chg30_bucket(c30):
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

    # 基线：时期×时点翻正率（train 拟合）
    train = [s for s in S if s[0] < SPLIT]
    pcell = defaultdict(list)
    for _, p, c30, f in train:
        pcell[p].append(f)
    pwin = {p: sum(1 for x in v if x > 0) / len(v) for p, v in pcell.items()}

    # P1-C：chg30 幅度桶翻正率（全样本）
    ccell = defaultdict(list)
    for _, p, c30, f in S:
        ccell[(p, chg30_bucket(c30))].append(f)
    cwin = {k: sum(1 for x in v if x > 0) / len(v) for k, v in ccell.items()}

    # 在 test 上算 Brier + 校准曲线
    test = [s for s in S if s[0] >= SPLIT]
    def brier(predwin_fn):
        errs = []
        for _, p, c30, f in test:
            pw = predwin_fn(p, c30)
            if pw is None:
                continue
            lab = 1.0 if f > 0 else 0.0
            errs.append((pw - lab) ** 2)
        return sum(errs) / len(errs) if errs else None

    b_baseline = brier(lambda p, c30: pwin.get(p))
    b_p1c = brier(lambda p, c30: cwin.get((p, chg30_bucket(c30))))

    # 校准曲线：P1-C 预测翻正率分桶，看实际翻正率
    buckets = defaultdict(list)
    for _, p, c30, f in test:
        pw = cwin.get((p, chg30_bucket(c30)))
        if pw is None:
            continue
        b = int(pw * 10)  # 0-9 桶（0-10%, 10-20%, ...）
        buckets[b].append(1.0 if f > 0 else 0.0)
    curve = {}
    for b in sorted(buckets):
        v = buckets[b]
        curve[f"{b*10}-{(b+1)*10}%"] = {"n": len(v), "pred_win": (b*5+5), "actual_win": round(sum(v)/len(v)*100, 1)}

    out = {"probe": "阶段15 P2 概率校准", "split": SPLIT,
           "brier_baseline": round(b_baseline, 4) if b_baseline else None,
           "brier_p1c": round(b_p1c, 4) if b_p1c else None,
           "calibration_curve_p1c": curve}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(f"\nBrier（越小越准）：基线={out['brier_baseline']}  P1-C={out['brier_p1c']}")
    print("\nP1-C 校准曲线（预测翻正率 vs 实际翻正率）：")
    for k, v in curve.items():
        print(f"  预测 {k:8s} n={v['n']:5d} 实际翻正={v['actual_win']}%")


if __name__ == "__main__":
    main()
