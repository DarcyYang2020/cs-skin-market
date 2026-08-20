# -*- coding: utf-8 -*-
"""全量特征最优划分 · 决策树双期限切分（2026-08-20，②；CP 预注册执行）

读 data/_exp_fullscan_features_2026-08-20.json，锁定 CB 同款分析集 208,517：
1. 决策树 fwd14 / fwd30 各一棵（min_leaf≥200, depth≤4）→ 叶=候选族；
2. pct 20 桶等频 + 低 pct 子空间(pct≤30) min_leaf≈50 细树（稀有探针）；
3. 每叶：提取决策路径 + 双期限 gate + 单事件三字段 + 引擎覆盖；
4. 产出候选族清单（过 gate）+ 全区域（含未过 gate 供参考）。
产物：data/_exp_optimal_partition_2026-08-20.json
"""
import json
from collections import Counter
import numpy as np
from sklearn.tree import DecisionTreeRegressor

FEAT_JSON = "data/_exp_fullscan_features_2026-08-20.json"
BASE_REPLAY = "data/_exp_cycle_replay_fullpool_2026.json"
OUT = "data/_exp_optimal_partition_2026-08-20.json"
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


def event_fields(dates):
    """单事件三字段：单月最大占比 / 最大事件窗口占比 / 独立事件数（相邻月差≤1 合并）。"""
    months = sorted(set(d[:7] for d in dates))
    def mdiff(a, b):
        ya, ma = int(a[:4]), int(a[5:7])
        yb, mb = int(b[:4]), int(b[5:7])
        return (yb - ya) * 12 + (mb - ma)
    windows = []
    for m in months:
        if windows and mdiff(windows[-1][-1], m) <= 1:
            windows[-1].append(m)
        else:
            windows.append([m])
    cnt = Counter(d[:7] for d in dates)
    n = len(dates)
    max_month_pct = max(cnt.values()) / n * 100 if n else 0
    win_counts = [sum(cnt[m] for m in w) for w in windows]
    max_window_pct = max(win_counts) / n * 100 if n else 0
    return {"max_month_pct": round(max_month_pct, 1),
            "max_window_pct": round(max_window_pct, 1),
            "n_events": len(windows),
            "months": dict(sorted(cnt.items()))}


def path_to(leaf, tree):
    cl = tree.children_left
    cr = tree.children_right
    parent = {}
    for i in range(tree.node_count):
        if cl[i] != -1:
            parent[cl[i]] = i
        if cr[i] != -1:
            parent[cr[i]] = i
    conds = []
    node = leaf
    while node != 0:
        p = parent[node]
        f = tree.feature[p]
        thr = tree.threshold[p]
        if cl[p] == node:
            conds.append(f"{FEATURES[f]}<={thr:.2f}")
        else:
            conds.append(f"{FEATURES[f]}>{thr:.2f}")
        node = p
    return " AND ".join(reversed(conds))


def centroid(X, mask):
    return {f: round(float(X[mask, i].mean()), 2) for i, f in enumerate(FEATURES)}


def main():
    X, f14, f30, names, dates, meta = load_matrix()
    n = len(names)
    print(f"分析集: {n} 条")

    regions = []
    masks = []

    def add_region(mask, src, rule=""):
        r = {"source": src, "rule": rule, "n": int(mask.sum()), "centroid": centroid(X, mask),
             "gate14": eval_tenor(mask, f14, dates), "gate30": eval_tenor(mask, f30, dates)}
        r["passed"] = r["gate14"]["pass"] or r["gate30"]["pass"]
        r["natural_tenor"] = [t for t, g in (("14d", r["gate14"]), ("30d", r["gate30"])) if g["pass"]]
        r["event"] = event_fields([dates[i] for i in np.where(mask)[0]])
        regions.append(r)
        masks.append(mask)

    # 主树 fwd14 / fwd30
    for tname, y in [("fwd14", f14), ("fwd30", f30)]:
        t = DecisionTreeRegressor(max_depth=4, min_samples_leaf=200, random_state=42)
        t.fit(X, y)
        apply = t.apply(X)
        leaves = [i for i in range(t.tree_.node_count) if t.tree_.children_left[i] == -1]
        for L in leaves:
            add_region(apply == L, f"tree_{tname}_leaf{L}", path_to(L, t.tree_))
        print(f"tree_{tname}: {len(leaves)} 叶")

    # pct 20 桶
    pct = X[:, 0]
    qs = np.percentile(pct, np.linspace(0, 100, 21))
    for b in range(20):
        mask = (pct >= qs[b]) & (pct < qs[b + 1])
        if b == 19:
            mask = pct >= qs[b]
        add_region(mask, f"pct_bin{b}({qs[b]:.0f}-{qs[b+1]:.0f})")

    # 低 pct 细树
    low_mask = pct <= 30
    if low_mask.sum() >= 100:
        low_idx = np.where(low_mask)[0]
        t = DecisionTreeRegressor(max_depth=4, min_samples_leaf=50, random_state=42)
        t.fit(X[low_mask], f30[low_mask])
        apply = t.apply(X[low_mask])
        leaves = [i for i in range(t.tree_.node_count) if t.tree_.children_left[i] == -1]
        for L in leaves:
            mask = np.zeros(n, dtype=bool)
            mask[low_idx[apply == L]] = True
            add_region(mask, f"rare_lowpct_leaf{L}", path_to(L, t.tree_))
        print(f"rare_lowpct_tree: {len(leaves)} 叶")

    # 引擎覆盖
    eng = set()
    try:
        bd = json.load(open(BASE_REPLAY, encoding="utf-8"))
        eng = {(s["name"], s["date"]) for s in bd.get("signals", []) if s["name"] not in POLLUTED}
    except Exception:
        eng = set()
    for r, mask in zip(regions, masks):
        keys = set(zip([names[i] for i in np.where(mask)[0]], [dates[i] for i in np.where(mask)[0]]))
        hits = keys & eng
        r["engine_hits"] = len(hits)
        r["coverage_ratio"] = round(len(hits) / len(keys), 4) if keys else None

    passed = [r for r in regions if r["passed"]]
    print(f"\n候选区域 {len(regions)}，过 gate {len(passed)}")

    json.dump({"meta": {"date": "2026-08-20", "analysis_n": n, "split": SPLIT,
                        "n_engine_signals": len(eng), "features": FEATURES,
                        "note": "event 字段=单事件三字段(单月最大占比/最大事件窗口占比/独立事件数，相邻月差≤1合并)"},
               "regions": regions,
               "passed": [r for r in regions if r["passed"]]},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"saved {OUT}")

    print("\n=== 通过 gate 的候选族（n 降序）===")
    for r in sorted(passed, key=lambda x: -x["n"]):
        c = r["centroid"]
        e = r["event"]
        print(f"[{r['source']:20s}] n={r['n']:6d} tenor={r['natural_tenor']} "
              f"单月={e['max_month_pct']}% 窗口={e['max_window_pct']}% 事件={e['n_events']} "
              f"| pct={c['pct']:.0f} z={c['z']:+.1f} chg7={c['chg7']:+.1f} mchg21={c['mchg21']:+.1f} mchg30={c['mchg30']:+.1f} sc30={c['sc30']:+.1f} "
              f"| g14 {r['gate14']['win']}%/{r['gate14']['avg']} | g30 {r['gate30']['win']}%/{r['gate30']['avg']} | hit={r['engine_hits']}")


if __name__ == "__main__":
    main()
