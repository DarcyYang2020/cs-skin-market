# -*- coding: utf-8 -*-
"""EXIT-1 正式 A2：路径依赖退出策略验证（2026-08-14，只读研究）。

预注册口径（见 references/decision-log.md 2026-08-13「量化优化三项立项排期」）：
- 基线 hold21；变体 trailing / chandelier / regime
- 组合口径 cap0.8 / 手续费 2% / 拒绝优先级 panic > accumulate/base > deep_value
- walk-forward 3 折 + 事件级 ±3 天去簇 + 置换 1000 次
- 通过门槛：相对 hold21，OOS Calmar 提升 >=15% 或 maxDD 改善 >=2pp，且总收益下降 <=5pp
- 只读产物：data/_exp_exit_1_a2.json；不修改引擎参数、阈值、信号族或闸门。
"""

import json
import math
import random
import statistics
from datetime import date as date_cls, timedelta
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "data" / "item_backtest_full_2025.json"
OUT = BASE / "data" / "_exp_exit_1_a2.json"

COST = 0.02
CAP = 0.8
HOLD = 21
TRAIL_K = (0.10, 0.15, 0.20, 0.25)
CHANDELIER_MULT = (3.0, 4.0)


def _is_panic(signal):
    return "恐慌" in (signal.get("action_label") or "")


def _priority(signal):
    """Canonical admission priority (aligned with b1_risk_backtest_v2.PRIORITY)."""
    lab = signal.get("action_label") or ""
    if "恐慌" in lab:
        return 3
    if "深值" in lab:
        return 1
    return 2


def exit_for(signal, rule, k=None, mult=None, max_hold=None):
    fwd = signal.get("fwd_series") or []
    if not fwd:
        return None
    entry = float(signal["entry_price"])
    if rule == "hold21":
        idx = min(HOLD, len(fwd)) - 1
        price = fwd[idx]
        reason = "hold21"
    elif rule == "trail":
        high = entry
        horizon = max_hold or 60
        idx = min(len(fwd), horizon) - 1
        price = fwd[idx]
        reason = "trail_max"
        for i, cur in enumerate(fwd[:horizon]):
            high = max(high, cur)
            if cur <= high * (1.0 - k):
                idx, price, reason = i, cur, "trail_hit"
                break
    elif rule == "chandelier":
        high = entry
        idx = min(len(fwd), 60) - 1
        price = fwd[idx]
        reason = "chandelier_max"
        closes = [entry] + list(fwd)
        for i in range(min(len(fwd), 60)):
            cur = fwd[i]
            high = max(high, cur)
            lookback = closes[max(0, i - 13):i + 1]
            if len(lookback) >= 2:
                diffs = [abs(lookback[j] - lookback[j - 1]) for j in range(1, len(lookback))]
                atr = statistics.mean(diffs)
            else:
                atr = 0.0
            stop = high - mult * atr
            if atr > 0 and cur <= stop:
                idx, price, reason = i, cur, "chandelier_hit"
                break
    elif rule == "regime":
        kk = 0.25 if _is_panic(signal) else 0.15
        max_hold = 30 if _is_panic(signal) else HOLD
        return exit_for(signal, "trail", k=kk, max_hold=max_hold)
    else:
        raise ValueError("unknown rule: %s" % rule)

    # regime 调用的递归路径已返回；仅 trail/chandelier/hold21 走到这里。
    # trail/chandelier 在 fwd 不足时 idx 为 0 也是合法的 1 日后退出。
    net_pct = (price / entry - 1.0 - COST) * 100.0
    return {"idx": idx, "price": price, "reason": reason, "net_pct": net_pct}


def _trade_stats(signals, rule, k=None, mult=None):
    rows = [exit_for(s, rule, k=k, mult=mult) for s in signals]
    vals = [r["net_pct"] for r in rows if r]
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "win_pct": round(100.0 * sum(1 for v in vals if v > 0) / len(vals), 1),
        "avg_pct": round(sum(vals) / len(vals), 2),
        "median_pct": round(statistics.median(vals), 2),
    }


