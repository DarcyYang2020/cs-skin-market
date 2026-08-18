# -*- coding: utf-8 -*-
"""优先级感知去重修复的回归 + 效果分析（2026-08-16，一次脚本跑完两批产物）。"""
import io
import json
import sys
from datetime import date
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

spec = spec_from_file_location("b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
b1v2 = module_from_spec(spec)
spec.loader.exec_module(b1v2)
spec2 = spec_from_file_location("pfb", str(ROOT / "references" / "portfolio_backtest.py"))
pfb = module_from_spec(spec2)
spec2.loader.exec_module(pfb)
sys.path.insert(0, str(ROOT / "references"))
from a2_emission import _stats  # noqa: E402


def keys(path):
    d = json.load(io.open(path, encoding="utf-8"))
    return {(s["name"], s["date"]) for s in d.get("signals", [])}, d


def sim(path, label):
    d = json.load(io.open(path, encoding="utf-8"))
    sigs = []
    for s in d.get("signals", []):
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = b1v2.classify(s.get("action_label"))
        sigs.append({"date": date.fromisoformat(s["date"]), "item": s["name"],
                     "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
                     "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1)})
    simr = b1v2.simulate(sigs, cap=0.8)
    r = pfb.risk_metrics(simr["curve"])
    split = "2025-08-10"
    def seg(pts):
        vals = [v for _, v in pts]
        if len(vals) < 2:
            return (0.0, 0.0, None)
        total = (vals[-1] / vals[0] - 1) * 100
        peak = vals[0]
        mdd = 0.0
        for v in vals:
            peak = max(peak, v)
            mdd = min(mdd, (v / peak - 1) * 100)
        return (round(total, 2), round(mdd, 2), round(abs(total / mdd), 2) if mdd < 0 else None)
    f = seg([(c[0], c[2]) for c in simr["curve"] if c[0] < split])
    b = seg([(c[0], c[2]) for c in simr["curve"] if c[0] >= split])
    print("%-28s n=%3d total=%8.2f mdd=%7.2f calmar=%5s ann=%6s | front=%s back=%s | trades=%d" % (
        label, len(sigs), r["total_return_pct"], r["max_drawdown_pct"],
        r["calmar"], r["ann_return_pct"], f, b, len(simr["closed"])))


def main():
    base = ROOT / "data" / "_exp_cycle_replay_2026.json"
    reg = ROOT / "data" / "_tmp_regression_186.json"
    onb = ROOT / "data" / "_exp_dedup_prio_base.json"
    onr = ROOT / "data" / "_exp_dedup_prio_rise.json"
    onx = ROOT / "data" / "_exp_dedup_prio_xishou.json"

    bk, _ = keys(base)
    print("=== 回归检查（开关关，须与 186 基线完全一致）===")
    if reg.exists():
        rk, rd = keys(reg)
        print("regression n=%d | only_reg=%d only_base=%d | 一致=%s" % (
            len(rd["signals"]), len(rk - bk), len(bk - rk), rk == bk))
    else:
        print("regression 产物未就绪")
    print()
    print("=== 组合模拟（canonical cap0.8/hold21/2%）===")
    sim(base, "基线 186 (开关关)")
    for p, lab in ((onb, "DEDUP_PRIO 开·基线"), (onr, "DEDUP_PRIO 开·rise"),
                   (onx, "DEDUP_PRIO 开·xishou")):
        if p.exists():
            sim(p, lab)
        else:
            print("%-28s 产物未就绪" % lab)
    print()
    print("=== 开关开·基线的发射足迹（vs 186）===")
    if onb.exists():
        onb_keys, _ = keys(onb)
        added = onb_keys - bk
        displaced = bk - onb_keys
        print("added=%d displaced=%d" % (len(added), len(displaced)))
        d = json.load(io.open(onb, encoding="utf-8"))
        sigs = [s for s in d["signals"] if (s["name"], s["date"]) in added]
        from collections import Counter
        print("added by label:", dict(Counter(s["action_label"] for s in sigs)))
        print("added stats:", _stats([{"net14": s.get("net14"), "net30": s.get("net30")} for s in sigs]))
        disp = [s for s in json.load(io.open(base, encoding="utf-8"))["signals"]
                if (s["name"], s["date"]) in displaced]
        print("displaced stats:", _stats([{"net14": s.get("net14"), "net30": s.get("net30")} for s in disp]))


if __name__ == "__main__":
    main()
