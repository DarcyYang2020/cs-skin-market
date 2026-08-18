# -*- coding: utf-8 -*-
"""EXIT-9/10/11 ATR adaptive stop/trailing grid (read-only research).

Pre-registered (2026-08-15 external review):
- Baseline: hold21, canonical admission priority panic > accumulate/base > deep_value.
- Ruler: portfolio_backtest.risk_metrics on b1_risk_backtest_v2-style portfolio curve,
  cap=0.8, cost=2%, window = replay args.start~end.
- Dual baselines: HIST-FULL (317, frozen v2-T4/T5) and CLEAN-CUR (230, v2-T9).
- Variants: atr_stop 2.5x/3x/4x and atr_trailing 2.5x/3x/4x, max hold 21.
- ATR: mean abs close-to-close over preceding 14 rows (>=10 required), price units,
  ATR% = ATR / entry_price. Trailing stop = rolling high - mult*ATR, fixed entry ATR.
- Gate: global Calmar improve >=15% OR maxDD improve >=2pp, AND total return drop <=5pp,
  AND front/back chronological halves direction-consistent for the passing metric.
"""
import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import date, timedelta
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE
HIST_REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
CLEAN_REPLAY = ROOT / "data" / "_exp_v2t9_win_replay.json"
DB = ROOT / "data" / "replay_v2t6_win.db"
OUT = ROOT / "data" / "_exp_exit_9_10_11_atr_grid.json"

COST = 0.02
CAP = 0.8
HOLD = 21
MULTS = (2.5, 3.0, 4.0)


def _load_module(name, path):
    spec = spec_from_file_location(name, str(path))
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b1v2 = _load_module("b1v2", ROOT / "references" / "b1_risk_backtest_v2.py")
pfb = _load_module("pfb", ROOT / "references" / "portfolio_backtest.py")


