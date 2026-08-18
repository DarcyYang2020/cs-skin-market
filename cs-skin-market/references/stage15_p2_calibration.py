# -*- coding: utf-8 -*-
"""阶段15（修复版）P2 概率校准：公平对照（2026-08-18，回应③审计#3「Brier 对照不公平 + 字段错位」）。

修复：① pred_win 字段错位（原 b*5+5 错，应为 b*10+5）；② Brier 公平对照——
基线 = train 拟合时期翻正率（OOS）；P1-C = train 拟合「时期×chg30 桶」翻正率（OOS，可验证部分）。
深跌 S3 桶 train 无样本，不参与（标注无样本外能力）。
输出 data/_exp_stage15_p2_calibration.json（覆盖）。
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
    return 2


def main():
    rows, run_map = load_and_fix()
    S = [(r[0], run_map[r[0]][0], r[2], r[20]) for r in rows if r[20] is not None]
    train = [s for s in S if s[0] < SPLIT]
    test = [s for s in S if s[0] >= SPLIT]

    # 基线：train 拟合时期翻正率
    pcell = defaultdict(list)
    for _, p, c30, f in train:
        pcell[p].append(f)
    pwin = {p: sum(1 for x in v if x > 0) / len(v) for p, v in pcell.items()}

    # P1-C：train 拟合「时期×chg30 桶」翻正率（OOS，可验证部分）
    ccell = defaultdict(list)
    for _, p, c30, f in train:
        ccell[(p, chg30_bucket(c30))].append(f)
    cwin = {k: sum(1 for x in v if x > 0) / len(v) for k, v in ccell.items()}

    def brier(predwin_fn):
        errs = []
        for _, p, c30, f in test:
            pw = predwin_fn(p, c30)
            if pw is None:
                continue
            lab = 1.0 if f > 0 else 0.0
            errs.append((pw - lab) ** 2)
        return sum(errs) / len(errs) if errs else None

    b_base = brier(lambda p, c30: pwin.get(p))
    b_chg30 = brier(lambda p, c30: cwin.get((p, chg30_bucket(c30)), pwin.get(p)))

    # 校准曲线（修复 pred_win 字段）：用 train 拟合 cwin 预测
    buckets = defaultdict(list)
    for _, p, c30, f in test:
        pw = cwin.get((p, chg30_bucket(c30)), pwin.get(p))
        if pw is None:
            continue
        b = int(pw * 10)
        buckets[b].append(1.0 if f > 0 else 0.0)
    curve = {}
    for b in sorted(buckets):
        v = buckets[b]
        curve[f"{b*10}-{(b+1)*10}%"] = {"n": len(v), "pred_win": b * 10 + 5,
                                        "actual_win": round(sum(v) / len(v) * 100, 1)}

    out = {"probe": "阶段15(修复) P2 概率校准 公平对照", "split": SPLIT,
           "note": "P1-C 用 train 拟合 chg30 桶（OOS 可验证部分）；深跌 S3 桶 train 无样本不参与",
           "brier_baseline": round(b_base, 4) if b_base else None,
           "brier_chg30_oos": round(b_chg30, 4) if b_chg30 else None,
           "calibration_curve": curve}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(f"Brier 公平对照：基线={out['brier_baseline']}  chg30(OOS)={out['brier_chg30_oos']}")
    for k, v in curve.items():
        print(f"  预测 {k:8s} n={v['n']:5d} 实际翻正={v['actual_win']}%")


if __name__ == "__main__":
    main()
