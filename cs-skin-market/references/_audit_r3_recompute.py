# -*- coding: utf-8 -*-
"""③审计 · R3 独立复算脚本（2026-08-27，只读，不覆盖②产物）。

对 R3 产物 data/_exp_family_isolation_2026-08-27.json 做独立只读核验：
- G3 前后半段 / 重叠矩阵 / 收益相关矩阵 / period 分布 / 零漂移 delta：独立实现交叉验证
- G4 置换检验：独立实现（seed=42 复现 + seed=7 敏感性）
- G1 A2 发射复算 / G2 组合级：复用生产设施 a2_emission / b1 重跑对比（②实现可审查）
- 版本冻结：SQL 直查 replay_cycle_win.db（items/price_history/market_index 计数）
输出：data/_audit_r3_recompute_2026-08-27.json（审计产物，只读原始输入）。
"""
import json
import math
import random
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "references"))

SPLIT = date(2025, 8, 10)
BASE = ROOT / "data" / "_exp_cycle_replay_fullpool_2026.json"
CUR = ROOT / "data" / "_exp_current_engine_fullpool_2026-08-27.json"
ISO = ROOT / "data" / "_exp_family_isolation_2026-08-27.json"
DB = ROOT / "data" / "replay_cycle_win.db"
FAMILY_KEYS = ("panic", "deep", "rise", "supply", "reversal", "base")
REPLAY = {k: ROOT / "data" / ("_exp_family_%s_replay_2026-08-27.json" % k) for k in FAMILY_KEYS}

audit = {"title": "③审计 R3 独立复算", "checks": {}, "pass": True}


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    return d, [s for s in d.get("signals", []) if s.get("net14") is not None]


def a_stats(recs):
    n = len(recs)
    if n == 0:
        return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
    n30 = [r for r in recs if r.get("net30") is not None]
    return {"n": n,
            "win14": round(100.0 * sum(1 for r in recs if r["net14"] > 0) / n, 1),
            "avg14": round(sum(r["net14"] for r in recs) / n, 2),
            "win30": round(100.0 * sum(1 for r in n30 if r["net30"] > 0) / len(n30), 1) if n30 else None,
            "avg30": round(sum(r["net30"] for r in n30) / len(n30), 2) if n30 else None}


# ---------- 1. G3 前后半段独立复算 ----------
def chk_g3():
    out = {}
    for k in FAMILY_KEYS:
        _, recs = load(REPLAY[k])
        fit = [s for s in recs if date.fromisoformat(s["date"]) < SPLIT]
        val = [s for s in recs if date.fromisoformat(s["date"]) >= SPLIT]
        fs, vs = a_stats(fit), a_stats(val)
        passed = (fs["win14"] is not None and fs["win14"] >= 60
                  and vs["win14"] is not None and vs["win14"] >= 60
                  and vs["avg14"] is not None and vs["avg14"] > 0)
        out[k] = {"fit": fs, "val": vs, "passed": passed}
    return out


# ---------- 2. 重叠矩阵独立复算 ----------
def chk_overlap(recs_map):
    key_sets = {k: {(s["date"], s["name"]) for s in recs_map[k]} for k in FAMILY_KEYS}
    out = {}
    for a in FAMILY_KEYS:
        out[a] = {}
        for b in FAMILY_KEYS:
            if a == b:
                out[a][b] = None
                continue
            inter = len(key_sets[a] & key_sets[b])
            union = len(key_sets[a] | key_sets[b])
            mn = min(len(key_sets[a]), len(key_sets[b])) or 1
            out[a][b] = {"inter": inter, "jaccard": round(inter / union, 3) if union else None,
                         "overlap_min": round(inter / mn, 3) if mn else None}
    return out


# ---------- 3. 收益相关矩阵独立复算 ----------
def monthly_avg(recs):
    b = {}
    for s in recs:
        b.setdefault(s["date"][:7], []).append(s["net14"])
    return {k: sum(v) / len(v) for k, v in sorted(b.items())}