def load_signals(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for s in d.get("signals") or []:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        try:
            entry = float(s["entry_price"])
            limit = float(s.get("position_limit") or 0.0)
            dt = date.fromisoformat(s["date"])
        except Exception:
            continue
        st = b1v2.classify(s.get("action_label"))
        out.append({
            "name": s["name"], "date": dt, "date_str": s["date"],
            "entry": entry, "limit": limit,
            "fwd": [float(x) for x in fwd], "st": st,
            "prio": b1v2.PRIORITY.get(st, 1),
        })
    return out, d.get("args", {})


def build_atr_map(signals):
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row
    items = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM items")}
    series = defaultdict(list)
    for r in con.execute("SELECT item_id, date, price_rmb FROM price_history ORDER BY item_id, date"):
        try:
            series[r["item_id"]].append((r["date"], float(r["price_rmb"])))
        except Exception:
            continue
    con.close()

    atr_map = {}
    for s in signals:
        iid = items.get(s["name"])
        arr = series.get(iid, [])
        idx = next((j for j, x in enumerate(arr) if x[0] == s["date_str"]), None)
        if idx is None:
            atr_map[id(s)] = None
            continue
        start = max(0, idx - 14)
        closes = [p for _, p in arr[start:idx]]
        if len(closes) >= 10:
            diffs = [abs(closes[j] - closes[j - 1]) for j in range(1, len(closes))]
            atr = statistics.mean(diffs)
            atr_map[id(s)] = atr / s["entry"]
        elif len(closes) >= 2:
            diffs = [abs(closes[j] - closes[j - 1]) for j in range(1, len(closes))]
            atr = statistics.mean(diffs)
            atr_map[id(s)] = atr / s["entry"]
        else:
            atr_map[id(s)] = None
    return atr_map


def exit_for(s, atr_pct, rule, mult=None):
    fwd = s["fwd"]
    entry = s["entry"]
    if not fwd:
        return None
    if rule == "hold21":
        idx = min(HOLD, len(fwd)) - 1
        price = fwd[idx]
        reason = "hold21"
    elif rule in ("atr_stop", "atr_trailing"):
        if atr_pct is None or mult is None:
            return None
        idx = min(HOLD, len(fwd)) - 1
        price = fwd[idx]
        reason = rule + "_max"
        high = entry
        stop = entry * (1.0 - mult * atr_pct)
        for i, cur in enumerate(fwd[:HOLD]):
            if rule == "atr_trailing":
                high = max(high, cur)
                stop = high * (1.0 - mult * atr_pct)
            if cur <= stop:
                idx, price, reason = i, cur, rule + "_hit"
                break
    else:
        raise ValueError("unknown rule %s" % rule)
    net_pct = (price / entry - 1.0 - COST) * 100.0
    return {"idx": idx, "price": price, "reason": reason, "net_pct": round(net_pct, 6)}


def simulate_portfolio(signals, atr_map, rule, mult=None):
    by_day = defaultdict(list)
    valid = []
    for s in signals:
        ex = exit_for(s, atr_map.get(id(s)), rule, mult=mult)
        if ex is None:
            continue
        by_day[s["date"]].append((s, ex))
        valid.append(s["date"])
    if not valid:
        return None
    first = min(valid)
    last = max(s["date"] for s in signals) + timedelta(days=HOLD + 2)
    day = first
    active = []
    total_invested = 0.0
    realized = 0.0
    closed = []
    curve = []
    while day <= last:
        for a in active:
            a["idx"] += 1
        for s, ex in sorted(by_day.get(day, []), key=lambda x: -x[0]["prio"]):
            lim = s["limit"]
            if total_invested + lim > CAP + 1e-9:
                continue
            active.append({"s": s, "ex": ex, "idx": 0, "lim": lim})
            total_invested += lim
        unreal = 0.0
        pos_sum = 0.0
        for a in active:
            pos_sum += a["lim"]
            k = a["idx"]
            fwd = a["s"]["fwd"]
            if k > 0 and k < a["ex"]["idx"] + 1 and k <= len(fwd):
                px = fwd[min(k - 1, len(fwd) - 1)]
                unreal += a["lim"] * (px / a["s"]["entry"] - 1.0)
        for a in list(active):
            if a["idx"] >= a["ex"]["idx"] + 1:
                pnl = a["lim"] * (a["ex"]["price"] / a["s"]["entry"] - 1.0 - COST)
                realized += pnl
                closed.append(pnl)
                total_invested -= a["lim"]
                active.remove(a)
        equity = 1.0 + realized + unreal
        curve.append((day.isoformat(), pos_sum, equity, 0, len(active)))
        day += timedelta(days=1)
    return {"curve": curve, "closed": closed}


def metrics(sim, args, n_signals):
    if not sim:
        return None
    curve = sim["curve"]
    wstart = args.get("start")
    wend = args.get("end")
    if wstart:
        curve = [c for c in curve if wstart <= c[0] <= (wend or "9999-12-31")]
    if len(curve) < 2:
        return None
    m = pfb.risk_metrics(curve)
    closed = sim.get("closed") or []
    m.update({
        "n_signals": n_signals,
        "n_trades": len(closed),
        "portfolio_win_rate_pct": round(100.0 * sum(1 for x in closed if x > 0) / len(closed), 1) if closed else None,
        "max_position": round(max((c[1] for c in sim["curve"]), default=0.0), 3),
        "rejected_cap": 0,
    })
    return m


def split_halves(signals):
    ordered = sorted(signals, key=lambda s: (s["date"], s["name"]))
    n = len(ordered)
    return ordered[:n // 2], ordered[n // 2:]


def _delta_num(base, variant, key):
    b = base.get(key)
    v = variant.get(key)
    if b is None or v is None:
        return None
    return round(v - b, 4)


def _calmar_improve(base, variant):
    b = base.get("calmar")
    v = variant.get("calmar")
    if not b or b <= 0 or v is None:
        return None
    return round((v - b) / b * 100.0, 2)


def _rule_id(rule, mult):
    if rule == "hold21":
        return "hold21"
    return "%s_%.1f" % (rule, mult)


def evaluate(signals, args, atr_map):
    baseline_rule = "hold21"
    bm = metrics(simulate_portfolio(signals, atr_map, baseline_rule), args, len(signals))
    h1, h2 = split_halves(signals)
    half_base = [
        metrics(simulate_portfolio(h1, atr_map, baseline_rule), args, len(h1)),
        metrics(simulate_portfolio(h2, atr_map, baseline_rule), args, len(h2)),
    ]
    variants = []
    for rule, mult in [(baseline_rule, None)] + [("atr_stop", x) for x in MULTS] + [("atr_trailing", x) for x in MULTS]:
        vm = metrics(simulate_portfolio(signals, atr_map, rule, mult), args, len(signals))
        half_variant = [
            metrics(simulate_portfolio(h1, atr_map, rule, mult), args, len(h1)),
            metrics(simulate_portfolio(h2, atr_map, rule, mult), args, len(h2)),
        ]
        entry = {
            "rule": _rule_id(rule, mult),
            "kind": rule,
            "mult": mult,
            "global": vm,
            "halves": half_variant,
        }
        if rule != baseline_rule and bm and vm:
            calmar_imp = _calmar_improve(bm, vm)
            dd_imp = _delta_num(bm, vm, "max_drawdown_pct")
            total_delta = _delta_num(bm, vm, "total_return_pct")
            half_calmar = [_calmar_improve(b, v) if b and v else None for b, v in zip(half_base, half_variant)]
            half_dd = [_delta_num(b, v, "max_drawdown_pct") if b and v else None for b, v in zip(half_base, half_variant)]
            half_total = [_delta_num(b, v, "total_return_pct") if b and v else None for b, v in zip(half_base, half_variant)]
            gate_calmar = calmar_imp is not None and calmar_imp >= 15.0
            gate_dd = dd_imp is not None and dd_imp >= 2.0
            gate_total = total_delta is not None and total_delta >= -5.0
            direction_ok = True
            if gate_calmar:
                direction_ok = direction_ok and all(x is not None and x >= 0.0 for x in half_calmar)
            if gate_dd:
                direction_ok = direction_ok and all(x is not None and x >= 0.0 for x in half_dd)
            passed = (gate_calmar or gate_dd) and gate_total and direction_ok
            entry["vs_baseline"] = {
                "calmar_improve_pct": calmar_imp,
                "maxdd_improve_pp": dd_imp,
                "total_return_delta_pp": total_delta,
                "half_calmar_improve_pct": half_calmar,
                "half_maxdd_improve_pp": half_dd,
                "half_total_return_delta_pp": half_total,
                "gate_calmar": gate_calmar,
                "gate_maxdd": gate_dd,
                "gate_total_drop_ok": gate_total,
                "direction_consistent": direction_ok,
                "pass_pre_registered_gate": passed,
            }
        variants.append(entry)
    return {"baseline": bm, "variants": variants}


def main():
    out = {
        "probe": "EXIT-9/10/11 ATR adaptive stop/trailing grid",
        "generated": date.today().isoformat(),
        "pre_registered": {
            "baseline": "hold21",
            "ruler": "portfolio_backtest.risk_metrics on b1-style portfolio curve; cap=0.8, cost=2%, window=replay args.start~end; annualized Calmar",
            "baselines": {
                "HIST-FULL": {"replay": "data/item_backtest_full_2025.json", "signals": 317, "engine": "v2-T4/T5 frozen"},
                "CLEAN-CUR": {"replay": "data/_exp_v2t9_win_replay.json", "signals": 230, "engine": "v2-T9"},
            },
            "variants": ["atr_stop_2.5/3.0/4.0", "atr_trailing_2.5/3.0/4.0", "max_hold=21"],
            "atr": "mean abs close-to-close over preceding 14 rows (>=10 required); ATR%=ATR/entry; trailing stop=rolling high - mult*ATR (fixed entry ATR)",
            "gate": "global Calmar improve >=15% OR maxDD improve >=2pp, AND total return drop <=5pp, AND front/back halves direction-consistent for passing metric",
        },
        "db": str(Path("data/replay_v2t6_win.db")),
        "baselines": {},
        "conclusions": [],
    }
    for label, path, engine in (
        ("HIST-FULL", HIST_REPLAY, "v2-T4/T5 frozen"),
        ("CLEAN-CUR", CLEAN_REPLAY, "v2-T9"),
    ):
        signals, args = load_signals(path)
        atr_map = build_atr_map(signals)
        n_atr = sum(1 for v in atr_map.values() if v is not None)
        res = evaluate(signals, args, atr_map)
        out["baselines"][label] = {
            "replay": str(Path(path).relative_to(ROOT)),
            "engine": engine,
            "n_signals": len(signals),
            "n_atr_available": n_atr,
            "results": res,
        }
        passing = [v["rule"] for v in res["variants"] if v.get("vs_baseline", {}).get("pass_pre_registered_gate")]
        out["conclusions"].append({
            "baseline": label,
            "baseline_total_pct": res["baseline"]["total_return_pct"] if res["baseline"] else None,
            "baseline_maxdd_pct": res["baseline"]["max_drawdown_pct"] if res["baseline"] else None,
            "baseline_calmar": res["baseline"]["calmar"] if res["baseline"] else None,
            "passing_variants": passing,
        })
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["conclusions"], ensure_ascii=False, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
