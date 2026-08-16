# -*- coding: utf-8 -*-
"""无黑天鹅引擎拆解（2026-08-15）：回答「遇不到黑天鹅时引擎还剩什么」。

用 cycle 186（v2-T10 回放）组合模拟：
- 全量（含 panic/deep_dip 两个 100% 事件依赖族）
- 去 panic（恐慌共振+退潮）
- 去 panic+deep_dip（只留 supply_accum/base/deep_value 三个跨周期验证过的族）
"""
import io, json, sys
from datetime import date
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

ROOT = Path(r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "references"))

REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
SPLIT = "2025-08-10"

_spec = spec_from_file_location("b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
b1v2 = module_from_spec(_spec); _spec.loader.exec_module(b1v2)


def load():
    d = json.load(io.open(REPLAY, encoding="utf-8"))
    sigs = []
    for s in d["signals"]:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        lab = s.get("action_label") or ""
        st = "panic" if "恐慌" in lab else ("deep_value" if "深值" in lab else "accumulate")
        sigs.append({"date": date.fromisoformat(s["date"]), "item": s["name"],
                     "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
                     "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1),
                     "label": lab})
    return sigs


def metrics(pts):
    vals = [v for _, v in pts]
    total = (vals[-1] / vals[0] - 1) * 100
    peak = vals[0]; mdd = 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100)
    calmar = round(abs(total / mdd), 2) if mdd < 0 else None
    days = max(1, len(vals))
    ann = ((vals[-1] / vals[0]) ** (365.0 / days) - 1) * 100
    return {"total": round(total, 2), "mdd": round(mdd, 2), "calmar": calmar, "ann": round(ann, 2)}


def run(sigs, cap=0.8):
    sim = b1v2.simulate(sigs, cap=cap)
    pts = [(c[0], c[2]) for c in sim["curve"]]
    m = metrics(pts)
    m["front"] = metrics([(d, v) for d, v in pts if d < SPLIT])
    m["back"] = metrics([(d, v) for d, v in pts if d >= SPLIT])
    m["n_signals"] = len(sigs)
    return m


sigs = load()
is_panic = lambda s: "恐慌" in s["label"]
is_dd = lambda s: "深度回调" in s["label"]

variants = {
    "全量（v2-T10，186 信号）": sigs,
    "去 panic（无恐慌族）": [s for s in sigs if not is_panic(s)],
    "去 panic+deep_dip（只留跨周期验证族）": [s for s in sigs if not is_panic(s) and not is_dd(s)],
}
out = {}
for name, ss in variants.items():
    m = run(ss)
    out[name] = m
    print(f"{name:38s} n={m['n_signals']:3d}  total={m['total']:>8}%  maxDD={m['mdd']:>7}%  calmar={m['calmar']}  "
          f"front={m['front']['total']}%  back={m['back']['total']}%")

with io.open(ROOT / "data" / "_exp_no_swan_engine.json", "w", encoding="utf-8") as f:
    json.dump({"probe": "无黑天鹅引擎拆解", "variants": out}, f, ensure_ascii=False, indent=1)
