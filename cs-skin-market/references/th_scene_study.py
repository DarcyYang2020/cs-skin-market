# -*- coding: utf-8 -*-
"""TH x 场景条件期望表 + 离线候选模拟（2026-08-06，TH 矫正预研第二阶段）。

场景维度：pct 深度 / sent 情绪 / mchg30 大盘 / cycle
TH 档位：<20 / 20-34 / 35-44 / 45-54 / >=55（单品 th）与大盘 mth 分档
全部用干净样本（剔除 fwd30 与黑天鹅事件影响期重叠）
输出：data/th_scene_study.json
"""
import sys, io, json
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pipeline.market_macro import historical_event_impact

def load():
    with open("data/item_backtest_full_2025.json", encoding="utf-8") as f:
        return json.load(f)["signals"]

def clean(sigs):
    return [s for s in sigs if not historical_event_impact(s["date"], 30)]

def stats(recs):
    v = [(s.get("fwd30"), s.get("net30")) for s in recs]
    v = [(a, b) for a, b in v if a is not None and b is not None]
    if not v: return {"n": 0}
    vals = [a for a, _ in v]
    return {"n": len(vals), "win30": round(sum(1 for x in vals if x > 0)/len(vals)*100, 1),
            "avg30": round(sum(vals)/len(vals), 2), "net30": round(sum(b for _, b in v)/len(v), 2)}

def th_band(t):
    if t < 20: return "th<20"
    if t < 35: return "th20-34"
    if t < 45: return "th35-44"
    if t < 55: return "th45-54"
    return "th>=55"

def main():
    sigs = clean(load())
    out = {"generated": "2026-08-06", "n_clean": len(sigs)}

    # 1) TH 档位 x 深度场景（pct 分档）
    depth = [("deep pct<=15", lambda s: s["pct"] <= 15),
             ("mid pct15-30", lambda s: 15 < s["pct"] <= 30),
             ("high pct>30", lambda s: s["pct"] > 30)]
    out["scene_x_th"] = {}
    for dlab, dcond in depth:
        sub = [s for s in sigs if dcond(s)]
        out["scene_x_th"][dlab] = {th_band(s["th"]): stats([x for x in sub if th_band(x["th"]) == th_band(s["th"])]) for s in sub}
    # 2) TH 档位 x 情绪场景
    sent = [("fear sent>=75", lambda s: s["sentiment"] >= 75),
            ("mid 60-74", lambda s: 60 <= s["sentiment"] < 75),
            ("calm 40-59", lambda s: 40 <= s["sentiment"] < 60),
            ("greed <40", lambda s: s["sentiment"] < 40)]
    out["sent_x_th"] = {}
    for slab, scond in sent:
        sub = [s for s in sigs if scond(s)]
        out["sent_x_th"][slab] = {th_band(s["th"]): stats([x for x in sub if th_band(x["th"]) == th_band(s["th"])]) for s in sub}
    # 3) 大盘 mth 档位 x 单品 th 档位（矩阵）
    mth_band = lambda m: ("mth<35" if m < 35 else "mth35-44" if m < 45 else "mth45-54" if m < 55 else "mth>=55")
    out["th_x_mth"] = {}
    for tb in ["th<20", "th20-34", "th35-44", "th45-54", "th>=55"]:
        out["th_x_mth"][tb] = {}
        for mb in ["mth<35", "mth35-44", "mth45-54", "mth>=55"]:
            sub = [s for s in sigs if th_band(s["th"]) == tb and mth_band(s["market_th"]) == mb]
            out["th_x_mth"][tb][mb] = stats(sub)
    # 4) 离线候选模拟（基于当前引擎 503 信号，评估"剔除/收紧"效果）
    cand = {}
    # 4a. 当前引擎（干净样本）基线
    cand["baseline_current"] = stats(sigs)
    # 4b. 剔除深值族最差档：th 45-54 & pct<=30 & z<=0（deep_value 门槛纳入的最差组）
    bad_dv = [s for s in sigs if 45 <= s["th"] < 55 and s["pct"] <= 30 and s["z"] <= 0]
    cand["drop_deepvalue_45_54"] = {"removed": stats(bad_dv), "remaining": stats([s for s in sigs if s not in bad_dv])}
    # 4c. 剔除模糊带所有信号（th 35-54）
    bad_mid = [s for s in sigs if 35 <= s["th"] < 55]
    cand["drop_mid_35_54"] = {"removed": stats(bad_mid), "remaining": stats([s for s in sigs if s not in bad_mid])}
    # 4d. 深值场景按 TH 档保留（看如果 deep_value 只保留某档的期望）
    dv_all = [s for s in sigs if s["pct"] <= 20 and s["z"] <= -0.5 and s["sentiment"] >= 40 and s["sentiment"] <= 65]
    cand["deepvalue_scene"] = {th_band(s["th"]): stats([x for x in dv_all if th_band(x["th"]) == th_band(s["th"])]) for s in dv_all}
    out["candidates"] = cand

    with open("data/th_scene_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("baseline:", cand["baseline_current"])
    print("drop_deepvalue_45_54:", json.dumps(cand["drop_deepvalue_45_54"], ensure_ascii=False))
    print("drop_mid_35_54:", json.dumps(cand["drop_mid_35_54"], ensure_ascii=False))
    print("deepvalue_scene:", json.dumps(cand["deepvalue_scene"], ensure_ascii=False))
    print("scene_x_th deep pct<=15:", json.dumps(out["scene_x_th"]["deep pct<=15"], ensure_ascii=False))
    print("sent_x_th fear>=75:", json.dumps(out["sent_x_th"]["fear sent>=75"], ensure_ascii=False))

if __name__ == "__main__":
    main()