# -*- coding: utf-8 -*-
"""CQ-ADD-1 delta 清单审计（2026-08-20，②研究窗口，预注册 cq-add1-prereg-2026-08-20.md §五）。

独立重算族开回放 delta 四件套：①基线非新族信号逐条字节一致（零漂移）②added 量级对照
③displaced/relabeled ④月度/单品分布。并出 added/基线 分段统计（切点 2025-08-10）。
输出 data/_exp_cq_add1_delta_2026-08-20.json + 控制台清单。只读，不改生产。
"""
import json
import sys
from collections import Counter
from datetime import date

BASE = "data/_exp_cycle_replay_fullpool_2026.json"
FAM = "data/_exp_cq_add1_replay_2026-08-20.json"
OUT = "data/_exp_cq_add1_delta_2026-08-20.json"
SPLIT = date(2025, 8, 10)
NEW_LABEL = "牛市上行·高选择性窄化"


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    return [s for s in d.get("signals", []) if s.get("net14") is not None]


def key(s):
    return (s["name"], s["date"])


def stats(recs):
    n = len(recs)
    if n == 0:
        return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
    n30 = [r for r in recs if r.get("net30") is not None]
    return {
        "n": n,
        "win14": round(100.0 * sum(1 for r in recs if r["net14"] > 0) / n, 1),
        "avg14": round(sum(r["net14"] for r in recs) / n, 2),
        "win30": round(100.0 * sum(1 for r in n30 if r["net30"] > 0) / len(n30), 1) if n30 else None,
        "avg30": round(sum(r["net30"] for r in n30) / len(n30), 2) if n30 else None,
    }


base = load(BASE)
fam = load(FAM)

bkeys = {key(s) for s in base}
fkeys = {key(s) for s in fam}

added = [s for s in fam if key(s) not in bkeys]
displaced = [s for s in base if key(s) not in fkeys]
matched = [s for s in base if key(s) in fkeys]

fam_by_key = {key(s): s for s in fam}
drift = []
for s in matched:
    t = fam_by_key[key(s)]
    if s.get("net14") != t.get("net14") or s.get("net30") != t.get("net30"):
        drift.append((s["name"], s["date"], s.get("net14"), t.get("net14"), s.get("net30"), t.get("net30")))

relabeled = [s for s in matched if fam_by_key[key(s)]["action_label"] != s["action_label"]]

# 新族信号（added 中属 cq_add1 标签的）
new_sigs = [s for s in added if NEW_LABEL in (s.get("action_label") or "")]
non_new = [s for s in added if NEW_LABEL not in (s.get("action_label") or "")]  # knock-on 换标签？

# 否决线检查
max_month = None
if new_sigs:
    mm = Counter(s["date"][:7] for s in new_sigs).most_common(1)[0]
    max_month = {"month": mm[0], "n": mm[1], "pct": round(100.0 * mm[1] / len(new_sigs), 1),
                 "veto": 100.0 * mm[1] / len(new_sigs) > 50}
added_veto = len(added) >= 10000

# 分段（切点 2025-08-10）
def split_by(recs):
    fit = [s for s in recs if date.fromisoformat(s["date"]) < SPLIT]
    val = [s for s in recs if date.fromisoformat(s["date"]) >= SPLIT]
    return fit, val

fit_add, val_add = split_by(new_sigs)
fit_bk, val_bk = split_by(base)

# 单品分布（top5）
item_top = Counter(s["name"] for s in new_sigs).most_common(5)

report = {
    "baseline_n": len(base), "fam_on_n": len(fam),
    "added": len(added), "displaced": len(displaced), "matched": len(matched),
    "net_drift": len(drift), "relabeled": len(relabeled),
    "added_new_label": len(new_sigs), "added_knock_on": len(non_new),
    "added_veto_ge_10000": added_veto,
    "max_month": max_month,
    "item_top5": item_top,
    "new_sigs": {"fit": stats(fit_add), "val": stats(val_add)},
    "book": {"fit": stats(fit_bk), "val": stats(val_bk)},
    "monthly": dict(sorted(Counter(s["date"][:7] for s in new_sigs).items())),
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)

print("== CQ-ADD-1 delta 清单 ==")
print(f"baseline n={len(base)} | fam_on n={len(fam)}")
print(f"added={len(added)} (>=10,000 自动驳回: {added_veto}) | displaced={len(displaced)} | matched={len(matched)}")
print(f"net_drift={len(drift)} (应=0) | relabeled={len(relabeled)}")
print(f"added 中新族标签={len(new_sigs)} | knock-on={len(non_new)}")
print(f"added by label: {dict(Counter(s['action_label'] for s in added))}")
print(f"最大月={max_month}")
print(f"单品 top5: {item_top}")
print()
print("== 分段（切点 2025-08-10） ==")
print(f"新族 added: fit={stats(fit_add)} val={stats(val_add)}")
print(f"基线 book: fit={stats(fit_bk)} val={stats(val_bk)}")
print()
print(f"saved {OUT}")
