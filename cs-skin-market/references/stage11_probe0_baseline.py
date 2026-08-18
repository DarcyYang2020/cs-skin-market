# -*- coding: utf-8 -*-
"""阶段11 探针0：量化当前机制「算得多不准」（2026-08-18，预注册）。

「算得准」第一目标 → 先量化当前查表机制（全 SPLIT 前历史拟合）的误差。
度量：MAE（|预测中位数-实际fwd14|）+ 方向错误率（预测与实际中位数符号相反）+ 校准（预测翻正率 vs 实际翻正率）。
分时期 + S3 分「好 S3(SPLIT前样本内)/坏 S3(SPLIT后样本外)」——量化时期漂移导致的「算不准」。
输出 data/_exp_stage11_probe0_baseline.json。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage11_probe0_baseline.json"
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


def main():
    rows, run_map = load_and_fix()
    from pipeline.shortterm_expectancy import compute_shortterm_expectancy as _cse

    # 逐 item-day 用当前机制算预测
    recs = defaultdict(list)  # key -> [(pred_med, actual, pred_win)]
    for r in rows:
        if r[20] is None:
            continue
        p, day = run_map[r[0]]
        chg7 = r[11]; chg3 = r[14]; z = r[7]; th = r[8]; supply30 = r[10]
        pred = _cse(p, day, chg7, chg3, z, th, supply30)
        if not pred or not pred.get("fwd14") or pred["fwd14"].get("med") is None:
            continue
        pm = pred["fwd14"]["med"]; pw = pred["fwd14"].get("win"); act = r[20]
        key = (p, "sample_in" if r[0] < SPLIT else "sample_out")
        recs[key].append((pm, act, pw))

    out = {"probe": "阶段11 探针0", "split": SPLIT, "groups": {}}
    print("\n时期 × 样本内/外 的预测误差（当前机制）")
    print(f"{'分组':28s} {'n':>6s} {'MAE':>7s} {'预测med':>8s} {'实际med':>8s} {'方向错%':>8s} {'预测win':>8s} {'实际win':>8s}")
    for p in range(5):
        for seg in ["sample_in", "sample_out"]:
            v = recs.get((p, seg), [])
            if len(v) < 30:
                continue
            preds = [x[0] for x in v]; acts = [x[1] for x in v]
            mae = sum(abs(a - b) for a, b in zip(preds, acts)) / len(v)
            pm = median(preds); am = median(acts)
            # 方向错误率：预测 med 和实际 med 符号相反（用逐样本）
            wrong = sum(1 for a, b in zip(preds, acts) if (a > 0) != (b > 0)) / len(v) * 100
            pw = median([x[2] for x in v if x[2] is not None]) if any(x[2] is not None for x in v) else None
            aw = sum(1 for x in acts if x > 0) / len(acts) * 100
            key = f"{PNAME[p]}-{seg}"
            out["groups"][key] = {"n": len(v), "mae": round(mae, 2), "pred_med": round(pm, 2),
                                  "actual_med": round(am, 2), "wrong_dir_pct": round(wrong, 1),
                                  "pred_win": pw, "actual_win": round(aw, 1)}
            print(f"{key:28s} {len(v):6d} {mae:7.2f} {pm:+8.2f} {am:+8.2f} {wrong:8.1f} {str(pw):>8s} {aw:8.1f}")

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nsaved", OUT)


if __name__ == "__main__":
    main()
