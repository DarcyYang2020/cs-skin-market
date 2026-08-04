# -*- coding: utf-8 -*-
"""Pre-1/23 non-panic small bull replay + 1/23~3/17 crash-rally window (v2)."""
import sys, json, statistics
from collections import Counter
sys.path.insert(0, '.')
from pipeline import item_analysis as ia
from pipeline import db
from pipeline.backtest_common import patch_sentiment, build_market_context
import run_item_backtest as rib

COST_PCT = 2.0
WARMUP = 60
WINDOWS = [
    ("pre123", "2025-11-02", "2026-01-22"),
    ("crash_rally", "2026-01-23", "2026-03-17"),
]
EXCLUDED = {"AK-47 | 水栽竹 (崭新出厂)", "AWP | 珊瑚树 (崭新出厂)"}

market_ctx = build_market_context("2025-11-02")
print(f"market_ctx days: {len(market_ctx)}", flush=True)

conn = db.get_conn()
items = [r for r in conn.execute("SELECT id, name FROM items ORDER BY id").fetchall()
         if r["name"] not in EXCLUDED]

sig_by_win = {w: [] for w, _, _ in WINDOWS}
phase_by_win = {w: Counter() for w, _, _ in WINDOWS}
n_run = 0

for item_id, name in items:
    dates, prices, in_sale = rib.load_item_series(item_id)
    if len(prices) < WARMUP + 1:
        continue
    n = len(prices)
    recent_buys = []
    for i in range(WARMUP, n):
        d = dates[i]
        if d not in market_ctx:
            continue
        win = None
        for w, ws, we in WINDOWS:
            if ws <= d <= we:
                win = w
                break
        if win is None:
            continue
        mc = market_ctx[d]
        patch_sentiment(mc["sentiment"])
        prefix = prices[:i + 1]
        try:
            res = ia.run_item_analysis(
                name=name, prices=prefix, volumes=[0] * len(prefix),
                supply_hist=in_sale[:i + 1], market_history=None,
                market_pct_90d=mc["pct"], market_cycle=mc["cycle"],
                market_zscore=mc["z"], market_th_score=mc["th"],
                market_30d_change=mc.get("chg30", 0), market_drop21=mc.get("drop21", 0),
                recent_buy_dates=recent_buys, signal_date=d,
            )
        except Exception:
            continue
        n_run += 1
        fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
        action = fd.get("action", "")
        if action in ("buy", "oversold_buy"):
            recent_buys.append(d)
        f14 = (prices[i + 14] / prices[i] - 1) * 100 - COST_PCT if i + 14 < n else None
        f30 = (prices[i + 30] / prices[i] - 1) * 100 - COST_PCT if i + 30 < n else None
        th = res.trend_health or {}
        cyc = res.cycle
        sup = res.supply_analysis or {}
        rec = {
            "date": d, "name": name, "action": action,
            "label": fd.get("action_label", action),
            "pct": getattr(res.position, "percentile_90d", None),
            "z": getattr(res.position, "zscore_90d", None),
            "th": th.get("score"),
            "mth": mc["th"], "sent": round(mc["sentiment"], 1),
            "cycle": cyc.phase if cyc else "unknown",
            "supply_trend": sup.get("supply_trend"),
            "supply_risk": sup.get("supply_risk"),
            "price": round(prices[i], 2), "net14": f14, "net30": f30,
        }
        sig_by_win[win].append(rec)
        phase_by_win[win][cyc.phase if cyc else "unknown"] += 1

print(f"replay done: {n_run} analysis calls", flush=True)


