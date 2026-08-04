"""Portfolio-level execution backtest for the market index engine (P0-1/P0-2).

Simulates what actually happens after a buy signal:
  entry at signal close, position = engine position_limit,
  exit on first of {take-profit, stop-loss, max holding days, next buy signal}.

P0-1: capital curve + annualized / max drawdown / sharpe / profit factor /
      win rate / max consecutive losses.
P0-2: exit-rule grid scan (stop loss x take profit x holding days) and pick
      the combination with the highest per-trade expectancy.

Usage:
  python run_portfolio_backtest.py --sl -20 --tp 20 --hold 30   # one combo
  python run_portfolio_backtest.py                               # default + grid scan
"""
import sys, json, argparse
from datetime import datetime as _dt
from pathlib import Path
sys.path.insert(0, ".")
from run_backtest import generate_index_signals
from pipeline import db

START_CAPITAL = 100000.0
DEFAULT_SL = -20.0
DEFAULT_TP = 20.0
DEFAULT_HOLD = 30


def simulate_trades(dates, values, signals, sl_pct, tp_pct, max_hold):
    """Sequential single-asset simulation.

    - Entry: signal close price, position = position_limit fraction of equity.
    - Exit (first hit wins): stop-loss, take-profit (close-based, SL checked
      first), max holding days, or the next buy signal (roll-over re-entry).
    """
    trades = []
    for k, sig in enumerate(signals):
        i = sig["idx"]
        entry_price = values[i]
        limit = sig["position_limit"]
        next_i = signals[k + 1]["idx"] if k + 1 < len(signals) else None
        exit_i = None
        exit_type = "hold"
        for j in range(i + 1, min(i + max_hold + 1, len(values))):
            if next_i is not None and j >= next_i:
                exit_i, exit_type = j, "roll"
                break
            ret_pct = (values[j] / entry_price - 1) * 100
            if ret_pct <= sl_pct:
                exit_i, exit_type = j, "sl"
                break
            if ret_pct >= tp_pct:
                exit_i, exit_type = j, "tp"
                break
        else:
            exit_i = min(i + max_hold, len(values) - 1)
            if exit_i <= i:
                continue  # no forward data at all
            exit_type = "data_end" if i + max_hold >= len(values) else "hold"

        ret_pct = (values[exit_i] / entry_price - 1) * 100
        trades.append({
            "date": sig["date"], "exit_date": dates[exit_i],
            "action": sig["action"], "action_label": sig["action_label"],
            "regime": sig["regime"], "limit": limit,
            "entry_price": round(entry_price, 2), "exit_price": round(values[exit_i], 2),
            "hold_days": exit_i - i, "exit_type": exit_type,
            "trade_ret_pct": round(ret_pct, 2), "contrib_pct": round(limit * ret_pct, 2),
        })
    return trades


def build_equity_curve(dates, values, signals, trades, start_capital=START_CAPITAL):
    """Daily equity from first entry to last exit; marked to market while in a position."""
    if not trades:
        return [], []
    first_i = signals[0]["idx"]
    last_i = max(signals[k]["idx"] + t["hold_days"] for k, t in enumerate(trades))
    exit_at = {signals[k]["idx"] + t["hold_days"]: t for k, t in enumerate(trades)}
    entry_at = {s["idx"]: s for s in signals}
    curve_dates, curve = [], []
    equity = start_capital
    pos = None  # (entry_idx, entry_price, base_equity, limit)
    for day in range(first_i, last_i + 1):
        if day in exit_at:  # close before opening on roll-over days
            t = exit_at[day]
            if pos:
                equity = pos[2] * (1 + t["contrib_pct"] / 100)
            pos = None
        if day in entry_at:
            sig = entry_at[day]
            pos = (day, values[day], equity, sig["position_limit"])
        if pos:
            _, entry_px, base_eq, limit = pos
            equity = base_eq * (1 + limit * (values[day] / entry_px - 1))
        curve_dates.append(dates[day])
        curve.append(round(equity, 2))
    return curve_dates, curve


