# -*- coding: utf-8 -*-
"""退出层 exit-aware 组合模拟（2026-08-17，只读研究，预注册判据）。

对官方 v2-T13 回放产物做「按族×时期退出规则」组合模拟：
  - 口径对齐 b1v2.simulate：cap 0.8 / 优先级拒绝（panic>accumulate/base>deep_value）/ 2% 双边成本 /
    未部署资金按现金计 / 权益逐日（fwd 路径）；
  - 新增：逐日持仓峰值跟踪（rise 腿 5% 跟踪止盈）+ 按族/时期持有期（panic 14d / rise 21d+跟踪 /
    S4 时期 14d / 其余 21d）；
  - 供给扩张全止损与情绪档静态止盈止损为实盘层（回放无前视在售/ATR，不进模拟）。

预注册判据（decision-log）：
  1. 组合级：variant total ≥ baseline total 且 variant maxDD ≤ baseline maxDD + 0.5pp；
  2. 前后半段（切点 2026-03-02，同路由口径）：两段 total 均 ≥ 基线同段 − 2pp；
  3. 诚实报告：平仓笔数 / 平均净收益 / 各退出原因计数。
输出 data/_exp_exit_layer_compare.json。
"""
import json
import os
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import benchmark_compare as bc  # noqa: E402
from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.signal_tracking import family_key_for_label  # noqa: E402

REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
OUT = ROOT / "data" / "_exp_exit_layer_compare.json"
CUT = "2026-03-02"
COST = 0.02
CAP = 0.8

# ---- 预注册退出规则表（族 × 时期）----
# panic 族：14d（P 期 14d +28.2 优于 30d +24.1；hold_guidance 一贯口径）
# rise 腿：21d 上限 + 自峰值回撤 5% 跟踪止盈（v2-T12 方案 I 口径，由指导转自动化）
# S4 时期：max 14d（反抽陷阱：B-1 S4 14d 70.3%→30d 50%、引擎 S4 30d 胜率 44% 全场最低）
# 其余：21d（现行口径）
HOLD_BY_FAM = {
    "panic_resonance": 14, "panic_easing": 14,
    "rise_accum": 21, "rise_contract": 21, "volatile_accum": 21,
    "deep_value": 21, "supply_accum": 21, "base": 21, "oversold": 21,
}
TRAILING_FAMS = {"rise_accum", "rise_contract"}
TRAIL_PCT = 0.05
S4_MAX_HOLD = 14


def load_chg180():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]
    out = {}
    for i in range(180, len(mvals)):
        if mvals[i - 180] > 0:
            out[mdates[i]] = (mvals[i] / mvals[i - 180] - 1) * 100
    return out


def hold_for(fam, period):
    h = HOLD_BY_FAM.get(fam, 21)
    if period == "S4弱市反弹":
        h = min(h, S4_MAX_HOLD)
    return h


def simulate(sigs, rule="hold21", cap_map=None):
    """rule: 'hold21'（基线）/ 'family_period'（全量预注册表）/ 单成分消融
    'panic14'（仅 panic 族 14d）/ 'trail5'（仅 rise 腿跟踪-5%）/ 's4_14'（仅 S4 max14d）。
    cap_map: {period: cap} 时期乘子（信号入场日时期决定 cap；None=全局 CAP）。"""
    by_day = {}
    for s in sigs:
        by_day.setdefault(s["date"], []).append(s)
    first = min(s["date"] for s in sigs)
    last = max(s["date"] for s in sigs) + timedelta(days=21)
    day, active, realized = first, [], 0.0
    total_invested = 0.0
    curve, closed, exit_reasons = [], [], {}
    while day <= last:
        for a in active:
            a["idx"] += 1
        for s in sorted(by_day.get(day, []), key=lambda x: -x["prio"]):
            _cap = CAP if cap_map is None else cap_map.get(s["period"], CAP)
            if total_invested + s["limit"] > _cap + 1e-9:
                continue
            active.append({"s": s, "idx": 0, "peak": s["entry"]})
            total_invested += s["limit"]
        unreal = 0.0
        pos_sum = 0.0
        for a in active:
            pos_sum += a["s"]["limit"]
            k = a["idx"]
            fwd = a["s"]["fwd"]
            # 与 b1v2 口径一致：到期日持仓不计未实现（当日平仓进 realized）
            if k <= 0 or k >= (21 if rule == "hold21" else a["s"]["hold"]) or k > len(fwd):
                continue
            px = fwd[k - 1]
            a["peak"] = max(a["peak"], px)
            unreal += a["s"]["limit"] * (px / a["s"]["entry"] - 1)
        for a in list(active):
            k = a["idx"]
            fwd = a["s"]["fwd"]
            if k <= 0 or k > len(fwd):
                continue
            px = fwd[k - 1]
            fam, period, hold = a["s"]["fam"], a["s"]["period"], a["s"]["hold"]
            reason = None
            if rule == "hold21":
                if k >= 21:
                    reason = "到期21"
            elif rule == "family_period":
                if k >= hold:
                    reason = "到期%d" % hold
                elif fam in TRAILING_FAMS and px <= a["peak"] * (1 - TRAIL_PCT):
                    reason = "跟踪-5%"
            elif rule == "panic14":
                if k >= (14 if fam.startswith("panic") else 21):
                    reason = "到期%d" % (14 if fam.startswith("panic") else 21)
            elif rule == "trail5":
                if k >= 21:
                    reason = "到期21"
                elif fam in TRAILING_FAMS and px <= a["peak"] * (1 - TRAIL_PCT):
                    reason = "跟踪-5%"
            elif rule == "s4_14":
                h = min(21, S4_MAX_HOLD) if period == "S4弱市反弹" else 21
                if k >= h:
                    reason = "到期%d" % h
            if not reason:
                continue
            pnl = a["s"]["limit"] * (px / a["s"]["entry"] - 1 - COST)
            realized += pnl
            closed.append(pnl)
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
            total_invested -= a["s"]["limit"]
            active.remove(a)
        eq = 1.0 + realized + unreal
        curve.append((day.isoformat(), pos_sum, eq))
        day += timedelta(days=1)
    return {"curve": curve, "closed": closed, "exit_reasons": exit_reasons}


