"""Single-item engine backtest runner (offline, data-driven).

Usage:
  python run_item_backtest.py --items "AK-47 | 抽象派 1337 (崭新出厂)" --warmup 60
  python run_item_backtest.py --warmup 30 --start 2026-05-20   # key-point analysis
  python run_item_backtest.py --all

Notes:
- price_history starts 2026-04-21 for most items -> ~102 days available.
- sentiment is NOT fetched live; it is approximated from market index
  price action (same approach as run_backtest.py) so the replay is offline.
- volumes/supply/order_book are missing in history -> neutral defaults used;
  the reported data_quality per signal reflects that.
"""
import sys, json, argparse
from pathlib import Path
from datetime import datetime
sys.path.insert(0, ".")
from pipeline import db
import pipeline.item_analysis as ia
from pipeline.backtest_common import approx_sentiment, patch_sentiment, build_market_context


def load_item_series(item_id):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT p.date, p.price_rmb, p.volume_day, p.in_sale_count
           FROM price_history p
           WHERE p.item_id = ? AND p.id IN (
               SELECT MAX(id) FROM price_history WHERE item_id = ? GROUP BY date
           ) ORDER BY p.date""",
        (item_id, item_id),
    ).fetchall()
    conn.close()
    dates = [r["date"] for r in rows]
    prices = [r["price_rmb"] for r in rows]
    in_sale = [r["in_sale_count"] or 0 for r in rows]
    return dates, prices, in_sale


# 庄盘异常品：无真实流通（日均成交≈0.2件、价格2.9~4.4万），价格被操纵，不参与回测
EXCLUDED_ITEMS = {"AK-47 | 水栽竹 (崭新出厂)"}


def load_items(conn=None):
    conn = db.get_conn()
    rows = conn.execute("SELECT id, name FROM items ORDER BY id").fetchall()
    conn.close()
    return {r["id"]: r["name"] for r in rows if r["name"] not in EXCLUDED_ITEMS}


def backtest_item(item_id, name, start, end, warmup, market_ctx, cost=0.02):
    dates, prices, in_sale = load_item_series(item_id)
    if len(prices) < warmup + 1:
        return {"item_id": item_id, "name": name, "days": len(dates),
                "signals": [], "error": "not enough history"}
    n = len(prices)
    signals = []
    recent_buys = []
    for i in range(warmup, n):
        d = dates[i]
        if end and d > end:
            break
        if d < start:
            continue
        if d not in market_ctx:
            continue
        mc = market_ctx[d]
        patch_sentiment(mc["sentiment"])
        prefix = prices[:i + 1]
        try:
            res = ia.run_item_analysis(
                name=name,
                prices=prefix,
                volumes=[0] * len(prefix),
                supply_hist=in_sale[:i + 1],
                market_history=None,
                market_pct_90d=mc["pct"],
                market_cycle=mc["cycle"],
                market_zscore=mc["z"],
                market_th_score=mc["th"],
                market_30d_change=mc.get("chg30", 0),
                market_drop21=mc.get("drop21", 0),
                recent_buy_dates=recent_buys,
                signal_date=d,
            )
        except Exception as exc:
            signals.append({"date": d, "error": str(exc)})
            continue
        fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
        action = fd.get("action", "")
        if action not in ("buy", "oversold_buy"):
            continue
        recent_buys.append(d)
        fwd14 = (prices[i + 14] / prices[i] - 1) * 100 if i + 14 < n else None
        fwd30 = (prices[i + 30] / prices[i] - 1) * 100 if i + 30 < n else None
        # Net returns after round-trip cost (--cost, default 2% = UU 1% fee x2 + slippage)
        net14 = (fwd14 - cost * 100) if fwd14 is not None else None
        net30 = (fwd30 - cost * 100) if fwd30 is not None else None
        dd = 0.0
        for j in range(i + 1, min(i + 15, n)):
            dd = min(dd, (prices[j] / prices[i] - 1) * 100)
        th = res.trend_health or {}
        # ATR% at signal date (same formula as item_analysis price zones)
        rets = [(prices[j] - prices[j - 1]) / prices[j - 1]
                for j in range(max(1, i - 13), i + 1) if prices[j - 1] > 0]
        atr_pct = (sum(abs(r) for r in rets) / len(rets)) if rets else 0.03
        atr_pct = max(0.01, min(0.10, atr_pct))
        # Forward series for exit-rule grid (entry close -> up to 60d after)
        fwd_series = [round(prices[j], 2) for j in range(i + 1, min(i + 61, n))]
        signals.append({
            "name": name,
            "date": d,
            "entry_price": round(prices[i], 2),
            "action": action,
            "action_label": fd.get("action_label", action),
            "position_limit": fd.get("position_limit", 0.0),
            "pct": getattr(res.position, "percentile_90d", None),
            "z": getattr(res.position, "zscore_90d", None),
            "th": th.get("score"),
            "cycle": getattr(res.cycle, "phase", "unknown"),
            "value": getattr(res.value, "score", None),
            "risk": res.risk_level,
            "data_quality": res.data_quality,
            "market_th": mc["th"],
            "market_cycle": mc["cycle"],
            "sentiment": round(mc["sentiment"], 1),
            "fwd14": round(fwd14, 2) if fwd14 is not None else None,
            "fwd30": round(fwd30, 2) if fwd30 is not None else None,
            "net14": round(net14, 2) if net14 is not None else None,
            "net30": round(net30, 2) if net30 is not None else None,
            "fwd14": round(fwd14, 2) if fwd14 is not None else None,
            "fwd30": round(fwd30, 2) if fwd30 is not None else None,
            "max_dd": round(dd, 2),
            "fwd_series": fwd_series,
        })
    return {"item_id": item_id, "name": name, "days": len(dates),
            "first_signal_date": dates[warmup], "signals": signals}


def summarize(results):
    total = [s for r in results if "signals" in r for s in r["signals"] if "fwd14" in s]
    rows = []
    for r in results:
        sigs = [s for s in r.get("signals", []) if "fwd14" in s]
        f14 = [s.get("net14", s["fwd14"]) for s in sigs if s.get("net14", s["fwd14"]) is not None]
        f30 = [s.get("net30", s["fwd30"]) for s in sigs if s.get("net30", s["fwd30"]) is not None]
        row = {
            "name": r["name"], "days": r.get("days", 0), "signals": len(sigs),
            "win14": sum(1 for v in f14 if v > 0), "f14": len(f14),
            "avg14": round(sum(f14) / len(f14), 2) if f14 else None,
            "win30": sum(1 for v in f30 if v > 0), "f30": len(f30),
            "avg30": round(sum(f30) / len(f30), 2) if f30 else None,
        }
        rows.append(row)
    agg = None
    if total:
        f14 = [s.get("net14", s["fwd14"]) for s in total if s.get("net14", s["fwd14"]) is not None]
        f30 = [s.get("net30", s["fwd30"]) for s in total if s.get("net30", s["fwd30"]) is not None]
        agg = {
            "signals": len(total),
            "win14": sum(1 for v in f14 if v > 0), "n14": len(f14),
            "win14_pct": round(sum(1 for v in f14 if v > 0) / len(f14) * 100, 1) if f14 else None,
            "avg14": round(sum(f14) / len(f14), 2) if f14 else None,
            "win30": sum(1 for v in f30 if v > 0), "n30": len(f30),
            "win30_pct": round(sum(1 for v in f30 if v > 0) / len(f30) * 100, 1) if f30 else None,
            "avg30": round(sum(f30) / len(f30), 2) if f30 else None,
        }
    return rows, agg


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--items", default="", help="semicolon-separated item names; empty = all")
    p.add_argument("--all", action="store_true", help="backtest every item with history")
    p.add_argument("--start", default="2025-11-02")
    p.add_argument("--end", default=None)
    p.add_argument("--warmup", type=int, default=60, help="min days of item history before signals")
    p.add_argument("--stratify", action="store_true", help="print win-rate stratification by pct/z/th/sentiment/mth")
    p.add_argument("--cost", type=float, default=0.02, help="round-trip cost (fee+slippage), default 0.02")
    args = p.parse_args()

    patch_sentiment(50.0)
    market_ctx = build_market_context(args.start)
    print(f"market context dates: {len(market_ctx)} ({args.start} ~ {max(market_ctx) if market_ctx else '-'})")

    items = load_items()
    if args.all or not args.items:
        selected = items
    else:
        names = [x.strip() for x in args.items.split(";") if x.strip()]
        selected = {i: n for i, n in items.items() if n in names}

    results = []
    for iid, iname in selected.items():
        r = backtest_item(iid, iname, args.start, args.end, args.warmup, market_ctx, args.cost)
        results.append(r)
        sigs = [s for s in r.get("signals", []) if "fwd14" in s]
        print(f"\n== {iname} (days={r.get('days')}, signals={len(sigs)}) ==")
        for s in sigs:
            print(f"  {s['date']}: {s['action_label']} | pct={s['pct']:.0f}% z={s['z']:.2f} th={s['th']} "
                  f"val={s['value']} q={s['data_quality']} | fwd14={s['fwd14']}% fwd30={s['fwd30']}% dd={s['max_dd']}%")
        for s in r.get("signals", []):
            if "error" in s:
                print(f"  {s['date']}: ERROR {s['error']}")

    rows, agg = summarize(results)
    print("\n=== per-item summary ===")
    for row in rows:
        print(f"  {row['name'][:40]:42s} days={row['days']:4d} sig={row['signals']:3d} "
              f"14d win {row['win14']}/{row['f14']} avg={row['avg14']}  30d win {row['win30']}/{row['f30']} avg={row['avg30']}")
    print("\n=== aggregate ===")
    print(json.dumps(agg, ensure_ascii=False) if agg else "no signals")

    if args.stratify:
        all_sigs = [s for r in results for s in r.get("signals", []) if "fwd14" in s]
        def _bucket(rows, lo, hi, key, label):
            rows = [s for s in rows if lo <= (s.get(key) if s.get(key) is not None else -99) < hi]
            f14 = [s.get("net14", s["fwd14"]) for s in rows if s.get("fwd14") is not None]
            f30 = [s.get("net30", s["fwd30"]) for s in rows if s.get("fwd30") is not None]
            p14 = (f"14d {sum(1 for v in f14 if v>0)}/{len(f14)}={sum(1 for v in f14 if v>0)/len(f14)*100:.0f}% avg={sum(f14)/len(f14):+.1f}%"
                   if f14 else "14d n/a")
            p30 = (f"30d {sum(1 for v in f30 if v>0)}/{len(f30)}={sum(1 for v in f30 if v>0)/len(f30)*100:.0f}% avg={sum(f30)/len(f30):+.1f}%"
                   if f30 else "30d n/a")
            print(f"  {label}: n={len(rows)} | {p14} | {p30}")
        print("\n=== stratification (win rate) ===")
        for lo, hi in [(0,15),(15,25),(25,40),(40,100)]:
            _bucket(all_sigs, lo, hi, "pct", f"pct {lo}-{hi}")
        for lo, hi in [(-99,-2),(-2,-1.2),(-1.2,-0.5),(-0.5,99)]:
            _bucket(all_sigs, lo, hi, "z", f"z {lo}-{hi}")
        for lo, hi in [(0,40),(40,50),(50,60),(60,100)]:
            _bucket(all_sigs, lo, hi, "th", f"th {lo}-{hi}")
        for lo, hi in [(0,30),(30,50),(50,70),(70,101)]:
            _bucket(all_sigs, lo, hi, "sentiment", f"sent {lo}-{hi}")
        for lo, hi in [(0,45),(45,55),(55,100)]:
            _bucket(all_sigs, lo, hi, "market_th", f"mth {lo}-{hi}")
        deep = [s for s in all_sigs if (s.get("pct") if s.get("pct") is not None else 99) <= 25 and (s.get("th") if s.get("th") is not None else 0) >= 40]
        _bucket(deep, -99, 99, "pct", "deep+pct<=25&th>=40")

    sigs_out = [s for r in results for s in r.get("signals", []) if "fwd14" in s]
    with open("data/item_backtest_latest.json", "w", encoding="utf-8") as f:
        json.dump({"args": vars(args), "aggregate": agg, "per_item": rows, "signals": sigs_out},
                  f, ensure_ascii=False, indent=2)
    print("\nsaved: data/item_backtest_latest.json")

    # dated snapshot for factor-decay monitor (factor_monitor.py)
    snap_dir = Path("data/backtest_snapshots")
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_name = "item_backtest_%s.json" % datetime.now().strftime("%Y%m%d")
    with open(snap_dir / snap_name, "w", encoding="utf-8") as f:
        json.dump({"params": vars(args), "aggregate": agg, "signals": sigs_out},
                  f, ensure_ascii=False, indent=2)
    print("snapshot:", snap_dir / snap_name)
