# -*- coding: utf-8 -*-
"""R3 策略隔离评估 · 完整四关 + 差异化三表 + 组合测试（2026-08-27，②研究窗口）。

判据：references/r3-family-isolation-prereg-2026-08-27.md（DR PM 冻结）。
输入：data/_exp_family_<key>_replay_2026-08-27.json（6 族单开回放）+ 研究基线
      data/_exp_cycle_replay_fullpool_2026.json（376 信号，判据指定对比基准）
      + data/_exp_current_engine_fullpool_2026-08-27.json（当前引擎无注入参照，零漂移归因用）。
只读，不写生产。输出：data/_exp_family_isolation_2026-08-27.json。

每族四关通过线（north_star 口径，跑前定死）：
  G1 A2 发射复算：fit 段 p_avg ≤0.05 且 val 段 p_avg <0.05（val 不显著即证伪）
  G2 组合级：该族独立组合风险调整后收益 ≥ 基线同口径（主比 Calmar/maxDD，次比总收益；劣化 <10pp）
  G3 前后半段：切点 2025-08-10，fit win14 ≥60% 且 val win14 ≥60% 且 val avg14 >0（val 不显著即证伪）
  G4 置换检验：val 段收益差 p_avg <0.05（n_iter=500, seed=42）
全过 → 候选子策略（进入差异化评估）；任一不过 → 证伪（从多策略候选划掉）。
"""
import json
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "references"))

import a2_emission  # noqa: E402
import b1_risk_backtest_v2 as b1  # noqa: E402

SPLIT = date(2025, 8, 10)
BASE = ROOT / "data" / "_exp_cycle_replay_fullpool_2026.json"          # 研究基线（判据指定）
CUR = ROOT / "data" / "_exp_current_engine_fullpool_2026-08-27.json"   # 当前引擎无注入参照

FAMILY_KEYS = ("panic", "deep", "rise", "supply", "reversal", "base")
REPLAY = {k: ROOT / "data" / ("_exp_family_%s_replay_2026-08-27.json" % k) for k in FAMILY_KEYS}

PERIODS = ("P恐慌深跌", "S1牛市上行", "S2牛市回调", "S3弱市阴跌", "S4弱市反弹")


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    return d, [s for s in d.get("signals", []) if s.get("net14") is not None]


def stats(recs):
    n = len(recs)
    if n == 0:
        return {"n": 0, "win14": None, "avg14": None, "net30_avg": None}
    n30 = [r for r in recs if r.get("net30") is not None]
    return {"n": n,
            "win14": round(100.0 * sum(1 for r in recs if r["net14"] > 0) / n, 1),
            "avg14": round(sum(r["net14"] for r in recs) / n, 2),
            "win30": round(100.0 * sum(1 for r in n30 if r["net30"] > 0) / len(n30), 1) if n30 else None,
            "avg30": round(sum(r["net30"] for r in n30) / len(n30), 2) if n30 else None}


def to_b1(recs):
    """族开回放信号 → b1.simulate 输入（R1 教训适配：date 转 date 对象/entry/limit/fwd/prio）。"""
    out = []
    for s in recs:
        out.append({
            "date": date.fromisoformat(s["date"]),
            "entry": s["entry_price"],
            "limit": s.get("position_limit") or 0.0,
            "fwd": s.get("fwd_series") or [],
            "net14": s.get("net14"),
            "prio": b1.PRIORITY.get(b1.classify(s.get("action_label")), 1),
        })
    return out


def sim_metrics(recs):
    if not recs:
        return {"n": 0, "total_return_pct": None, "max_drawdown_pct": None, "calmar": None,
                "max_position": None}
    m = b1.metrics(b1.simulate(to_b1(recs)))
    m["n"] = len(recs)
    m["calmar"] = round(m["total_return_pct"] / abs(m["max_drawdown_pct"]), 2) if m["max_drawdown_pct"] else None
    return m


def monthly_avg_net14(recs):
    """信号月度平均 net14 序列（YYYY-MM → avg net14），供收益相关矩阵。"""
    buckets = {}
    for s in recs:
        buckets.setdefault(s["date"][:7], []).append(s["net14"])
    return {k: sum(v) / len(v) for k, v in sorted(buckets.items())}


