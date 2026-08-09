# -*- coding: utf-8 -*-
"""成本敏感性分析（Phase 1a，2026-08-07）。

读 data/item_backtest_full_2025.json（370 信号），对 fwd14/fwd30 施加不同双边成本
（1%/2%/3%/5%），重算全样本与去簇口径的胜率/期望，并求 avg 归零（盈亏平衡）成本。

结论（供决策，不修改引擎口径）:
  - 2% 双边成本假设偏保守：即使 5% 双边成本，14d 胜率仍 61.6%、期望 +13.7%。
  - 盈亏平衡成本 14d=18.7% / 30d=28.5%，远超真实费率，策略边际对成本不敏感。
  - 维持 2% 口径不变，无需 bump 回放 v2.1（改口径无收益且有断链风险）。
"""
import io
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "data" / "item_backtest_full_2025.json"
OUT = BASE / "data" / "cost_sensitivity.json"

sys.path.insert(0, str(BASE / "references"))
import j2_channel_monitor as _j2

COSTS = (1.0, 2.0, 3.0, 5.0)


def _agg(vals, cost):
    net = [x - cost for x in vals]
    return {
        "n": len(net),
        "win_pct": round(100.0 * sum(1 for x in net if x > 0) / len(net), 1),
        "avg": round(sum(net) / len(net), 2),
    }


def _breakeven(vals, lo=0.0, hi=100.0):
    for _ in range(60):
        mid = (lo + hi) / 2
        if sum(x - mid for x in vals) / len(vals) > 0:
            lo = mid
        else:
            hi = mid
    return round(lo, 2)


def main():
    replay = json.loads(io.open(REPLAY, encoding="utf-8").read())
    sigs = replay["signals"]
    f14 = [s["fwd14"] for s in sigs if s.get("fwd14") is not None]
    f30 = [s["fwd30"] for s in sigs if s.get("fwd30") is not None]
    d14 = _j2._cluster_dedup(sigs)
    df14 = [s["fwd14"] for s in d14 if s.get("fwd14") is not None]

    rows = []
    for c in COSTS:
        rows.append({
            "cost_pct": c,
            "14d_all": _agg(f14, c),
            "14d_dedup": _agg(df14, c),
            "30d_all": _agg(f30, c),
        })
    out = {
        "meta": "成本敏感性(Phase 1a): 对回放 370 信号 fwd 收益施加双边成本重算。结论: 2% 口径保守, 盈亏平衡远超真实费率, 维持 2% 口径。",
        "fwd14_dist": {
            "n": len(f14), "mean": round(sum(f14) / len(f14), 2),
            "median": round(sorted(f14)[len(f14) // 2], 2),
            "p10": round(sorted(f14)[len(f14) // 10], 2),
            "p90": round(sorted(f14)[int(len(f14) * 0.9) - 1], 2),
            "min": round(min(f14), 2), "max": round(max(f14), 2),
            "loss_share_pct": round(100.0 * sum(1 for x in f14 if x <= 0) / len(f14), 1),
        },
        "breakeven_cost_pct": {"14d": _breakeven(f14), "30d": _breakeven(f30)},
        "rows": rows,
        "conclusion": "2% 双边成本假设保守有效; 无需 bump 回放口径。",
    }
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written:", OUT)
    print("fwd14 dist:", out["fwd14_dist"])
    print("breakeven:", out["breakeven_cost_pct"])
    for r in rows:
        print('cost=%.1f%% 14d win=%.1f%% avg=%+.2f%% (去簇 win=%.1f%%) | 30d win=%.1f%% avg=%+.2f%%' % (
            r["cost_pct"], r["14d_all"]["win_pct"], r["14d_all"]["avg"],
            r["14d_dedup"]["win_pct"], r["30d_all"]["win_pct"], r["30d_all"]["avg"]))


if __name__ == "__main__":
    main()