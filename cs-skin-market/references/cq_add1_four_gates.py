# -*- coding: utf-8 -*-
"""CQ-ADD-1 完整四关（2026-08-20，②研究窗口，预注册 cq-add1-prereg-2026-08-20.md §五）。

第一关 A2 发射分布复算（a2_emission.analyze，含置换检验 _perm_p）
第二关 组合级（b1_risk_backtest_v2.simulate：期望/胜率/maxDD vs 基线）
第三关 前后半段一致（切点 2025-08-10）
第四关 置换检验（独立重跑 n_iter=500, seed=42）

输入：data/_exp_cq_add1_replay_2026-08-20.json（族开回放）+ 基线。只读。
"""
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "references"))

BASE = ROOT / "data" / "_exp_cycle_replay_fullpool_2026.json"
FAM = ROOT / "data" / "_exp_cq_add1_replay_2026-08-20.json"
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
        return {"n": 0, "win14": None, "avg14": None}
    return {"n": n,
            "win14": round(100.0 * sum(1 for r in recs if r["net14"] > 0) / n, 1),
            "avg14": round(sum(r["net14"] for r in recs) / n, 2)}


import a2_emission  # noqa: E402
import b1_risk_backtest_v2 as b1  # noqa: E402

base = load(BASE)
fam = load(FAM)
bkeys = {key(s) for s in base}
added = [s for s in fam if key(s) not in bkeys]
new_sigs = [s for s in added if NEW_LABEL in (s.get("action_label") or "")]
fit_new = [s for s in new_sigs if date.fromisoformat(s["date"]) < SPLIT]
val_new = [s for s in new_sigs if date.fromisoformat(s["date"]) >= SPLIT]
fit_bk = [s for s in base if date.fromisoformat(s["date"]) < SPLIT]
val_bk = [s for s in base if date.fromisoformat(s["date"]) >= SPLIT]

print("=" * 60)
print("第一关：A2 发射分布复算（a2_emission.analyze, regime=all, 含置换 n_iter=500 seed=42）")
print("=" * 60)
res = a2_emission.analyze(str(FAM), str(BASE), NEW_LABEL, "cq_add1", n_iter=500, seed=42, regime="all")
a2_emission.print_report(res)

print()
print("=" * 60)
print("第二关：组合级（b1_risk_backtest_v2.simulate）")
print("=" * 60)
for tag, recs in [("基线(全信号)", base), ("族开(全信号)", fam), ("新族 added", new_sigs)]:
    if not recs:
        print(f"{tag}: 无信号")
        continue
    r = b1.simulate(recs)
    print(f"{tag}: n={len(recs)} total_return={r.get('total_return_pct')}% maxDD={r.get('max_dd_pct')}% "
          f"realized={r.get('realized_return_pct')}% wins={r.get('wins')}/{r.get('closed_count')}")

print()
print("=" * 60)
print("第三关：前后半段一致（切点 2025-08-10）")
print("=" * 60)
print(f"新族 added fit: {stats(fit_new)}")
print(f"新族 added val: {stats(val_new)}")
print(f"基线 book fit: {stats(fit_bk)}")
print(f"基线 book val: {stats(val_bk)}")
if val_new:
    vw, va = stats(val_new)["win14"], stats(val_new)["avg14"]
    bw, ba = stats(val_bk)["win14"], stats(val_bk)["avg14"]
    print(f"val 对照: 新族 win14={vw}% avg14={va} vs 基线 book win14={bw}% avg14={ba}")
    print(f"方向正确(新族avg>0): {va is not None and va > 0} | 与book可比(新族win14>=60): {vw is not None and vw >= 60}")
else:
    print("val 段无 added → 验证段不显著，即证伪（按预注册 §三.3）")

print()
print("=" * 60)
print("第四关：置换检验（独立重跑 _perm_p, n_iter=500, seed=42）")
print("=" * 60)
p = a2_emission._perm_p(val_new, val_bk, n_iter=500, seed=42)
print(f"val 段置换: {p}")
sig = p.get("p_avg", 1.0) < 0.05
print(f"p_avg<0.05 显著: {sig}")
