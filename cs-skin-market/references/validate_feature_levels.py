# -*- coding: utf-8 -*-
"""特征层级增量校验（2026-08-18，预注册）：量化每维条件在样本外的预测价值。

复用 current_state_expectancy 的 load_and_fix / bucketize / spearman。
对每种条件方案（维度组合）在 train 上拟合收缩条件表，在 test 上预测 fwd14，
输出 RMSE（vs 全局均值基线）+ Spearman + 方向一致率 → 判断哪些维有样本外边际。

输出 data/_exp_feature_level_validation.json。
"""
import json
import math
from collections import defaultdict

import importlib.util
from pathlib import Path

_SPEC = Path("references/current_state_expectancy.py")
spec = importlib.util.spec_from_file_location("cse", str(_SPEC))
cse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cse)

OUT = "data/_exp_feature_level_validation.json"
K = 20
TRAIN_END = "2026-03-01"

# 方案（预注册顺序，逐维累加）：
SCHEMES = [
    ("period", ["period"]),
    ("period+period_days", ["period", "period_days"]),
    ("period+period_days+pct", ["period", "period_days", "pct"]),
    ("period+period_days+pct+th", ["period", "period_days", "pct", "th"]),
    ("period+period_days+pct+th+z", ["period", "period_days", "pct", "th", "z"]),
    ("period+pct+th", ["period", "pct", "th"]),
    ("period+cycle", ["period", "cycle"]),
    ("period+mchg30", ["period", "mchg30"]),
    ("period+sent", ["period", "sent"]),
]


def main():
    rows, _ = cse.load_and_fix()
    fidx = 11  # fwd14
    date_i = 0
    train = [r for r in rows if r[date_i] < TRAIN_END and r[fidx] is not None]
    test = [r for r in rows if r[date_i] >= TRAIN_END and r[fidx] is not None]
    global_mean = sum(r[fidx] for r in train) / len(train)

    def rmse(xs):
        return math.sqrt(sum((x - global_mean) ** 2 for x in xs) / len(xs))

    rmse_base_test = rmse([r[fidx] for r in test])

    results = []
    for name, dims in SCHEMES:
        agg = defaultdict(list)
        for r in train:
            b = cse.bucketize(r)
            agg[tuple(b[d] for d in dims)].append(r[fidx])
        cell_mean = {k: sum(v) / len(v) for k, v in agg.items()}

        def predict(r):
            b = cse.bucketize(r)
            key = tuple(b[d] for d in dims)
            vals = agg.get(key)
            if not vals:
                return global_mean
            lam = len(vals) / (len(vals) + K)
            return lam * cell_mean[key] + (1 - lam) * global_mean

        pred = [predict(r) for r in test]
        actual = [r[fidx] for r in test]
        rmse_p = math.sqrt(sum((p - a) ** 2 for p, a in zip(pred, actual)) / len(test))
        rho = cse.spearman(pred, actual)
        # 方向一致率：train cell 与 test cell 均值同号
        tcell = defaultdict(list)
        for r in test:
            b = cse.bucketize(r)
            tcell[tuple(b[d] for d in dims)].append(r[fidx])
        agree = tot = 0
        for k, v in tcell.items():
            if k in cell_mean and len(v) >= 5:
                tot += 1
                if (cell_mean[k] > 0) == (sum(v) / len(v) > 0):
                    agree += 1
        results.append({
            "scheme": name, "n_dims": len(dims),
            "rmse": round(rmse_p, 2),
            "rmse_improve_vs_global_pct": round((1 - rmse_p / rmse_base_test) * 100, 2),
            "spearman": round(rho, 4) if rho is not None else None,
            "sign_agree": f"{agree}/{tot}",
        })

    out = {"global_rmse_test": round(rmse_base_test, 2), "shrink_k": K,
           "train_end": TRAIN_END, "n_train": len(train), "n_test": len(test),
           "levels": results}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    for r in results:
        print(f"{r['scheme']:30s} rmse={r['rmse']:6.2f} "
              f"improve={r['rmse_improve_vs_global_pct']:5.2f}% "
              f"rho={r['spearman']} sign={r['sign_agree']}")


if __name__ == "__main__":
    main()
