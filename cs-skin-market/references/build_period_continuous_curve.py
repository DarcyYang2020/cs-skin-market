# -*- coding: utf-8 -*-
"""时期×时点连续期望表（2026-08-18）：每时期 fwd14/fwd30 vs 进入第 N 天的连续曲线。

原理（用户纠正：量化程度，不做"样本不足"）：
- 每时期对 (进入第 N 天) 用滚动中位数平滑 fwd（窗口 ±3 天，pooling 全部 item-day，天然按 n 加权）；
- 超历史区间外推 = 尾部收敛值（末 5 天 pooled 中位）+ 25/75 分位置信带，标"外推"；
- 永远给数字，只有"内插"vs"外推"两档置信。

输出 data/_exp_period_continuous_curve.json。
"""
import json
from collections import defaultdict
import statistics

import importlib.util
from pathlib import Path

_SPEC = Path("references/current_state_expectancy.py")
spec = importlib.util.spec_from_file_location("cse", str(_SPEC))
cse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cse)

OUT = "data/_exp_period_continuous_curve.json"
PERIOD_NAMES = {0: "P恐慌深跌", 1: "S1牛市上行", 2: "S2牛市回调", 3: "S3弱市阴跌", 4: "S4弱市反弹"}
WIN = 3  # 滚动半窗（±3 天 → 7 天窗口）


def pool_median(vals):
    return round(statistics.median(vals), 2) if vals else None


def main():
    rows, _ = cse.load_and_fix()
    fidx14, fidx30 = 11, 12
    # 按时期×天 汇总 fwd14/fwd30
    day = defaultdict(lambda: defaultdict(list))
    for r in rows:
        day[r[2]][r[3]].append(r)
    out = {"method": {"win": WIN, "smooth": "rolling median ±3d (pooling)", "extrapolate": "tail 5d median"},
           "periods": {}}
    for p in sorted(day):
        ds = sorted(day[p])
        maxd = max(ds)
        name = PERIOD_NAMES[p]
        curve = []
        for d in ds:
            lo = max(ds[0], d - WIN)
            hi = min(ds[-1], d + WIN)
            f14 = [r[fidx14] for dd in range(lo, hi + 1) for r in day[p].get(dd, []) if r[fidx14] is not None]
            f30 = [r[fidx30] for dd in range(lo, hi + 1) for r in day[p].get(dd, []) if r[fidx30] is not None]
            raw14 = [r[fidx14] for r in day[p][d] if r[fidx14] is not None]
            raw30 = [r[fidx30] for r in day[p][d] if r[fidx30] is not None]
            curve.append({
                "day": d,
                "n": len(raw14),
                "fwd14_raw": round(statistics.fmean(raw14), 2) if raw14 else None,
                "fwd14_smooth": pool_median(f14),
                "win14": round(sum(1 for x in raw14 if x > 0) / len(raw14) * 100, 1) if raw14 else None,
                "fwd30_smooth": pool_median(f30),
                "win30": round(sum(1 for x in raw30 if x > 0) / len(raw30) * 100, 1) if raw30 else None,
            })
        # 尾部收敛值：取「有 fwd14 数据的最后 5 天」pooled（排除回放终点前 14 天内的截尾天）
        valid_days = [d for d in ds if any(r[fidx14] is not None for r in day[p][d])]
        tail_days = valid_days[-5:] if len(valid_days) >= 5 else valid_days
        tail14 = [r[fidx14] for d in tail_days for r in day[p][d] if r[fidx14] is not None]
        tail30 = [r[fidx30] for d in tail_days for r in day[p][d] if r[fidx30] is not None]
        q = statistics.quantiles(tail14, n=4) if len(tail14) >= 4 else None
        out["periods"][name] = {
            "min_day": ds[0], "max_day": maxd, "n_days": len(ds),
            "curve": curve,
            "tail_asymptote": {
                "fwd14": pool_median(tail14),
                "win14": round(sum(1 for x in tail14 if x > 0) / len(tail14) * 100, 1) if tail14 else None,
                "fwd30": pool_median(tail30),
                "win30": round(sum(1 for x in tail30 if x > 0) / len(tail30) * 100, 1) if tail30 else None,
                "band25_75": [round(q[0], 1), round(q[2], 1)] if q else None,
                "n": len(tail14),
            },
        }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    for name in PERIOD_NAMES.values():
        pp = out["periods"][name]
        ta = pp["tail_asymptote"]
        print(f"{name:10s} 天范围 1~{pp['max_day']} | 尾部渐近 fwd14={ta['fwd14']}% win={ta['win14']}% (n={ta['n']}) 带={ta['band25_75']}")


if __name__ == "__main__":
    main()
