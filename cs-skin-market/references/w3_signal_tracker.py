# -*- coding: utf-8 -*-
"""W-3 吸筹信号跟踪 v3（每日可重跑，只读研究，零引擎参数）。

66 个吸筹信号（深回撤>70% + 30d CV<=5% + 企稳）：
- 30d 结果：price_history 实时优先（信号日在 2026-05-13 后），S-1 深历史兜底；
- 每信号附同期市场基准（deep 全池同日 30d 中位）与 alpha（信号 ret30 - 市场 med30）；
- 关键结论（2026-08-12 基准对照）：吸筹 alpha 仅存在于市场非暴跌期——
  早段（2025-12~2026-06）市场 med -3.3% 时信号 +18.2%（alpha +21.5pp）；2026-06-13 后市场暴跌
  （全池 30d med -18.3%）时信号 -16~-18% 与 beta 一致（alpha≈0）——市场暴跌期禁买。
产物：data/_exp_w3_signal_tracker.json；已挂 run_daily_collect.py。
"""
import io, json, sqlite3, statistics, collections
from datetime import datetime, timedelta

ROOT = r"C:\Users\81572\Desktop\codex\cs-model\cs-skin-market"
DEEP = ROOT + r"\data\_exp_sticker_deep_full.jsonl"
DB = ROOT + r"\data\market.db"
OUT = ROOT + r"\data\_exp_w3_signal_tracker.json"
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
    return statistics.pstdev(xs) / m if m > 0 else None

def net_ret(g):
    return (1 + g) * (1 - NET) - 1

def st(vals):
    if not vals: return {"n": 0}
    return {"n": len(vals),
            "win": round(sum(1 for v in vals if v > 0) / len(vals), 4),
            "median": round(statistics.median(vals), 4),
            "mean_net": round(statistics.fmean(net_ret(v) for v in vals), 4)}

