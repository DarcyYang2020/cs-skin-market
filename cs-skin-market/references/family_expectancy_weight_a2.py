# -*- coding: utf-8 -*-
"""FEW-1 family-expectancy-weighted position sizing A2 (2026-08-14, read-only).

Pre-registered treatment:
- Baseline: current per-signal position_limit (production config), cap0.8, hold21, cost2%.
- Treatment: expanding 3-fold walk-forward; for each test fold, family multiplier is
  m_f = clip(mean_f_net14 / mean_pool_net14, 0.5, 1.5) learned on prior folds only.
  Adjusted limit = min(0.30, original_limit * m_f).
- Gate: OOS Calmar improvement >=15% OR (maxDD improvement >=2pp AND total-return decline <=5pp).
- Permutation: cluster-level sign-flip (>=1000) on allocation-delta pnl per signal.
- Only writes data/_exp_family_expectancy_weight_a2.json. No engine/param/signal changes.
"""
import json
import random
import statistics
import sys
from datetime import date as date_cls
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "references"))
import exit_1_a2 as e1

REPLAY = BASE / "data" / "item_backtest_full_2025.json"
OUT = BASE / "data" / "_exp_family_expectancy_weight_a2.json"

COST = 0.02
CAP = 0.8
HOLD = "hold21"
MIN_N = 10
MULT_FLOOR = 0.5
MULT_CAP = 1.5
SINGLE_CAP = 0.30


def classify(s):
    lab = s.get("action_label") or ""
    if "恐慌" in lab:
        return "panic"
    if "深值" in lab:
        return "deep_value"
    return "accumulate"


def net14(s):
    fwd = s.get("fwd_series") or []
    if len(fwd) < 14:
        return None
    return (fwd[13] / float(s["entry_price"]) - 1.0 - COST)


def family_multipliers(train):
    vals = {}
    for s in train:
        v = net14(s)
        if v is None:
            continue
        vals.setdefault(classify(s), []).append(v)
    pool = [v for arr in vals.values() for v in arr]
    if not pool:
        return {}
    pool_mean = sum(pool) / len(pool)
    out = {}
    for fam, arr in vals.items():
        if len(arr) >= MIN_N and pool_mean > 0:
            m = (sum(arr) / len(arr)) / pool_mean
            out[fam] = max(MULT_FLOOR, min(MULT_CAP, m))
        else:
            out[fam] = 1.0
    return out


def apply_limits(sigs, mults):
    out = []
    for s in sigs:
        s2 = dict(s)
        lim = float(s2.get("position_limit") or 0.0)
        m = mults.get(classify(s2), 1.0)
        s2["position_limit"] = round(min(SINGLE_CAP, lim * m), 6)
        out.append(s2)
    return out


def sim(sigs):
    if not sigs:
        return None
    return e1._portfolio(sigs, HOLD)


def cluster_delta_permutation(folds_with_mults, n_perm=1000):
    rows = []
    for fold, mults in folds_with_mults:
        for s in fold:
            v = net14(s)
            if v is None:
                continue
            orig = float(s.get("position_limit") or 0.0)
            adj = min(SINGLE_CAP, orig * mults.get(classify(s), 1.0))
            rows.append((date_cls.fromisoformat(s["date"]), (adj - orig) * v * 100.0))
    if not rows:
        return {"n_signals": 0}
    rows.sort(key=lambda x: x[0])
    clusters = []
    cur = [rows[0]]
    for i in range(1, len(rows)):
        if (rows[i][0] - rows[i - 1][0]).days <= 3:
            cur.append(rows[i])
        else:
            clusters.append(cur)
            cur = [rows[i]]
    clusters.append(cur)
    cluster_means = [statistics.mean([v for _, v in c]) for c in clusters]
    obs = statistics.mean(cluster_means) if cluster_means else 0.0
    hits = 0
    rng = random.Random(20260814)
    for _ in range(n_perm):
        signs = [1.0 if rng.random() < 0.5 else -1.0 for _ in cluster_means]
        perm = statistics.mean(signs[j] * cluster_means[j] for j in range(len(cluster_means)))
        if abs(perm) >= abs(obs):
            hits += 1
    return {
        "n_signals": len(rows),
        "n_clusters": len(clusters),
        "obs_mean_alloc_delta_pp": round(obs, 3),
        "p_two_sided": round(hits / n_perm, 4),
        "n_perm": n_perm,
    }


def main():
    sigs = e1._load_signals()
    folds = e1._split_folds(sigs, folds=3)
    fold_info = []
    adj_all = []
    train = []
    folds_with_mults = []
    for i, fold in enumerate(folds):
        mults = family_multipliers(train)
        fold_adj = apply_limits(fold, mults)
        adj_all.extend(fold_adj)
        folds_with_mults.append((fold, mults))
        fold_info.append({
            "fold": i + 1,
            "n": len(fold),
            "train_n": len(train),
            "multipliers": mults,
            "baseline": sim(fold),
            "treatment": sim(fold_adj),
        })
        train.extend(fold)

    base = sim(sigs)
    treat = sim(adj_all)
    perm = cluster_delta_permutation(folds_with_mults, n_perm=1000)

    b_calmar = float(base.get("calmar") or 0.0)
    t_calmar = float(treat.get("calmar") or 0.0)
    calmar_delta_pct = round((t_calmar - b_calmar) / abs(b_calmar) * 100.0, 1) if b_calmar else None
    maxdd_improve_pp = round(float(base.get("max_drawdown_pct") or 0.0) - float(treat.get("max_drawdown_pct") or 0.0), 2)
    total_decline_pp = round(float(base.get("total_return_pct") or 0.0) - float(treat.get("total_return_pct") or 0.0), 2)
    passed = bool(calmar_delta_pct is not None and (calmar_delta_pct >= 15.0 or (maxdd_improve_pp >= 2.0 and total_decline_pp <= 5.0)))

    out = {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
        "note": "FEW-1 family-expectancy-weighted position sizing A2: expanding 3-fold walk-forward; multiplier m_f=clip(fam_net14/pool_net14,0.5,1.5) learned on prior folds; adjusted limit=min(0.30,orig*m_f). Baseline=current production limits; cap0.8/hold21/cost2%. Gate: OOS Calmar>=+15% OR (maxDD improve>=2pp AND total decline<=5pp).",
        "signals": len(sigs),
        "baseline": base,
        "treatment": treat,
        "calmar_delta_pct": calmar_delta_pct,
        "maxdd_improve_pp": maxdd_improve_pp,
        "total_decline_pp": total_decline_pp,
        "pass_pre_registered_gate": passed,
        "folds": fold_info,
        "permutation": perm,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({
        "baseline": base,
        "treatment": treat,
        "calmar_delta_pct": calmar_delta_pct,
        "maxdd_improve_pp": maxdd_improve_pp,
        "total_decline_pp": total_decline_pp,
        "pass": passed,
        "permutation": perm,
        "folds": [{"fold": x["fold"], "n": x["n"], "train_n": x["train_n"], "multipliers": x["multipliers"]} for x in fold_info],
    }, ensure_ascii=False, indent=1))
    print("written:", OUT)


if __name__ == "__main__":
    main()