def pearson(xs, ys):
    ks = [k for k in xs if k in ys]
    if len(ks) < 3:
        return None
    xv, yv = [xs[k] for k in ks], [ys[k] for k in ks]
    n = len(ks)
    mx, my = sum(xv) / n, sum(yv) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xv, yv))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xv))
    dy = math.sqrt(sum((b - my) ** 2 for b in yv))
    return round(num / (dx * dy), 3) if dx and dy else None


def chk_corr(recs_map):
    monthly = {k: monthly_avg(recs_map[k]) for k in FAMILY_KEYS}
    out = {}
    for a in FAMILY_KEYS:
        out[a] = {}
        for b in FAMILY_KEYS:
            out[a][b] = pearson(monthly[a], monthly[b]) if a != b else 1.0
    return out


# ---------- 4. period 分布独立复算（重建 market_ctx 重算 _period）----------
def chk_period(recs_map):
    try:
        from pipeline.backtest_common import build_market_context
        from pipeline.market_context import state_bucket as sb
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}
    mctx = build_market_context("2023-11-17", end="2026-08-05")
    out = {}
    for k, recs in recs_map.items():
        diff = 0
        for s in recs:
            mc = mctx.get(s["date"]) or {}
            try:
                p = sb(mc.get("chg180", 0.0), mc.get("chg30", 0.0))
            except Exception:
                p = None
            if p != s.get("_period"):
                diff += 1
        out[k] = {"checked": len(recs), "mismatch": diff}
    return out


# ---------- 5. 零漂移 delta 独立复算 ----------
def chk_delta(recs_map):
    _, base = load(BASE)
    _, cur = load(CUR)
    cur_keys = {(s["date"], s["name"]) for s in cur}
    out = {}
    for k, recs in recs_map.items():
        fam = json.load(open(REPLAY[k], encoding="utf-8"))
        labels = tuple(fam["args"]["labels"])
        match_exact = (k == "base")
        base_fam = [s for s in base
                    if (s.get("action_label") or "") in labels] if match_exact else \
                   [s for s in base if any(lb in (s.get("action_label") or "") for lb in labels)]
        fam_keys = {(s["date"], s["name"], s["net14"]) for s in recs}
        missing = [s for s in base_fam if (s["date"], s["name"], s["net14"]) not in fam_keys]
        real_missing, legacy = [], []
        for s in missing:
            cur_has = any(cs["name"] == s["name"] and cs["date"] == s["date"] for cs in cur)
            (real_missing if cur_has else legacy).append(s)
        base_keys = {(s["date"], s["name"], s["net14"]) for s in base}
        added = [s for s in recs if (s["date"], s["name"], s["net14"]) not in base_keys]
        out[k] = {"baseline_family_sigs": len(base_fam), "kept": len(base_fam) - len(missing),
                  "missing_total": len(missing), "missing_real": len(real_missing),
                  "missing_legacy_baseline": len(legacy), "added_vs_baseline": len(added),
                  "zero_drift": len(real_missing) == 0}
    return out


# ---------- 6. G4 置换独立实现 ----------
def perm_p(added, book, n_iter=500, seed=0):
    if not added or not book:
        return {"p_avg": None, "p_win": None, "book_avg14": None, "book_win14": None}
    obs_avg = sum(r["net14"] for r in added) / len(added)
    obs_win = sum(1 for r in added if r["net14"] > 0) / len(added)
    rng = random.Random(seed)
    k = len(added)
    with_rep = len(book) < k
    pick = (lambda: rng.choices(book, k=k)) if with_rep else (lambda: rng.sample(book, k))
    ge_avg = ge_win = 0
    for _ in range(n_iter):
        sample = pick()
        if sum(r["net14"] for r in sample) / k >= obs_avg:
            ge_avg += 1
        if sum(1 for r in sample if r["net14"] > 0) / k >= obs_win:
            ge_win += 1
    return {"p_avg": round(ge_avg / n_iter, 3), "p_win": round(ge_win / n_iter, 3),
            "book_avg14": round(sum(r["net14"] for r in book) / len(book), 2),
            "book_win14": round(100.0 * sum(1 for r in book if r["net14"] > 0) / len(book), 1),
            "with_replacement": with_rep}


