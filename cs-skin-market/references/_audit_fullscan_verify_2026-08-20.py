# -*- coding: utf-8 -*-
"""③审计独立重算：复现 fullscan_regions 的 63 区域构造，补充 gate 未暴露的
fit_n/val_n 与月度/单品集中度，核验候选②的「单事件簇」断言。"""
import sys, json
from collections import Counter
sys.path.insert(0, "references")
import fullscan_regions as fr
import numpy as np

X, f14, f30, names, dates, meta = fr.load_matrix()
SPLIT = fr.SPLIT
n = len(names)
print("analysis_n", n, "SPLIT", SPLIT)

regions = []
def add_region(mask, src):
    regions.append((src, mask))

for tname, y in [("fwd14", f14), ("fwd30", f30)]:
    leaves, apply = fr.run_tree(X, y, depth=4, min_leaf=200)
    for L in leaves:
        add_region(apply == L, f"tree_{tname}_leaf{L}")
pct = X[:, 0]
qs = np.percentile(pct, np.linspace(0, 100, 21))
for b in range(20):
    mask = (pct >= qs[b]) & (pct < qs[b + 1])
    if b == 19:
        mask = pct >= qs[b]
    add_region(mask, f"pct_bin{b}")
low_mask = pct <= 30
if low_mask.sum() >= 100:
    low_idx = np.where(low_mask)[0]
    leaves, apply = fr.run_tree(X[low_mask], f30[low_mask], depth=4, min_leaf=50)
    for L in leaves:
        mask = np.zeros(n, dtype=bool)
        mask[low_idx[apply == L]] = True
        add_region(mask, f"rare_lowpct_leaf{L}")

dates_arr = np.array(dates)
def enhanced(mask, y):
    m = mask & ~np.isnan(y)
    nn = int(m.sum())
    dts = dates_arr[m]
    fit = dts < SPLIT
    val = ~fit
    fit_n = int(fit.sum()); val_n = int(val.sum())
    months = Counter(d[:7] for d in dts)
    items = Counter(names[i] for i in np.where(m)[0])
    return nn, fit_n, val_n, months, items

focus = {"tree_fwd30_leaf8": "牛市上行段①", "tree_fwd30_leaf21": "深跌反弹右侧②"}
for src, mask in regions:
    if src in focus:
        for y, tname in [(f14, "14d"), (f30, "30d")]:
            nn, fit_n, val_n, months, items = enhanced(mask, y)
            top_item, top_cnt = items.most_common(1)[0]
            top_month, top_mcnt = months.most_common(1)[0]
            print(f"\n[{focus[src]}] {src} target={tname} n={nn} fit_n={fit_n} val_n={val_n}")
            print("  months:", dict(sorted(months.items())))
            print("  max-month share: %s = %d (%.1f%%)" % (top_month, top_mcnt, 100*top_mcnt/nn))
            print("  top item: %s  count=%d share=%.1f%%" % (top_item[:50], top_cnt, 100*top_cnt/nn))
        r = fr.eval_region(mask, f14, f30, dates, X)
        print("  >> gate recheck passed=%s tenor=%s" % (r["passed"], r["natural_tenor"]))

# 全 63 区：passed 区的 fit_n 分布（看 walk-forward 拟合段是否过薄）
print("\n=== passed 区 fit_n 概览（任一期限 pass）===")
thin = 0
for src, mask in regions:
    r = fr.eval_region(mask, f14, f30, dates, X)
    if not r["passed"]:
        continue
    _, fn14, vn14, _, _ = enhanced(mask, f14)
    _, fn30, vn30, _, _ = enhanced(mask, f30)
    fn = fn14 if r["gate14"]["pass"] else fn30
    if fn < 15:
        thin += 1
        print("  THIN fit_n<15: %s fit_n=%d n=%d" % (src, fn, r["n"]))
print("passed 区中 fit_n<15 数:", thin)
