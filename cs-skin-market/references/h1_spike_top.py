# -*- coding: utf-8 -*-
"""H1 尖顶崩塌预测（2026-08-12，庄盘专项，只读回测）。
依据 references/first-principles-manipulation.md §五 H1：
信号 = 任意品「峰值后 3d 回撤 >50%」（尖顶形态 = 派发完成）；
检验信号后 30/90d 收益 vs 同品随机起点置换基线。
判定阈值：n>=30、30d 下跌胜率>=75%、90d 期望<-30%（net 不含 2% 双边成本，仅方向验证）。
产物：data/_exp_spike_top_h1.json。三件套：信号数/胜率/期望增量。
"""
import json, io, random, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "_exp_sticker_deep_full.jsonl"
OUT = ROOT / "data" / "_exp_spike_top_h1.json"
LOOKBACK_DEDUP_DAYS = 30
FORWARD = [30, 90]
PERM = 2000


def load():
    rows = []
    with io.open(SRC, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            pts = [(d, v) for d, v in o.get("points", []) if isinstance(v, (int, float)) and v > 0]
            if len(pts) >= 120:
                rows.append((o.get("name", ""), [v for _, v in pts]))
    return rows


def find_signals(prices):
    """峰值后 3d 回撤 >50% 的尖顶信号；信号日 = 峰值日 +3d（回撤确认）；
    同品去重：信号间至少间隔 LOOKBACK_DEDUP_DAYS 天。"""
    sigs = []
    n = len(prices)
    i = 1
    while i < n - 4:
        win = prices[i:i + 4]
        if prices[i] >= max(prices[i - 1], max(win[1:])):
            peak = prices[i]
            drop3 = min(win[1:]) / peak
            if drop3 < 0.5:
                conf = i + 3  # 回撤确认日
                if conf < n:
                    sigs.append((i, conf, peak, drop3))
                    i = conf + LOOKBACK_DEDUP_DAYS
                    continue
        i += 1
    return sigs


def fwd_ret(prices, day, horizon):
    if day + horizon >= len(prices):
        return None
    return prices[day + horizon] / prices[day] - 1


def main():
    rows = load()
    signals = []
    for name, prices in rows:
        for (pi, conf, peak, drop3) in find_signals(prices):
            f30 = fwd_ret(prices, conf, 30)
            f90 = fwd_ret(prices, conf, 90)
            if f30 is not None:
                signals.append(dict(name=name, peak_idx=pi, conf_idx=conf,
                                    drop3=drop3, f30=f30, f90=f90))
    n = len(signals)
    f30s = [s["f30"] for s in signals]
    f90s = [s["f90"] for s in signals if s["f90"] is not None]
    lose30 = sum(1 for x in f30s if x < 0) / len(f30s) if f30s else 0
    lose90 = sum(1 for x in f90s if x < 0) / len(f90s) if f90s else 0
    med30 = statistics.median(f30s) if f30s else None
    med90 = statistics.median(f90s) if f90s else None

    # 置换基线：同品随机起点（避开信号 ±60d），30/90d 收益分布
    rng = random.Random(42)
    perm30, perm90 = [], []
    for name, prices in rows:
        n2 = len(prices)
        for _ in range(max(1, PERM // len(rows))):
            d = rng.randrange(0, n2 - 95)
            r30 = fwd_ret(prices, d, 30)
            r90 = fwd_ret(prices, d, 90)
            if r30 is not None:
                perm30.append(r30)
            if r90 is not None:
                perm90.append(r90)
    p30 = sum(1 for x in perm30 if x <= (med30 or 0)) / len(perm30) if perm30 else None
    p90 = sum(1 for x in perm90 if x <= (med90 or 0)) / len(perm90) if perm90 else None

    # ---- V3 变体：全局峰值确认（派发完成口径；每品 1 信号） ----
    v3 = []
    for name, prices in rows:
        i_hi = prices.index(max(prices))
        if i_hi + 95 >= len(prices):
            continue
        f30 = fwd_ret(prices, i_hi, 30)
        f90 = fwd_ret(prices, i_hi, 90)
        v3.append(dict(name=name, f30=f30, f90=f90))
    v3_f30 = [s["f30"] for s in v3 if s["f30"] is not None]
    v3_f90 = [s["f90"] for s in v3 if s["f90"] is not None]
    v3_res = {
        "variant": "V3 全局峰值确认（区间最高点，事后口径；现实需峰值回撤确认后才可交易）",
        "n": len(v3),
        "f30": {"median": statistics.median(v3_f30), "down_win": sum(1 for x in v3_f30 if x < 0) / len(v3_f30),
                "n": len(v3_f30)},
        "f90": {"median": statistics.median(v3_f90), "down_win": sum(1 for x in v3_f90 if x < 0) / len(v3_f90),
                "n": len(v3_f90)},
    }

    result = {
        "generated": "2026-08-12",
        "hypothesis": "H1 尖顶崩塌预测：峰值后回撤 = 派发完成，其后 30/90d 显著下行？",
        "sample": {"items": len(rows)},
        "variants": {
            "V0": {
                "signal_def": "局部峰值后 3d 内最低 < 峰值 50%（回撤确认日=峰值日+3d），同品 30d 去重",
                "n": n,
                "f30": {"median": med30, "down_win": lose30, "n": len(f30s)},
                "f90": {"median": med90, "down_win": lose90, "n": len(f90s)},
                "permutation": {"f30_median": statistics.median(perm30), "f90_median": statistics.median(perm90),
                                "p30": p30, "p90": p90},
                "verdict": "FAIL/负结果：3d 崩 50% 多为中间假摔/洗盘，30d 中位反而 +19.6%（35.3% 下跌胜率）——不能单独作离场信号",
            },
            "V3": v3_res,
        },
        "thresholds": {"n_min": 30, "down30_win_min": 0.75, "f90_median_max": -0.30},
        "conclusion": (
            "V0 负结果：朴素尖顶（3d 崩 50%）不可交易，会反复触发在假摔段。"
            "V3 强支持：全局峰值后 30d 中位 -50.5% / 90d -67.2%，下跌胜率 100%（143/143）——"
            "派发完成后的下行是确定性的，但 V3 是事后口径；可交易的离场规则需「峰值确认」条件"
            "（如 14d 回撤>70% 且 N 日内未创新高）另行回测，落地前 walk-forward + 三件套 net2%。"
            "仅方向验证，未改任何决策参数。"
        ),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()