def metrics(curve):
    base = curve[0][2]
    peak, mdd = base, 0.0
    for _, _, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100 if peak else 0.0)
    return {"total_return_pct": round((curve[-1][2] / base - 1) * 100, 2),
            "max_drawdown_pct": round(mdd, 2)}


def seg(curve, lo=None, hi=None):
    pts = [(d, v) for d, _, v in curve if (lo is None or d >= lo) and (hi is None or d < hi)]
    if len(pts) < 2:
        return {"total_return_pct": None}
    return {"total_return_pct": round((pts[-1][1] / pts[0][1] - 1) * 100, 2)}


def main():
    raw = json.load(open(REPLAY, encoding="utf-8"))
    m180 = load_chg180()
    fam_of = {}
    period_of = {}
    for s in raw["signals"]:
        k = (s["date"], s["name"])
        fam_of[k] = family_key_for_label(s.get("action_label") or "")
        period_of[k] = state_bucket(m180.get(s["date"]), s.get("mkt_chg30"))

    sigs, _ = bc.load_signals(REPLAY)
    for s in sigs:
        k = (s["date"].isoformat(), s["item"])
        s["fam"] = fam_of.get(k, "base")
        s["period"] = period_of.get(k, "S3弱市阴跌")
        s["hold"] = hold_for(s["fam"], s["period"])

    b21 = simulate(sigs, "hold21")
    vfp = simulate(sigs, "family_period")
    vp14 = simulate(sigs, "panic14")
    vt5 = simulate(sigs, "trail5")
    vs4 = simulate(sigs, "s4_14")
    mb, mv = metrics(b21["curve"]), metrics(vfp["curve"])

    def row(res, label):
        m = metrics(res["curve"])
        fb_, fv_ = seg(b21["curve"], None, CUT), seg(res["curve"], None, CUT)
        bb_, bv_ = seg(b21["curve"], CUT, None), seg(res["curve"], CUT, None)
        print("%-16s total=%+8.2f%% maxDD=%+7.2f%% | front %+7.2f (Δ%+6.2f) back %+7.2f (Δ%+6.2f) | closed=%d %s" % (
            label, m["total_return_pct"], m["max_drawdown_pct"],
            fv_["total_return_pct"] or 0, (fv_["total_return_pct"] or 0) - (fb_["total_return_pct"] or 0),
            bv_["total_return_pct"] or 0, (bv_["total_return_pct"] or 0) - (bb_["total_return_pct"] or 0),
            len(res["closed"]), res["exit_reasons"]))
        return m

    print("== 基线 vs 全量变体 vs 单成分消融（cap0.8，切点 %s）==" % CUT)
    row(b21, "基线 hold21")
    row(vfp, "全量 族×时期")
    row(vp14, "消融 仅panic14")
    row(vt5, "消融 仅trail5")
    row(vs4, "消融 仅S4-14")

    fb, fv = seg(b21["curve"], None, CUT), seg(vfp["curve"], None, CUT)
    bb, bv = seg(b21["curve"], CUT, None), seg(vfp["curve"], CUT, None)
    ok1 = mv["total_return_pct"] >= mb["total_return_pct"] and \
        mv["max_drawdown_pct"] <= mb["max_drawdown_pct"] + 0.5
    ok2 = (fv["total_return_pct"] is not None and fv["total_return_pct"] >= fb["total_return_pct"] - 2.0 and
           bv["total_return_pct"] is not None and bv["total_return_pct"] >= bb["total_return_pct"] - 2.0)
    out = {
        "probe": "退出层 exit-aware 组合模拟（预注册：组合级+前后半段；含单成分消融）",
        "rules": {"hold_by_fam": HOLD_BY_FAM, "trailing_fams": sorted(TRAILING_FAMS),
                  "trail_pct": TRAIL_PCT, "s4_max_hold": S4_MAX_HOLD, "cap": CAP, "cut": CUT},
        "baseline_hold21": {**mb, "n_closed": len(b21["closed"]),
                            "exit_reasons": b21["exit_reasons"]},
        "variant_family_period": {**mv, "n_closed": len(vfp["closed"]),
                                  "exit_reasons": vfp["exit_reasons"]},
        "ablation": {
            "panic14_only": {**metrics(vp14["curve"]), "exit_reasons": vp14["exit_reasons"]},
            "trail5_only": {**metrics(vt5["curve"]), "exit_reasons": vt5["exit_reasons"]},
            "s4_14_only": {**metrics(vs4["curve"]), "exit_reasons": vs4["exit_reasons"]},
        },
        "front": {"base": fb, "variant": fv}, "back": {"base": bb, "variant": bv},
        "verdict": {"criteria1_combo": bool(ok1), "criteria2_frontback": bool(ok2),
                    "candidate": bool(ok1 and ok2)},
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("== 判定（全量变体）== 组合级:%s 前后半段:%s → %s" % (ok1, ok2, "候选通过" if ok1 and ok2 else "未通过"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
