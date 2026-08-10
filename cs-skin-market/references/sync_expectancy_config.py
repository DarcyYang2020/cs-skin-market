# -*- coding: utf-8 -*-
"""期望统计单一事实源同步器（J-3 口径，2026-08-07 定稿）。

单一事实源 = data/item_backtest_full_2025.json（去量引擎 v2 回放产物）。
本脚本把回放产物按展示键（panic / deep_value / accumulate）重算
n / events / win14 / avg14 / ci14 / win30 / avg30，并同步写入：

  1) pipeline/config.py 的 ITEM_EXPECTANCY_STATS（防止手工双写漂移，该块勿手改）
  2) data/signal_event_counts.json（调用 j1_event_counts.py 同口径重算，供进度卡 J-3 展示）

用法: python references/sync_expectancy_config.py
改回放产物（重跑 run_item_backtest_full.py / 调整引擎）后必须重跑本脚本；
tests/test_smoke.py 的 t_expectancy_sync 硬校验 config 与回放计算值一致（防漂移）。
"""
import io
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import j1_event_counts as j1  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "pipeline" / "config.py"
REPLAY = ROOT / "data" / "item_backtest_full_2025.json"

DISPLAY_KEYS = ("panic", "deep_value", "accumulate")
LABELS = {"panic": "恐慌族", "deep_value": "深值企稳", "accumulate": "吸筹族"}
# 族构成（fine family 关键词 → 展示键），生成注释用，与 j1.FAMILIES 同源
FINE_TO_DISPLAY = {"panic_resonance": "panic", "panic_easing": "panic",
                   "deep_value": "deep_value",
                   "supply_accum": "accumulate", "deep_dip": "accumulate", "base": "accumulate"}
FINE_LABELS = {"panic_resonance": "恐慌共振", "panic_easing": "恐慌退潮",
               "deep_value": "深值企稳", "supply_accum": "供给收缩吸筹",
               "deep_dip": "深度回调低吸", "base": "基础分批"}


def compute_display_stats(replay_path=None):
    """按展示键重算期望统计（与 j1_event_counts.display_keys 完全同口径）。

    返回 (stats, total_signals, composition)：
      stats[key] = {n, events, win14, avg14, ci14_lo, ci14_hi, win30, avg30, n30}
      composition[key] = [("恐慌共振", 46), ...]（生成构成注释用）
    """
    path = Path(replay_path) if replay_path else REPLAY
    data = json.load(io.open(path, encoding="utf-8"))
    signals = data["signals"]
    stats, composition = {}, {}
    for key in DISPLAY_KEYS:
        sigs = [s for s in signals if j1.display_key(s.get("action_label") or "") == key]
        st = j1.family_stats([s["date"] for s in sigs])
        p14 = j1.pnl_stats(sigs)
        ci = p14["win14"]["ci"] or (None, None)
        stats[key] = {
            "n": len(sigs),
            "events": st["events"],
            "win14": p14["win14"]["win"],
            "avg14": p14["win14"]["avg"],
            "ci14_lo": ci[0],
            "ci14_hi": ci[1],
            "win30": p14["win30"]["win"],
            "avg30": p14["win30"]["avg"],
            "n30": p14["win30"]["n"],
        }
        comp = {}
        for s in sigs:
            fine = j1.assign_family(s.get("action_label") or "")
            comp[fine] = comp.get(fine, 0) + 1
        composition[key] = [(FINE_LABELS[f], n) for f, n in sorted(comp.items(), key=lambda kv: -kv[1])]
    return stats, len(signals), composition


def render_block(stats, total, composition):
    lines = []
    lines.append("ITEM_EXPECTANCY_STATS = {")
    lines.append("    # 口径：自动生成（references/sync_expectancy_config.py），勿手改；改回放产物后必须重跑同步。")
    lines.append("    # 数据源：data/item_backtest_full_2025.json（去量引擎 v2（I-13 大盘 chg30>=3 深值禁买）回放 %d 信号，net 已扣 2%% 双边成本）。" % total)
    lines.append("    # events = ±3 天去簇独立事件数（J-1 口径，backtest_methodology.signal_cluster_report window=3）。")
    lines.append("    # 展示键按单品报告 action_label 匹配：含「恐慌」→panic / 含「深值」→deep_value / 其余→accumulate。")
    lines.append("    # win30/avg30 为 n30 口径（含 net30 信号的子集）；ci14 = Wilson 95%% 区间。")
    lines.append("    # 历史备注：panic 旧 n=21 为 2026-08-02 强信号层切片；accumulate 旧 n=16 为短窗口切片；deep_value 旧 154 为 I-13 前，均已废弃。")
    for key in DISPLAY_KEYS:
        v = stats[key]
        comp_txt = " + ".join("%s(%d)" % (lab, n) for lab, n in composition[key])
        lines.append('    # %s：%s 全量（自动生成）' % (LABELS[key], comp_txt))
        lines.append('    "%s": {' % key)
        lines.append('        "label": "%s",' % LABELS[key])
        lines.append('        "n": %d,' % v["n"])
        lines.append('        "events": %d,' % v["events"])
        lines.append('        "win14": %.1f, "avg14": %.2f, "ci14_lo": %.1f, "ci14_hi": %.1f,' % (
            v["win14"], v["avg14"], v["ci14_lo"], v["ci14_hi"]))
        lines.append('        "win30": %.1f, "avg30": %.2f,  # n30=%d' % (v["win30"], v["avg30"], v["n30"]))
        lines.append('    },')
    lines.append("}")
    return "\n".join(lines)


def sync():
    stats, total, composition = compute_display_stats()
    block = render_block(stats, total, composition)

    src = io.open(CONFIG, encoding="utf-8").read()
    pat = re.compile(r"ITEM_EXPECTANCY_STATS = \{(?s:.*?)\n\}")
    new_src, n_sub = pat.subn(block, src, count=1)
    if n_sub != 1:
        raise RuntimeError("config.py 未找到 ITEM_EXPECTANCY_STATS 块，中止同步")
    if new_src != src:
        io.open(CONFIG, "w", encoding="utf-8", newline="").write(new_src)
        print("updated pipeline/config.py ITEM_EXPECTANCY_STATS")
    else:
        print("pipeline/config.py ITEM_EXPECTANCY_STATS 无变化")

    # 进度卡同源文件
    j1.REPLAY = str(REPLAY)
    j1.OUT = str(ROOT / "data" / "signal_event_counts.json")
    j1.main()
    print("updated data/signal_event_counts.json")

    return stats, total, composition


if __name__ == "__main__":
    stats, total, composition = sync()
    print("=== 期望统计（去量 v2 回放 %d 信号）===" % total)
    for key in DISPLAY_KEYS:
        v = stats[key]
        print("%-12s n=%3d n30=%3d events=%2d win14=%5.1f avg14=%6.2f ci14=[%4.1f,%4.1f] win30=%5.1f avg30=%6.2f" % (
            key, v["n"], v["n30"], v["events"], v["win14"], v["avg14"],
            v["ci14_lo"], v["ci14_hi"], v["win30"], v["avg30"]))