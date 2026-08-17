# -*- coding: utf-8 -*-
"""组合层时期乘子（2026-08-17，只读研究，预注册判据）。

在官方 v2-T13 产物 + hold21 口径（exit_sim 基线）上验证「按时期组合 cap」变体：
  基线: 全期 cap 0.8
  V1 风险预算: P 0.9 / S1 0.8 / S2 0.8 / S3 0.6 / S4 0.6
  V2 保守弱市: P 0.8 / S1 0.8 / S2 0.8 / S3 0.5 / S4 0.5
  V3 只提 P :  P 1.0 / S1 0.8 / S2 0.8 / S3 0.8 / S4 0.8
依据（预注册自五时期证据，非本次拟合）：P 抄底区引擎 14d +28.2 全场最强（可提）；
S4 14d 胜率 48% 全场最弱（可降）；S3 只剩 base 腿（77.8%/+27.4，温和降）。
预注册判据：total ≥ 基线 且 maxDD ≤ 基线+1.0pp 且前后半段（2026-03-02）两段 ≥ 基线−2pp；
置换检验：V1 的 cap 值随机洗到时期上 200 次，报 dTotal/dDD 分布与 p 值。
输出 data/_exp_period_cap_compare.json。
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exit_sim as es  # noqa: E402

OUT = ROOT / "data" / "_exp_period_cap_compare.json"
CUT = "2026-03-02"
PERIODS = ["P恐慌深跌", "S1牛市上行", "S2牛市回调", "S3弱市阴跌", "S4弱市反弹"]
VARIANTS = {
    "V1_risk_budget": {"P恐慌深跌": 0.9, "S1牛市上行": 0.8, "S2牛市回调": 0.8,
                       "S3弱市阴跌": 0.6, "S4弱市反弹": 0.6},
    "V2_conservative_weak": {"P恐慌深跌": 0.8, "S1牛市上行": 0.8, "S2牛市回调": 0.8,
                             "S3弱市阴跌": 0.5, "S4弱市反弹": 0.5},
    "V3_boost_p_only": {"P恐慌深跌": 1.0, "S1牛市上行": 0.8, "S2牛市回调": 0.8,
                        "S3弱市阴跌": 0.8, "S4弱市反弹": 0.8},
}


def main():
    raw = json.load(open(es.REPLAY, encoding="utf-8"))
    m180 = es.load_chg180()
    period_of = {}
    from pipeline.signal_tracking import family_key_for_label  # noqa: E402
    from pipeline.market_context import state_bucket  # noqa: E402
    fam_of = {}
    for s in raw["signals"]:
        k = (s["date"], s["name"])
        fam_of[k] = family_key_for_label(s.get("action_label") or "")
        period_of[k] = state_bucket(m180.get(s["date"]), s.get("mkt_chg30"))
    sigs, _ = es.bc.load_signals(es.REPLAY)
    for s in sigs:
        k = (s["date"].isoformat(), s["item"])
        s["fam"] = fam_of.get(k, "base")
        s["period"] = period_of.get(k, "S3弱市阴跌")
        s["hold"] = es.hold_for(s["fam"], s["period"])

    base = es.simulate(sigs, "hold21")
    mb = es.metrics(base["curve"])
    fb, bb = es.seg(base["curve"], None, CUT), es.seg(base["curve"], CUT, None)

    def evalm(cap_map):
        res = es.simulate(sigs, "hold21", cap_map=cap_map)
        m = es.metrics(res["curve"])
        f_, b_ = es.seg(res["curve"], None, CUT), es.seg(res["curve"], CUT, None)
        return res, m, f_, b_

    print("== 基线 cap0.8（hold21）== total=%+.2f%% maxDD=%+.2f%%" % (mb["total_return_pct"], mb["max_drawdown_pct"]))
    results = {}
    verdicts = {}
    for name, cm in VARIANTS.items():
        res, m, f_, b_ = evalm(cm)
        ok1 = m["total_return_pct"] >= mb["total_return_pct"] and \
            m["max_drawdown_pct"] <= mb["max_drawdown_pct"] + 1.0
        ok2 = (f_["total_return_pct"] is not None and f_["total_return_pct"] >= fb["total_return_pct"] - 2.0 and
               b_["total_return_pct"] is not None and b_["total_return_pct"] >= bb["total_return_pct"] - 2.0)
        results[name] = {**m, "front": f_, "back": b_, "n_closed": len(res["closed"])}
        verdicts[name] = {"criteria1_combo": bool(ok1), "criteria2_frontback": bool(ok2),
                          "candidate": bool(ok1 and ok2)}
        print("%-22s total=%+8.2f%% maxDD=%+7.2f%% | front %+7.2f (Δ%+6.2f) back %+7.2f (Δ%+6.2f) → %s" % (
            name, m["total_return_pct"], m["max_drawdown_pct"],
            f_["total_return_pct"] or 0, (f_["total_return_pct"] or 0) - (fb["total_return_pct"] or 0),
            b_["total_return_pct"] or 0, (b_["total_return_pct"] or 0) - (bb["total_return_pct"] or 0),
            "通过" if ok1 and ok2 else "未过"))

    # 置换检验：V1 的 cap 值随机洗到时期上（200 次）
    caps = sorted(VARIANTS["V1_risk_budget"].values())
    best = results.get("V1_risk_budget", {})
    d_best = best.get("total_return_pct", 0) - mb["total_return_pct"]
    dd_best = best.get("max_drawdown_pct", 0) - mb["max_drawdown_pct"]
    dts, dds = [], []
    for seed in range(200):
        rnd = random.Random(seed)
        ps = PERIODS[:]
        rnd.shuffle(ps)
        cm = {p: c for p, c in zip(ps, caps)}
        res, m, _, _ = evalm(cm)
        dts.append(m["total_return_pct"] - mb["total_return_pct"])
        dds.append(m["max_drawdown_pct"] - mb["max_drawdown_pct"])
    dts.sort()
    dds.sort()
    p_t = sum(1 for x in dts if x >= d_best) / len(dts)
    p_d = sum(1 for x in dds if x >= dd_best) / len(dds)
    perm = {"d_total_med": round(dts[100], 2), "d_total_p90": round(dts[180], 2),
            "d_dd_med": round(dds[100], 2), "d_dd_p90": round(dds[180], 2),
            "p_total": round(p_t, 3), "p_dd": round(p_d, 3)}
    out = {"probe": "组合层时期乘子（hold21 口径，预注册 V1/V2/V3 + 置换检验）",
           "cut": CUT, "baseline": mb, "variants": results, "verdicts": verdicts,
           "permutation_v1": perm}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("== 置换（V1 cap 值随机洗时期 ×200）== V1 dTotal=%+.2f dMaxDD=%+.2f | "
          "随机 dTotal 中位%+.2f/p90 %+.2f, dDD 中位%+.2f/p90 %+.2f | p_total=%.3f p_dd=%.3f" % (
              d_best, dd_best, perm["d_total_med"], perm["d_total_p90"],
              perm["d_dd_med"], perm["d_dd_p90"], perm["p_total"], perm["p_dd"]))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
