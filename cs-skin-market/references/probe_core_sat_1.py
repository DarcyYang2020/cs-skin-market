# -*- coding: utf-8 -*-
"""CORE-SAT-1 三组对照模拟（只读，replay_cycle_win.db）。

A=纯引擎 cap0.8；B=纯等权买入持有；C=核心70%+卫星30%（MA30>MA90 跟随 + Δspread>+8.9pp veto）。
"""
import os
import sys
import json
from collections import defaultdict
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
OUT = ROOT / "data" / "_exp_core_sat_1.json"
VETO = 8.9  # Δspread 走阔阈值（A2-2 资产）


def build_regime():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    dates = [r["date"] for r in rows]
    vals = [r["value"] for r in rows]
    regime = {}
    for i in range(90, len(vals)):
        ma30 = sum(vals[i - 29:i + 1]) / 30
        ma90 = sum(vals[i - 89:i + 1]) / 90
        regime[dates[i]] = ma30 > ma90
    return regime


def build_spread_veto():
    """item_id -> date -> Δspread（5 日价差变化 pp），用于品级 veto。"""
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = {r["id"]: r["good_id"] for r in c.execute("SELECT id, good_id FROM items WHERE good_id > 0").fetchall()}
    ph = {}
    for r in c.execute("SELECT item_id, date, price_rmb FROM price_history WHERE price_rmb IS NOT NULL ORDER BY date"):
        ph.setdefault(r["item_id"], {})[r["date"]] = r["price_rmb"]
    c.close()
    m = sqlite3.connect(MARKET_DB)
    m.row_factory = sqlite3.Row
    bid = {}
    for r in m.execute("SELECT good_id, date, buy_price_last FROM bid_history WHERE buy_price_last IS NOT NULL ORDER BY date"):
        bid.setdefault(r["good_id"], {})[r["date"]] = r["buy_price_last"]
    m.close()
    veto = defaultdict(dict)
    for iid, gid in items.items():
        prices = ph.get(iid, {})
        bp = bid.get(gid, {})
        ds = sorted(prices)
        for k in range(5, len(ds)):
            d = ds[k]
            d5 = ds[k - 5]
            p, p5 = prices[d], prices[d5]
            b, b5 = bp.get(d), bp.get(d5)
            if not all([p, p5, b, b5]) or p <= 0 or p5 <= 0:
                continue
            sp = (p - b) / p * 100
            sp5 = (p5 - b5) / p5 * 100
            veto[iid][d] = sp - sp5
    return veto, {iid: sorted(ph.get(iid, {})) for iid in items}


def main():
    regime = build_regime()
    veto, item_dates = build_spread_veto()

    # 卫星：regime ON 时等权持池内品（veto 跳过），OFF 现金
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM items WHERE good_id > 0").fetchall()}
    ph = {}
    for r in c.execute("SELECT item_id, date, price_rmb FROM price_history WHERE price_rmb IS NOT NULL ORDER BY date"):
        ph.setdefault(r["item_id"], {})[r["date"]] = r["price_rmb"]
    c.close()

    all_days = sorted({d for m in ph.values() for d in m})
    sat_curve = []  # [(date, equity)]
    equity = 1.0
    prev_day = None
    for d in all_days:
        on = regime.get(d, False)
        ret = 0.0
        if on:
            rets = []
            for iid, m in ph.items():
                keys = [k for k in m if k <= d]
                if len(keys) < 2:
                    continue
                if veto.get(iid, {}).get(d, 0) > VETO:
                    continue  # 品级 veto
                prev_k = keys[-2]
                prev_p = m[prev_k]
                cur_p = m[keys[-1]]
                if prev_p and prev_p > 0:
                    rets.append(cur_p / prev_p - 1.0)
            if rets:
                ret = sum(rets) / len(rets)
        equity *= (1.0 + ret)
        sat_curve.append((d, equity))

    # 核心（A）：纯引擎 cap0.8
    sigs, args = bc.load_signals(CYCLE)
    sim = bc.b1v2.simulate(sigs, cap=0.8)
    core_curve = [(c[0], c[2]) for c in sim["curve"]]
    core_dates = [c[0] for c in core_curve]

    # C = 0.7 * core + 0.3 * satellite（按日对齐，core 无仓位日按现金）
    sat_map = dict(sat_curve)
    core_map = dict(core_curve)
    combined = []
    for d, cv in core_curve:
        sv = sat_map.get(d, sat_curve[-1][1] if sat_curve else 1.0)
        combined.append((d, 0.7 * cv + 0.3 * sv))

    a_m = bc.metrics(core_curve)
    # B = 纯等权买入持有（复用 benchmark 口径）
    names = sorted({s["item"] for s in sigs})
    idmap = bc.id_by_name(names)
    prices = bc.price_series(list(idmap.keys()))
    full_start = date.fromisoformat(args.get("start", "2023-11-17"))
    full_end = date.fromisoformat(args.get("end", "2026-08-05"))
    pool_curve = bc.buy_hold(prices, full_start, full_end)
    b_m = bc.metrics(pool_curve)
    c_m = bc.metrics(combined)
    sat_m = bc.metrics(sat_curve)

    # 卫星四小牛市窗口明细（累计收益）
    windows = [("W1真趋势", "2025-08-10", "2025-10-24"), ("W2V反弹", "2025-11-01", "2025-12-31"),
               ("W3陷阱", "2026-02-01", "2026-03-31"), ("W4恐慌反弹", "2026-05-27", "2026-06-10")]
    sat_win = {}
    for wn, ws, we in windows:
        pts = [v for d, v in sat_curve if ws <= d <= we]
        if len(pts) >= 2:
            sat_win[wn] = {"on_days": sum(1 for d, _ in sat_curve if ws <= d <= we and regime.get(d, False)),
                           "pnl_pct": round((pts[-1] / pts[0] - 1) * 100, 2)}
        else:
            sat_win[wn] = {"on_days": 0, "pnl_pct": None}

    out = {"probe": "CORE-SAT-1 三组对照", "A_pure_engine": a_m, "B_pool_buy_hold": b_m,
           "C_core70_sat30": c_m, "satellite_standalone": sat_m, "satellite_windows": sat_win,
           "window": [full_start.isoformat(), full_end.isoformat()]}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== CORE-SAT-1 三组对照 ===")
    for leg, m in (("A 纯引擎", a_m), ("B 纯等权", b_m), ("C 核心70+卫星30", c_m), ("卫星(单独)", sat_m)):
        print(f"  {leg:18s} total={m['total_return_pct']:>9.2f}%  maxDD={m['max_drawdown_pct']:>8.2f}%  ann={m['annualized_pct']}")
    print("=== 卫星四小牛市窗口 ===")
    for wn, v in sat_win.items():
        print(f"  {wn:8s} on_days={v['on_days']:>3} pnl={v['pnl_pct']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
