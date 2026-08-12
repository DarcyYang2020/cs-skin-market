# -*- coding: utf-8 -*-
"""W-1 峰值确认离场回测（只读研究，零引擎参数）。

背景：V0 朴素尖顶（3d 崩 50%）证伪（假摔，30d med +19.6%）；V3 全局峰值后 30/90d 下跌 100%（事后口径）。
W-1 = 可交易变体：距历史峰值回撤 >=70% 且峰值发生在 >=N 天前（近 N 日未创新高 = 派发确认）→ 离场。
检验：信号后 14/30/90d 是否显著继续下跌（离场正确率），对比无确认的 dd>=70% 池，walk-forward + 置换。
产物：data/_exp_w1_peak_exit.json
"""
import io, json, statistics, random
from datetime import date

ROOT = r"C:\Users\81572\Desktop\codex\cs-model\cs-skin-market"
DEEP = ROOT + r"\data\_exp_sticker_deep_full.jsonl"
OUT = ROOT + r"\data\_exp_w1_peak_exit.json"
NET = 0.02

def load_deep():
    rows = []
    with io.open(DEEP, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                r["points"] = sorted(r["points"], key=lambda x: x[0])
                rows.append(r)
    return rows

def net_ret(g):
    return (1 + g) * (1 - NET) - 1

def stats(vals):
    if not vals:
        return {"n": 0}
    sv = sorted(vals)
    return {"n": len(vals),
            "down_win": round(sum(1 for v in vals if v < 0) / len(vals), 4),
            "median": round(statistics.median(vals), 4),
            "mean": round(statistics.fmean(vals), 4),
            "mean_net": round(statistics.fmean(net_ret(v) for v in vals), 4),
            "q25": round(sv[len(sv)//4], 4), "q75": round(sv[3*len(sv)//4], 4)}

def main():
    deep = load_deep()
    # 主信号：dd>=0.70 + 峰值确认 confirm_days（峰值距今 >= confirm_days）
    def collect(confirm_days, dd_th, dedup_days=30):
        sigs = []
        for r in deep:
            pts = r["points"]; px = [p for _, p in pts]
            n = len(px); last = -10**9
            for t in range(confirm_days, n):
                peak_idx = max(range(t + 1), key=lambda i: px[i])
                if px[peak_idx] <= 0:
                    continue
                dd = 1 - px[t] / px[peak_idx]
                if dd < dd_th:
                    continue
                if t - peak_idx < confirm_days:
                    continue
                if t - last < dedup_days:
                    continue
                last = t
                rec = {"name": r["name"], "t": t, "date": pts[t][0], "dd": dd, "peak_idx": peak_idx}
                if t + 14 < n: rec["ret14"] = px[t+14] / px[t] - 1
                if t + 30 < n: rec["ret30"] = px[t+30] / px[t] - 1
                if t + 90 < n: rec["ret90"] = px[t+90] / px[t] - 1
                sigs.append(rec)
        return sigs

    # 无确认对照：dd>=0.70 任意日（同 30d 去重）
    def collect_noconfirm(dd_th=0.70, dedup_days=30):
        sigs = []
        for r in deep:
            pts = r["points"]; px = [p for _, p in pts]
            n = len(px); last = -10**9; peak = -1.0
            for t in range(1, n):
                if px[t] > peak: peak = px[t]
                if peak <= 0 or 1 - px[t]/peak < dd_th: continue
                if t - last < dedup_days: continue
                last = t
                rec = {"name": r["name"], "t": t, "date": pts[t][0]}
                if t + 30 < n: rec["ret30"] = px[t+30]/px[t] - 1
                sigs.append(rec)
        return sigs

    out = {"meta": {"title": "W-1 峰值确认离场（可交易变体）", "date": "2026-08-12",
                    "note": "只读研究零引擎参数；V0 朴素尖顶已证伪、V3 事后口径已确认，本回测为可交易确认规则"}}
    out["params"] = {"dd_th": 0.70, "confirm_days_grid": [7, 14, 21], "dedup": "30d per item",
                     "cost": "net2% 双边", "judge": "down_win30>=65% 且 med30<=-10% 且优于无确认池 + 置换显著"}
    for cd in (7, 14, 21):
        sigs = collect(cd, 0.70)
        key = "confirm%d" % cd
        out[key] = {"n": len(sigs),
                    "r14": stats([s["ret14"] for s in sigs if "ret14" in s]),
                    "r30": stats([s["ret30"] for s in sigs if "ret30" in s]),
                    "r90": stats([s["ret90"] for s in sigs if "ret90" in s])}
    noconf = collect_noconfirm()
    out["no_confirm_dd70"] = {"n": len(noconf),
                              "r30": stats([s["ret30"] for s in noconf if "ret30" in s])}
    # 主信号 confirm14 深看：walk-forward + 置换
    main_sigs = collect(14, 0.70)
    cut = date(2025, 11, 1)
    fwd = [s for s in main_sigs if date.fromisoformat(s["date"]) < cut]
    bwd = [s for s in main_sigs if date.fromisoformat(s["date"]) >= cut]
    out["confirm14_deep"] = {
        "walk_forward": {
            "before_2025-11": {"n": len(fwd), "r30": stats([s["ret30"] for s in fwd if "ret30" in s])},
            "after_2025-11": {"n": len(bwd), "r30": stats([s["ret30"] for s in bwd if "ret30" in s])}},
        "unique_items": len(set(s["name"] for s in main_sigs))}
    pool = [s["ret30"] for s in noconf if "ret30" in s]
    obs = [s["ret30"] for s in main_sigs if "ret30" in s]
    random.seed(42)
    null_down = []; null_med = []
    for _ in range(500):
        samp = random.sample(pool, len(obs))
        null_down.append(sum(1 for v in samp if v < 0) / len(samp))
        null_med.append(statistics.median(samp))
    obs_down = sum(1 for v in obs if v < 0) / len(obs)
    obs_med = statistics.median(obs)
    out["confirm14_deep"]["permutation_500"] = {
        "p_down_ge_obs": round(sum(1 for x in null_down if x >= obs_down) / len(null_down), 3),
        "p_med_le_obs": round(sum(1 for x in null_med if x <= obs_med) / len(null_med), 3),
        "null_down_q50": round(statistics.median(null_down), 4),
        "null_med_q50": round(statistics.median(null_med), 4)}
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("== W-1 峰值确认离场 ==")
    for cd in (7, 14, 21):
        key = "confirm%d" % cd
        r30 = out[key]["r30"]; r14 = out[key]["r14"]
        print("confirm=%dd n30=%d down30=%.1f%% med30=%+.1f%% net30=%+.1f%% | n14=%d down14=%.1f%% med14=%+.1f%%" % (
            cd, r30["n"], 100*r30["down_win"], 100*r30["median"], 100*r30["mean_net"],
            r14["n"], 100*r14["down_win"], 100*r14["median"]))
    nc = out["no_confirm_dd70"]["r30"]
    print("无确认 dd70: n=%d down30=%.1f%% med30=%+.1f%%" % (nc["n"], 100*nc["down_win"], 100*nc["median"]))
    dp = out["confirm14_deep"]
    print("confirm14 深看: unique=%d" % dp["unique_items"])
    print("  wf before: %s" % dp["walk_forward"]["before_2025-11"]["r30"])
    print("  wf after : %s" % dp["walk_forward"]["after_2025-11"]["r30"])
    p = dp["permutation_500"]
    print("  置换500: p_down=%.3f p_med=%.3f null_down=%.1f%% null_med=%+.1f%%" % (
        p["p_down_ge_obs"], p["p_med_le_obs"], 100*p["null_down_q50"], 100*p["null_med_q50"]))
    r90 = out["confirm14"]["r90"]
    print("confirm14 r90: n=%d down90=%.1f%% med90=%+.1f%%" % (r90["n"], 100*r90["down_win"], 100*r90["median"]))
    print("OUT:", OUT)

if __name__ == "__main__":
    main()
