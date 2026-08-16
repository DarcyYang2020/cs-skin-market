# -*- coding: utf-8 -*-
"""买涨腿 v5 组合构建级验证（2026-08-16，零重放，基于 _exp_rise_v4_hold.json 258 信号）。

判据（north_star + O1 预注册）：total ≥ v2-T11 基线 320.72 且 maxDD 不破 −20% 且前后半段方向一致。
变体：
  A v4 原样复现（rise limit 0.10 入主池）
  B rise limit 0.05 / C 0.03 入主池
  D rise 仅留 TH≥55 格（0.10）
  E rise TH≥55 格（0.05）
  F 独立 sleeve：主池=190 基线信号（cap0.8），动量池=68 rise 信号（cap 0.15 分账），权益合并
  G 独立 sleeve + TH≥55 过滤 + 动量池 cap 0.10
"""
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

V4 = ROOT / "data" / "_exp_rise_v4_hold.json"
BASE = ROOT / "data" / "_exp_dedup_prio_base.json"
OUT = ROOT / "data" / "_exp_rise_sleeve.json"
SPLIT = "2025-08-10"


def load(path):
    d = json.load(io.open(path, encoding="utf-8"))
    out = []
    for s in d.get("signals", []):
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = b1v2.classify(s.get("action_label"))
        out.append({"date": date.fromisoformat(s["date"]), "item": s["name"],
                    "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
                    "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1),
                    "is_rise": "吸筹型上涨" in (s.get("action_label") or ""),
                    "mkt_th": s.get("market_th")})
    return out


def seg(curve):
    def _seg(pts):
        vals = [v for _, v in pts]
        if len(vals) < 2:
            return (0.0, 0.0)
        total = (vals[-1] / vals[0] - 1) * 100
        peak = vals[0]
        mdd = 0.0
        for v in vals:
            peak = max(peak, v)
            mdd = min(mdd, (v / peak - 1) * 100)
        return (round(total, 2), round(mdd, 2))
    return _seg([(c[0], c[2]) for c in curve if c[0] < SPLIT]), _seg([(c[0], c[2]) for c in curve if c[0] >= SPLIT])


def report(label, curve, n, trades):
    r = pfb.risk_metrics(curve)
    f, b = seg(curve)
    print("%-30s n=%3d total=%8.2f mdd=%7.2f calmar=%5s | front=%s back=%s | trades=%d" % (
        label, n, r["total_return_pct"], r["max_drawdown_pct"], r["calmar"], f, b, trades))


