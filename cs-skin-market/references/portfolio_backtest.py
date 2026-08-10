# -*- coding: utf-8 -*-
"""组合层回测（Phase 2a，2026-08-07）。

在 benchmark_compare（cap0.8 组合模拟）基础上升级组合口径指标：
  - 权益曲线派生: 年化/最大回撤/Calmar/Sharpe/Sortino/月度收益
  - 组合级胜率: 逐笔平仓盈亏（simulate 新增 closed 输出）
  - 去簇纪律变体: 同事件簇（日期间隔<4天）内限 K 笔（默认5），对照现行 cap0.8
  - 与 benchmark_compare full.strategy 一致性校验

口径: hold21（2026-08-10 对齐单品 hold_guidance，见 decision-log）/ 双边成本2% / 拒绝优先级 panic>accumulate>deep_value / 未部署资金按现金。
结论写入 data/portfolio_backtest.json。
"""
import io
import json
import math
import statistics
from collections import defaultdict
from datetime import date
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE
REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
OUT = ROOT / "data" / "portfolio_backtest.json"
BENCH = ROOT / "data" / "benchmark_compare.json"

_spec = spec_from_file_location("b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
b1v2 = module_from_spec(_spec)
_spec.loader.exec_module(b1v2)

CLUSTER_GAP = 4   # 同簇定义（与 j2_channel_monitor 一致）: 日期间隔 <4 天
CLUSTER_K = 5     # 簇内限次: 每簇最多 K 笔（按优先级保留）
HOLD = 21


def load_signals():
    d = json.load(io.open(REPLAY, encoding="utf-8"))
    sigs = []
    for s in d["signals"]:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = b1v2.classify(s.get("action_label"))
        sigs.append({
            "date": date.fromisoformat(s["date"]), "item": s["name"],
            "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
            "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1),
            "net14": s.get("net14"),
        })
    return sigs


def cluster_cap(sigs, gap_days=CLUSTER_GAP, k=CLUSTER_K):
    """同事件簇内限 K 笔（按优先级保留前 K），返回子集。"""
    ordered = sorted(sigs, key=lambda x: x["date"])
    clusters = []
    cur, last = [], None
    for s in ordered:
        if last is None or (s["date"] - last).days >= gap_days:
            if cur:
                clusters.append(cur)
            cur = [s]
        else:
            cur.append(s)
        last = s["date"]
    if cur:
        clusters.append(cur)
    kept = []
    for cl in clusters:
        cl = sorted(cl, key=lambda x: (-x["prio"], x["date"], x["item"]))
        kept.extend(cl[:k])
    return sorted(kept, key=lambda x: x["date"])


def risk_metrics(curve):
    """curve: [(date, pos, eq, gate, n_active)] → 组合指标。"""
    eqs = [c[2] for c in curve]
    if len(eqs) < 2:
        return {"days": len(eqs)}
    rets = [eqs[i] / eqs[i - 1] - 1 for i in range(1, len(eqs))]
    total = (eqs[-1] / eqs[0] - 1) * 100
    days = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(curve[0][0])).days
    ann = ((eqs[-1] / eqs[0]) ** (365.0 / days) - 1) * 100 if days > 0 else None
    peak, max_dd = eqs[0], 0.0
    for v in eqs:
        peak = max(peak, v)
        max_dd = min(max_dd, (v / peak - 1) * 100)
    mean = statistics.mean(rets)
    sd = statistics.pstdev(rets)
    down = [r for r in rets if r < 0]
    dsd = statistics.pstdev(down) if len(down) > 1 else 0.0
    sharpe = mean / sd * math.sqrt(365) if sd > 0 else None
    sortino = mean / dsd * math.sqrt(365) if dsd > 0 else None
    calmar = ann / abs(max_dd) if ann is not None and max_dd < 0 else None
    # 月度收益（月末净资产环比）
    by_month = defaultdict(list)
    for c in curve:
        by_month[c[0][:7]].append(c[2])
    monthly = {}
    prev = None
    for m in sorted(by_month):
        end = by_month[m][-1]
        if prev is not None:
            monthly[m] = round((end / prev - 1) * 100, 2)
        prev = end
    return {
        "days": len(eqs), "total_return_pct": round(total, 2),
        "ann_return_pct": round(ann, 2) if ann is not None else None,
        "max_drawdown_pct": round(max_dd, 2),
        "calmar": round(calmar, 2) if calmar is not None else None,
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "sortino": round(sortino, 2) if sortino is not None else None,
        "monthly_returns": monthly,
    }


