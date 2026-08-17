# -*- coding: utf-8 -*-
"""长持 sleeve 回撤预算测试（2026-08-17，预注册判据，研究版）。

背景：用户裁定回撤预算放宽到 −25% 与 −30% 两档都测。本探针回答：
「独立资金池的长持腿（rs/ct）在放宽后的预算下，能否让组合总收益超过纯核心？」
预注册判据（跑数前锁定）：
  结构：核心腿=官方 189 信号（cap0.8/hold21）；sleeve 腿=冷却变体 rs/ct 信号
        （独立资金 f，hold180，两个规则变体：纯持有 / 自峰值−20%止损）。
  组合曲线 = (1−f)×核心相对净值 + f×sleeve 相对净值。
  网格：f ∈ {0.1, 0.2, 0.3, 0.5} × 预算 B ∈ {25, 30}。
  通过标准（每 B 独立）：存在 f 使 组合 maxDD ≥ −B（预算内）且 组合 total > 核心 total。
  任一 B 通过 → sleeve 方向在该预算下存活（进细化设计）；
  两档全不过 → sleeve 在放宽预算下仍证伪（呼应 CORE-SAT-2 边界）。
输出 data/_exp_sleeve_budget.json。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exit_sim as es  # noqa: E402
from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.signal_tracking import family_key_for_label  # noqa: E402

OUT = ROOT / "data" / "_exp_sleeve_budget.json"
CORE_PATH = ROOT / "data" / "_exp_cycle_replay_2026.json"
SLEEVE_PATH = ROOT / "data" / "_exp_cycle_replay_rs_ct_cd.json"
FRACS = (0.1, 0.2, 0.3, 0.5)
BUDGETS = (25, 30)
RULES = (("sleeve_hold", "纯持有180d"), ("sleeve_trail", "自峰值-20%止损"))


def load_sigs(path, only_fams=None):
    raw = json.load(open(path, encoding="utf-8"))
    m180 = es.load_chg180()
    fam_of, per_of = {}, {}
    for s in raw["signals"]:
        k = (s["date"], s["name"])
        fam_of[k] = family_key_for_label(s.get("action_label") or "")
        per_of[k] = state_bucket(m180.get(s["date"]), s.get("mkt_chg30"))
    sigs, _ = es.bc.load_signals(path)
    out = []
    for s in sigs:
        k = (s["date"].isoformat(), s["item"])
        fam = fam_of.get(k, "base")
        if only_fams and fam not in only_fams:
            continue
        s["fam"] = fam
        s["period"] = per_of.get(k, "S3弱市阴跌")
        s["hold"] = es.hold_for(s["fam"], s["period"])
        out.append(s)
    return out


def combine(core_curve, sleeve_curve, f):
    d2v = {}
    for d, v in sleeve_curve:
        d2v[d] = v
    last = 1.0
    out = []
    for d, v in core_curve:
        sv = d2v.get(d, last)
        last = sv
        out.append((d, (1 - f) * v + f * sv))
    return out


def _m(curve):
    """(date, value) 对曲线指标（组合曲线用；与 bc.metrics 同口径）。"""
    base = curve[0][1]
    peak, mdd = base, 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100 if peak else 0.0)
    return {"total_return_pct": round((curve[-1][1] / base - 1) * 100, 2),
            "max_drawdown_pct": round(mdd, 2)}


def main():
    core = load_sigs(CORE_PATH)
    sleeve = load_sigs(SLEEVE_PATH, only_fams=es.LEG_FAMS)
    core_res = es.simulate(core, "hold21")
    core_curve = [(c[0], c[2]) for c in core_res["curve"]]
    mc = es.metrics(core_res["curve"])
    print("核心（官方 189，cap0.8/hold21）: total=%+.2f%% maxDD=%+.2f%%" % (
        mc["total_return_pct"], mc["max_drawdown_pct"]))
    print("sleeve 信号（rs/ct 冷却变体）: n=%d" % len(sleeve))

    results = {}
    verdicts = {}
    for bname, btext in RULES:
        sr = es.simulate(sleeve, bname, cap=1.0)  # sleeve 独立资金池，池内满额可用
        sc = [(c[0], c[2]) for c in sr["curve"]]
        ms = es.metrics(sr["curve"])
        print("\n== sleeve 规则: %s（单独净值 total=%+.2f%% maxDD=%+.2f%%）==" % (
            btext, ms["total_return_pct"], ms["max_drawdown_pct"]))
        for f in FRACS:
            comb = combine(core_curve, sc, f)
            m = _m(comb)
            row = {"f": f, **m}
            results["%s_f%.1f" % (bname, f)] = row
            flags = []
            for B in BUDGETS:
                ok = (m["max_drawdown_pct"] >= -B and m["total_return_pct"] > mc["total_return_pct"])
                flags.append("B%d:%s" % (B, "过" if ok else "否"))
                verdicts.setdefault(str(B), []).append((bname, f, ok, m["total_return_pct"], m["max_drawdown_pct"]))
            print("  f=%.1f total=%+8.2f%% maxDD=%+7.2f%% | %s" % (
                f, m["total_return_pct"], m["max_drawdown_pct"], " ".join(flags)))

    print("\n== 预算裁定 ==")
    summary = {}
    for B in BUDGETS:
        passed = [x for x in verdicts[str(B)] if x[2]]
        best = max(passed, key=lambda x: x[3]) if passed else None
        summary[str(B)] = {"passed_n": len(passed),
                           "best": ({"rule": best[0], "f": best[1],
                                     "total": round(best[3], 2), "maxDD": round(best[4], 2)}
                                    if best else None)}
        if best:
            print("  B=%d: %d 组合过 → 最优 %s f=%.1f total=%+.2f%% maxDD=%+.2f%%" % (
                B, len(passed), best[0], best[1], best[3], best[4]))
        else:
            print("  B=%d: 全不过 → sleeve 在该预算下证伪" % B)
    out = {"probe": "长持 sleeve 回撤预算测试", "core": mc, "sleeve_n": len(sleeve),
           "grid": results, "budget_verdicts": summary}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
