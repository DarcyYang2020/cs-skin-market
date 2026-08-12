# -*- coding: utf-8 -*-
"""W-3 吸筹信号跟踪（每日可重跑，只读研究，零引擎参数）。

对 W-3 探索版 66 个吸筹信号（深回撤>70% + 30d CV<=5% + 企稳）输出落地状态：
已落地（30d 前视可算）实时胜率/中位/净收益 + 未落地清单与预计落地日。
依赖：S-1 深历史快照刷新后自动更新落地（_exp_sticker_deep_full.jsonl）。
产物：data/_exp_w3_signal_tracker.json
"""
import io, json, sqlite3, statistics

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

def cv(xs):
    m = statistics.fmean(xs)
    return statistics.pstdev(xs) / m if m > 0 else None

def net_ret(g):
    return (1 + g) * (1 - NET) - 1

def main():
    deep = load_deep()
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
            rec = {"name": r["name"], "t": t, "date": pts[t][0], "px": px[t]}
            if t + 30 < n: rec["ret30"] = px[t+30] / px[t] - 1
            if t + 90 < n: rec["ret90"] = px[t+90] / px[t] - 1
            signals.append(rec)
    # 深历史最新日期（数据截止）
    last_date = max(r["points"][-1][0] for r in deep)
    done = [s for s in signals if "ret30" in s]
    pending = [s for s in signals if "ret30" not in s]
    done_r30 = [s["ret30"] for s in done]
    done_r90 = [s["ret90"] for s in done if "ret90" in s]
    # price_history 最新日期（提示刷新）
    con = sqlite3.connect(DB); cur = con.cursor()
    cur.execute("SELECT MAX(p.date) FROM price_history p JOIN items i ON p.item_id=i.id WHERE i.source='sticker'")
    ph_last = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM items WHERE source='sticker'")
    n_items = cur.fetchone()[0]
    con.close()
    out = {
        "meta": {"title": "W-3 吸筹信号跟踪（每日重跑）", "date": "2026-08-12",
                 "deep_last_date": last_date, "price_history_last_date": ph_last,
                 "sticker_items": n_items,
                 "note": "深历史刷新后重跑本脚本即可推进落地状态"},
        "signals": sorted(signals, key=lambda s: s["date"]),
        "status": {
            "n_total": len(signals),
            "n_done_30d": len(done_r30),
            "n_pending": len(pending),
            "done": {
                "r30": {"n": len(done_r30),
                        "win": round(sum(1 for v in done_r30 if v > 0) / len(done_r30), 4) if done_r30 else 0,
                        "median": round(statistics.median(done_r30), 4) if done_r30 else None,
                        "mean": round(statistics.fmean(done_r30), 4) if done_r30 else None,
                        "mean_net": round(statistics.fmean(net_ret(v) for v in done_r30), 4) if done_r30 else None},
                "r90": {"n": len(done_r90),
                        "win": round(sum(1 for v in done_r90 if v > 0) / len(done_r90), 4) if done_r90 else 0,
                        "median": round(statistics.median(done_r90), 4) if done_r90 else None}},
            "pending": {
                "n": len(pending),
                "eta_dates": sorted({s["date"][:10] for s in pending}),
                "list": [{"name": s["name"], "date": s["date"], "eta": (s["date"])} for s in pending]},
        },
    }
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    st = out["status"]
    print("== W-3 吸筹信号跟踪 ==")
    print("deep last=%s | price_history last=%s | sticker items=%d" % (last_date, ph_last, n_items))
    print("total=%d done30=%d pending=%d" % (st["n_total"], st["n_done_30d"], st["n_pending"]))
    d = st["done"]["r30"]
    print("done r30: win=%.1f%% med=%+.1f%% net=%+.1f%%" % (100*d["win"], 100*d["median"], 100*d["mean_net"]))
    d90 = st["done"]["r90"]
    print("done r90: n=%d win=%.1f%% med=%+.1f%%" % (d90["n"], 100*d90["win"], 100*d90["median"]))
    print("pending eta dates:", st["pending"]["eta_dates"])
    print("OUT:", OUT)

if __name__ == "__main__":
    main()
