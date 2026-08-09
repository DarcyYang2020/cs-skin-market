# -*- coding: utf-8 -*-
"""Phase 3 重拟合流水线（A2 三件套落地，2026-08-07）。

触发：J-2 三通道任一达标（见 references/j2_channel_monitor.py 的 overall.trigger_action），
人工确认后运行本脚本，用"冻结后新增"的信号执行重拟合验证：
  - walk-forward: 按时间 70/30 切 train/test，比较样本内外胜率；
  - 聚类: 信号时间聚类，量化事件集中度（单事件主导时胜率不可外推）；
  - 置换检验: 符号置换 p 值，估计"随机信号也能达到该胜率"的概率。

用法:
  python references/refit_pipeline.py                 # 生产模式：读 signal_tracking 冻结后新增信号
  python references/refit_pipeline.py --simulate      # 演练：用现有 370 信号回放跑一遍，验证流水线
  python references/refit_pipeline.py --frozen-at YYYY-MM-DD

输出 data/refit_pipeline_report.json（gate.passed 判定达标/未达标）。
"""
import argparse
import io
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from pipeline.config import ENGINE_VERSION, PARAM_REGIME, J2_THRESHOLDS
from pipeline.backtest_methodology import (
    walk_forward_split,
    permutation_baseline,
    signal_cluster_report,
)

REPLAY = BASE / "data" / "item_backtest_full_2025.json"
OUT = BASE / "data" / "refit_pipeline_report.json"

C14_2M = J2_THRESHOLDS["c14_2m"]   # 样本外胜率阈值（%，对齐 C 通道连续 2 月 14d）
MIN_TEST_N = 10                    # 样本外净收益样本数下限
ANCHOR_RATIO = 0.7                 # walk-forward 切分比例（沿用 A2 方法论）
N_PERM = 1000                      # 置换检验次数


def _load(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_production_signals(monitor_start):
    """生产模式：signal_tracking 表中 signal_date >= monitor_start 的 buy 信号。"""
    dbp = BASE / "data" / "market.db"
    if not dbp.exists():
        return []
    conn = sqlite3.connect(str(dbp))
    try:
        rows = conn.execute(
            "SELECT signal_date, action, action_label, entry_price, engine_version, "
            "       fwd14, fwd30, net14, net30 "
            "FROM signal_tracking WHERE signal_date >= ? ORDER BY signal_date",
            (monitor_start,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "date": r[0], "action": r[1], "action_label": r[2],
            "entry_price": r[3], "engine_version": r[4],
            "fwd14": r[5], "fwd30": r[6], "net14": r[7], "net30": r[8],
        }
        for r in rows
    ]


def compute(mode="production", monitor_start=None):
    monitor_start = monitor_start or PARAM_REGIME["monitor_start"]
    if mode == "simulate":
        d = _load(REPLAY)
        sigs = d["signals"]
        replay_generated = d.get("generated")
    else:
        sigs = _load_production_signals(monitor_start)
        replay_generated = None
    records = []
    for s in sigs:
        ret = s.get("net14")
        if ret is None:
            ret = s.get("fwd14")
        records.append({"date": s["date"], "ret": ret})

    wf = walk_forward_split(
        [{"date": r["date"], "fwd14": r["ret"]} for r in records],
        anchor_ratio=ANCHOR_RATIO, return_field="fwd14", min_samples=MIN_TEST_N,
    )
    perm = permutation_baseline([r["ret"] for r in records], n_perm=N_PERM, seed=42)
    cluster = signal_cluster_report([r["date"] for r in records], window=3)

    test = wf.get("test") or {}
    test_wr = test.get("win_rate")
    gate = {
        "valid": bool(wf.get("valid")),
        "samples_ok": bool((test.get("n_with_return") or 0) >= MIN_TEST_N),
        "p_ok": bool(perm.get("p_value") is not None and perm["p_value"] < 0.05),
        "cluster_ok": not cluster.get("flagged"),
        "winrate_ok": bool(test_wr is not None and test_wr * 100 >= C14_2M),
    }
    reasons = []
    if not gate["valid"]:
        reasons.append("样本外分段不足: " + str(wf.get("reason") or "无"))
    if not gate["samples_ok"]:
        reasons.append("样本外净收益样本 < " + str(MIN_TEST_N))
    if not gate["p_ok"]:
        reasons.append("置换 p 值 >= 0.05（随机符号也能达到该胜率）")
    if not gate["cluster_ok"]:
        reasons.append("信号聚类告警（单事件主导，胜率不可外推）")
    if not gate["winrate_ok"]:
        reasons.append("样本外胜率 < " + str(int(C14_2M)) + "%")
    gate["reasons"] = reasons
    gate["passed"] = all(gate[k] for k in ("valid", "samples_ok", "p_ok", "cluster_ok", "winrate_ok"))

    return {
        "generated": date.today().isoformat(),
        "engine_version": ENGINE_VERSION,
        "mode": mode,
        "monitor_start": monitor_start,
        "replay_generated": replay_generated,
        "input": {"signals": len(records), "with_ret": sum(1 for r in records if r["ret"] is not None)},
        "walk_forward": wf,
        "cluster": cluster,
        "permutation": perm,
        "gate": gate,
        "action": (
            "达标：进入人工确认 -> 发布新参数版本（bump ENGINE_VERSION）并复位 J-2 监测"
            if gate["passed"]
            else "未达标：维持冻结，继续积累独立样本（A/B 通道自然累积）"
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Phase 3 重拟合流水线")
    ap.add_argument("--simulate", action="store_true", help="用现有回放信号演练流水线")
    ap.add_argument("--monitor-start", default=None, help="v2 引擎起点 YYYY-MM-DD（默认取 config.PARAM_REGIME）")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    mode = "simulate" if args.simulate else "production"
    rep = compute(mode=mode, monitor_start=args.monitor_start)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    g = rep["gate"]
    wf = rep["walk_forward"]
    print("refit pipeline: mode=%s signals=%d monitor_start=%s" % (mode, rep["input"]["signals"], rep["monitor_start"]))
    print("  walk-forward valid=%s train_wr=%s test_wr=%s p_value=%s" % (
        g["valid"],
        (wf.get("train") or {}).get("win_rate"),
        (wf.get("test") or {}).get("win_rate"),
        rep["permutation"].get("p_value"),
    ))
    print("  gate.passed=%s reasons=%s" % (g["passed"], "; ".join(g["reasons"]) if g["reasons"] else "无"))
    print("written:", args.out)


if __name__ == "__main__":
    main()
