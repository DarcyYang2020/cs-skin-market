# -*- coding: utf-8 -*-
"""大盘时期路由 发射口径重放对比（2026-08-16，只读；预注册判据）。

输入：官方基线 data/_exp_cycle_replay_2026.json（v2-T12，233 信号）
      vs 路由变体 data/_exp_cycle_replay_period_route.json（CS_ENGINE_PERIOD_ROUTE=1）
口径：benchmark_compare 同源（b1v2.simulate cap0.8 / HOLD21 / 2% 成本，bc.metrics）。

预注册判据（decision-log 条目，样本内选择只产生候选）：
  1. 组合级：routed total ≥ base total 且 routed maxDD ≥ base maxDD − 1.0pp（不放大回撤）；
  2. 前后半段一致：切点=基线信号日中位数 2026-03-02，front/back 两段 total 均 ≥ 基线同段 − 2pp；
  3. 被移除信号诚实清单：族×时期 n/win14/avg14/win30/avg30（net，已扣 2%）。
通过 1+2 才具备落地候选资格（仍须 live pilot/C 通道监测）。
输出 data/_exp_period_route_compare.json。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark_compare as bc  # noqa: E402
from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.signal_tracking import family_key_for_label  # noqa: E402

BASE = ROOT / "data" / "_exp_cycle_replay_2026.json"
VAR = ROOT / "data" / "_exp_cycle_replay_period_route.json"
OUT = ROOT / "data" / "_exp_period_route_compare.json"
CUT = "2026-03-02"  # 基线信号日中位数（预注册切点）


def load_m180():
    import sqlite3
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
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


def segment_metrics(curve, lo=None, hi=None):
    pts = [(d, v) for d, v in curve if (lo is None or d >= lo) and (hi is None or d < hi)]
    if len(pts) < 2:
        return {"total_return_pct": None, "max_drawdown_pct": None}
    m = bc.metrics(pts)
    return {"total_return_pct": m["total_return_pct"], "max_drawdown_pct": m["max_drawdown_pct"]}


def win_avg(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def main():
    base = json.load(open(BASE, encoding="utf-8"))
    var = json.load(open(VAR, encoding="utf-8")) if VAR.exists() else None
    if var is None:
        print("变体产物缺失:", VAR, "——先跑 CS_ENGINE_PERIOD_ROUTE=1 重放")
        return

    sigs_b, _ = bc.load_signals(BASE)
    sigs_v, _ = bc.load_signals(VAR)
    sim_b = bc.b1v2.simulate(sigs_b, cap=0.8)
    sim_v = bc.b1v2.simulate(sigs_v, cap=0.8)
    curve_b = [(c[0], c[2]) for c in sim_b["curve"]]
    curve_v = [(c[0], c[2]) for c in sim_v["curve"]]

    mb = bc.metrics(curve_b)
    mv = bc.metrics(curve_v)
    fb = segment_metrics(curve_b, None, CUT)
    fv = segment_metrics(curve_v, None, CUT)
    bb = segment_metrics(curve_b, CUT, None)
    bv = segment_metrics(curve_v, CUT, None)

    # 被移除信号清单（key = date|name，原始产物字段 net14/net30/mkt_chg30）
    raw_b = base["signals"]
    raw_v = {(s["date"], s["name"]) for s in var["signals"]}
    m180 = load_m180()
    removed_stats = {}
    for s in raw_b:
        if (s["date"], s["name"]) in raw_v:
            continue
        lab = family_key_for_label(s.get("action_label") or "")
        period = state_bucket(m180.get(s["date"]), s.get("mkt_chg30"))
        removed_stats.setdefault(f"{lab}×{period}", []).append(s)

    out = {
        "probe": "大盘时期路由发射口径对比（预注册判据：组合级 + 前后半段一致 + 置换检验）",
        "cut": CUT, "base": {"signals": len(sigs_b), **mb},
        "variant": {"signals": len(sigs_v), **mv},
        "front": {"base": fb, "variant": fv}, "back": {"base": bb, "variant": bv},
        "removed": {k: {"n": len(v),
                        "win14": win_avg([s["net14"] for s in v if s.get("net14") is not None]),
                        "win30": win_avg([s["net30"] for s in v if s.get("net30") is not None])}
                    for k, v in sorted(removed_stats.items())},
    }
    ok1 = mv["total_return_pct"] >= mb["total_return_pct"] and \
        mv["max_drawdown_pct"] >= mb["max_drawdown_pct"] - 1.0
    ok2 = (fv["total_return_pct"] is not None and fb["total_return_pct"] is not None and
           fv["total_return_pct"] >= fb["total_return_pct"] - 2.0 and
           bv["total_return_pct"] is not None and bb["total_return_pct"] is not None and
           bv["total_return_pct"] >= bb["total_return_pct"] - 2.0)

    # ---- 置换检验（A2 第五件套纪律）：随机移除同数量信号的提升分布 ----
    # 路由提升 = 定向移除 44 条坏信号；若随机移除同规模也能普遍达到该提升，
    # 说明提升只是「少买=少亏」的机械效果，路由无选择价值 → 判据3 不通过。
    import random as _rnd
    n_removed = len(sigs_b) - len(sigs_v)
    d_total = mv["total_return_pct"] - mb["total_return_pct"]
    d_dd = mv["max_drawdown_pct"] - mb["max_drawdown_pct"]  # 正值=回撤改善
    rand_totals, rand_dds = [], []
    for _seed in range(200):
        _r = _rnd.Random(_seed)
        _idx = set(_r.sample(range(len(sigs_b)), n_removed))
        _sub = [s for i, s in enumerate(sigs_b) if i not in _idx]
        _sim = bc.b1v2.simulate(_sub, cap=0.8)
        _curve = [(c[0], c[2]) for c in _sim["curve"]]
        _m = bc.metrics(_curve)
        rand_totals.append(_m["total_return_pct"] - mb["total_return_pct"])
        rand_dds.append(_m["max_drawdown_pct"] - mb["max_drawdown_pct"])
    p_total = sum(1 for x in rand_totals if x >= d_total) / len(rand_totals)
    p_dd = sum(1 for x in rand_dds if x >= d_dd) / len(rand_dds)
    rand_totals.sort()
    rand_dds.sort()
    out["permutation"] = {
        "n_removed": n_removed, "trials": 200,
        "route": {"d_total": round(d_total, 2), "d_maxdd": round(d_dd, 2)},
        "random": {
            "d_total_med": round(rand_totals[100], 2), "d_total_p90": round(rand_totals[180], 2),
            "d_dd_med": round(rand_dds[100], 2), "d_dd_p90": round(rand_dds[180], 2),
            "p_total": round(p_total, 3), "p_dd": round(p_dd, 3),
        },
    }
    ok3 = p_total <= 0.05 or p_dd <= 0.05  # 任一维度显著优于随机移除
    out["verdict"] = {"criteria1_combo": bool(ok1), "criteria2_frontback": bool(ok2),
                      "criteria3_permutation": bool(ok3),
                      "candidate": bool(ok1 and ok2 and ok3)}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("== 组合级（cap0.8 / hold21 / 2%%）==")
    print("  base     n=%d total=%+.2f%% maxDD=%+.2f%%" % (len(sigs_b), mb["total_return_pct"], mb["max_drawdown_pct"]))
    print("  variant  n=%d total=%+.2f%% maxDD=%+.2f%%" % (len(sigs_v), mv["total_return_pct"], mv["max_drawdown_pct"]))
    print("== 前后半段（切点 %s）==" % CUT)
    print("  front: base %+.2f%% vs variant %+.2f%%" % (fb["total_return_pct"], fv["total_return_pct"]))
    print("  back : base %+.2f%% vs variant %+.2f%%" % (bb["total_return_pct"], bv["total_return_pct"]))
    print("== 被移除信号（net 已扣2%）==")
    for k, v in out["removed"].items():
        print("  %-28s n=%d | 14d %s | 30d %s" % (k, v["n"], _f(v["win14"]), _f(v["win30"])))
    _pm = out["permutation"]
    print("== 置换检验（200 次随机移除同规模）==")
    print("  路由: dTotal=%+.2fpp dMaxDD=%+.2fpp | 随机: dTotal 中位%+.2f/p90 %+.2f, "
          "dMaxDD 中位%+.2f/p90 %+.2f | p_total=%.3f p_dd=%.3f" % (
              _pm["route"]["d_total"], _pm["route"]["d_maxdd"],
              _pm["random"]["d_total_med"], _pm["random"]["d_total_p90"],
              _pm["random"]["d_dd_med"], _pm["random"]["d_dd_p90"],
              _pm["random"]["p_total"], _pm["random"]["p_dd"]))
    print("== 判定 == 组合级:%s 前后半段:%s 置换:%s → %s" % (
        ok1, ok2, ok3, "候选通过" if ok1 and ok2 and ok3 else "未通过"))


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
