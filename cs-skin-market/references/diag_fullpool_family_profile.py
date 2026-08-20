# -*- coding: utf-8 -*-
"""全池新信号族分布分析（2026-08-20）：族收益画像 + 同质性 + 去簇 + 时间分布。

只读 data/_exp_cycle_replay_fullpool_2026.json（并行回放产物），落盘
data/_exp_fullpool_family_profile_2026-08-20.json（原始产物，交③审计）。
"""
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "_exp_cycle_replay_fullpool_2026.json"
OUT = ROOT / "data" / "_exp_fullpool_family_profile_2026-08-20.json"
POLLUTED = {"AK-47 | 流金王朝 (崭新出厂)", "挂件 | 丁烷拍档"}
COST = 2.0

d = json.load(open(SRC, encoding="utf-8"))
sigs = [s for s in d["signals"] if s["name"] not in POLLUTED]


def profile(ss):
    x14 = [s["fwd14"] for s in ss if s.get("fwd14") is not None]
    x30 = [s["fwd30"] for s in ss if s.get("fwd30") is not None]
    n14 = [x - COST for x in x14]
    n30 = [x - COST for x in x30]
    def w(xs): return round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1) if xs else None
    def m(xs): return round(sum(xs) / len(xs), 2) if xs else None
    def q(xs, p): return round(xs[int(len(xs) * p)], 2) if xs else None
    xs = sorted(n14)
    return {"n": len(ss), "win14": w(n14), "avg14": m(n14), "med14": q(xs, 0.5),
            "p10_14": q(xs, 0.1), "p25_14": q(xs, 0.25), "p75_14": q(xs, 0.75), "p90_14": q(xs, 0.9),
            "win30": w(n30), "avg30": m(n30)}


by_label = defaultdict(list)
for s in sigs:
    by_label[s["action_label"]].append(s)
by_type = defaultdict(list)
for s in sigs:
    by_type[s["signal_type"]].append(s)

bym = Counter(s["date"][:7] for s in sigs)
out = {
    "meta": {"date": "2026-08-20", "src": str(SRC), "n_raw": len(d["signals"]),
             "n_after_polluted": len(sigs), "polluted": list(POLLUTED),
             "pool": d["args"].get("pool"), "engine": d["args"].get("engine")},
    "by_signal_type": {k: profile(v) for k, v in sorted(by_type.items(), key=lambda kv: -len(kv[1]))},
    "by_action_label": {k: profile(v) for k, v in sorted(by_label.items(), key=lambda kv: -len(kv[1]))},
    "monthly": {m: bym[m] for m in sorted(bym)},
    "panic_decluster": {
        "total": len(by_type.get("panic", [])),
        "n_2026_05_cluster": sum(1 for s in by_type.get("panic", []) if s["date"].startswith("2026-05")),
        "n_other": sum(1 for s in by_type.get("panic", []) if not s["date"].startswith("2026-05")),
        "other_dates": sorted(set(s["date"] for s in by_type.get("panic", []) if not s["date"].startswith("2026-05"))),
    },
    "new_categories_signals": {  # 手套/武器箱/挂件/冷门枪 是否产生信号
        "glove": [s for s in sigs if "手套" in s["name"] and "箱" not in s["name"]],
        "case": [s for s in sigs if "武器箱" in s["name"]],
    },
}
# 新品类计数
out["new_categories_signals"] = {
    "glove_n": len([s for s in sigs if "手套" in s["name"] and "箱" not in s["name"]]),
    "case_n": len([s for s in sigs if "武器箱" in s["name"]]),
}

json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved", OUT)
print(json.dumps({k: v for k, v in out.items() if k in ("by_signal_type", "panic_decluster", "new_categories_signals")},
                 ensure_ascii=False, indent=1))
