# -*- coding: utf-8 -*-
"""组合层敏感性研究 v3（修复 k=0 越界）：cap 网格 + 出场策略 + 稳健性。"""
import io, json, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util
spec = importlib.util.spec_from_file_location("b1v2", str(Path(__file__).resolve().parent / "b1_risk_backtest_v2.py"))
b1v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1v2)

REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
COST = 0.02
MAX_HOLD = 30

def load_sigs():
    d = json.load(io.open(REPLAY, encoding="utf-8"))
    out = []
    for s in d["signals"]:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = b1v2.classify(s.get("action_label"))
        out.append({"date": date.fromisoformat(s["date"]), "item": s["name"],
                    "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
                    "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1)})
    return out

def exit_simulate(sigs, cap=None, rule=None):
    rule = rule or {"type": "hold", "days": 14}
    by_day = {}
    for s in sigs:
        by_day.setdefault(s["date"], []).append(s)
    first = min(s["date"] for s in sigs)
    last = max(s["date"] for s in sigs) + timedelta(days=MAX_HOLD)
    day, active, total_invested, realized, rejected_cap = first, [], 0.0, 0.0, 0
    closed, curve, max_pos = [], [], 0.0
    while day <= last:
        for a in active:
            a["idx"] += 1
        for s in sorted(by_day.get(day, []), key=lambda x: -x["prio"]):
            if cap is not None and total_invested + s["limit"] > cap + 1e-9:
                rejected_cap += 1
                continue
            active.append({"s": s, "idx": 0, "base": s["limit"], "peak_ret": 0.0})
            total_invested += s["limit"]
        for a in active:
            k = a["idx"]
            if k <= 0:
                a["ret"] = 0.0; a["exit_now"] = False; continue
            fwd = a["s"]["fwd"]
            if k > len(fwd):
                a["ret"] = 0.0; a["exit_now"] = False; continue
            px = fwd[k - 1]
            ret = px / a["s"]["entry"] - 1
            a["ret"] = ret
            a["peak_ret"] = max(a["peak_ret"], ret)
            t = rule.get("type")
            if t == "hold":
                a["exit_now"] = k >= rule.get("days", 14)
            elif t == "stop":
                a["exit_now"] = (ret <= -rule.get("stop", 0.08)) or k >= MAX_HOLD
            elif t == "tp_sl":
                a["exit_now"] = (ret >= rule.get("take", 0.20) or ret <= -rule.get("stop", 0.08)) or k >= MAX_HOLD
            elif t == "trail":
                a["exit_now"] = (a["peak_ret"] - ret >= rule.get("trail", 0.10)) or k >= MAX_HOLD
            elif t == "hold_stop":
                a["exit_now"] = (k >= rule.get("days", 14)) or (ret <= -rule.get("stop", 0.12))
            else:
                a["exit_now"] = False
        unreal = sum(a["base"] * a["ret"] for a in active if not a["exit_now"])
        for a in active:
            if a["exit_now"]:
                pnl = a["base"] * (a["ret"] - COST)
                realized += pnl
                closed.append({"pnl": pnl, "st": a["s"]["st"], "ret": a["ret"], "days": a["idx"]})
                total_invested -= a["base"]
        active = [a for a in active if not a["exit_now"]]
        eq = 1.0 + realized + unreal
        curve.append((day.isoformat(), sum(a["base"] for a in active), eq, len(active)))
        max_pos = max(max_pos, sum(a["base"] for a in active))
        day += timedelta(days=1)
    return {"curve": curve, "closed": closed, "rejected_cap": rejected_cap, "max_pos": max_pos}

def metrics(res):
    vals = [c[2] for c in res["curve"]]
    peak, max_dd = 1.0, 0.0
    for v in vals:
        peak = max(peak, v)
        max_dd = min(max_dd, (v / peak - 1) * 100)
    total = (vals[-1] / 1.0 - 1) * 100 if vals else 0.0
    wins = sum(1 for c in res["closed"] if c["pnl"] > 0)
    fam = defaultdict(list)
    for c in res["closed"]:
        fam[c["st"]].append(c["pnl"])
    fam_stats = {k: {"n": len(v), "win_pct": round(sum(1 for p in v if p > 0)/len(v)*100, 1),
                     "avg_pct": round(sum(v)/len(v)*100, 2)} for k, v in fam.items()}
    return {"total_return_pct": round(total, 2), "max_drawdown_pct": round(max_dd, 2),
            "n_trades": len(res["closed"]),
            "win_pct": round(wins / len(res["closed"]) * 100, 1) if res["closed"] else None,
            "avg_trade_pct": round(sum(c["pnl"] for c in res["closed"]) / len(res["closed"]) * 100, 2) if res["closed"] else None,
            "avg_hold_days": round(sum(c["days"] for c in res["closed"]) / len(res["closed"]), 1) if res["closed"] else None,
            "max_position": round(res["max_pos"], 3), "rejected_cap": res["rejected_cap"],
            "days": len(res["curve"]), "by_family": fam_stats}

def main():
    sigs = load_sigs()
    print("signals:", len(sigs), "| types:", dict(Counter(s["st"] for s in sigs)))
    # 校验与 b1v2 完全一致
    m0 = metrics(exit_simulate(sigs, cap=0.8, rule={"type": "hold", "days": 14}))
    print("CHECK hold14 total=%.2f maxDD=%.2f (expect 83.65 / -13.05)" % (m0["total_return_pct"], m0["max_drawdown_pct"]))

    cap_res = {}
    for cap in (None, 0.4, 0.6, 0.8, 1.0, 1.5):
        r = b1v2.simulate(sigs, cap=cap)
        m = {"total_return_pct": round((r["curve"][-1][2]/1.0-1)*100, 2),
             "n_trades": len(r["closed"]), "max_position": round(r["max_pos"], 3),
             "rejected_cap": r["rejected_cap"]}
        vals = [c[2] for c in r["curve"]]; peak, dd = 1.0, 0.0
        for v in vals:
            peak = max(peak, v); dd = min(dd, (v/peak-1)*100)
        m["max_drawdown_pct"] = round(dd, 2)
        cap_res[str(cap)] = m
        print("cap %-5s total %8.2f  maxDD %7.2f  trades %3d  rejCap %d" % (
            str(cap), m["total_return_pct"], m["max_drawdown_pct"], m["n_trades"], m["rejected_cap"]))

    rules = {"hold7": {"type": "hold", "days": 7}, "hold14": {"type": "hold", "days": 14},
             "hold21": {"type": "hold", "days": 21}, "hold30": {"type": "hold", "days": 30},
             "stop12_max30": {"type": "stop", "stop": 0.12},
             "tp20_sl8_max30": {"type": "tp_sl", "take": 0.20, "stop": 0.08},
             "tp30_sl12_max30": {"type": "tp_sl", "take": 0.30, "stop": 0.12},
             "trail10_max30": {"type": "trail", "trail": 0.10},
             "hold14_stop12": {"type": "hold_stop", "days": 14, "stop": 0.12}}
    results = {}
    for name, rule in rules.items():
        m = metrics(exit_simulate(sigs, cap=0.8, rule=rule))
        results[name] = m
        print("exit %-15s total %8.2f  maxDD %7.2f  trades %3d  win %5.1f%%  avg %6.2f  hold %4.1fd" % (
            name, m["total_return_pct"], m["max_drawdown_pct"], m["n_trades"],
            m["win_pct"], m["avg_trade_pct"], m["avg_hold_days"]))

    sigs_sorted = sorted(sigs, key=lambda s: s["date"])
    mid = sigs_sorted[len(sigs_sorted)//2]["date"]
    halves = {"first_half": [s for s in sigs if s["date"] <= mid], "second_half": [s for s in sigs if s["date"] > mid]}
    no_panic = [s for s in sigs if s["st"] != "panic"]
    rob = {}
    for hname, hs in halves.items():
        for rname, rule in (("hold14", {"type": "hold", "days": 14}), ("tp20_sl8", {"type": "tp_sl", "take": 0.20, "stop": 0.08})):
            m = metrics(exit_simulate(hs, cap=0.8, rule=rule))
            rob["%s_%s" % (hname, rname)] = {"total": m["total_return_pct"], "maxDD": m["max_drawdown_pct"], "n": m["n_trades"]}
            print("robust %-12s %-9s total %8.2f  maxDD %7.2f  trades %3d" % (hname, rname, m["total_return_pct"], m["max_drawdown_pct"], m["n_trades"]))
    for rname, rule in (("hold14", {"type": "hold", "days": 14}), ("tp20_sl8", {"type": "tp_sl", "take": 0.20, "stop": 0.08})):
        m = metrics(exit_simulate(no_panic, cap=0.8, rule=rule))
        rob["no_panic_%s" % rname] = {"total": m["total_return_pct"], "maxDD": m["max_drawdown_pct"], "n": m["n_trades"]}
        print("robust no_panic %-9s total %8.2f  maxDD %7.2f  trades %3d" % (rname, m["total_return_pct"], m["max_drawdown_pct"], m["n_trades"]))

    out = {"generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
           "note": "组合层敏感性 v3：cap 网格复用 b1v2.simulate；出场策略同骨架只改平仓判定，平仓笔与 unreal 互斥，hold14 基准与 b1v2 完全一致（83.65/-13.05）。稳健性=分半窗口+去panic。",
           "signals": len(sigs), "baseline_hold14": {"total": 83.65, "maxDD": -13.05},
           "cap_grid": cap_res, "results": results, "robustness": rob}
    with io.open(ROOT / "data" / "_exp_exit_strategy.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written: data/_exp_exit_strategy.json")

if __name__ == "__main__":
    main()
