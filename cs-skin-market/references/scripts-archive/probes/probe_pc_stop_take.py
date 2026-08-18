#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P-C: hold21 vs stop/take portfolio A/B on aligned signals.

Reconstructs a 14d ATR% per signal, then applies the item-level
sentiment-adaptive stop/take rules as an exit path. Read-only research.
"""
import io
import json
import sys
from datetime import date, timedelta
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OFFICIAL = ROOT / "data" / "item_backtest_full_2025.json"
COVERAGE = ROOT / "data" / "_exp_guard_coverage.json"
OUT = ROOT / "data" / "_exp_stop_take_ab.json"

from pipeline import db

_spec = spec_from_file_location("b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
b1v2 = module_from_spec(_spec)
_spec.loader.exec_module(b1v2)
_spec2 = spec_from_file_location("pfb", str(ROOT / "references" / "portfolio_backtest.py"))
pfb = module_from_spec(_spec2)
_spec2.loader.exec_module(pfb)


def load_series_map():
    conn = db.get_conn()
    rows = conn.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    conn.close()
    return {r["name"]: r["id"] for r in rows}


def series_for(item_id):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT date, price_rmb FROM price_history
           WHERE item_id=? AND id IN (
             SELECT MAX(id) FROM price_history WHERE item_id=? GROUP BY date
           ) ORDER BY date""",
        (item_id, item_id),
    ).fetchall()
    conn.close()
    return [r["date"] for r in rows], [r["price_rmb"] for r in rows]


def atr_pct(item_id, signal_date):
    dates, prices = series_for(item_id)
    if signal_date not in dates:
        return None
    idx = dates.index(signal_date)
    lo = max(1, idx - 14)
    rets = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(lo, idx) if prices[i - 1] > 0]
    if not rets:
        return None
    atr = sum(abs(r) for r in rets) / len(rets)
    return max(0.01, min(0.10, atr))


def build_signals():
    official = json.load(io.open(OFFICIAL, encoding="utf-8"))
    cov = json.load(io.open(COVERAGE, encoding="utf-8"))
    aligned = {(s["name"], s["date"]) for s in cov["signals"] if s.get("aligned_action") in ("buy", "oversold_buy")}
    name_to_id = load_series_map()
    sigs = []
    for s in official.get("signals", []):
        if (s["name"], s["date"]) not in aligned:
            continue
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = b1v2.classify(s.get("action_label"))
        item_id = name_to_id.get(s["name"])
        atr = atr_pct(item_id, s["date"]) if item_id else None
        sent = s.get("sentiment")
        if sent is None:
            sent = 50
        sigs.append({
            "date": date.fromisoformat(s["date"]),
            "item": s["name"],
            "entry": s["entry_price"],
            "limit": s.get("position_limit") or 0.0,
            "fwd": fwd,
            "st": st,
            "prio": b1v2.PRIORITY.get(st, 1),
            "sent": sent,
            "atr_pct": atr,
        })
    return sigs, official.get("args", {})


def exit_params(sig):
    sent = sig["sent"]
    if sent >= 75:
        return {"stop": 0.30, "take": 0.40, "name": "fear"}
    if sent <= 30:
        return {"stop": 0.08, "take": None, "name": "greed"}
    stop = None
    if sig.get("atr_pct"):
        stop = max(0.20, 2.5 * sig["atr_pct"])
    return {"stop": stop, "take": 0.15, "name": "neutral"}


def simulate_stop_take(sigs, cap=0.8):
    by_day = {}
    for s in sigs:
        by_day.setdefault(s["date"], []).append(s)
    first = min(s["date"] for s in sigs)
    last = max(s["date"] for s in sigs) + timedelta(days=21)
    day = first
    active = []
    total_invested = 0.0
    realized = 0.0
    rejected_cap = 0
    closed = []
    curve = []
    max_pos = 0.0
    while day <= last:
        for a in active:
            a["idx"] += 1
        for s in sorted(by_day.get(day, []), key=lambda x: -x["prio"]):
            if cap is not None and total_invested + s["limit"] > cap + 1e-9:
                rejected_cap += 1
                continue
            active.append({"s": s, "idx": 0, "base": s["limit"]})
            total_invested += s["limit"]
        unreal = 0.0
        pos_sum = 0.0
        closes = []
        for a in active:
            pos_sum += a["base"]
            k = a["idx"]
            if k <= 0:
                continue
            fwd = a["s"]["fwd"]
            px = fwd[min(k - 1, len(fwd) - 1)]
            ret = px / a["s"]["entry"] - 1
            params = exit_params(a["s"])
            hit_stop = params["stop"] is not None and ret <= -params["stop"]
            hit_take = params["take"] is not None and ret >= params["take"]
            if hit_stop or hit_take or k >= 21:
                pnl = a["base"] * (ret - 0.02)
                realized += pnl
                closed.append(pnl)
                total_invested -= a["base"]
                closes.append(a)
            else:
                unreal += a["base"] * ret
        for a in closes:
            active.remove(a)
        eq = 1.0 + realized + unreal
        curve.append((day.isoformat(), pos_sum, eq, 0, len(active)))
        max_pos = max(max_pos, pos_sum)
        day += timedelta(days=1)
    return {"curve": curve, "closed": closed, "rejected_cap": rejected_cap, "max_pos": max_pos}


def metrics_from_curve(curve, sim, wstart, wend):
    if wstart is not None:
        curve = [c for c in curve if wstart <= c[0] <= (wend or "9999-12-31")]
    m = pfb.risk_metrics(curve)
    closed = sim["closed"]
    m.update({
        "n_trades": len(closed),
        "portfolio_win_rate_pct": round(100.0 * sum(1 for x in closed if x > 0) / len(closed), 1) if closed else None,
        "avg_trade_pct": round(sum(closed) / len(closed) * 100, 2) if closed else None,
        "max_position": round(sim["max_pos"], 3),
        "rejected_cap": sim["rejected_cap"],
    })
    return m


def main():
    sigs, args = build_signals()
    wstart = args.get("start")
    wend = args.get("end")
    hold_sim = b1v2.simulate(sigs, cap=0.8)
    hold_curve = hold_sim["curve"]
    if wstart is not None:
        hold_curve = [c for c in hold_curve if wstart <= c[0] <= (wend or "9999-12-31")]
    hold_m = pfb.risk_metrics(hold_curve)
    hold_m.update({
        "n_trades": len(hold_sim.get("closed") or []),
        "portfolio_win_rate_pct": round(100.0 * sum(1 for x in hold_sim.get("closed") or [] if x > 0) / len(hold_sim.get("closed") or []), 1) if hold_sim.get("closed") else None,
        "avg_trade_pct": round(sum(hold_sim.get("closed") or []) / len(hold_sim.get("closed") or []) * 100, 2) if hold_sim.get("closed") else None,
        "max_position": round(hold_sim["max_pos"], 3),
        "rejected_cap": hold_sim["rejected_cap"],
    })
    st_sim = simulate_stop_take(sigs, cap=0.8)
    st_m = metrics_from_curve(st_sim["curve"], st_sim, wstart, wend)
    out = {
        "generated": date.today().isoformat(),
        "n_signals": len(sigs),
        "variants": {"hold21": hold_m, "stop_take": st_m},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()