def compute_metrics(trades, curve_dates, curve, start_capital=START_CAPITAL):
    if not trades:
        return None
    final = curve[-1]
    days = max(1, (_dt.strptime(curve_dates[-1], "%Y-%m-%d") - _dt.strptime(curve_dates[0], "%Y-%m-%d")).days)
    total_return = (final / start_capital - 1) * 100
    annualized = ((final / start_capital) ** (365 / days) - 1) * 100
    peak, max_dd = start_capital, 0.0
    for v in curve:
        peak = max(peak, v)
        max_dd = min(max_dd, (v / peak - 1) * 100)
    rets = [curve[j] / curve[j - 1] - 1 for j in range(1, len(curve))]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var = sum((r - mean_r) ** 2 for r in rets) / len(rets) if rets else 0.0
    sharpe = mean_r / (var ** 0.5) * (365 ** 0.5) if var > 0 else 0.0
    contribs = [t["contrib_pct"] for t in trades]
    limits = [t.get("limit") or 0.0 for t in trades]
    wins = [c for c in contribs if c > 0]
    losses = [c for c in contribs if c <= 0]
    # 资金加权期望：每笔交易按 limit 占仓比重，而非信号等权
    wsum = sum(limits)
    wexpect = (sum(c for c, w in zip(contribs, limits)) / wsum) if wsum > 0 else None
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (float("inf") if wins else 0.0)
    max_consec_loss = cur = 0
    for c in contribs:
        cur = cur + 1 if c <= 0 else 0
        max_consec_loss = max(max_consec_loss, cur)
    return {
        "trades": len(trades),
        "total_return_pct": round(total_return, 2),
        "annualized_pct": round(annualized, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "win_rate_pct": round(len(wins) / len(contribs) * 100, 1),
        "profit_factor": round(pf, 2) if pf != float("inf") else None,
        "expectancy_pct": round(sum(contribs) / len(contribs), 3),
        "wexpectancy_pct": round(wexpect, 3) if wexpect is not None else None,
        "avg_win_pct": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else None,
        "max_consec_loss": max_consec_loss,
        "final_equity": round(final, 2),
    }


def run_combo(dates, values, signals, sl_pct, tp_pct, max_hold):
    trades = simulate_trades(dates, values, signals, sl_pct, tp_pct, max_hold)
    cd, cv = build_equity_curve(dates, values, signals, trades)
    metrics = compute_metrics(trades, cd, cv)
    return trades, cd, cv, metrics


def scan_exit_rules(dates, values, signals):
    """P0-2: grid over stop-loss / take-profit / max holding days."""
    rows = []
    for sl in (-15, -20, -25, -30):
        for tp in (15, 20, 25, 30):
            for hold in (14, 30, 60):
                _, _, _, m = run_combo(dates, values, signals, sl, tp, hold)
                if m is None:
                    continue
                rows.append({"sl": sl, "tp": tp, "hold": hold, **m})
    # 优选目标：资金加权期望（结合占仓），非信号等权期望
    rows.sort(key=lambda r: (r.get("wexpectancy_pct") is not None, r.get("wexpectancy_pct") or 0), reverse=True)
    return rows


def slice_by(dates, values, signals, key):
    """Re-run the default combo per unique value of key (regime / action)."""
    groups = {}
    order = []
    for sig in signals:
        v = sig.get(key, "?")
        if v not in groups:
            groups[v] = []
            order.append(v)
        groups[v].append(sig)
    out = {}
    for v in order:
        _, _, _, m = run_combo(dates, values, groups[v], DEFAULT_SL, DEFAULT_TP, DEFAULT_HOLD)
        out[v] = m
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2025-11-02")
    p.add_argument("--end", default=None)
    p.add_argument("--cluster", type=int, default=3)
    p.add_argument("--sl", type=float, default=DEFAULT_SL)
    p.add_argument("--tp", type=float, default=DEFAULT_TP)
    p.add_argument("--hold", type=int, default=DEFAULT_HOLD)
    p.add_argument("--scan", action="store_true", help="run exit-rule grid scan (P0-2)")
    args = p.parse_args()

    dates, values, signals = generate_index_signals(args.start, args.end, args.cluster)
    print(f"signals: {len(signals)} ({args.start} ~ {dates[-1]})")
    if not signals:
        print("no signals in window, nothing to simulate")
        return

    trades, cd, cv, metrics = run_combo(dates, values, signals, args.sl, args.tp, args.hold)
    print(f"\n== P0-1 default combo: sl={args.sl}% tp={args.tp}% hold={args.hold}d ==")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print("\nper-trade:")
    for t in trades:
        print(f"  {t['date']} -> {t['exit_date']} ({t['exit_type']:8s}) "
              f"limit={t['limit']:.0%} ret={t['trade_ret_pct']:+.2f}% contrib={t['contrib_pct']:+.2f}% [{t['action_label']}]")

    slices = {}
    for key in ("regime", "action"):
        s = slice_by(dates, values, signals, key)
        slices[key] = s
        print(f"\nslice by {key}:")
        for k, m in s.items():
            if m:
                print(f"  {k}: n={m['trades']} win={m['win_rate_pct']}% avg_win={m['avg_win_pct']} "
                      f"avg_loss={m['avg_loss_pct']} expect={m['expectancy_pct']}% total={m['total_return_pct']}%")

    grid = scan_exit_rules(dates, values, signals) if args.scan else []
    if grid:
        print("\n== P0-2 exit-rule grid scan (sorted by expectancy) ==")
        print(f"{'sl':>5} {'tp':>5} {'hold':>5} {'n':>3} {'win%':>6} {'expect':>8} {'avgW':>7} {'avgL':>7} "
              f"{'total%':>8} {'ann%':>7} {'dd%':>7} {'sharpe':>7} {'PF':>6}")
        for r in grid[:20]:
            pf = r["profit_factor"] if r["profit_factor"] is not None else float("inf")
            print(f"{r['sl']:>5} {r['tp']:>5} {r['hold']:>5} {r['trades']:>3} {r['win_rate_pct']:>6.1f} "
                  f"{r['expectancy_pct']:>8.3f} {str(r['avg_win_pct']):>7} {str(r['avg_loss_pct']):>7} "
                  f"{r['total_return_pct']:>8.2f} {r['annualized_pct']:>7.1f} {r['max_drawdown_pct']:>7.2f} "
                  f"{r['sharpe']:>7.2f} {pf:>6.2f}")
        best = grid[0]
        print(f"\nbest combo: sl={best['sl']}% tp={best['tp']}% hold={best['hold']}d "
              f"expectancy={best['expectancy_pct']}%/trade win={best['win_rate_pct']}%")

    out = {
        "args": vars(args),
        "default_combo": {"sl": args.sl, "tp": args.tp, "hold": args.hold, "metrics": metrics},
        "signals": signals,
        "trades": trades,
        "slices": slices,
        "grid_scan": grid,
    }
    with open("data/portfolio_backtest_latest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nsaved: data/portfolio_backtest_latest.json")

    snap_dir = Path("data/backtest_snapshots")
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = snap_dir / ("portfolio_backtest_%s.json" % _dt.now().strftime("%Y%m%d"))
    with open(snap, "w", encoding="utf-8") as f:
        json.dump({"params": vars(args), "default_combo": metrics, "grid_scan": grid[:20]},
                  f, ensure_ascii=False, indent=2)
    print("snapshot:", snap)

    # persist the default combo into backtest_results (item_id NULL = market-level)
    conn = db.get_conn()
    try:
        db.save_backtest(
            conn, "market_portfolio_v1", None, args.start, dates[-1],
            START_CAPITAL, metrics["final_equity"], metrics["total_return_pct"],
            metrics["annualized_pct"], metrics["max_drawdown_pct"], metrics["sharpe"],
            metrics["win_rate_pct"], metrics["trades"],
            round(metrics["trades"] * metrics["win_rate_pct"] / 100),
            json.dumps(out, ensure_ascii=False),
        )
        conn.commit()
        print("saved to backtest_results: market_portfolio_v1")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
