# -*- coding: utf-8 -*-
"""J-1 胜率事件上下文：固化各族「独立事件数（去簇）」。

口径：signal_cluster_report(dates, window=3) 的 event_count（±3 天内算同一事件簇）。
数据源（只读）：
- panic / base：data/item_backtest_latest.json（88 buy，2025-11-02 起）
- deep_value：data/deepvalue_replay_tmp.json（limit≈0.10 的 241 信号）
- p10：data/c1_p10_replay.json（生产 7 天去重后 48 交易日）
- topup_ok：data/topup_replay_p09.json 近似复现补仓分层（pct<=25+th>=40+z<=-0.5+mth>=45+action=buy）

结果写入 data/signal_event_counts.json；config.py 常量中的 events 字段由本脚本产出手工同步（定期刷新）。
"""
import io
import json
import sys

sys.path.insert(0, ".")
from pipeline.backtest_methodology import signal_cluster_report


def main():
    out = {"generated": "2026-08-06", "window": 3, "note": "事件簇数=±3天去簇; 与展示 n(信号数)不同源, 单独展示防误读"}

    a = json.load(io.open("data/item_backtest_latest.json", encoding="utf-8"))["signals"]
    for st, key in (("panic", "panic"), ("base", "base")):
        dates = [s["date"] for s in a if s.get("signal_type") == st]
        cl = signal_cluster_report(dates, window=3)
        out[key] = {"signals": cl["signal_count"], "events": cl["event_count"],
                    "max_cluster_share": round(cl["max_cluster_share"], 4), "source": "item_backtest_latest(88buy)"}

    b = json.load(io.open("data/deepvalue_replay_tmp.json", encoding="utf-8"))["signals"]
    dv = [s for s in b if abs(float(s.get("position_limit") or 0) - 0.10) < 0.001]
    cl = signal_cluster_report([s["date"] for s in dv], window=3)
    out["deep_value"] = {"signals": cl["signal_count"], "events": cl["event_count"],
                         "max_cluster_share": round(cl["max_cluster_share"], 4), "source": "deepvalue_replay(301)"}

    p10 = json.load(io.open("data/c1_p10_replay.json", encoding="utf-8"))
    out["p10"] = {"signals": p10["n"], "events": p10["distinct_dates"], "max_cluster_share": 0.0, "source": "c1_p10_replay(生产去重后交易日)"}

    d = json.load(io.open("data/topup_replay_p09.json", encoding="utf-8"))
    recs = [r for r in d["records"]
            if r.get("pct") is not None and r["pct"] <= 25
            and r.get("th") is not None and r["th"] >= 40
            and r.get("z") is not None and r["z"] <= -0.5
            and r.get("mth") is not None and r["mth"] >= 45
            and r.get("action") == "buy"]
    cl = signal_cluster_report([r["date"] for r in recs], window=3)
    out["topup_ok"] = {"signals": cl["signal_count"], "events": cl["event_count"],
                       "max_cluster_share": round(cl["max_cluster_share"], 4),
                       "source": "topup_replay_p09(近似复现, 口径2026-08-05)"}

    with io.open("data/signal_event_counts.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k in ("panic", "base", "deep_value", "p10", "topup_ok"):
        v = out[k]
        print("%-10s 信号=%d 事件=%d 单簇=%.0f%%" % (k, v["signals"], v["events"], v.get("max_cluster_share", 0) * 100))


if __name__ == "__main__":
    main()