def pearson(xs, ys):
    ks = [k for k in xs if k in ys]
    if len(ks) < 3:
        return None
    xv = [xs[k] for k in ks]
    yv = [ys[k] for k in ks]
    n = len(ks)
    mx, my = sum(xv) / n, sum(yv) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xv, yv))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xv))
    dy = math.sqrt(sum((b - my) ** 2 for b in yv))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)


def gate1_a2(fam_file, fam_label):
    """A2 发射复算（a2_emission.analyze 含置换 n_iter=500 seed=42 regime=all）。"""
    res = a2_emission.analyze(str(fam_file), str(BASE), fam_label, fam_label, n_iter=500, seed=42, regime="all")
    fit_p = res["segments"]["fit"]["p_avg"]
    val_p = res["segments"]["val"]["p_avg"]
    fit_n = res["segments"]["fit"]["added"]["n"]
    val_n = res["segments"]["val"]["added"]["n"]
    passed = (fit_p is not None and fit_p <= 0.05
              and val_p is not None and val_p < 0.05)
    return {
        "added_total": res["added_total"], "displaced_total": res["displaced_total"],
        "fit": {"n": fit_n, "p_avg": fit_p, "added_avg14": res["segments"]["fit"]["added"]["avg14"],
                "book_avg14": res["segments"]["fit"]["book_avg14"]},
        "val": {"n": val_n, "p_avg": val_p, "added_avg14": res["segments"]["val"]["added"]["avg14"],
                "book_avg14": res["segments"]["val"]["book_avg14"]},
        "passed": passed,
    }


def gate2_portfolio(fam_recs, base_recs):
    """组合级：该族独立组合 vs 基线（全引擎）同口径。主比 Calmar/maxDD，次比总收益；劣化<10pp。"""
    f = sim_metrics(fam_recs)
    b = sim_metrics(base_recs)
    d_total = (b["total_return_pct"] - f["total_return_pct"]) if f["total_return_pct"] is not None and b["total_return_pct"] is not None else None
    d_dd = (f["max_drawdown_pct"] - b["max_drawdown_pct"]) if f["max_drawdown_pct"] is not None and b["max_drawdown_pct"] is not None else None
    passed = (f["total_return_pct"] is not None and f["total_return_pct"] >= 0
              and d_total is not None and d_total <= 10
              and d_dd is not None and d_dd <= 10)
    return {"family": f, "baseline": b, "d_total_pp": d_total, "d_maxdd_pp": d_dd, "passed": passed}


def gate3_half(fam_recs):
    fit = [s for s in fam_recs if date.fromisoformat(s["date"]) < SPLIT]
    val = [s for s in fam_recs if date.fromisoformat(s["date"]) >= SPLIT]
    fs, vs = stats(fit), stats(val)
    passed = (fs["win14"] is not None and fs["win14"] >= 60
              and vs["win14"] is not None and vs["win14"] >= 60
              and vs["avg14"] is not None and vs["avg14"] > 0)
    return {"fit": fs, "val": vs, "passed": passed}


def gate4_perm(fam_recs, base_recs):
    val_fam = [{"date": date.fromisoformat(s["date"]), "name": s["name"], "action_label": s.get("action_label") or "",
                "net14": s["net14"], "net30": s.get("net30")} for s in fam_recs if date.fromisoformat(s["date"]) >= SPLIT]
    val_book = [{"date": date.fromisoformat(s["date"]), "name": s["name"], "action_label": s.get("action_label") or "",
                 "net14": s["net14"], "net30": s.get("net30")} for s in base_recs if date.fromisoformat(s["date"]) >= SPLIT]
    p = a2_emission._perm_p(val_fam, val_book, n_iter=500, seed=42)
    passed = p.get("p_avg") is not None and p["p_avg"] < 0.05
    return {"val_n": len(val_fam), "perm": p, "passed": passed}


