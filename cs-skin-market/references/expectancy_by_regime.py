# -*- coding: utf-8 -*-
"""B-1 期望统计·市场状态分层聚合（只读展示口径，不改引擎/配置）

数据源：data/item_backtest_full_2025.json（去量引擎 v2 回放，365d 窗口 317 信号）
分层：pipeline/market_context.state_bucket（大盘五时期，2026-08-16 定稿，旧六态退役）；
      chg30 用回放信号自带 mkt_chg30，chg180 按信号日从回放库 market_index 联算
      （与 family_feature_card.py 同模式，回放产物无 chg180 列）。
族划分：action_label 含「恐慌」→panic / 「深值」→deep_value / 其余→accumulate
      （与 config.ITEM_EXPECTANCY_STATS 展示口径一致，由 sync_expectancy_config.py 同步，本脚本不碰 config）
统计：net14/net30（回放内已扣 2% 双边成本），win = net > 0

用途：评估「选股/择时 alpha 是否随市场状态存在系统性差异」，为 P-2 立项提供状态分层证据。
      只读：不写库、不改配置、不跑回放。
运行：python references/expectancy_by_regime.py
"""
import io
import json
import sqlite3
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.market_context import state_bucket  # noqa: E402

REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_expectancy_by_regime.json"

REGIME_ORDER = ["P恐慌深跌", "S1牛市上行", "S2牛市回调", "S3弱市阴跌", "S4弱市反弹"]


def display_key(action_label):
    label = action_label or ""
    if "恐慌" in label:
        return "panic"
    if "深值" in label:
        return "deep_value"
    return "accumulate"


def load_chg180_by_date():
    """{date: chg180} 从回放库大盘指数（180 日窗口）逐日联算。"""
    c = sqlite3.connect(REPLAY_DB)
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]
    out = {}
    for i in range(180, len(mvals)):
        if mvals[i - 180] > 0:
            out[mdates[i]] = (mvals[i] / mvals[i - 180] - 1) * 100
    return out


def slice_stats(sigs, key):
    ok = [s for s in sigs if s.get(key) is not None]
    if not ok:
        return {"n": 0, "win": None, "avg": None}
    wins = sum(1 for s in ok if s[key] > 0)
    return {"n": len(ok), "win": round(100.0 * wins / len(ok), 1),
            "avg": round(sum(s[key] for s in ok) / len(ok), 2)}


def main():
    data = json.load(io.open(REPLAY, encoding="utf-8"))
    signals = data["signals"]
    m180 = load_chg180_by_date()

    buckets = OrderedDict((r, []) for r in REGIME_ORDER)
    misses = 0
    for s in signals:
        d = s.get("date")
        c180 = m180.get(d)
        if c180 is None:
            misses += 1
        r = state_bucket(c180, s.get("mkt_chg30"))
        if r in buckets:
            buckets[r].append(s)
        else:
            print("WARN: 未识别 regime=%r date=%s label=%s" % (r, s.get("date"), s.get("action_label")))
    if misses:
        print("WARN: %d 信号无 chg180（180 日窗口前）" % misses)

    out = OrderedDict()
    out["generated"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
    out["source"] = str(REPLAY)
    out["total_signals"] = len(signals)
    out["note"] = ("B-1 状态分层聚合（只读展示口径）：regime 取 market_context.state_bucket "
                   "（大盘五时期 chg180×chg30，2026-08-16 定稿，旧六态退役；chg180 按信号日"
                   "从回放库大盘指数联算）；族划分同 ITEM_EXPECTANCY_STATS 展示口径"
                   "（恐慌/深值/其余）；net14/net30 已扣 2% 双边成本；win = net > 0。"
                   "不参与引擎决策，仅供选股/择时 alpha 状态分层评估。")
    out["families"] = ["panic", "deep_value", "accumulate"]
    out["regimes"] = {}

    for r in REGIME_ORDER:
        sigs = buckets[r]
        row = {"signals": len(sigs)}
        fam = {}
        for key in ("panic", "deep_value", "accumulate"):
            fs = [s for s in sigs if display_key(s.get("action_label")) == key]
            p14 = slice_stats(fs, "net14")
            p30 = slice_stats(fs, "net30")
            fam[key] = {
                "n": len(fs),
                "n14": p14["n"], "win14": p14["win"], "avg14": p14["avg"],
                "n30": p30["n"], "win30": p30["win"], "avg30": p30["avg"],
            }
        row["family"] = fam
        t14 = slice_stats(sigs, "net14")
        t30 = slice_stats(sigs, "net30")
        row["total"] = {
            "n14": t14["n"], "win14": t14["win"], "avg14": t14["avg"],
            "n30": t30["n"], "win30": t30["win"], "avg30": t30["avg"],
        }
        out["regimes"][r] = row

    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("=== B-1 期望统计·市场状态分层（回放 %d 信号）===" % len(signals))
    for r in REGIME_ORDER:
        v = out["regimes"][r]
        t = v["total"]
        print("%-8s n=%d win14=%s avg14=%s win30=%s avg30=%s" % (r, v["signals"], t["win14"], t["avg14"], t["win30"], t["avg30"]))
    print("产物:", OUT)


if __name__ == "__main__":
    main()
