# -*- coding: utf-8 -*-
"""引擎独立全量扫描 · 结构发现 + 双期限正期望 gate + 盲区对照（2026-08-20，②）

读 data/_exp_fullscan_features_2026-08-20.json，执行预注册 §四/§五（③审修订双期限版）：
1. 决策树回归 fwd14 / fwd30 各一棵（min_leaf≥200, depth≤4）→ 叶=区域；
2. 稀有结构探针：pct 20 桶等频 + 低 pct 子空间(pct≤30) min_leaf≈50 细树；
3. 对每个区域跑双期限 gate（任一期限全套达标即过，记自然期限）；
4. 引擎覆盖对照：基线回放信号 (name,date) 匹配区域 → 盲区 = 正期望区域 − 引擎覆盖。
产物：data/_exp_fullscan_regions_2026-08-20.json（全区域）+ data/_exp_fullscan_blindspots_2026-08-20.json（盲区清单）。
"""
import json
import numpy as np
from sklearn.tree import DecisionTreeRegressor

FEAT_JSON = "data/_exp_fullscan_features_2026-08-20.json"
BASE_REPLAY = "data/_exp_cycle_replay_fullpool_2026.json"
OUT_REGIONS = "data/_exp_fullscan_regions_2026-08-20.json"
OUT_BLIND = "data/_exp_fullscan_blindspots_2026-08-20.json"
SPLIT = "2025-08-10"
FEATURES = ["pct", "z", "chg7", "chg30", "chg90", "sc7", "sc30", "vol7", "vol30",
            "mchg7", "mchg21", "mchg30"]
POLLUTED = {"AK-47 | 流金王朝 (崭新出厂)", "挂件 | 丁烷拍档"}


def load_matrix():
    d = json.load(open(FEAT_JSON, encoding="utf-8"))
    X = d["X"]
    n = len(d["item_id"])
    feat_cols = [X[f] for f in FEATURES]
    keep = np.ones(n, dtype=bool)
    for c in feat_cols:
        keep &= np.array([x is not None for x in c], dtype=bool)
    f14 = np.array([np.nan if x is None else x for x in d["fwd14"]])
    f30 = np.array([np.nan if x is None else x for x in d["fwd30"]])
    keep &= ~np.isnan(f14) & ~np.isnan(f30)
    idx = np.where(keep)[0]
    Xmat = np.column_stack([[c[i] for i in idx] for c in feat_cols]).astype(float)
    names = [d["meta"]["item_name"][str(d["item_id"][i])] for i in idx]
    dates = [d["date"][i] for i in idx]
    return Xmat, f14[idx], f30[idx], names, dates, d["meta"]


def eval_tenor(mask, y, dates):
    m = mask & ~np.isnan(y)
    n = int(m.sum())
    out = {"n": n}
    if n < 200:
        out.update({"win": None, "avg": None, "trimmed_avg": None,
                    "fit_avg": None, "fit_win": None, "val_avg": None, "val_win": None, "pass": False})
        return out
    yy = y[m]
    win = float((yy > 0).mean() * 100)
    avg = float(yy.mean())
    k = max(1, int(len(yy) * 0.05))
    trimmed = float(np.sort(yy)[:-k].mean()) if len(yy) > k else avg
    dts = np.array(dates)[m]
    fit = dts < SPLIT
    val = ~fit
    fit_avg = float(yy[fit].mean()) if fit.sum() else None
    fit_win = float((yy[fit] > 0).mean() * 100) if fit.sum() else None
    val_avg = float(yy[val].mean()) if val.sum() else None
    val_win = float((yy[val] > 0).mean() * 100) if val.sum() else None
    passed = (win >= 55 and avg >= 2.0 and trimmed >= 1.0
              and fit_avg is not None and fit_avg > 0 and fit_win >= 50
              and val_avg is not None and val_avg > 0 and val_win >= 50)
    out.update({"win": round(win, 1), "avg": round(avg, 2), "trimmed_avg": round(trimmed, 2),
                "fit_avg": round(fit_avg, 2) if fit_avg is not None else None,
                "fit_win": round(fit_win, 1) if fit_win is not None else None,
                "val_avg": round(val_avg, 2) if val_avg is not None else None,
                "val_win": round(val_win, 1) if val_win is not None else None,
                "pass": bool(passed)})
    return out


def centroid(X, mask):
    return {f: round(float(X[mask, i].mean()), 2) for i, f in enumerate(FEATURES)}