def chk_g4(recs_map, base_recs):
    out = {}
    for k, recs in recs_map.items():
        val_fam = [{"date": date.fromisoformat(s["date"]), "name": s["name"],
                    "action_label": s.get("action_label") or "", "net14": s["net14"],
                    "net30": s.get("net30")} for s in recs if date.fromisoformat(s["date"]) >= SPLIT]
        val_book = [{"date": date.fromisoformat(s["date"]), "name": s["name"],
                     "action_label": s.get("action_label") or "", "net14": s["net14"],
                     "net30": s.get("net30")} for s in base_recs if date.fromisoformat(s["date"]) >= SPLIT]
        out[k] = {"val_n": len(val_fam),
                  "seed42": perm_p(val_fam, val_book, n_iter=500, seed=42),
                  "seed7": perm_p(val_fam, val_book, n_iter=500, seed=7)}
    return out


# ---------- 7. G2 组合级独立复算（复用 b1 生产设施）----------
def to_b1(recs):
    import b1_risk_backtest_v2 as b1
    out = []
    for s in recs:
        out.append({"date": date.fromisoformat(s["date"]), "entry": s["entry_price"],
                    "limit": s.get("position_limit") or 0.0, "fwd": s.get("fwd_series") or [],
                    "net14": s.get("net14"),
                    "prio": b1.PRIORITY.get(b1.classify(s.get("action_label")), 1)})
    return out


def chk_g2(recs_map, base_recs):
    import b1_risk_backtest_v2 as b1
    out = {}
    for k, recs in recs_map.items():
        m = b1.metrics(b1.simulate(to_b1(recs)))
        m["n"] = len(recs)
        m["calmar"] = round(m["total_return_pct"] / abs(m["max_drawdown_pct"]), 2) if m["max_drawdown_pct"] else None
        out[k] = m
    b = b1.metrics(b1.simulate(to_b1(base_recs)))
    b["n"] = len(base_recs)
    b["calmar"] = round(b["total_return_pct"] / abs(b["max_drawdown_pct"]), 2) if b["max_drawdown_pct"] else None
    out["__baseline__"] = b
    return out


# ---------- 8. G1 A2 独立复算（复用 a2_emission 重跑）----------
def chk_g1():
    import a2_emission as a2
    out = {}
    for k in FAMILY_KEYS:
        fam = json.load(open(REPLAY[k], encoding="utf-8"))
        lab = fam["args"]["family_label"]
        res = a2.analyze(str(REPLAY[k]), str(BASE), lab, lab, n_iter=500, seed=42, regime="all")
        out[k] = {"added_total": res["added_total"], "displaced_total": res["displaced_total"],
                  "fit": {"n": res["segments"]["fit"]["added"]["n"], "p_avg": res["segments"]["fit"]["p_avg"],
                          "added_avg14": res["segments"]["fit"]["added"]["avg14"],
                          "book_avg14": res["segments"]["fit"]["book_avg14"]},
                  "val": {"n": res["segments"]["val"]["added"]["n"], "p_avg": res["segments"]["val"]["p_avg"],
                          "added_avg14": res["segments"]["val"]["added"]["avg14"],
                          "book_avg14": res["segments"]["val"]["book_avg14"]},
                  "passed": (res["segments"]["fit"]["p_avg"] is not None and res["segments"]["fit"]["p_avg"] <= 0.05
                             and res["segments"]["val"]["p_avg"] is not None and res["segments"]["val"]["p_avg"] < 0.05)}
    return out


# ---------- 9. 版本冻结 SQL 直查 ----------
def chk_version_freeze():
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    def q(sql):
        return cur.execute(sql).fetchone()[0]
    return {"items": q("SELECT COUNT(*) FROM items"),
            "price_history": q("SELECT COUNT(*) FROM price_history"),
            "market_index": q("SELECT COUNT(*) FROM market_index")}