def main():
    v4 = load(V4)
    base_keys = {(s["item"], s["date"]) for s in load(BASE)}
    print("v4 n=%d | rise-labeled n=%d | 基线键内 n=%d" % (
        len(v4), sum(1 for s in v4 if s["is_rise"]), sum(1 for s in v4 if (s["item"], s["date"]) in base_keys)))

    def run(sigs, cap=0.8, label=""):
        simr = b1v2.simulate(sigs, cap=cap)
        return simr["curve"], len(sigs), len(simr["closed"])

    # A 原样复现
    curve, n, t = run(v4)
    report("A v4原样 rise0.10", curve, n, t)

    # B/C limit 网格
    for lim, lab in ((0.05, "B"), (0.03, "C")):
        sigs = [dict(s, limit=lim) if s["is_rise"] else s for s in v4]
        curve, n, t = run(sigs)
        report("%s rise limit %.2f 入主池" % (lab, lim), curve, n, t)

    # D/E TH≥55 格过滤
    for lim, lab in ((0.10, "D"), (0.05, "E")):
        sigs = [s for s in v4 if not s["is_rise"] or (s["mkt_th"] is not None and s["mkt_th"] >= 55)]
        sigs = [dict(s, limit=lim) if s["is_rise"] else s for s in sigs]
        curve, n, t = run(sigs)
        report("%s rise TH≥55格 limit %.2f" % (lab, lim), curve, n, t)

    # F 独立 sleeve（分账：主池 cap0.8 + 动量池 cap0.15）
    main = [s for s in v4 if not s["is_rise"]]
    mom = [s for s in v4 if s["is_rise"]]
    cm = b1v2.simulate(main, cap=0.8)["curve"]
    cs = b1v2.simulate(mom, cap=0.15)["curve"]
    merged = []
    mcur = {c[0]: c[2] for c in cm}
    scur = {c[0]: c[2] for c in cs}
    for d in sorted(set(mcur) | set(scur)):
        merged.append((d, mcur.get(d, 1.0), mcur.get(d, 1.0) + scur.get(d, 1.0) - 1.0, 0, 0))
    report("F 独立sleeve 主0.8+动量0.15", merged, len(v4), 0)

    # G sleeve + TH≥55 过滤 + 动量池 cap 0.10
    mom55 = [s for s in mom if s["mkt_th"] is not None and s["mkt_th"] >= 55]
    cs = b1v2.simulate(mom55, cap=0.10)["curve"]
    scur = {c[0]: c[2] for c in cs}
    merged = []
    for d in sorted(set(mcur) | set(scur)):
        merged.append((d, mcur.get(d, 1.0), mcur.get(d, 1.0) + scur.get(d, 1.0) - 1.0, 0, 0))
    report("G sleeve主0.8+动量TH≥55 cap0.10", merged, len(v4), 0)

    # H/I 动量专用退出：rise 信号跟踪止损 −8%（自运行最高价回撤），非 rise 保持 hold21
    from datetime import timedelta
    def sim_trailing(sigs, cap=0.8, trail=0.08):
        by_day = {}
        for s in sigs:
            by_day.setdefault(s["date"], []).append(s)
        first = min(s["date"] for s in sigs)
        last = max(s["date"] for s in sigs) + timedelta(days=21)
        day = first
        active = []
        total_invested = 0.0
        realized = 0.0
        closed = []
        curve = []
        while day <= last:
            for a in active:
                a["idx"] += 1
            for s in sorted(by_day.get(day, []), key=lambda x: -x["prio"]):
                if cap is not None and total_invested + s["limit"] > cap + 1e-9:
                    continue
                active.append({"s": s, "idx": 0, "base": s["limit"], "peak": 1.0})
                total_invested += s["limit"]
            unreal = 0.0
            pos_sum = 0.0
            closes = []
            for a in active:
                pos_sum += a["base"]
                k = a["idx"]
                if k <= 0:
                    continue
                fwd = a["s"]["fwd"]
                px = fwd[min(k - 1, len(fwd) - 1)]
                ret = px / a["s"]["entry"] - 1
                a["peak"] = max(a["peak"], 1 + ret)
                exit_now = k >= 21
                if a["s"]["is_rise"] and 1 + ret <= a["peak"] * (1 - trail):
                    exit_now = True
                if exit_now:
                    pnl = a["base"] * (ret - 0.02)
                    realized += pnl
                    closed.append(pnl)
                    total_invested -= a["base"]
                    closes.append(a)
                else:
                    unreal += a["base"] * ret
            for a in closes:
                active.remove(a)
            eq = 1.0 + realized + unreal
            curve.append((day.isoformat(), pos_sum, eq, 0, len(active)))
            day += timedelta(days=1)
        return curve, len(closed)

    for lab, flt in (("H", False), ("I", True)):
        sigs = [s for s in v4 if not s["is_rise"] or not flt
                or (s["mkt_th"] is not None and s["mkt_th"] >= 55)]
        curve, t = sim_trailing(sigs, cap=0.8)
        report("%s 跟踪止损8%% rise（TH≥55过滤=%s）" % (lab, flt), curve, len(sigs), t)

    # 基线对照
    base = load(BASE)
    curve, n, t = run(base)
    report("v2-T11 基线 190", curve, n, t)


if __name__ == "__main__":
    main()
