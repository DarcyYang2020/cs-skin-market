"""Item-level exit-rule grid scan (P1): fit stop-loss / take-profit / holding days.

Loads data/item_backtest_latest.json (produced by run_item_backtest.py, which now
records entry_price, position_limit, atr_pct and the post-signal price series per
buy signal), then simulates each trade exiting on the first of {stop-loss,
take-profit, max holding days, end of data}. Contribution = position_limit x trade
return, so the fitted rules are comparable with the portfolio backtest (P0-2).

Usage:
  python run_item_exit_backtest.py                     # full grid + summary
  python run_item_exit_backtest.py --sl -15 --tp 25 --hold 14
"""
import sys, json, argparse
from pathlib import Path
from datetime import datetime as _dt
sys.path.insert(0, ".")

SL_GRID = [-8, -10, -12, -15, -20, -25, -30]
TP_GRID = [8, 10, 15, 20, 25, 30, 40]
HOLD_GRID = [7, 10, 14, 21, 30]
DEFAULT_SL = -15.0
DEFAULT_TP = 25.0
DEFAULT_HOLD = 14


def load_signals():
    p = Path("data/item_backtest_latest.json")
    if not p.exists():
        raise SystemExit("run `python run_item_backtest.py --all --warmup 30` first")
    data = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for s in data.get("signals", []):
        if "fwd_series" not in s or not s["fwd_series"]:
            continue
        out.append(s)
    return out


def simulate_one(sig, sl_pct, tp_pct, max_hold):
    """Simulate one trade; returns dict or None when no forward data."""
    entry = sig["entry_price"]
    fwd = sig["fwd_series"]
    if entry <= 0 or not fwd:
        return None
    exit_i, exit_type = len(fwd) - 1, "data_end"
    for j, px in enumerate(fwd):
        if j >= max_hold:
            exit_i, exit_type = j - 1, "hold"
            break
        ret_pct = (px / entry - 1) * 100
        if ret_pct <= sl_pct:
            exit_i, exit_type = j, "sl"
            break
        if ret_pct >= tp_pct:
            exit_i, exit_type = j, "tp"
            break
    if exit_i < 0:
        return None
    exit_price = fwd[exit_i]
    trade_ret = (exit_price / entry - 1) * 100
    limit = sig.get("position_limit", 0.0) or 0.0
    return {
        "date": sig["date"], "name": sig["name"],
        "label": sig.get("action_label", sig.get("action", "")),
        "sentiment": sig.get("sentiment"), "atr_pct": sig.get("atr_pct"),
        "limit": limit, "exit_type": exit_type, "hold_days": exit_i + 1,
        "trade_ret_pct": round(trade_ret, 2),
        "contrib_pct": round(limit * trade_ret, 2),
    }


def aggregate(trades):
    if not trades:
        return None
    contribs = [t["contrib_pct"] for t in trades]
    wins = [c for c in contribs if c > 0]
    losses = [c for c in contribs if c < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(contribs) * 100, 1),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "expectancy_pct": round(sum(contribs) / len(contribs), 3),
        "total_return_pct": round(sum(contribs), 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "exit_types": {k: sum(1 for t in trades if t["exit_type"] == k) for k in ("sl", "tp", "hold", "data_end")},
    }


def run_combo(signals, sl, tp, hold):
    trades = []
    for s in signals:
        t = simulate_one(s, sl, tp, hold)
        if t:
            trades.append(t)
    return trades, aggregate(trades)


def current_rule(sig):
    """Engine's display rule: fear widens stop, greed tightens stop/take."""
    sent = sig.get("sentiment", 50)
    atr = sig.get("atr_pct", 0.03) or 0.03
    if sent >= 75:
        return -30.0, 30.0
    if sent <= 30:
        return -8.0, round(atr * 100 * 1.5, 1)
    return round(-2.5 * atr * 100, 1), round(2.5 * atr * 100, 1)


def scan_grid(signals):
    rows = []
    for sl in SL_GRID:
        for tp in TP_GRID:
            for hold in HOLD_GRID:
                _, m = run_combo(signals, sl, tp, hold)
                if m is None:
                    continue
                rows.append({"sl": sl, "tp": tp, "hold": hold, **m})
    rows.sort(key=lambda r: r["expectancy_pct"], reverse=True)
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sl", type=float, default=DEFAULT_SL)
    p.add_argument("--tp", type=float, default=DEFAULT_TP)
    p.add_argument("--hold", type=int, default=DEFAULT_HOLD)
    p.add_argument("--no-scan", action="store_true")
    args = p.parse_args()

    signals = load_signals()
    print(f"signals with forward data: {len(signals)}")
    if not signals:
        return

    # current engine rule benchmark
    cur_trades = []
    for s in signals:
        sl, tp = current_rule(s)
        t = simulate_one(s, sl, tp, 30)
        if t:
            cur_trades.append(t)
    cur_m = aggregate(cur_trades)
    print("\n== current display rule (sent-adaptive, hold 30) ==")
    print(json.dumps(cur_m, ensure_ascii=False))

    trades, m = run_combo(signals, args.sl, args.tp, args.hold)
    print(f"\n== chosen combo: sl={args.sl}% tp={args.tp}% hold={args.hold}d ==")
    print(json.dumps(m, ensure_ascii=False))

    grid = [] if args.no_scan else scan_grid(signals)
    if grid:
        print("\n== grid scan (top 20 by expectancy) ==")
        print(f"{'sl':>5} {'tp':>5} {'hold':>5} {'n':>3} {'win%':>6} {'expect':>8} {'avgW':>7} {'avgL':>7} "
              f"{'total%':>8} {'PF':>6}  sl/tp/hold counts")
        for r in grid[:20]:
            pf = r["profit_factor"] if r["profit_factor"] is not None else float("inf")
            et = r["exit_types"]
            print(f"{r['sl']:>5} {r['tp']:>5} {r['hold']:>5} {r['trades']:>3} {r['win_rate_pct']:>6.1f} "
                  f"{r['expectancy_pct']:>8.3f} {r['avg_win_pct']:>7.3f} {r['avg_loss_pct']:>7.3f} "
                  f"{r['total_return_pct']:>8.2f} {pf:>6.2f}  sl={et['sl']} tp={et['tp']} hold={et['hold']} end={et['data_end']}")

    # stratification of the chosen combo by label type + sentiment bucket
    print("\n== chosen combo stratified ==")
    buckets = {}
    for s in signals:
        label = "panic" if "\u6050\u614c" in s.get("action_label", "") else "accumulate"
        sent = s.get("sentiment", 50)
        if sent >= 75:
            sb = "fear>=75"
        elif sent <= 30:
            sb = "greed<=30"
        else:
            sb = "neutral"
        buckets.setdefault((label, sb), []).append(s)
    for (label, sb), sigs in sorted(buckets.items()):
        _, bm = run_combo(sigs, args.sl, args.tp, args.hold)
        if bm:
            print(f"  {label:10s} {sb:10s}: n={bm['trades']} win={bm['win_rate_pct']}% "
                  f"expect={bm['expectancy_pct']}% total={bm['total_return_pct']}%")

    out = {
        "args": vars(args),
        "signals": len(signals),
        "current_rule": cur_m,
        "chosen_combo": {"sl": args.sl, "tp": args.tp, "hold": args.hold, "metrics": m},
        "grid_scan": grid,
    }
    with open("data/item_exit_backtest_latest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nsaved: data/item_exit_backtest_latest.json")


if __name__ == "__main__":
    main()