def eq(a, b, tol=0.01):
    if a is None or b is None:
        return a == b or (a is None and b is None)
    return abs(a - b) <= tol


def cmp(name, actual, expected, keys=None):
    """逐键对比；None 兼容。返回 (ok, diff)。"""
    if keys is None:
        keys = actual.keys() if isinstance(actual, dict) else []
    diffs = {}
    ok = True
    for kk in keys:
        av, ev = actual.get(kk), (expected.get(kk) if isinstance(expected, dict) else None)
        if isinstance(av, dict) or isinstance(ev, dict):
            sub_ok, sub_d = cmp(name + "." + str(kk), av or {}, ev or {})
            ok &= sub_ok
            if not sub_ok:
                diffs[kk] = sub_d
            continue
        if isinstance(av, (int, float)) and isinstance(ev, (int, float)):
            if not eq(av, ev):
                ok = False
                diffs[kk] = {"actual": av, "expected": ev}
        elif av != ev:
            ok = False
            diffs[kk] = {"actual": av, "expected": ev}
    return ok, diffs


def main():
    iso = json.load(open(ISO, encoding="utf-8"))
    _, base_recs = load(BASE)
    recs_map = {k: load(REPLAY[k])[1] for k in FAMILY_KEYS}

    # G3
    g3 = chk_g3()
    g3_diffs = {}
    for k in FAMILY_KEYS:
        exp = iso["families"][k]["gates"]["G3_half"]
        ok, d = cmp("G3." + k, g3[k], exp, keys=("n", "win14", "avg14", "win30", "avg30"))
        if not ok:
            g3_diffs[k] = d
    audit["checks"]["G3_half"] = {"actual": g3, "diffs": g3_diffs, "ok": not g3_diffs}

    # overlap
    ov = chk_overlap(recs_map)
    ov_diffs = {}
    for a in FAMILY_KEYS:
        for b in FAMILY_KEYS:
            if a == b:
                continue
            act, exp = ov[a][b], iso["three_tables"]["overlap_matrix"]["matrix"][a][b]
            ok, d = cmp("OV.%s.%s" % (a, b), act, exp)
            if not ok:
                ov_diffs.setdefault(a, {})[b] = d
    audit["checks"]["overlap_matrix"] = {"actual": ov, "diffs": ov_diffs, "ok": not ov_diffs}

    # corr
    cr = chk_corr(recs_map)
    cr_diffs = {}
    for a in FAMILY_KEYS:
        for b in FAMILY_KEYS:
            if a == b:
                continue
            act, exp = cr[a][b], iso["three_tables"]["return_corr_matrix"]["matrix"][a][b]
            ok, d = cmp("CR.%s.%s" % (a, b), {"v": act}, {"v": exp})
            if not ok:
                cr_diffs.setdefault(a, {})[b] = d
    audit["checks"]["return_corr_matrix"] = {"actual": cr, "diffs": cr_diffs, "ok": not cr_diffs}

    # period（mismatch==0 即一致）
    pd = chk_period(recs_map)
    pd_ok = all(v.get("mismatch") == 0 for v in pd.values())
    audit["checks"]["period_recompute"] = {"actual": pd, "ok": pd_ok}

    # delta
    dl = chk_delta(recs_map)
    dl_diffs = {}
    for k in FAMILY_KEYS:
        exp = iso["families"][k]["delta"]
        ok, d = cmp("DL." + k, dl[k], exp, keys=("baseline_family_sigs", "kept", "missing_total",
                                                 "missing_real", "missing_legacy_baseline",
                                                 "added_vs_baseline", "zero_drift"))
        if not ok:
            dl_diffs[k] = d
    audit["checks"]["delta"] = {"actual": dl, "diffs": dl_diffs, "ok": not dl_diffs}

    # G4（seed42 复现 + seed7 敏感性）
    g4 = chk_g4(recs_map, base_recs)
    g4_diffs, g4_sens = {}, {}
    for k in FAMILY_KEYS:
        exp = iso["families"][k]["gates"]["G4_perm"]["perm"]
        ok, d = cmp("G4." + k, g4[k]["seed42"], exp, keys=("p_avg", "p_win", "book_avg14", "book_win14",
                                                           "with_replacement"))
        if not ok:
            g4_diffs[k] = d
        p42, p7 = g4[k]["seed42"]["p_avg"], g4[k]["seed7"]["p_avg"]
        g4_sens[k] = {"p_seed42": p42, "p_seed7": p7,
                      "stable_below_0.05": (p42 is None) or (p42 < 0.05) == (p7 is not None and p7 < 0.05)}
    audit["checks"]["G4_perm"] = {"seed42_diffs": g4_diffs, "sensitivity_seed7": g4_sens,
                                  "ok": not g4_diffs}

    # G2（b1 重跑）
    g2 = chk_g2(recs_map, base_recs)
    g2_diffs = {}
    for k in FAMILY_KEYS:
        exp = iso["families"][k]["gates"]["G2_portfolio"]["family"]
        ok, d = cmp("G2." + k, g2[k], exp, keys=("total_return_pct", "max_drawdown_pct", "max_position",
                                                 "rejected_cap", "rejected_breaker", "rejected_item",
                                                 "breaker_active_pct", "days", "n", "calmar"))
        if not ok:
            g2_diffs[k] = d
    bexp = iso["families"]["panic"]["gates"]["G2_portfolio"]["baseline"]
    bok, bd = cmp("G2.baseline", g2["__baseline__"], bexp, keys=("total_return_pct", "max_drawdown_pct",
                                                                 "max_position", "rejected_cap",
                                                                 "rejected_breaker", "rejected_item",
                                                                 "breaker_active_pct", "days", "n", "calmar"))
    if not bok:
        g2_diffs["__baseline__"] = bd
    audit["checks"]["G2_portfolio"] = {"actual": g2, "diffs": g2_diffs, "ok": not g2_diffs}

    # G1（a2 重跑）
    g1 = chk_g1()
    g1_diffs = {}
    for k in FAMILY_KEYS:
        exp = iso["families"][k]["gates"]["G1_a2"]
        ok, d = cmp("G1." + k, g1[k], exp, keys=("added_total", "displaced_total", "passed"))
        ok2, d2 = cmp("G1." + k + ".fit", g1[k]["fit"], exp["fit"], keys=("n", "p_avg", "added_avg14", "book_avg14"))
        ok3, d3 = cmp("G1." + k + ".val", g1[k]["val"], exp["val"], keys=("n", "p_avg", "added_avg14", "book_avg14"))
        if not (ok and ok2 and ok3):
            g1_diffs[k] = {"top": d, "fit": d2, "val": d3}
    audit["checks"]["G1_a2"] = {"actual": g1, "diffs": g1_diffs, "ok": not g1_diffs}

    # 版本冻结
    vf = chk_version_freeze()
    audit["checks"]["version_freeze"] = {"actual": vf,
                                         "expected": {"items": 405, "price_history": 259222,
                                                      "market_index": 1015},
                                         "ok": vf == {"items": 405, "price_history": 259222,
                                                      "market_index": 1015}}

    # 汇总
    for name, c in audit["checks"].items():
        audit["pass"] &= bool(c.get("ok"))
    out_path = ROOT / "data" / "_audit_r3_recompute_2026-08-27.json"
    json.dump(audit, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("AUDIT PASS" if audit["pass"] else "AUDIT FAIL")
    for name, c in audit["checks"].items():
        print("  %-22s %s" % (name, "PASS" if c.get("ok") else "FAIL"))
        if not c.get("ok"):
            print("    diffs:", json.dumps(c.get("diffs"), ensure_ascii=False)[:600])
    print("saved:", out_path)


if __name__ == "__main__":
    main()
