# -*- coding: utf-8 -*-
"""W-3 探索版 v3：修复 monthly（Counter）+ 决定性同期对照（2025-12 后深回撤日按 cv 分层）。"""
import io, json, sqlite3, statistics, random, collections
from datetime import date

ROOT = r"C:\Users\81572\Desktop\codex\cs-model\cs-skin-market"
DEEP = ROOT + r"\data\_exp_sticker_deep_full.jsonl"
DB = ROOT + r"\data\market.db"
OUT = ROOT + r"\data\_exp_w3_accum_continuation.json"
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

def load_ph():
    con = sqlite3.connect(DB); cur = con.cursor()
    cur.execute("""SELECT i.name, p.date, p.price_rmb, p.in_sale_count
                   FROM price_history p JOIN items i ON p.item_id = i.id
                   WHERE i.source='sticker' AND p.in_sale_count IS NOT NULL
                   ORDER BY i.name, p.date""")
    by = {}
    for name, d, px, ins in cur.fetchall():
        by.setdefault(name, []).append((d, px, ins))
    con.close(); return by

def cv(xs):
    m = statistics.fmean(xs)
    return statistics.pstdev(xs)/m if m > 0 else None

def net_ret(g): return (1 + g) * (1 - NET) - 1

def stats(vals):
    if not vals: return {"n": 0}
    sv = sorted(vals)
    return {"n": len(vals), "win": round(sum(1 for v in vals if v > 0)/len(vals), 4),
            "median": round(statistics.median(vals), 4), "mean_net": round(statistics.fmean(net_ret(v) for v in vals), 4),
            "q25": round(sv[len(sv)//4], 4), "q75": round(sv[3*len(sv)//4], 4)}

def main():
    deep = load_deep(); ph = load_ph()
    out = {"meta": {"title": "W-3 探索版 v3：吸筹痕迹 + 拉升承接（Major 脱钩）", "date": "2026-08-12",
                    "note": "只读研究零引擎参数；正式立项过 A2"}}
    # ---- 信号 A：cv<=5% 吸筹 ----
    sigs = []
    for r in deep:
        px = [p for _, p in r["points"]]; peak = -1.0; last = -10**9
        for t in range(60, len(px)):
            if px[t] > peak: peak = px[t]
            if peak <= 0 or 1 - px[t]/peak < 0.70: continue
            c30 = cv(px[t-29:t+1])
            if c30 is None or c30 > 0.05: continue
            if px[t] <= min(px[t-29:t+1]) * 1.02: continue
            if t - last < 30: continue
            last = t
            rec = {"name": r["name"], "t": t, "date": r["points"][t][0]}
            if t + 30 < len(px): rec["ret30"] = px[t+30]/px[t] - 1
            if t + 90 < len(px): rec["ret90"] = px[t+90]/px[t] - 1
            sigs.append(rec)
    sig_ret30 = [s["ret30"] for s in sigs if "ret30" in s]
    # ---- 同期对照：2025-12-01 起所有深回撤日，按 cv 分层 ----
    CUT = date(2025, 12, 1)
    layers = {"cv<=0.05": [], "0.05<cv<=0.10": [], "0.10<cv<=0.15": [], "cv>0.15": []}
    for r in deep:
        pts = r["points"]; px = [p for _, p in pts]; peak = -1.0
        for t in range(60, len(pts)):
            if px[t] > peak: peak = px[t]
            if peak <= 0 or 1 - px[t]/peak < 0.70: continue
            if date.fromisoformat(pts[t][0]) < CUT: continue
            c30 = cv(px[t-29:t+1])
            if c30 is None: continue
            if c30 <= 0.05: g = "cv<=0.05"
            elif c30 <= 0.10: g = "0.05<cv<=0.10"
            elif c30 <= 0.15: g = "0.10<cv<=0.15"
            else: g = "cv>0.15"
            if t + 30 < len(px):
                layers[g].append(px[t+30]/px[t] - 1)
    out["signal_a"] = {"n_total": len(sigs), "n_ret30": len(sig_ret30),
                       "unique_items": len(set(s["name"] for s in sigs)),
                       "r30_signal": stats(sig_ret30),
                       "r90_signal": stats([s["ret90"] for s in sigs if "ret90" in s])}
    out["signal_a"]["same_period_control_by_cv"] = {k: stats(v) for k, v in layers.items()}
    # 时间簇与月度
    ds = sorted(s["date"] for s in sigs)
    months = collections.Counter(d[:7] for d in ds)
    clusters = []
    for d in ds:
        dd = date.fromisoformat(d)
        if not clusters or (dd - clusters[-1][-1]).days > 30: clusters.append([dd])
        else: clusters[-1].append(dd)
    out["signal_a"]["monthly"] = dict(sorted(months.items()))
    out["signal_a"]["clusters_30d"] = len(clusters)
    out["signal_a"]["cluster_ranges"] = [[c[0].isoformat(), c[-1].isoformat(), len(c)] for c in clusters]
    # 置换：同期非信号深回撤日池抽 n 个
    pool = []
    for r in deep:
        pts = r["points"]; px = [p for _, p in pts]; peak = -1.0
        for t in range(60, len(pts)):
            if px[t] > peak: peak = px[t]
            if peak <= 0 or 1 - px[t]/peak < 0.70: continue
            if date.fromisoformat(pts[t][0]) < CUT: continue
            c30 = cv(px[t-29:t+1])
            if c30 is None or c30 > 0.05: continue
            if t + 30 < len(px):
                pool.append(px[t+30]/px[t] - 1)
    random.seed(42)
    null_med = []; null_win = []
    for _ in range(500):
        samp = random.sample(pool, len(sig_ret30))
        null_med.append(statistics.median(samp))
        null_win.append(sum(1 for v in samp if v > 0)/len(samp))
    obs_med = statistics.median(sig_ret30); obs_win = sum(1 for v in sig_ret30 if v > 0)/len(sig_ret30)
    out["signal_a"]["permutation_500_same_period"] = {
        "p_med_ge_obs": round(sum(1 for x in null_med if x >= obs_med)/len(null_med), 3),
        "p_win_ge_obs": round(sum(1 for x in null_win if x >= obs_win)/len(null_win), 3),
        "null_med_q50": round(statistics.median(null_med), 4),
        "null_win_q50": round(statistics.median(null_win), 4)}
    # ---- 信号 B：拉升承接（90d 价格+在售） ----
    groups = {"shrink": [], "stable": [], "expand": []}; all_fw = []
    for name, bars in ph.items():
        px = [b[1] for b in bars]; ins = [b[2] for b in bars]; n = len(px)
        last = {"shrink": -10**9, "stable": -10**9, "expand": -10**9}
        for t in range(21, n - 1):
            if px[t]/px[t-20] - 1 < 0.30: continue
            if px[t]/px[t-7] - 1 < -0.15: continue
            rec = {"name": name, "t": t}
            if t + 14 < n: rec["ret14"] = px[t+14]/px[t] - 1
            if t + 30 < n: rec["ret30"] = px[t+30]/px[t] - 1
            all_fw.append(rec)
            if ins[t] is not None and ins[t-7] and ins[t-7] > 0:
                d7 = ins[t]/ins[t-7] - 1
                g = "shrink" if d7 <= -0.10 else ("stable" if d7 <= 0.05 else "expand")
                if t - last[g] >= 14:
                    last[g] = t; groups[g].append(rec)
    out["signal_b"] = {"params": {"first_wave_20d": 0.30, "pullback_7d_floor": -0.15,
                                  "in_sale_7d": "shrink<=-10% / stable<=+5% / expand>+5%"}}
    for g in ("shrink", "stable", "expand"):
        out["signal_b"][g] = {"r14": stats([s["ret14"] for s in groups[g] if "ret14" in s]),
                              "r30": stats([s["ret30"] for s in groups[g] if "ret30" in s])}
    out["signal_b"]["baseline_all_first_wave"] = {"r14": stats([s["ret14"] for s in all_fw if "ret14" in s]),
                                                  "r30": stats([s["ret30"] for s in all_fw if "ret30" in s])}
    # B2: mid-consolidation variant (first wave done >=8d ago, last 7d pullback <=10%)
    b2 = []
    for name, bars in ph.items():
        px = [b[1] for b in bars]
        n = len(px)
        for t in range(25, n - 1):
            if px[t] / px[t-20] - 1 < 0.30:
                continue
            hi = max(range(t-19, t+1), key=lambda i: px[i])
            if hi > t - 8:
                continue
            if px[t] / px[t-7] - 1 < -0.10:
                continue
            rec = {"name": name, "t": t}
            if t + 14 < n:
                rec["ret14"] = px[t+14] / px[t] - 1
            if t + 30 < n:
                rec["ret30"] = px[t+30] / px[t] - 1
            b2.append(rec)
    out["signal_b"]["b2_mid_consolidation"] = {
        "r14": stats([s["ret14"] for s in b2 if "ret14" in s]),
        "r30": stats([s["ret30"] for s in b2 if "ret30" in s])}
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("== 信号 A：吸筹（cv<=5%）==")
    sa = out["signal_a"]
    print("n_total=%d n_ret30=%d unique=%d" % (sa["n_total"], sa["n_ret30"], sa["unique_items"]))
    s = sa["r30_signal"]
    print("信号组 r30: win=%.1f%% med=%+.1f%% net=%+.1f%%" % (100*s["win"], 100*s["median"], 100*s["mean_net"]))
    print("同期对照（2025-12 起深回撤日按 cv 分层 r30）:")
    for k, v in sa["same_period_control_by_cv"].items():
        print("  %-16s n=%4d win=%.1f%% med=%+.1f%%" % (k, v["n"], 100*v["win"], 100*v["median"]))
    print("monthly:", sa["monthly"])
    print("clusters=%d %s" % (sa["clusters_30d"], sa["cluster_ranges"]))
    p = sa["permutation_500_same_period"]
    print("置换(同期cv<=5%%池): p_med=%.3f p_win=%.3f null_med=%.1f%% null_win=%.1f%%" % (p["p_med_ge_obs"], p["p_win_ge_obs"], 100*p["null_med_q50"], 100*p["null_win_q50"]))
    print("== 信号 B：拉升承接 ==")
    for g in ("shrink", "stable", "expand"):
        r14 = out["signal_b"][g]["r14"]; r30 = out["signal_b"][g]["r30"]
        print("%s n14=%d win14=%.1f%% med14=%+.1f%% | n30=%d win30=%.1f%% med30=%+.1f%%" % (
            g, r14["n"], 100*r14["win"], 100*r14["median"], r30["n"], 100*r30["win"], 100*r30["median"]))
    b14 = out["signal_b"]["baseline_all_first_wave"]["r14"]
    print("基线全部第一波 n=%d win14=%.1f%% med14=%+.1f%%" % (b14["n"], 100*b14["win"], 100*b14["median"]))
    b2r = out["signal_b"]["b2_mid_consolidation"]["r14"]
    print("B2 mid-consolidation n14=%d win14=%.1f%% med14=%+.1f%%" % (b2r["n"], 100*b2r["win"], 100*b2r["median"]))
    print("OUT:", OUT)

if __name__ == "__main__":
    main()