def main():
    deep = load_deep()
    ph = load_ph()
    # 市场基准：deep 全池每日 30d 中位
    by_day = collections.defaultdict(list)
    for r in deep:
        px = [p for _, p in r["points"]]
        for t in range(len(px) - 30):
            by_day[r["points"][t][0]].append(px[t+30]/px[t] - 1)
    market_med = {d: statistics.median(v) for d, v in by_day.items()}
    # 信号
    signals = []
    for r in deep:
        pts = r["points"]; px = [p for _, p in pts]
        n = len(px); peak = -1.0; last = -10**9
        for t in range(60, n):
            if px[t] > peak: peak = px[t]
            if peak <= 0 or 1 - px[t] / peak < 0.70: continue
            c30 = cv(px[t-29:t+1])
            if c30 is None or c30 > 0.05: continue
            if px[t] <= min(px[t-29:t+1]) * 1.02: continue
            if t - last < 30: continue
            last = t
            rec = {"name": r["name"], "t": t, "date": pts[t][0], "px_deep": px[t]}
            if t + 30 < n: rec["ret30_deep"] = px[t+30] / px[t] - 1
            signals.append(rec)
    for s in signals:
        s["market_med30"] = market_med.get(s["date"])
        sdate = datetime.strptime(s["date"], "%Y-%m-%d").date()
        bars = ph.get(s["name"])
        if bars:
            dates = [b[0] for b in bars]
            try: i0 = dates.index(s["date"])
            except ValueError: i0 = None
            if i0 is not None:
                px0 = bars[i0][1]
                ph_last = datetime.strptime(bars[-1][0], "%Y-%m-%d").date()
                tgt = sdate + timedelta(days=30)
                if px0 and px0 > 0 and tgt <= ph_last:
                    i1 = i0
                    for j in range(i0, len(bars)):
                        if datetime.strptime(bars[j][0], "%Y-%m-%d").date() <= tgt: i1 = j
                        else: break
                    if i1 > i0: s["ret30_ph"] = bars[i1][1] / px0 - 1
                ins_series = [b[2] for b in bars]
                ins0 = bars[i0][2]
                if i0 >= 7 and ins_series[i0-7]:
                    s["ins_chg7d"] = round(ins0 / ins_series[i0-7] - 1, 4)
                if ins0 is not None:
                    s["ins_pct_rank"] = round(sum(1 for x in ins_series if x <= ins0) / len(ins_series), 3)
        if "ret30_ph" in s:
            s["ret30"] = s["ret30_ph"]; s["src30"] = "ph"
        elif "ret30_deep" in s:
            s["ret30"] = s["ret30_deep"]; s["src30"] = "deep"
        else:
            s["ret30"] = None; s["src30"] = "pending"
            s["eta"] = (sdate + timedelta(days=30)).isoformat()
        if s["ret30"] is not None and s["market_med30"] is not None:
            s["alpha"] = round(s["ret30"] - s["market_med30"], 4)
    done = [s for s in signals if s["ret30"] is not None]
    pending = [s for s in signals if s["ret30"] is None]
    def alpha_st(vals):
        vals = [v for v in vals if v is not None]
        if not vals: return {"n": 0}
        return {"n": len(vals), "median": round(statistics.median(vals), 4),
                "win_gt0": round(sum(1 for v in vals if v > 0) / len(vals), 4)}
    deep_done = [s for s in done if s["src30"] == "deep"]
    ph_done = [s for s in done if s["src30"] == "ph"]
    # regime 分层：市场暴跌（med30 <= -10%）vs 非暴跌
    crash = [s for s in done if s["market_med30"] is not None and s["market_med30"] <= -0.10]
    calm = [s for s in done if s["market_med30"] is not None and s["market_med30"] > -0.10]
    # 在售分层（alpha 口径，ph 段）
    layers = {"shrink": [], "stable": [], "expand": [], "na": []}
    for s in ph_done:
        c = s.get("ins_chg7d")
        if c is None: layers["na"].append(s.get("alpha"))
        elif c <= -0.10: layers["shrink"].append(s.get("alpha"))
        elif c <= 0.05: layers["stable"].append(s.get("alpha"))
        else: layers["expand"].append(s.get("alpha"))
    out = {
        "meta": {"title": "W-3 吸筹信号跟踪 v3（每日重跑，已挂 run_daily_collect.py）",
                 "date": "2026-08-12",
                 "key_finding": "吸筹 alpha 仅存在于市场非暴跌期：早段市场 med -3.3% 时信号 +18.2%（alpha +21.5pp）；2026-06-13 后市场暴跌（全池 med -18.3%）信号跟随 beta（alpha~0）——市场暴跌期禁买",
                 "note": "market_med30 = deep 全池同日 30d 中位；alpha = ret30 - market_med30"},
        "status": {
            "n_total": len(signals), "n_done": len(done), "n_pending": len(pending),
            "r30": st([s["ret30"] for s in done]),
            "alpha": alpha_st([s.get("alpha") for s in done]),
            "by_src": {"deep": {"n": len(deep_done), "r30": st([s["ret30"] for s in deep_done]),
                                "alpha": alpha_st([s.get("alpha") for s in deep_done])},
                       "ph": {"n": len(ph_done), "r30": st([s["ret30"] for s in ph_done]),
                              "alpha": alpha_st([s.get("alpha") for s in ph_done])}},
            "regime": {"crash(market<=-10%)": {"n": len(crash), "r30": st([s["ret30"] for s in crash]),
                                                "alpha": alpha_st([s.get("alpha") for s in crash])},
                       "calm(market>-10%)": {"n": len(calm), "r30": st([s["ret30"] for s in calm]),
                                              "alpha": alpha_st([s.get("alpha") for s in calm])}},
            "supply_layers_alpha_ph": {k: alpha_st(v) for k, v in layers.items()},
            "pending_eta": sorted({s["eta"] for s in pending if "eta" in s}),
        },
        "signals": [{"name": s["name"], "date": s["date"], "ret30": s["ret30"], "src30": s["src30"],
                     "market_med30": s.get("market_med30"), "alpha": s.get("alpha"),
                     "ins_chg7d": s.get("ins_chg7d"), "ins_pct_rank": s.get("ins_pct_rank"),
                     "eta": s.get("eta")} for s in sorted(signals, key=lambda x: x["date"])],
    }
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    sts = out["status"]
    print("== W-3 吸筹信号跟踪 v3 ==")
    print("total=%d done=%d pending=%d" % (sts["n_total"], sts["n_done"], sts["n_pending"]))
    r = sts["r30"]; a = sts["alpha"]
    print("r30: win=%.1f%% med=%+.1f%% | alpha: n=%d med=%+.1f%% win>0=%.1f%%" % (
        100*r["win"], 100*r["median"], a["n"], 100*a["median"], 100*a["win_gt0"]))
    for k in ("deep", "ph"):
        v = sts["by_src"][k]
        print("  %-5s n=%d r30 med=%+.1f%% | alpha med=%+.1f%%" % (k, v["n"], 100*v["r30"]["median"], 100*v["alpha"]["median"]))
    for k in ("crash(market<=-10%)", "calm(market>-10%)"):
        v = sts["regime"][k]
        print("  %-20s n=%d r30 med=%+.1f%% | alpha med=%+.1f%%" % (k, v["n"], 100*v["r30"]["median"], 100*v["alpha"]["median"]))
    for k in ("shrink", "stable", "expand", "na"):
        v = sts["supply_layers_alpha_ph"][k]
        print("  supply %-7s n=%d alpha med=%+.1f%%" % (k, v["n"], 100*v.get("median", 0)))
    print("pending eta:", sts["pending_eta"])
    print("OUT:", OUT)

if __name__ == "__main__":
    main()
