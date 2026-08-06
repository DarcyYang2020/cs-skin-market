# -*- coding: utf-8 -*-
"""统一大脑研究 · 阶段1b：信号族 × 市场状态桶条件期望表（2026-08-06）。

数据：data/item_backtest_full_2025.json（阶段1a 全窗口回放，池A=96老品，581 信号）。
细分 6 族（按 action_label，比 signal_type 更细）：
  panic 恐慌共振 / oversold 超跌反弹 / deep_value 深值企稳(P0-8)
  supply_accum 供给收缩吸筹(P1-0/S3) / accumulate 周期吸筹(P0-5) / base 低位低估
状态桶：market_regime(sent, chg30, mth) 六态（I-1 口径，与展示层一致）。
输出：data/unified_brain_expectancy.json + 控制台摘要。
"""
import sys, io, json, statistics
from datetime import datetime
sys.path.insert(0, ".")
from collections import Counter, defaultdict
from pipeline.backtest_common import build_market_context
from pipeline.batch_scan import market_regime
from pipeline.backtest_methodology import signal_cluster_report

SRC = "data/item_backtest_full_2025.json"
COST = 0.02


def family_of(action_label):
    lab = action_label or ""
    if "恐慌" in lab: return "panic"
    if "超跌" in lab: return "oversold"
    if "深值" in lab: return "deep_value"
    if "供给收缩" in lab: return "supply_accum"
    if "吸筹" in lab: return "accumulate"
    return "base"


def bucket_of(sent, chg30, mth):
    lab, _, _ = market_regime(sent, chg30, mth)
    return lab


def weighted(vals, limits):
    ws = [l for l, v in zip(limits, vals) if v is not None]
    vs = [v for v in vals if v is not None]
    if not ws: return None
    return sum(w * v for w, v in zip(ws, vs)) / sum(ws)


def main():
    ctx = build_market_context("2025-01-01", end="2026-08-05")
    d = json.load(io.open(SRC, encoding="utf-8"))
    sigs = d["signals"]
    for s in sigs:
        s["family"] = family_of(s.get("action_label", ""))
        mc = ctx.get(s["date"], {})
        s["chg30"] = mc.get("chg30", 0.0)
        s["bucket"] = bucket_of(s.get("sentiment", 50), s["chg30"], s.get("market_th", 50))
    fam_counter = Counter(s["family"] for s in sigs)
    bkt_counter = Counter(s["bucket"] for s in sigs)
    print("family:", dict(fam_counter))
    print("bucket:", dict(bkt_counter))

    out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "source": SRC, "cost": COST, "n": len(sigs),
           "families": dict(fam_counter), "buckets": dict(bkt_counter),
           "table": {}}
    for fam in ("panic", "oversold", "deep_value", "supply_accum", "accumulate", "base"):
        fs = [s for s in sigs if s["family"] == fam]
        out["table"][fam] = {}
        for bkt in ("V型底区", "阴跌中继区", "恐慌浅跌",
                    "中性企稳", "弱市观望", "贪婪禁入"):
            recs = [s for s in fs if s["bucket"] == bkt]
            if not recs:
                out["table"][fam][bkt] = {"n": 0}
                continue
            n14 = [s["net14"] for s in recs if s.get("net14") is not None]
            n30 = [s["net30"] for s in recs if s.get("net30") is not None]
            limits = [s.get("position_limit") or 0 for s in recs]
            cl = signal_cluster_report([s["date"] for s in recs], window=3)
            blk = {
                "n": len(recs),
                "cluster": {"events": cl["event_count"], "unique_dates": cl["unique_dates"],
                            "max_cluster_share": round(cl["max_cluster_share"], 3),
                            "flagged": cl["flagged"]},
                "net14": {"n": len(n14),
                          "win%": round(sum(1 for v in n14 if v > 0) / len(n14) * 100, 1) if n14 else None,
                          "avg%": round(statistics.mean(n14), 2) if n14 else None,
                          "wavg%": round(weighted(n14, limits), 2) if n14 else None},
                "net30": {"n": len(n30),
                          "win%": round(sum(1 for v in n30 if v > 0) / len(n30) * 100, 1) if n30 else None,
                          "avg%": round(statistics.mean(n30), 2) if n30 else None,
                          "wavg%": round(weighted(n30, limits), 2) if n30 else None},
            }
            out["table"][fam][bkt] = blk
            if blk["n"] >= 3:
                print(f"  {fam:14s} {bkt:8s} n={blk['n']:4d} ev={blk['cluster']['events']:2d} "
                      f"14d {blk['net14']['win%']:4.0f}%/{blk['net14']['avg%']:+6.1f} "
                      f"30d {blk['net30']['win%']:4.0f}%/{blk['net30']['avg%']:+6.1f}")
    with open("data/unified_brain_expectancy.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nsaved: data/unified_brain_expectancy.json")


if __name__ == "__main__":
    main()
