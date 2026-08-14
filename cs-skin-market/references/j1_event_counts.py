# -*- coding: utf-8 -*-
"""J-1/J-3 信号族样本深度：从当前引擎回放同源统计各族「信号数 / 独立事件数（±3天去簇）」。

口径（K-3：展示统计必须与回放产物同源）：
- 数据源：data/item_backtest_full_2025.json（去量引擎 v2（I-13）回放 370 信号）
- 细族划分：按 action_label 关键词（恐慌共振/恐慌退潮/深值/供给收缩/深度回调/分批建仓）
- 展示键：action_label 匹配（含「恐慌」→panic / 含「深值」→deep_value / 其余→accumulate，与 config.ITEM_EXPECTANCY_STATS 同口径）
- 事件数：backtest_methodology.signal_cluster_report(dates, window=3) 的 event_count
- win/avg：net14/net30（回放内已扣 2% 双边成本）；ci14 = Wilson 95% 区间（与 config 旧口径一致）

产出：data/signal_event_counts.json（供数据积累进度卡 J-3 展示「信号数/独立事件数」随采集增长；
      display_keys 与 config.ITEM_EXPECTANCY_STATS 同源；config 块由 references/sync_expectancy_config.py
     自动同步生成（勿手改），改回放产物后重跑该同步脚本即可双端一致）。
运行：python references/j1_event_counts.py
"""
import io
import json
import sys

sys.path.insert(0, ".")
from pipeline.backtest_methodology import signal_cluster_report
from pipeline.config import SIGNAL_FAMILY_TAXONOMY, assign_fine_family, display_key_for_label

REPLAY = "data/item_backtest_full_2025.json"
REPLAY_CLEAN = "data/_exp_v2t7_win_replay.json"
OUT = "data/signal_event_counts.json"

FAMILIES = [(k, SIGNAL_FAMILY_TAXONOMY["fine_labels"][k]) for k in SIGNAL_FAMILY_TAXONOMY["fine_order"]]
DISPLAY_KEYS = SIGNAL_FAMILY_TAXONOMY["display_keys"]


def wilson_ci(k: int, n: int, z: float = 1.96):
    """Wilson 95% 置信区间（百分比）。"""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (round(100.0 * max(0.0, center - half), 1), round(100.0 * min(1.0, center + half), 1))


def assign_family(action_label: str) -> str:
    return assign_fine_family(action_label)


def display_key(action_label: str) -> str:
    return display_key_for_label(action_label)


def family_stats(dates):
    cl = signal_cluster_report(dates, window=3)
    ds = sorted(set(d for d in dates if d))
    return {"signals": cl["signal_count"], "events": cl["event_count"],
            "unique_dates": cl["unique_dates"],
            "max_cluster_share": round(cl["max_cluster_share"], 4),
            "date_range": [ds[0], ds[-1]] if ds else None}


def pnl_stats(sigs):
    def _slice(key):
        ok = [s for s in sigs if s.get(key) is not None]
        if not ok:
            return {"n": 0, "win": None, "avg": None, "ci": None}
        wins = sum(1 for s in ok if s[key] > 0)
        return {"n": len(ok), "win": round(100.0 * wins / len(ok), 1),
                "avg": round(sum(s[key] for s in ok) / len(ok), 2),
                "ci": wilson_ci(wins, len(ok))}
    return {"win14": _slice("net14"), "win30": _slice("net30")}


def generate_payload(replay_path, source_label=None):

    data = json.load(io.open(replay_path, encoding="utf-8"))
    signals = data["signals"]

    out = {"generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d"), "window": 3, "total_signals": len(signals),
           "note": "去量引擎 v2 回放同源（item_backtest_full_2025.json）；事件簇数=±3天去簇；细族按 action_label 关键词，展示键按「恐慌/深值」匹配（与 config.ITEM_EXPECTANCY_STATS 同口径，config 由 sync_expectancy_config.py 同步生成）",
           "source": str(replay_path),
           "baseline": source_label}

    for key, kw in FAMILIES:
        sigs = [s for s in signals if assign_family(s.get("action_label") or "") == key]
        if not sigs:
            continue
        st = family_stats([s["date"] for s in sigs])
        p14 = pnl_stats(sigs)
        st["win14"] = p14["win14"]["win"]
        st["avg14"] = p14["win14"]["avg"]
        st["win30"] = p14["win30"]["win"]
        st["avg30"] = p14["win30"]["avg"]
        st["match"] = kw or "其余(基础分批)"
        out[key] = st

    # 展示键（action_label 匹配，同 config.ITEM_EXPECTANCY_STATS 口径）
    out["display_keys"] = {}
    for key in DISPLAY_KEYS:
        sigs = [s for s in signals if display_key(s.get("action_label") or "") == key]
        st = family_stats([s["date"] for s in sigs])
        p14 = pnl_stats(sigs)
        st["n"] = len(sigs)
        st["win14"] = p14["win14"]["win"]
        st["avg14"] = p14["win14"]["avg"]
        st["ci14_lo"], st["ci14_hi"] = p14["win14"]["ci"] or (None, None)
        st["win30"] = p14["win30"]["win"]
        st["avg30"] = p14["win30"]["avg"]
        out["display_keys"][key] = st

    return out


def main():
    hist_payload = generate_payload(REPLAY, source_label="HIST-FULL")
    clean_payload = generate_payload(REPLAY_CLEAN, source_label="CLEAN-CUR")
    out = {k: v for k, v in hist_payload.items()}
    out["baselines"] = {"HIST-FULL": hist_payload, "CLEAN-CUR": clean_payload}
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("=== 信号族样本深度（HIST-FULL 回放 %d 信号）===" % len(json.load(io.open(REPLAY, encoding="utf-8"))["signals"]))
    print("written:", OUT)


if __name__ == "__main__":
    main()