def _portfolio(signals, rule, k=None, mult=None):
    by_day = {}
    valid = []
    for s in signals:
        ex = exit_for(s, rule, k=k, mult=mult)
        if ex is None:
            continue
        by_day.setdefault(s["date"], []).append((s, ex))
        valid.append(date_cls.fromisoformat(s["date"]))
    if not valid:
        return None
    first = min(valid)
    last = max(date_cls.fromisoformat(s["date"]) for s in signals) + timedelta(days=70)
    day = first
    active = []
    total_invested = 0.0
    realized = 0.0
    peak = 1.0
    max_dd = 0.0
    while day <= last:
        for a in active:
            a["idx"] += 1
        for s, ex in sorted(by_day.get(day.isoformat(), []), key=lambda x: -_priority(x[0])):
            lim = float(s.get("position_limit") or 0)
            if total_invested + lim > CAP + 1e-9:
                continue
            active.append({"s": s, "ex": ex, "idx": 0, "limit": lim})
            total_invested += lim
        unreal = 0.0
        for a in active:
            kk = a["idx"]
            fwd = a["s"].get("fwd_series") or []
            if kk <= 0 or kk >= a["ex"]["idx"] + 1 or kk > len(fwd):
                continue
            px = fwd[min(kk - 1, len(fwd) - 1)]
            unreal += a["limit"] * (px / float(a["s"]["entry_price"]) - 1.0)
        for a in list(active):
            if a["idx"] >= a["ex"]["idx"] + 1:
                pnl = a["limit"] * (a["ex"]["price"] / float(a["s"]["entry_price"]) - 1.0 - COST)
                realized += pnl
                total_invested -= a["limit"]
                active.remove(a)
        equity = 1.0 + realized + unreal
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity / peak - 1.0) * 100.0)
        day += timedelta(days=1)
    total = (equity - 1.0) * 100.0
    days = (last - first).days
    ann = (((equity) ** (365.0 / days) - 1.0) * 100.0) if days > 0 and equity > 0 else 0.0
    calmar = (ann / abs(max_dd)) if max_dd < 0 else 0.0
    return {
        "total_return_pct": round(total, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "calmar": round(calmar, 2),
    }


def _load_signals():
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    out = []
    for s in replay.get("signals") or []:
        if not s.get("fwd_series"):
            continue
        out.append(s)
    return out


def _date_clusters(signals, window=3):
    dates = sorted(set(date_cls.fromisoformat(s["date"]) for s in signals))
    cluster = {}
    cid = 0
    last_end = None
    for d in dates:
        if last_end is None or (d - last_end).days > window:
            cid += 1
            last_end = d
        else:
            last_end = max(last_end, d)
        cluster[d] = cid
    return cluster


def _paired_cluster_permutation(signals, rule, k=None, mult=None, n_perm=1000):
    base = [exit_for(s, "hold21") for s in signals]
    variant = [exit_for(s, rule, k=k, mult=mult) for s in signals]
    clusters = _date_clusters(signals)
    groups = {}
    for s, b, v in zip(signals, base, variant):
        if not b or not v:
            continue
        cid = clusters[date_cls.fromisoformat(s["date"])]
        groups.setdefault(cid, []).append(v["net_pct"] - b["net_pct"])
    obs_means = [statistics.mean(vals) for vals in groups.values()]
    obs = statistics.mean(obs_means) if obs_means else 0.0
    hits = 0
    rng = random.Random(20260814)
    for _ in range(n_perm):
        signs = [1.0 if rng.random() < 0.5 else -1.0 for _ in obs_means]
        perm = statistics.mean(signs[j] * obs_means[j] for j in range(len(obs_means)))
        if abs(perm) >= abs(obs):
            hits += 1
    return {"n_clusters": len(groups), "obs_mean_diff_pct": round(obs, 3),
            "p_two_sided": round(hits / n_perm, 4), "n_perm": n_perm}


def _rule_id(rule, k=None, mult=None):
    if rule == "trail":
        return "trail_%.2f" % k
    if rule == "chandelier":
        return "chandelier_%.1f" % mult
    return rule


def _split_folds(signals, folds=3):
    ordered = sorted(signals, key=lambda s: s["date"])
    chunks = []
    size = math.ceil(len(ordered) / folds)
    for i in range(folds):
        chunks.append(ordered[i * size:(i + 1) * size])
    return chunks


def main():
    signals = _load_signals()
    rules = [("hold21", None, None)]
    for k in TRAIL_K:
        rules.append(("trail", k, None))
    for mult in CHANDELIER_MULT:
        rules.append(("chandelier", None, mult))
    rules.append(("regime", None, None))

    # 全局 + fold 指标
    folds = _split_folds(signals)
    rows = []
    for rule, k, mult in rules:
        rid = _rule_id(rule, k, mult)
        fold_rows = []
        for sigs in folds:
            p = _portfolio(sigs, rule, k=k, mult=mult)
            t = _trade_stats(sigs, rule, k=k, mult=mult)
            fold_rows.append({"portfolio": p, "trades": t})
        rows.append({"rule": rid, "kind": rule, "k": k, "mult": mult,
                     "global_portfolio": _portfolio(signals, rule, k=k, mult=mult),
                     "global_trades": _trade_stats(signals, rule, k=k, mult=mult),
                     "folds": fold_rows})

    baseline = rows[0]
    conclusions = []
    for row in rows[1:]:
        if not baseline["global_portfolio"]:
            continue
        # OOS 门槛用三折平均相对基线
        calmar_imp = []
        dd_imp = []
        total_drop = []
        for bf, vf in zip(baseline["folds"], row["folds"]):
            if bf["portfolio"] and vf["portfolio"]:
                calmar_imp.append((vf["portfolio"]["calmar"] - bf["portfolio"]["calmar"]) / bf["portfolio"]["calmar"] * 100
                                  if bf["portfolio"]["calmar"] else 0.0)
                dd_imp.append(bf["portfolio"]["max_drawdown_pct"] - vf["portfolio"]["max_drawdown_pct"])
                total_drop.append(vf["portfolio"]["total_return_pct"] - bf["portfolio"]["total_return_pct"])
        avg_calmar = statistics.mean(calmar_imp) if calmar_imp else None
        avg_dd = statistics.mean(dd_imp) if dd_imp else None
        avg_total = statistics.mean(total_drop) if total_drop else None
        perm = _paired_cluster_permutation(signals, row["kind"], k=row["k"], mult=row["mult"])
        passed = bool(avg_calmar is not None and avg_dd is not None and avg_total is not None
                      and ((avg_calmar >= 15.0) or (avg_dd >= 2.0)) and avg_total >= -5.0)
        conclusions.append({
            "rule": row["rule"],
            "fold_avg_calmar_improve_pct": round(avg_calmar, 2) if avg_calmar is not None else None,
            "fold_avg_maxdd_improve_pp": round(avg_dd, 2) if avg_dd is not None else None,
            "fold_avg_total_return_delta_pp": round(avg_total, 2) if avg_total is not None else None,
            "permutation": perm,
            "pass_pre_registered_gate": passed,
        })

    out = {
        "generated": "2026-08-14",
        "stage": "formal_a2",
        "pre_registered": {
            "baseline": "hold21",
            "variants": ["trail_0.10/0.15/0.20/0.25", "chandelier_3.0/4.0", "regime"],
            "folds": 3,
            "event_cluster_window_days": 3,
            "permutations": 1000,
            "pass_gate": "OOS fold avg Calmar improve >=15% OR maxDD improve >=2pp, AND total return drop <=5pp",
        },
        "signals": len(signals),
        "results": rows,
        "conclusions": conclusions,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", OUT)
    print(json.dumps({"signals": len(signals), "conclusions": conclusions}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
