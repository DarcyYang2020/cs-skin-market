# -*- coding: utf-8 -*-
"""CORE-SAT-1 不择时等权卫星三变体（只读）：C1 20% / C2 30% / C3 20%+veto。

卫星 = 池内等权（不择时），用仓位比例封顶回撤，不用 MA 择时。
"""
import os
import sys
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark_compare as bc  # noqa: E402
import sqlite3  # noqa: E402

CYCLE = ROOT / "data" / "_exp_cycle_replay_2026.json"
MARKET_DB = ROOT / "data" / "market.db"
OUT = ROOT / "data" / "_exp_core_sat_2.json"
VETO = 8.9


def build_veto():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"]); c.row_factory = sqlite3.Row
    items = {r["id"]: r["good_id"] for r in c.execute("SELECT id, good_id FROM items WHERE good_id>0").fetchall()}
    ph = {}
    for r in c.execute("SELECT item_id, date, price_rmb FROM price_history WHERE price_rmb IS NOT NULL ORDER BY date"):
        ph.setdefault(r["item_id"], {})[r["date"]] = r["price_rmb"]
    c.close()
    m = sqlite3.connect(MARKET_DB); m.row_factory = sqlite3.Row
    bid = {}
    for r in m.execute("SELECT good_id, date, buy_price_last FROM bid_history WHERE buy_price_last IS NOT NULL ORDER BY date"):
        bid.setdefault(r["good_id"], {})[r["date"]] = r["buy_price_last"]
    m.close()
    veto = {}
    for iid, gid in items.items():
        prices = ph.get(iid, {}); bp = bid.get(gid, {})
        ds = sorted(prices)
        for k in range(5, len(ds)):
            d, d5 = ds[k], ds[k-5]
            p, p5, b, b5 = prices[d], prices[d5], bp.get(d), bp.get(d5)
            if not all([p, p5, b, b5]) or p <= 0 or p5 <= 0:
                continue
            veto[(iid, d)] = (p - b) / p * 100 - (p5 - b5) / p5 * 100
    return ph, veto


def equal_weight_curve(ph, veto, use_veto):
    """池内等权（不择时）每日权益曲线，veto 跳过 Δspread>8.9 的品。"""
    all_days = sorted({d for m in ph.values() for d in m})
    equity = 1.0
    curve = []
    for d in all_days:
        rets = []
        for iid, m in ph.items():
            keys = [k for k in m if k <= d]
            if len(keys) < 2:
                continue
            if use_veto and veto.get((iid, d), 0) > VETO:
                continue
            p0, p1 = m[keys[-2]], m[keys[-1]]
            if p0 and p0 > 0:
                rets.append(p1 / p0 - 1.0)
        if rets:
            equity *= (1.0 + sum(rets) / len(rets))
        curve.append((d, equity))
    return curve


def combine(core_map, sat_map, w):
    """w = 卫星权重；core 无仓位日按现金 1.0。"""
    days = sorted(set(core_map) | set(sat_map))
    last_sat = 1.0
    out = []
    for d in days:
        cv = core_map.get(d)
        if cv is None:
            cv = core_map.get(days[days.index(d) - 1], 1.0) if days.index(d) > 0 else 1.0
        sv = sat_map.get(d, last_sat)
        last_sat = sv
        out.append((d, (1 - w) * cv + w * sv))
    return out


def main():
    ph, veto = build_veto()
    sigs, args = bc.load_signals(CYCLE)
    sim = bc.b1v2.simulate(sigs, cap=0.8)
    core_curve = [(c[0], c[2]) for c in sim["curve"]]
    core_map = dict(core_curve)
    sat_no_veto = equal_weight_curve(ph, veto, use_veto=False)
    sat_veto = equal_weight_curve(ph, veto, use_veto=True)
    sat_no_map = dict(sat_no_veto)
    sat_veto_map = dict(sat_veto)

    c1 = combine(core_map, sat_no_map, 0.20)
    c2 = combine(core_map, sat_no_map, 0.30)
    c3 = combine(core_map, sat_veto_map, 0.20)

    a_m = bc.metrics(core_curve)
    b_m = bc.metrics(sat_no_veto)
    c1_m, c2_m, c3_m = bc.metrics(c1), bc.metrics(c2), bc.metrics(c3)

    out = {"probe": "CORE-SAT-1 不择时等权三变体",
           "A_pure_engine": a_m, "B_equal_weight": b_m,
           "C1_20pct": c1_m, "C2_30pct": c2_m, "C3_20pct_veto": c3_m}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== 不择时等权卫星三变体 ===")
    for leg, m in (("A 纯引擎", a_m), ("B 纯等权", b_m), ("C1 20%", c1_m), ("C2 30%", c2_m), ("C3 20%+veto", c3_m)):
        print(f"  {leg:14s} total={m['total_return_pct']:>9.2f}%  maxDD={m['max_drawdown_pct']:>8.2f}%  ann={m['annualized_pct']}")
    print("判定线: total>=+400% 且 maxDD<=-25%")
    for leg, m in (("C1", c1_m), ("C2", c2_m), ("C3", c3_m)):
        ok = m['total_return_pct'] >= 400 and m['max_drawdown_pct'] >= -25
        print(f"  {leg}: {'PASS' if ok else 'FAIL'} (total {m['total_return_pct']}%, maxDD {m['max_drawdown_pct']}%)")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
