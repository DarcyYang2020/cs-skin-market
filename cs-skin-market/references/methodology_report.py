# -*- coding: utf-8 -*-
"""回测方法学报告（A2 工作流，只读分析，不改引擎/口径）。
在 2025-11-02 ~ 2026-08-05 窗口上，对 buy 信号的 fwd14/fwd30 运行三个方法学
检验（signal_cluster_report / walk_forward_split / permutation_baseline），
输出 data/methodology_report.json 并在控制台打印摘要。
口径说明（重要）:
- 信号明细来自 data/item_backtest_full_2025.json（去量 v2 标准回放，references/run_item_backtest_full.py --all
  产物：start=2025-11-02, warmup=60, cost=2%），即最新快照
  item_backtest_20260803.json 的同一份 88 条 buy 信号（2025-11-15 ~ 2026-06-21），
  已含 fwd14/fwd30/net14/net30，无需重放全量引擎；
- 窗口终点 2026-08-05：数据中最后一条 buy 信号出现在 2026-06-21，之后市场
  反弹未再触发 buy，故信号窗口实际为 2025-11-15 ~ 2026-06-21；
- 现有回测胜率口径为 net（fwd - 2% 双边成本）：win14 79.5% / win30 61.4%，
  本报告同时给出 fwd 毛收益与 net 净收益两套结果以便对照。
用法:
    python references/methodology_report.py [--signals-file data/item_backtest_full_2025.json]
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ".")

from pipeline.backtest_methodology import (  # noqa: E402
    permutation_baseline,
    signal_cluster_report,
    walk_forward_split,
)

WINDOW_START = "2025-11-02"
WINDOW_END = "2026-08-05"
REPORT_SAVE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "methodology_report.json",
)
FIELDS = [("fwd14", "毛收益 14d"), ("fwd30", "毛收益 30d"),
          ("net14", "净收益 14d（扣2%成本）"), ("net30", "净收益 30d（扣2%成本）")]


def load_buy_signals(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    sigs = [s for s in data.get("signals", [])
            if s.get("action") in ("buy", "oversold_buy") and s.get("date")]
    for s in sigs:
        if "fwd14" not in s and "fwd30" not in s:
            raise ValueError("信号缺 fwd14/fwd30 字段: %s" % s.get("date"))
    return data, sigs


def event_level_stats(sigs, cluster_report):
    """按事件簇去重：一簇 = 一个事件，给出事件级胜率/均值。"""
    date_to_cluster = {}
    for c in cluster_report["clusters"]:
        for d in c["dates"]:
            date_to_cluster[d] = c["index"]
    rows = []
    for c in cluster_report["clusters"]:
        members = [s for s in sigs if date_to_cluster.get(s["date"]) == c["index"]]
        row = {"start": c["start"], "end": c["end"], "signals": len(members)}
        for field, _label in FIELDS:
            vals = [s[field] for s in members if s.get(field) is not None]
            cnt, wins, wr, avg = 0, 0, None, None
            if vals:
                cnt = len(vals)
                wins = sum(1 for v in vals if v > 0)
                wr = round(wins / cnt, 4)
                avg = round(sum(vals) / cnt, 4)
            row[field] = {"n": cnt, "wins": wins, "win_rate": wr, "avg": avg}
        rows.append(row)
    out = {"event_count": len(rows), "events": rows}
    for field, _label in FIELDS:
        avgs = [r[field]["avg"] for r in rows if r[field]["avg"] is not None]
        cnt, wins = len(avgs), sum(1 for a in avgs if a > 0)
        out[field + "_event_win"] = {
            "n": cnt, "wins": wins,
            "win_rate": round(wins / cnt, 4) if cnt else None,
        }
    return out


def fmt_stats(st, key):
    if st is None:
        return "n/a"
    return "n=%d win=%s%% avg=%+.2f" % (st["n"], _pct(st["win_rate"]), st["avg"] or 0.0)


def _pct(x):
    return "%.1f" % (x * 100) if x is not None else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals-file", default=None)
    args = ap.parse_args()
    default_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "item_backtest_full_2025.json",
    )
    path = args.signals_file or default_file
    data, sigs = load_buy_signals(path)
    dates = [s["date"] for s in sigs]
    print("信号来源: %s" % path)
    print("buy 信号: %d 条 (%s ~ %s)，窗口 %s ~ %s" % (len(sigs), min(dates), max(dates), WINDOW_START, WINDOW_END))

    cluster = signal_cluster_report(dates, window=3)
    events = event_level_stats(sigs, cluster)

    wf = {}
    perm = {}
    for field, _label in FIELDS:
        recs = [s for s in sigs if s.get(field) is not None]
        wf[field] = walk_forward_split(recs, anchor_ratio=0.7, return_field=field)
        perm[field] = permutation_baseline([s[field] for s in sigs if s.get(field) is not None])

    report = {
        "generated_at": None,
        "window": {"start": WINDOW_START, "end": WINDOW_END,
                   "signal_start": min(dates), "signal_end": max(dates)},
        "口径": {
            "signals_file": os.path.basename(path),
            "source": "run_item_backtest.py --all (start=2025-11-02, warmup=60, cost=2%)",
            "note": "信号明细来自 item_backtest_full_2025.json（去量 v2 370 信号回放），直接基于其分析，未重放全量引擎。",
            "win_rate_note": "现有回测胜率口径为 net（fwd - 2% 双边成本）：win14 79.5% / win30 61.4%。",
        },
        "signal_cluster": cluster,
        "event_level": events,
        "walk_forward": wf,
        "permutation": perm,
    }
    from datetime import datetime
    report["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    print()
    print("=== 聚类报告 (window=3) ===")
    print("信号 %d 条 / 唯一日期 %d 个 / 事件簇 %d 个 / 最大簇占比 %.1f%%" % (
        cluster["signal_count"], cluster["unique_dates"], cluster["cluster_count"],
        cluster["max_cluster_share"] * 100))
    for c in cluster["clusters"]:
        print("  簇 %d: %s ~ %s  signals=%d share=%.1f%%" % (c["index"], c["start"], c["end"], c["signals"], c["share"] * 100))
    if cluster["warnings"]:
        print("  [警告] " + "?".join(cluster["warnings"]))
    else:
        print("  无触发警告（但请结合簇分布人工判断集中度）")

    print()
    print("=== 事件级统计（每簇聚合一个事件）===")
    ev = events["net14_event_win"]
    print("net14 事件级: %d 事件, win %d/%d = %s%%, avg>0 口径" % (ev["n"], ev["wins"], ev["n"], _pct(ev["win_rate"])))

    print()
    print("=== Walk-forward (anchor=0.7, 严格时序) ===")
    for field, label in FIELDS:
        w = wf[field]
        if not w["valid"]:
            print("  %s: 无效 (%s)" % (label, w["reason"]))
            continue
        print("  %s: train %s | test %s | 严格时序=%s" % (
            label, fmt_stats(w["train"], field), fmt_stats(w["test"], field),
            w["strict_after"]))

    print()
    print("=== 置换检验 (sign-flip, n_perm=1000) ===")
    for field, label in FIELDS:
        p = perm[field]
        print("  %s: 观察胜率 %s%% vs 随机基线 %.1f%%±%.1f%%, p=%.4f" % (
            label, _pct(p["observed_win_rate"]), p["perm_mean_win_rate"] * 100,
            p["perm_std_win_rate"] * 100, p["p_value"] or -1))

    with open(REPORT_SAVE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print()
    print("saved: %s" % REPORT_SAVE)


if __name__ == "__main__":
    main()
