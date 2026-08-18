# -*- coding: utf-8 -*-
"""阶段12 P1 修时期漂移（2026-08-18，预注册）。

目标：把「全 SPLIT 前历史拟合」的时期先验，改成「近期」拟合，修 S3 时期漂移（+0.88→−7.54 方向错）。
方案（预注册候选值，非跑完挑最好）：
  P1-A 近期滚动：只用预测日前近 N 个月样本拟合（N=3/6/12）。
  P1-B 时间衰减加权：样本按距今衰减（半衰期 H=3/6 个月）。
判据：S3 样本外 MAE 从基线 13.24 降 ≥10%（<11.92），且 S3 样本内（好 S3）MAE 不劣化（≤3.51×1.2）。
输出 data/_exp_stage12_p1_drift.json。
"""
import json
import math
from collections import defaultdict
from pathlib import Path

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage12_p1_drift.json"
SPLIT = "2025-08-10"
BASE_S3_OUT_MAE = 13.24
BASE_S3_IN_MAE = 3.51


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


def days_before(d1, d2):
    """d2 - d1 的天数（d1<d2 为正）。"""
    import datetime
    a = datetime.date(*map(int, d1.split("-")))
    b = datetime.date(*map(int, d2.split("-")))
    return (b - a).days


def main():
    rows, run_map = load_and_fix()
    # 按日期排序的 S3 样本（含 fwd14）
    s3 = [(r[0], r[20]) for r in rows if r[20] is not None and run_map[r[0]][0] == 3]
    s3.sort(key=lambda x: x[0])
    dates = sorted({x[0] for x in s3})

    out = {"probe": "阶段12 P1 修时期漂移", "baseline_s3_out_mae": BASE_S3_OUT_MAE, "schemes": {}}

    # 对每个 val 段 S3 日（>= SPLIT），用「该日前近 N 月/时间衰减」拟合 S3 先验，预测 = 中位数
    def eval_scheme(name, weight_fn):
        """weight_fn(date_now, date_past) -> 权重（0=不用该样本）。"""
        results = {}
        for d in dates:
            if d < SPLIT:
                continue
            weights = []
            vals = []
            for pd, v in s3:
                if pd >= d:
                    break
                w = weight_fn(d, pd)
                if w > 0:
                    weights.append(w)
                    vals.append(v)
            if not vals:
                continue
            # 加权中位数
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            cum = 0
            total = sum(weights)
            pred = None
            for i in order:
                cum += weights[i]
                if cum >= total / 2:
                    pred = vals[i]
                    break
            results[d] = pred
        # 计算 S3 样本外 MAE
        errs = []
        for d, pred in results.items():
            if pred is None:
                continue
            for pd, v in s3:
                if pd == d:
                    errs.append(abs(pred - v))
        mae = sum(errs) / len(errs) if errs else None
        return mae, len(errs)

    # P1-A 近期滚动（N 月）
    for N in [3, 6, 12]:
        def roll_w(d_now, d_past, N=N):
            return 1.0 if 0 <= days_before(d_past, d_now) <= N * 30 else 0.0
        mae, n = eval_scheme(f"P1A_roll_{N}m", roll_w)
        out["schemes"][f"P1A_roll_{N}m"] = {"s3_out_mae": round(mae, 2) if mae else None, "n_days": n}

    # P1-B 时间衰减（半衰期 H 月）
    for H in [3, 6]:
        halflife = H * 30
        def decay_w(d_now, d_past, H=halflife):
            dd = days_before(d_past, d_now)
            if dd < 0:
                return 0.0
            return 0.5 ** (dd / halflife)
        mae, n = eval_scheme(f"P1B_decay_{H}m", decay_w)
        out["schemes"][f"P1B_decay_{H}m"] = {"s3_out_mae": round(mae, 2) if mae else None, "n_days": n}

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(f"\n基线 S3 样本外 MAE = {BASE_S3_OUT_MAE}（降10%目标 < {round(BASE_S3_OUT_MAE*0.9,2)}）")
    for k, v in out["schemes"].items():
        m = v["s3_out_mae"]
        if m is not None:
            flag = "✓ 达标" if m < BASE_S3_OUT_MAE * 0.9 else "✗ 未达"
            print(f"  {k:16s} S3_out_MAE={m:6.2f} (n_days={v['n_days']}) {flag}")


if __name__ == "__main__":
    main()