def run_variant(sigs, label, cap, wstart=None, wend=None):
    sim = b1v2.simulate(sigs, cap=cap)
    # 窗口口径对齐 benchmark_compare（full 窗口 = 回放 args.start~end 固定区间）：
    # 组合总收益与基准同窗对比，消除末笔平仓日落在窗口外导致的边界漂移（t_portfolio_backtest 一致性校验）。
    curve = sim["curve"]
    if wstart is not None:
        curve = [c for c in curve if wstart <= c[0] <= (wend or "9999-12-31")]
    sim = dict(sim, curve=curve)
    m = risk_metrics(curve)
    closed = sim.get("closed") or []
    m.update({
        "n_signals": len(sigs),
        "n_trades": len(closed),
        "portfolio_win_rate_pct": round(100.0 * sum(1 for x in closed if x > 0) / len(closed), 1) if closed else None,
        "avg_trade_pct": round(sum(closed) / len(closed) * 100, 2) if closed else None,
        "max_position": round(sim["max_pos"], 3),
        "rejected_cap": sim["rejected_cap"],
        "rejected_breaker": sim["rejected_breaker"],
        "max_concurrent_positions": max((c[4] for c in sim["curve"]), default=0),
    })
    return m


def main():
    sigs = load_signals()
    dargs = json.load(io.open(REPLAY, encoding="utf-8")).get("args", {})
    wstart = dargs.get("start")
    wend = dargs.get("end")
    cur = run_variant(sigs, "cap0.8", cap=0.8, wstart=wstart, wend=wend)
    cl5 = cluster_cap(sigs, k=CLUSTER_K)
    cluster_v = run_variant(cl5, "cap0.8+簇限次5", cap=0.8, wstart=wstart, wend=wend)
    nocap = run_variant(sigs, "nocap_ref", cap=None, wstart=wstart, wend=wend)

    bench = {}
    try:
        b = json.load(io.open(BENCH, encoding="utf-8"))
        bench["benchmark_full_strategy_total_pct"] = b["windows"]["full"]["strategy"]["total_return_pct"]
        bench["our_cap08_total_pct"] = cur["total_return_pct"]
        bench["consistent"] = abs(bench["benchmark_full_strategy_total_pct"] - cur["total_return_pct"]) < 0.5
    except Exception as e:
        bench["error"] = str(e)

    out = {
        "meta": "组合层回测(Phase 2a): hold21/成本2%/拒绝优先级panic>accumulate>deep_value/未部署资金按现金。簇限次=同簇(间隔<4天)内限5笔。窗口口径=回放 args.start~end 固定区间（与 benchmark_compare full 窗口对齐，2026-08-10）。",
        "generated": date.today().isoformat(),
        "variants": {"cap0_8": cur, "cap0_8_cluster5": cluster_v, "nocap_ref": nocap},
        "consistency_with_benchmark": bench,
        "conclusion": "簇限次纪律显著降低事件簇集中度与最大回撤（若结论支持）；组合口径指标供 J-2 C 通道参考。",
    }
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written:", OUT)
    for k, v in out["variants"].items():
        print('%s: total=%s%% ann=%s%% maxDD=%s%% calmar=%s sharpe=%s sortino=%s n_trades=%s win=%s%% maxPos=%s rejCap=%s' % (
            k, v["total_return_pct"], v["ann_return_pct"], v["max_drawdown_pct"], v["calmar"],
            v["sharpe"], v["sortino"], v["n_trades"], v["portfolio_win_rate_pct"],
            v["max_position"], v["rejected_cap"]))
    print('benchmark consistency:', bench)


if __name__ == "__main__":
    main()