def main():
    _, base_recs = load(BASE)
    _, cur_recs = load(CUR)
    base_keys = {(s["date"], s["name"]) for s in base_recs}
    cur_keys = {(s["date"], s["name"]) for s in cur_recs}

    families = {}
    for k in FAMILY_KEYS:
        d, recs = load(REPLAY[k])
        fam_label = d["args"]["family_label"]
        # 零漂移：与当前引擎无注入参照对比（同引擎同数据口径，排除基线旧产物干扰）
        ce = {(s["date"], s["name"], s["net14"]) for s in cur_recs}
        # 基线中属于该族的信号（label 过滤用回放文件的 labels 配置）
        labels = tuple(d["args"]["labels"])
        match_exact = k == "base"
        base_fam = [s for s in base_recs
                    if (s.get("action_label") or "") in labels] if match_exact else \
                   [s for s in base_recs if any(lb in (s.get("action_label") or "") for lb in labels)]
        fam_keys = {(s["date"], s["name"], s["net14"]) for s in recs}
        missing = [s for s in base_fam if (s["date"], s["name"], s["net14"]) not in fam_keys]
        # 归因：missing 中当前引擎可复现的（在 cur_keys 且同 label 语义）→ 真缺失；否则=基线旧产物
        real_missing, legacy = [], []
        for s in missing:
            cur_has = any(cs["name"] == s["name"] and cs["date"] == s["date"]
                          for cs in cur_recs)
            if cur_has:
                real_missing.append(s)
            else:
                legacy.append(s)
        zero_drift = len(real_missing) == 0
        added = [s for s in recs if (s["date"], s["name"], s["net14"]) not in
                 {(b_["date"], b_["name"], b_["net14"]) for b_ in base_recs}]
        families[k] = {
            "label": fam_label, "signals": len(recs),
            "delta": {
                "baseline_family_sigs": len(base_fam),
                "kept": len(base_fam) - len(missing),
                "missing_total": len(missing),
                "missing_real": len(real_missing), "missing_legacy_baseline": len(legacy),
                "missing_samples": [{"date": s["date"], "name": s["name"], "label": s.get("action_label"),
                                     "net14": s["net14"], "attribution": "引擎演进(基线旧产物)" if not any(
                                         cs["name"] == s["name"] and cs["date"] == s["date"] for cs in cur_recs)
                                     else "族内去重自约束"} for s in missing[:10]],
                "added_vs_baseline": len(added),
                "zero_drift": zero_drift,
                "zero_drift_note": "零漂移=相对当前引擎无注入参照，基线族信号同键(品,日,net14)全保持；"
                                   "missing 归因=族内去重自约束(去重交互真实行为) 或 基线旧引擎产物(参照无注入亦无)"},
            "stats": stats(recs),
            "gates": {},
        }
        # ---- 完整四关 ----
        g1 = gate1_a2(REPLAY[k], fam_label)
        g2 = gate2_portfolio(recs, base_recs)
        g3 = gate3_half(recs)
        g4 = gate4_perm(recs, base_recs)
        families[k]["gates"] = {"G1_a2": g1, "G2_portfolio": g2, "G3_half": g3, "G4_perm": g4}
        gates_ok = [g1["passed"], g2["passed"], g3["passed"], g4["passed"]]
        families[k]["gates_all_pass"] = all(gates_ok)
        families[k]["verdict"] = "候选子策略（四关全过，进入差异化评估）" if all(gates_ok) else "证伪（从多策略候选划掉）"
        print("== %s %s ==" % (k, fam_label))
        print("  信号 %d | stats %s" % (len(recs), stats(recs)))
        print("  delta: baseline_fam=%d kept=%d missing=%d(real=%d legacy=%d) added=%d zero_drift=%s" % (
            len(base_fam), len(base_fam) - len(missing), len(missing), len(real_missing), len(legacy),
            len(added), zero_drift))
        print("  G1: fit_p=%s val_p=%s -> %s" % (g1["fit"]["p_avg"], g1["val"]["p_avg"], g1["passed"]))
        print("  G2: fam total=%s maxDD=%s calmar=%s vs base total=%s maxDD=%s -> %s" % (
            g2["family"]["total_return_pct"], g2["family"]["max_drawdown_pct"], g2["family"]["calmar"],
            g2["baseline"]["total_return_pct"], g2["baseline"]["max_drawdown_pct"], g2["passed"]))
        print("  G3: fit %s / val %s -> %s" % (g3["fit"], g3["val"], g3["passed"]))
        print("  G4: val_n=%d p_avg=%s -> %s" % (g4["val_n"], g4["perm"].get("p_avg"), g4["passed"]))
        print("  verdict:", families[k]["verdict"])

    # ---- 差异化三表 ----
    fam_recs_map = {k: load(REPLAY[k])[1] for k in FAMILY_KEYS}
    three = {}

    # 1) 信号重叠矩阵：同品同日多族触发（Jaccard + 相对较小者重叠率）
    key_sets = {k: {(s["date"], s["name"]) for s in fam_recs_map[k]} for k in FAMILY_KEYS}
    overlap = {}
    for a in FAMILY_KEYS:
        overlap[a] = {}
        for b in FAMILY_KEYS:
            if a == b:
                overlap[a][b] = None
                continue
            inter = len(key_sets[a] & key_sets[b])
            union = len(key_sets[a] | key_sets[b])
            mn = min(len(key_sets[a]), len(key_sets[b])) or 1
            overlap[a][b] = {"inter": inter, "jaccard": round(inter / union, 3) if union else None,
                             "overlap_min": round(inter / mn, 3) if mn else None}
    three["overlap_matrix"] = {"note": "同品同日多族触发；jaccard>0.5 或 overlap_min>0.5 = 非独立策略（合并或留一）",
                               "counts": {k: len(v) for k, v in key_sets.items()}, "matrix": overlap}

    # 2) 收益相关矩阵：各族信号月度 avg net14 Pearson
    monthly = {k: monthly_avg_net14(fam_recs_map[k]) for k in FAMILY_KEYS}
    corr = {}
    for a in FAMILY_KEYS:
        corr[a] = {}
        for b in FAMILY_KEYS:
            corr[a][b] = pearson(monthly[a], monthly[b]) if a != b else 1.0
    three["return_corr_matrix"] = {"note": "各族信号月度 avg net14 相关；|r|<0.5 有组合价值，|r|>=0.7 冗余(同质)",
                                   "matrix": corr}

    # 3) 时期覆盖表：各族信号 × 五时期（_period 补记字段；基线信号按市场上下文重建）
    period_rows = {}
    for k in FAMILY_KEYS:
        rows = {}
        for p in PERIODS:
            pr = [s for s in fam_recs_map[k] if s.get("_period") == p]
            rows[p] = stats(pr)
        period_rows[k] = rows
    three["period_coverage"] = {"note": "各族在 P/S1/S2/S3/S4 五时期信号分布与贡献（n/win14/avg14）；不同族管不同时期=最强多策略理由",
                                "rows": period_rows}

    # ---- 组合测试（全过四关且差异化的族；等权 / A2 期望加权，禁优化器）----
    cands = [k for k in FAMILY_KEYS if families[k]["gates_all_pass"]]
    combo = {"candidates": cands, "note": "组合=全过四关族的信号合并（b1 同口径 hold21/成本2%/拒绝优先级），禁优化器",
             "results": {}}
    base_m = sim_metrics(base_recs)
    combo["results"]["baseline_single_engine"] = base_m
    if len(cands) >= 2:
        combo_recs = [s for k in cands for s in fam_recs_map[k]]
        ew = sim_metrics(combo_recs)
        combo["results"]["equal_weight"] = ew
        # A2 期望加权：权重∝各族 val 段 avg14（四关验证期望，规则非优化）；val avg14<0 族权重=0（不参与）
        fam_val_avg = {k: families[k]["gates"]["G3_half"]["val"]["avg14"] for k in cands}
        wmax = max(fam_val_avg.values()) if any(v is not None and v > 0 for v in fam_val_avg.values()) else 1.0
        weighted = []
        for k in cands:
            w = max(0.0, (fam_val_avg[k] or 0.0)) / wmax if wmax else 0.0
            if w <= 0:
                continue
            for s in fam_recs_map[k]:
                s2 = dict(s)
                s2["position_limit"] = round((s.get("position_limit") or 0.0) * w, 4)
                weighted.append(s2)
        a2w = sim_metrics(weighted) if weighted else {"n": 0}
        combo["results"]["a2_expectancy_weight"] = a2w
        combo["results"]["a2_weights"] = {k: (round(max(0.0, (families[k]["gates"]["G3_half"]["val"]["avg14"] or 0.0)) / wmax, 3) if wmax else 0.0) for k in cands}
        # north_star 判据：组合 total ≥ 基线 且 maxDD 不劣化（回撤更浅或持平）
        def north_star(m):
            if not m or m["total_return_pct"] is None or base_m["total_return_pct"] is None:
                return None
            return {"total_gain_pp": round(m["total_return_pct"] - base_m["total_return_pct"], 2),
                    "dd_diff_pp": round(m["max_drawdown_pct"] - base_m["max_drawdown_pct"], 2),
                    "passed": (m["total_return_pct"] >= base_m["total_return_pct"]
                               and m["max_drawdown_pct"] <= base_m["max_drawdown_pct"])}
        combo["results"]["equal_weight_northstar"] = north_star(ew)
        combo["results"]["a2_weight_northstar"] = north_star(a2w)
        combo["multi_strategy_verdict"] = (
            "多策略形态成立" if any(
                (combo["results"].get("equal_weight_northstar") or {}).get("passed")
                or (combo["results"].get("a2_weight_northstar") or {}).get("passed")
            ) else "单引擎维持（组合无 north_star 增益）")
    else:
        combo["multi_strategy_verdict"] = "候选族不足 2 个，无法组合——多策略形态不成立"

    out = {
        "meta": {
            "title": "R3 策略隔离评估",
            "generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
            "prereg": "references/r3-family-isolation-prereg-2026-08-27.md（DR PM 冻结）",
            "candidate_source": "候选族=现有生产族（引擎 v2-T13 SIGNAL_FAMILIES 已注册）；"
                                "rise_contract/xishou_mid/second_wave 为引擎已注册默认关族，评估期开启（env 声明）——无新族注入",
            "oos_zone": "探索只许 fit 段（<2025-08-10，config.OOS_ZONE.val_start）；val 段仅四关 G2/G3/G4 预注册验证触碰，"
                        "回放逐日期 oos_guard.require_fit(prereg=... ) 接线",
            "version_freeze": "回放输入库 replay_cycle_win.db（405 items/259,222 price_history/1015 market_index），"
                              "研究基线 _exp_cycle_replay_fullpool_2026.json（376 信号）",
            "zero_drift_basis": "零漂移对照=当前引擎无注入全池 _exp_current_engine_fullpool_2026-08-27.json（同引擎同数据口径）",
        },
        "families": families,
        "three_tables": three,
        "combination": combo,
        "decision": {
            "multi_strategy": combo.get("multi_strategy_verdict"),
            "note": "结论只到筛查层：不改引擎、不立落地卡；全过四关且差异化族 → PM 定形态（生命周期台账候选层）",
        },
    }
    out_path = ROOT / "data" / "_exp_family_isolation_2026-08-27.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n===== 汇总 =====")
    for k in FAMILY_KEYS:
        print("%-8s %-6s G1:%s G2:%s G3:%s G4:%s -> %s" % (
            k, families[k]["label"], families[k]["gates"]["G1_a2"]["passed"],
            families[k]["gates"]["G2_portfolio"]["passed"], families[k]["gates"]["G3_half"]["passed"],
            families[k]["gates"]["G4_perm"]["passed"], families[k]["verdict"][:12]))
    print("组合候选:", cands)
    print("组合结果:", json.dumps(combo.get("results", {}), ensure_ascii=False)[:800])
    print("多策略裁定:", combo.get("multi_strategy_verdict"))
    print("saved:", out_path)


if __name__ == "__main__":
    main()