def eval_region(mask, f14, f30, dates, X):
    g14 = eval_tenor(mask, f14, dates)
    g30 = eval_tenor(mask, f30, dates)
    passed = g14["pass"] or g30["pass"]
    natural = [t for t, g in (("14d", g14), ("30d", g30)) if g["pass"]]
    return {"n": int(mask.sum()), "centroid": centroid(X, mask),
            "gate14": g14, "gate30": g30, "passed": passed, "natural_tenor": natural}


def run_tree(X, y, depth, min_leaf):
    t = DecisionTreeRegressor(max_depth=depth, min_samples_leaf=min_leaf, random_state=42)
    t.fit(X, y)
    apply = t.apply(X)
    leaves = [i for i in range(t.tree_.node_count) if t.tree_.children_left[i] == -1]
    return leaves, apply


def main():
    X, f14, f30, names, dates, meta = load_matrix()
    n = len(names)
    print(f"分析集（完整样例）: {n} 条  （原始 {meta['n_records']}）")

    regions = []   # 每项含 mask + 描述
    masks = []

    def add_region(mask, src):
        r = eval_region(mask, f14, f30, dates, X)
        r["source"] = src
        regions.append(r)
        masks.append(mask)

    # 1. 主树 fwd14 / fwd30
    for tname, y in [("fwd14", f14), ("fwd30", f30)]:
        leaves, apply = run_tree(X, y, depth=4, min_leaf=200)
        for L in leaves:
            add_region(apply == L, f"tree_{tname}_leaf{L}")
        print(f"tree_{tname}: {len(leaves)} 叶")

    # 2. pct 20 桶等频
    pct = X[:, 0]
    qs = np.percentile(pct, np.linspace(0, 100, 21))
    for b in range(20):
        mask = (pct >= qs[b]) & (pct < qs[b + 1])
        if b == 19:
            mask = pct >= qs[b]
        add_region(mask, f"pct_bin{b}({qs[b]:.0f}-{qs[b+1]:.0f})")

    # 3. 低 pct 子空间细树
    low_mask = pct <= 30
    if low_mask.sum() >= 100:
        low_idx = np.where(low_mask)[0]
        leaves, apply = run_tree(X[low_mask], f30[low_mask], depth=4, min_leaf=50)
        for L in leaves:
            mask = np.zeros(n, dtype=bool)
            mask[low_idx[apply == L]] = True
            add_region(mask, f"rare_lowpct_leaf{L}")
        print(f"rare_lowpct_tree: {len(leaves)} 叶")

    # 4. 引擎覆盖对照
    eng = set()
    try:
        bd = json.load(open(BASE_REPLAY, encoding="utf-8"))
        eng = {(s["name"], s["date"]) for s in bd.get("signals", [])
               if s["name"] not in POLLUTED}
    except Exception:
        eng = set()

    for r, mask in zip(regions, masks):
        keys = set(zip([names[i] for i in np.where(mask)[0]], [dates[i] for i in np.where(mask)[0]]))
        hits = keys & eng
        r["engine_hits"] = len(hits)
        r["coverage_ratio"] = round(len(hits) / len(keys), 4) if keys else None
        r["n_engine_signal_names"] = len({nm for nm, _ in hits})

    passed = [r for r in regions if r["passed"]]
    blind = [r for r in passed if r["engine_hits"] == 0]
    print(f"\n候选区域 {len(regions)}，通过双期限 gate {len(passed)}，其中引擎零覆盖（盲区）{len(blind)}")

    # 输出：region 不含 mask
    def slim(r):
        return {k: v for k, v in r.items() if k != "mask"}

    json.dump({"meta": {"date": "2026-08-20", "analysis_n": n, "split": SPLIT, "n_engine_signals": len(eng),
                        "features": FEATURES},
               "regions": [slim(r) for r in regions]},
              open(OUT_REGIONS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"meta": {"date": "2026-08-20", "n_blind": len(blind)},
               "blindspots": [slim(r) for r in blind]},
              open(OUT_BLIND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"saved {OUT_REGIONS} 和 {OUT_BLIND}")

    print("\n=== 通过 gate 的区域（n 降序，* 标记=引擎零覆盖盲区）===")
    for r in sorted(passed, key=lambda x: -x["n"]):
        c = r["centroid"]
        star = "*" if r["engine_hits"] == 0 else " "
        print(f"{star}[{r['source']:22s}] n={r['n']:6d} tenor={r['natural_tenor']} "
              f"pct={c['pct']:.0f} z={c['z']:+.1f} chg7={c['chg7']:+.1f} mchg21={c['mchg21']:+.1f} sc30={c['sc30']:+.1f} "
              f"| g14 {r['gate14']['win']}%/{r['gate14']['avg']} | g30 {r['gate30']['win']}%/{r['gate30']['avg']} | 引擎hit={r['engine_hits']}")


if __name__ == "__main__":
    main()
