# -*- coding: utf-8 -*-
"""③独立核验 CE：从原始产物重算 delta / crash_vol 集中度 / bull_steady 分段统计 / 基线买书，
并重跑 a2_emission.analyze 复算 bull_steady 五门。只读，不依赖②结论。"""
import json
import sys
from collections import Counter
from datetime import date

BASE = "data/_exp_cycle_replay_fullpool_2026.json"
FAM = "data/_exp_family_variant_replay_2026-08-20.json"
BULL = "data/_exp_family_bull_replay_2026-08-20.json"
SPLIT = date(2025, 8, 10)


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    return [s for s in d.get("signals", []) if s.get("net14") is not None]


def key(s):
    return (s["name"], s["date"])


def stats(recs):
    n = len(recs)
    if n == 0:
        return None
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
bull = load(BULL)

bkeys = {key(s) for s in base}
fkeys = {key(s) for s in fam}

added = [s for s in fam if key(s) not in bkeys]
displaced = [s for s in base if key(s) not in fkeys]
matched = [s for s in base if key(s) in fkeys]

# net 漂移：matched 中 net14/net30 逐条比较
fam_by_key = {key(s): s for s in fam}
drift = []
for s in matched:
    t = fam_by_key[key(s)]
    if s.get("net14") != t.get("net14") or s.get("net30") != t.get("net30"):
        drift.append((s["name"], s["date"], s.get("net14"), t.get("net14"), s.get("net30"), t.get("net30")))

relabeled = [s for s in matched if fam_by_key[key(s)]["action_label"] != s["action_label"]]

print("== delta 独立重算 ==")
print("baseline n:", len(base), "| fam_on n:", len(fam))
print("added:", len(added), "| displaced:", len(displaced), "| matched(unchanged+relabeled):", len(matched))
print("net_drift 条数:", len(drift), "(应=0)")
print("relabeled:", len(relabeled))
print("added_by_label:", dict(Counter(s["action_label"] for s in added)))
# added 是否只含两新族（knock-on=0）
non_new = [s for s in added if "牛市稳态上行" not in s["action_label"] and "急跌高波动" not in s["action_label"]]
print("added 中非两新族 knock-on:", len(non_new))

print()
print("== crash_vol（急跌高波动）月度集中 ==")
cr = [s for s in fam if "急跌高波动" in (s.get("action_label") or "")]
print("n:", len(cr), "| by month:", dict(sorted(Counter(s["date"][:7] for s in cr).items())))
if cr:
    mx = Counter(s["date"][:7] for s in cr).most_common(1)[0]
    print("max month pct:", round(100.0 * mx[1] / len(cr), 1), "-> 否决线(>50%):", 100.0 * mx[1] / len(cr) > 50)

print()
print("== bull_steady added 分段统计（独立重算） ==")
bu = [s for s in added if "牛市稳态上行" in (s.get("action_label") or "")]
fit_bu = [s for s in bu if date.fromisoformat(s["date"]) < SPLIT]
val_bu = [s for s in bu if date.fromisoformat(s["date"]) >= SPLIT]
print("added total:", len(bu), "| fit:", stats(fit_bu), "| val:", stats(val_bu))

print()
print("== 基线买书对照（独立重算） ==")
fit_bk = [s for s in base if date.fromisoformat(s["date"]) < SPLIT]
val_bk = [s for s in base if date.fromisoformat(s["date"]) >= SPLIT]
print("book fit:", stats(fit_bk), "| book val:", stats(val_bk))

print()
print("== bull-only 回放（A2 复算输入）核验 ==")
bkeys2 = {key(s) for s in base}
badd = [s for s in bull if key(s) not in bkeys2]
print("bull replay signals:", len(bull), "| added:", len(badd),
      "| by label:", dict(Counter(s["action_label"] for s in badd)))

print()
print("== 重跑 a2_emission.analyze（bull vs baseline, regime=all） ==")
sys.path.insert(0, "references")
import a2_emission  # noqa: E402
res = a2_emission.analyze(BULL, BASE, "bull_steady", "bull_steady", regime="all")
a2_emission.print_report(res)
