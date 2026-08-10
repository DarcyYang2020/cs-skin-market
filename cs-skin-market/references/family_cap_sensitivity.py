# -*- coding: utf-8 -*-
"""分级仓位比例敏感性（2026-08-10）：族级 position_limit 缩放 × hold21 组合模拟。

数据源: data/item_backtest_full_2025.json（332 信号，365d 同源回放）
口径:   cap0.8 / hold21 / 费2% / 优先级拒绝 / 现金计息（与组合层研究一致，hold21 已落地）
方法:   按族（panic/deep_value/accumulate）对 position_limit 乘缩放系数，逐配置跑组合模拟；
        族贡献=closed 逐笔按 st 汇总（与基准 ×1.0 对照）。
产物:   data/_exp_family_cap_sensitivity.json（实验归档，不参与引擎）
"""
import io, json, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
from references.portfolio_sensitivity import load_sigs, exit_simulate, metrics  # noqa

REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
COST = 0.02

def scaled(sigs, scales):
    out = []
    for s in sigs:
        ss = dict(s)
        ss["limit"] = round(s["limit"] * scales.get(s["st"], 1.0), 4)
        out.append(ss)
    return out

def family_pnl(res):
    fam = defaultdict(list)
    for c in res["closed"]:
        fam[c["st"]].append(c["pnl"])
    return {k: {"n": len(v), "sum_pct": round(sum(v) * 100, 1)} for k, v in fam.items()}

def main():
    sigs = load_sigs()
    base_rule = {"type": "hold", "days": 21}
    # 网格：族级缩放（panic 含 resonance 0.3 + easing 0.1；deep_value 0.1；accumulate 0.1/0.12/0.2）
    grid = {
        "baseline_x1.0": {"panic": 1.0, "deep_value": 1.0, "accumulate": 1.0},
        # panic 缩放
        "panic_x0.5": {"panic": 0.5},
        "panic_x0.75": {"panic": 0.75},
        "panic_x1.25": {"panic": 1.25},
        # deep_value 缩放
        "deep_x0.5": {"deep_value": 0.5},
        "deep_x1.5": {"deep_value": 1.5},
        "deep_x2.0": {"deep_value": 2.0},
        # accumulate 缩放
        "accum_x0.5": {"accumulate": 0.5},
        "accum_x0.8": {"accumulate": 0.8},
        "accum_x1.25": {"accumulate": 1.25},
        "accum_x1.5": {"accumulate": 1.5},
        # 组合尝试
        "panic_x0.75_accum_x1.25": {"panic": 0.75, "accumulate": 1.25},
        "accum_x1.25_deep_x0.5": {"accumulate": 1.25, "deep_value": 0.5},
        "panic_x1.0_accum_x1.5": {"accumulate": 1.5},
    }
    results = {}
    for name, scales in grid.items():
        sg = scaled(sigs, scales)
        res = exit_simulate(sg, cap=0.8, rule=base_rule)
        m = metrics(res)
        m["by_family"] = family_pnl(res)
        results[name] = m
        print("%-24s total %8.2f  maxDD %7.2f  trades %3d  win %5.1f%%  avg %6.2f  rejCap %d  %s" % (
            name, m["total_return_pct"], m["max_drawdown_pct"], m["n_trades"], m["win_pct"],
            m["avg_trade_pct"], m["rejected_cap"],
            {k: "%d(%.0f)" % (v["n"], v["sum_pct"]) for k, v in m["by_family"].items()}))
    out = {"generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
           "note": "分级仓位比例敏感性：族级 position_limit 缩放 × cap0.8/hold21/费2%；基线=现行分级（panic 0.3+0.1/deep 0.1/accum 0.1-0.2）。by_family.sum_pct=族累计盈亏占比%。",
           "signals": len(sigs), "baseline_hold21": results["baseline_x1.0"], "grid": results}
    with io.open(ROOT / "data" / "_exp_family_cap_sensitivity.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written: data/_exp_family_cap_sensitivity.json")

if __name__ == "__main__":
    main()
