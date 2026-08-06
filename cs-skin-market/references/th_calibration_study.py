# -*- coding: utf-8 -*-
"""TH 阈值体系矫正预研（2026-08-06，回测先行）。

背景：TH>=55 曾判为「全样本最差档」但受 pre-1/23 护栏窗口 regime 效应牵制未动；
TH<35 恐慌共振期望最高、TH 门槛对熊市过高（恐慌共振内 th 无区分度）。
现在样本已扩（K-2 引擎 503 信号，2025-01-31 起）+ 事件日历剔除，可重新评估。

口径：
- 数据：data/item_backtest_full_2025.json（503 信号，字段 th/market_th/micro_th/sentiment/pct/z/signal_type/fwd14/fwd30/net14/net30/date）
- 事件剔除：fwd30 窗口与 EVENT_CALENDAR 影响期重叠（historical_event_impact，horizon=30）
- 独立事件数：信号日期 ±3 天去簇（J-1 口径）
- net 已扣 2% 双边成本
输出：data/th_calibration_study.json
"""
import sys, io, json
from datetime import datetime, timedelta
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pipeline.market_macro import historical_event_impact

COST = 0.02

def load():
    with open("data/item_backtest_full_2025.json", encoding="utf-8") as f:
        return json.load(f)["signals"]

def clean(sigs):
    """剔除 fwd30 窗口与事件影响期重叠的信号"""
    return [s for s in sigs if not historical_event_impact(s["date"], horizon_days=30)]

def stats(recs, fwd="fwd30", net="net30"):
    v = [(r.get(fwd), r.get(net)) for r in recs]
    v = [(a, b) for a, b in v if a is not None and b is not None]
    if not v:
        return {"n": 0}
    vals = [a for a, _ in v]
    return {"n": len(vals),
            "win%": round(sum(1 for x in vals if x > 0) / len(vals) * 100, 1),
            "avg%": round(sum(vals) / len(vals), 2),
            "net%": round(sum(b for _, b in v) / len(v), 2)}

def n_events(recs):
    """±3 天去簇独立事件数（J-1 口径）"""
    ds = sorted(set(r["date"] for r in recs))
    if not ds:
        return 0
    clusters = 1
    prev = datetime.strptime(ds[0], "%Y-%m-%d")
    for d in ds[1:]:
        cur = datetime.strptime(d, "%Y-%m-%d")
        if (cur - prev).days > 3:
            clusters += 1
        prev = cur
    return clusters

def bucket_stats(recs, key_fn, buckets):
    out = {}
    for label, cond in buckets:
        sub = [r for r in recs if cond(r)]
        s = stats(sub)
        s["events"] = n_events(sub)
        out[label] = s
    return out

