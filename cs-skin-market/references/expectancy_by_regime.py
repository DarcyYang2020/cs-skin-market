# -*- coding: utf-8 -*-
"""B-1 期望统计·市场状态分层聚合（只读展示口径，不改引擎/配置）

数据源：data/item_backtest_full_2025.json（去量引擎 v2 回放，365d 窗口 317 信号）
分层：pipeline/market_context.state_bucket（六态，引擎统一口径）
族划分：action_label 含「恐慌」→panic / 「深值」→deep_value / 其余→accumulate
      （与 config.ITEM_EXPECTANCY_STATS 展示口径一致，由 sync_expectancy_config.py 同步，本脚本不碰 config）
统计：net14/net30（回放内已扣 2% 双边成本），win = net > 0

用途：评估「选股/择时 alpha 是否随市场状态存在系统性差异」，为 P-2 立项提供状态分层证据。
     只读：不写库、不改配置、不跑回放。
运行：python references/expectancy_by_regime.py
"""
import io
import json
import sys
from collections import OrderedDict

sys.path.insert(0, ".")
from pipeline.market_context import state_bucket

REPLAY = "data/item_backtest_full_2025.json"
OUT = "data/_exp_expectancy_by_regime.json"

REGIME_ORDER = ["贪婪禁入", "V型底区", "阴跌中继区", "恐慌浅跌", "中性企稳", "弱市观望"]


def display_key(action_label):
    label = action_label or ""
    if "恐慌" in label:
        return "panic"
    if "深值" in label:
        return "deep_value"
    return "accumulate"


def regime_of(sig):
    return state_bucket(sig.get("sentiment"), sig.get("market_th"), sig.get("mkt_chg30"))


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

    buckets = OrderedDict((r, []) for r in REGIME_ORDER)
    for s in signals:
        r = regime_of(s)
        if r in buckets:
            buckets[r].append(s)
        else:
            print("WARN: 未识别 regime=%r date=%s label=%s" % (r, s.get("date"), s.get("action_label")))

    out = OrderedDict()
    out["generated"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
    out["source"] = REPLAY
    out["total_signals"] = len(signals)
    out["note"] = ("B-1 状态分层聚合（只读展示口径）：regime 取 market_context.state_bucket "
                   "（sent/market_th/mkt_chg30 三输入六态）；族划分同 ITEM_EXPECTANCY_STATS 展示口径"
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