def show_window(w, ws, we):
    sigs = sig_by_win[w]
    print(f"\n===== window {w} ({ws} ~ {we}) =====", flush=True)
    print("action:", dict(Counter(s["action"] for s in sigs)), flush=True)
    print("cycle:", dict(phase_by_win[w]), flush=True)
    buy = [s for s in sigs if s["action"] in ("buy", "oversold_buy")]
    watch = [s for s in sigs if s["action"] == "watch"]
    print(f"BUY signals ({len(buy)}):", flush=True)
    for s in sorted(buy, key=lambda x: x["date"]):
        print(f"  {s['date']} {s['name']} pct={s['pct']} z={s['z']} th={s['th']} mth={s['mth']} sent={s['sent']} cycle={s['cycle']} supply={s['supply_risk']} net14={s['net14'] and round(s['net14'],1)} net30={s['net30'] and round(s['net30'],1)}", flush=True)
    f14 = [s["net14"] for s in buy if s["net14"] is not None]
    f30 = [s["net30"] for s in buy if s["net30"] is not None]
    if f14:
        print(f"  BUY 14d: n={len(f14)} win={sum(1 for v in f14 if v>0)/len(f14)*100:.0f}% avg={statistics.mean(f14):+.2f}% med={statistics.median(f14):+.2f}%", flush=True)
    if f30:
        print(f"  BUY 30d: n={len(f30)} win={sum(1 for v in f30 if v>0)/len(f30)*100:.0f}% avg={statistics.mean(f30):+.2f}% med={statistics.median(f30):+.2f}%", flush=True)
    w14 = [s["net14"] for s in watch if s["net14"] is not None]
    w30 = [s["net30"] for s in watch if s["net30"] is not None]
    if w14:
        print(f"  WATCH 14d: n={len(w14)} win={sum(1 for v in w14 if v>0)/len(w14)*100:.0f}% avg={statistics.mean(w14):+.2f}%", flush=True)
    if w30:
        print(f"  WATCH 30d: n={len(w30)} win={sum(1 for v in w30 if v>0)/len(w30)*100:.0f}% avg={statistics.mean(w30):+.2f}%", flush=True)
    hord = [s for s in sigs if s.get("supply_risk") == "hoarding"]
    print(f"supply hoarding (吸筹) item-days: {len(hord)}", flush=True)
    for s in sorted(hord, key=lambda x: x["date"])[:10]:
        print(f"    {s['date']} {s['name'][:22]:<24} action={s['action']} pct={s['pct']} z={s['z']} th={s['th']} net14={s['net14'] and round(s['net14'],1)} net30={s['net30'] and round(s['net30'],1)}", flush=True)
    if w == "crash_rally":
        bot = sorted([s for s in sigs if "2026-01-23" <= s["date"] <= "2026-02-12" and s["action"] in ("watch", "buy", "oversold_buy")],
                     key=lambda x: (x["net30"] or -99), reverse=True)
        print(f"bottom 01-23~02-12 watch/buy top15 by net30:", flush=True)
        for s in bot[:15]:
            print(f"    {s['date']} {s['name'][:22]:<24} {s['action']:<7} pct={s['pct']} z={s['z']} th={s['th']} mth={s['mth']} net14={s['net14'] and round(s['net14'],1)} net30={s['net30'] and round(s['net30'],1)}", flush=True)
    acc = sorted({(s["date"], s["name"]) for s in sigs if s["cycle"] == "accumulation"})
    print(f"accumulation-phase item-days: {len(acc)}", flush=True)
    for d, nm in acc[:10]:
        print(f"    {d} {nm}", flush=True)


for w, ws, we in WINDOWS:
    show_window(w, ws, we)

print("\n===== market index =====", flush=True)
mv = dict((r[0], r[1]) for r in conn.execute(
    "SELECT date, value FROM market_index WHERE date BETWEEN '2025-11-02' AND '2026-03-17'"))
for a, b in [("2025-11-02", "2026-01-22"), ("2026-01-23", "2026-03-17"),
             ("2026-01-22", "2026-01-23"), ("2026-02-03", "2026-03-17")]:
    if a in mv and b in mv:
        print(f"  market {a}={mv[a]:.0f} -> {b}={mv[b]:.0f} = {(mv[b]/mv[a]-1)*100:+.1f}%", flush=True)

with open("data/pre123_replay_report.json", "w", encoding="utf-8") as f:
    json.dump({w: {"signals": sig_by_win[w]} for w, _, _ in WINDOWS}, f, ensure_ascii=False, indent=1)
print("saved: data/pre123_replay_report.json", flush=True)
conn.close()
