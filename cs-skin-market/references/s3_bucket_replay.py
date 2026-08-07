# -*- coding: utf-8 -*-
"""I-7 S3 分桶复验（2026-08-07）：去量 v2 370 信号，吸筹族（S3）按恐慌/非恐慌桶对比。

背景：I-7 = 样本扩大后按恐慌/非恐慌桶对比 S3 期望，决定是否在恐慌桶提升触发优先级。
口径：族分类同 cap_family_backtest（action_label 含「恐慌」=panic、「吸筹/分批」=accumulate）；
分桶用信号自带 sentiment / market_th（引擎回放同源）：恐慌桶 = sentiment>=60 或 market_th<45，
非恐慌桶 = 其余。事件簇按日期 gap>=7 天。

用法: python references/s3_bucket_replay.py
结论写入 data/s3_bucket_replay.json
"""
import io as _io
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    d = json.load(_io.open(ROOT / "data" / "item_backtest_full_2025.json", encoding="utf-8"))
    return d["signals"]


def classify_action(label):
    lab = label or ""
    if "恐慌" in lab:
        return "panic"
    if "深值" in lab:
        return "deep_value"
    if "深度回调" in lab or "低吸" in lab:
        return "oversold"
    return "accumulate"


def stats(sigs):
    n = len(sigs)
    if not n:
        return {"n": 0, "win14_pct": None, "avg14": None, "win30_pct": None, "avg30": None,
                "clusters": 0, "max_cluster_pct": 0}
    w14 = sum(1 for s in sigs if (s.get("net14") or 0) > 0)
    w30 = sum(1 for s in sigs if (s.get("net30") or 0) > 0)
    a14 = sum(s.get("net14") or 0 for s in sigs) / n
    a30 = sum(s.get("net30") or 0 for s in sigs) / n
    # 事件簇（去重）
    ds = sorted(set(s["date"] for s in sigs))
    clusters = []
    cur = [ds[0]]
    for i in range(1, len(ds)):
        if (date.fromisoformat(ds[i]) - date.fromisoformat(ds[i-1])).days <= 7:
            cur.append(ds[i])
        else:
            clusters.append(cur)
            cur = [ds[i]]
    clusters.append(cur)
    return {
        "n": n, "win14_pct": round(100.0 * w14 / n, 1), "avg14": round(a14, 2),
        "win30_pct": round(100.0 * w30 / n, 1), "avg30": round(a30, 2),
        "clusters": len(clusters), "max_cluster_pct": round(100.0 * max(len(c) for c in clusters) / n, 1),
        "cluster_dates": [(c[0], c[-1], len(c)) for c in clusters],
    }


def main():
    sigs = load()
    # S3 吸筹族 = accumulate（含 base 的低位低估 112 个也归 accumulate？区分：action_label 含「吸筹」）
    s3 = [s for s in sigs if "吸筹" in (s.get("action_label") or "")]
    print("S3(吸筹族) signals:", len(s3))
    # 分桶：恐慌桶 = sentiment>=60 或 market_th<45
    panic_bucket = [s for s in s3 if (s.get("sentiment") or 50) >= 60 or (s.get("market_th") or 50) < 45]
    normal_bucket = [s for s in s3 if not ((s.get("sentiment") or 50) >= 60 or (s.get("market_th") or 50) < 45)]
    print("恐慌桶:", len(panic_bucket), " 非恐慌桶:", len(normal_bucket))
    r = {
        "s3_all": stats(s3),
        "s3_panic_bucket": stats(panic_bucket),
        "s3_normal_bucket": stats(normal_bucket),
    }
    # 强牛段（sent<40 + TH>=60，I-8 强牛边界）
    bull = [s for s in s3 if (s.get("sentiment") or 99) < 40 and (s.get("market_th") or 0) >= 60]
    r["s3_bull_segment"] = stats(bull)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    out = {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
        "note": "I-7 S3 分桶复验：吸筹族按恐慌/非恐慌桶 + 强牛段对比。恐慌桶=sentiment>=60 或 market_th<45；强牛段=sent<40 + market_th>=60。事件簇 gap>=7 天去重。",
        **r,
    }
    out_path = ROOT / "data" / "s3_bucket_replay.json"
    _io.open(out_path, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    print("written:", out_path)


if __name__ == "__main__":
    main()