def main():
    sigs = load()
    clean_sigs = clean(sigs)
    out = {"generated": "2026-08-06", "note": "TH 阈值体系矫正预研；net 扣 2% 双边成本；干净样本=剔除 fwd30 与黑天鹅事件影响期重叠",
           "all": stats(sigs), "clean_total": stats(clean_sigs)}

    def th_buckets(recs):
        return [
            ("th<20", lambda r: r["th"] < 20),
            ("th 20-34", lambda r: 20 <= r["th"] < 35),
            ("th 35-44", lambda r: 35 <= r["th"] < 45),
            ("th 45-54", lambda r: 45 <= r["th"] < 55),
            ("th>=55", lambda r: r["th"] >= 55),
        ]

    def mth_buckets(recs):
        return [
            ("mth<35", lambda r: r["market_th"] < 35),
            ("mth 35-44", lambda r: 35 <= r["market_th"] < 45),
            ("mth 45-54", lambda r: 45 <= r["market_th"] < 55),
            ("mth>=55", lambda r: r["market_th"] >= 55),
        ]

    # A. 单品 th 档位（全样本 + 干净样本）
    out["A_th_bands"] = {
        "all": bucket_stats(sigs, None, th_buckets(sigs)),
        "clean": bucket_stats(clean_sigs, None, th_buckets(clean_sigs)),
    }
    # B. 大盘 market_th 档位（干净样本）
    out["B_market_th_bands"] = bucket_stats(clean_sigs, None, mth_buckets(clean_sigs))
    # C. 信号族 x th 档位（干净样本）
    fam = lambda s: s.get("signal_type", "base")
    out["C_family_x_th"] = {}
    for f in ["panic", "accumulate", "base"]:
        sub = [r for r in clean_sigs if fam(r) == f]
        out["C_family_x_th"][f] = bucket_stats(sub, None, th_buckets(sub))
    # D. 恐慌共振（sent>=75）内 th 区分度（干净样本）
    panic_res = [r for r in clean_sigs if r["sentiment"] >= 75]
    out["D_panic_resonance"] = {
        "sent>=75 all": stats(panic_res),
        "sent>=75 & th<35": stats([r for r in panic_res if r["th"] < 35]),
        "sent>=75 & th>=35": stats([r for r in panic_res if r["th"] >= 35]),
        "sent>=75 & micro>=60": stats([r for r in panic_res if r["micro_th"] >= 60]),
        "sent>=75 & micro<60": stats([r for r in panic_res if r["micro_th"] < 60]),
    }
    # E. 窗口复核：护栏窗口（2025-11-02~2026-01-23）与其余（干净样本）
    def win(d0, d1):
        return lambda r: d0 <= r["date"] <= d1
    w_guard = [r for r in clean_sigs if "2025-11-02" <= r["date"] <= "2026-01-23"]
    w_other = [r for r in clean_sigs if not ("2025-11-02" <= r["date"] <= "2026-01-23")]
    out["E_windows"] = {
        "guard 2025-11-02~2026-01-23": stats(w_guard),
        "guard th>=55": stats([r for r in w_guard if r["th"] >= 55]),
        "other windows": stats(w_other),
        "other th>=55": stats([r for r in w_other if r["th"] >= 55]),
        "2025-01-31~2025-10-31(五合一前)": stats([r for r in clean_sigs if "2025-01-31" <= r["date"] <= "2025-10-31"]),
        "2025-11-02~2026-07-17(旧回测段)": stats(w_guard + [r for r in clean_sigs if r["date"] > "2026-01-23"]),
    }
    # F. TH 矫正候选：深值+企稳场景 TH 门槛（参考线 pct<=30 + TH>=55 + z<=0）重估
    deep_est = [r for r in clean_sigs if r["pct"] <= 30 and r["z"] <= 0]
    out["F_deep_value_candidates"] = {
        "pct<=30 & z<=0 & th>=55": stats([r for r in deep_est if r["th"] >= 55]),
        "pct<=30 & z<=0 & th 45-54": stats([r for r in deep_est if 45 <= r["th"] < 55]),
        "pct<=30 & z<=0 & th 35-44": stats([r for r in deep_est if 35 <= r["th"] < 45]),
        "pct<=30 & z<=0 & th<35": stats([r for r in deep_est if r["th"] < 35]),
    }
    # 受影响信号明细（TH>=55 部分，用于人工核对事件归因）
    impacted = [r for r in sigs if historical_event_impact(r["date"], horizon_days=30) and r["th"] >= 55]
    out["impacted_th55_detail"] = [{"date": r["date"], "item": r["name"][:20],
                                     "th": r["th"], "fwd30": r.get("fwd30"),
                                     "events": historical_event_impact(r["date"], 30)} for r in impacted][:30]

    with open("data/th_calibration_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("ALL:", out["all"], "| CLEAN:", out["clean_total"])
    print("A th bands clean:", json.dumps(out["A_th_bands"]["clean"], ensure_ascii=False))
    print("B mth bands clean:", json.dumps(out["B_market_th_bands"], ensure_ascii=False))
    print("D panic resonance:", json.dumps(out["D_panic_resonance"], ensure_ascii=False))
    print("E windows:", json.dumps(out["E_windows"], ensure_ascii=False))
    print("F deep candidates:", json.dumps(out["F_deep_value_candidates"], ensure_ascii=False))

if __name__ == "__main__":
    main()