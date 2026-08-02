"""Market index backtest runner using low-level engine functions.
Usage: python run_backtest.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
"""
import sys, json, argparse
sys.path.insert(0, ".")
from pipeline import db
from pipeline.index_analysis import (
    analyze_index, compute_micro_th, analyze_cycle_probability,
    compute_selling_pressure_exhaustion
)
from pipeline.market_th import (
    compute_market_trend_health, compute_market_fusion_decision,
    compute_market_regime
)
from pipeline.backtest_common import approx_sentiment, patch_sentiment, real_greedy_sentiment


def generate_index_signals(start_date="2025-11-02", end_date=None, cluster_days=3):
    """Replay the market fusion engine day by day.

    Returns (dates, values, signals). Every buy/oversold_buy signal carries the
    engine position limit (global_position_limit) and the market regime at that
    date so portfolio-level execution backtests can size positions from it.
    """
    from datetime import datetime as _dt, timedelta as _td
    warmup_start = (_dt.strptime(start_date, "%Y-%m-%d") - _td(days=120)).strftime("%Y-%m-%d")
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT date, value FROM market_index WHERE date >= ? ORDER BY date",
        (warmup_start,)
    ).fetchall()
    conn.close()

    dates = [r["date"] for r in rows]
    raw_values = [r["value"] for r in rows]

    real_sent = real_greedy_sentiment()  # real greedy history if collected, else {}
    signals = []
    for i in range(90, len(raw_values)):
        current_date = dates[i]
        if current_date < start_date:
            continue
        if end_date and current_date > end_date:
            break

        window = [(dates[j], raw_values[j]) for j in range(i - 90, i + 1)]
        vals_only = [raw_values[j] for j in range(i - 90, i + 1)]
        current_value = raw_values[i]

        result = analyze_index(window)
        if not result.get("has_data"):
            continue

        pos = result["position"]
        pct = pos.get("percentile_90d", 50)
        zscore = pos.get("zscore_90d", 0)

        mth = compute_market_trend_health(vals_only, volumes=None)
        if not hasattr(mth, "z_floor_applied"):
            mth.z_floor_applied = False
        micro_th = compute_micro_th(vals_only)

        # Compute is_bear directly (matches live engine with persistence fix)
        is_bear = False
        if len(vals_only) >= 90:
            ma30 = sum(vals_only[-30:]) / 30
            ma90 = sum(vals_only[-90:]) / 90
            is_bear = ma30 < ma90 and vals_only[-1] < ma90

        cycle = analyze_cycle_probability(vals_only, pct, zscore)
        cycle_phase = cycle.get("phase", "unknown") if isinstance(cycle, dict) else "unknown"

        # cap_triggered
        cap_triggered = False
        if len(vals_only) >= 30 and micro_th >= 50:
            max30 = max(vals_only[-30:])
            drop30 = (vals_only[-1] - max30) / max30 * 100
            if len(vals_only) >= 14:
                near_low = vals_only[-1] <= min(vals_only[-14:]) * 1.05
                at_low = vals_only[-1] <= min(vals_only[-14:]) * 1.02
            else:
                near_low = at_low = False
            cap_triggered = (drop30 < -20 and near_low) or (drop30 < -25 and at_low)

        # Rally decay (matches live engine)
        rally_decay = False
        if is_bear and micro_th >= 60 and len(vals_only) >= 21:
            p21 = vals_only[-21:]
            low21 = min(p21)
            bounce = (p21[-1] - low21) / low21 * 100
            if bounce >= 5:
                peak_prev = max(p21[:-7]) if len(p21) >= 14 else max(p21[:-3])
                peak_recent = max(p21[-7:])
                failed_new_high = peak_recent < peak_prev * 0.995
                d_gains = [p21[j] - p21[j-1] for j in range(-6, 0)]
                gains_abs = [abs(g) for g in d_gains if g > 0]
                narrowing = False
                if len(gains_abs) >= 3:
                    narrowing = gains_abs[-1] < gains_abs[0] * 0.5 and gains_abs[-1] < gains_abs[-2]
                rally_decay = failed_new_high or narrowing

        sp = compute_selling_pressure_exhaustion(vals_only)
        sp_score = sp["score"] if isinstance(sp, dict) else 50

        sent = real_sent.get(current_date, approx_sentiment(raw_values, i))
        patch_sentiment(sent)  # deterministic: cycle/other modules use the same historical sentiment

        regime = compute_market_regime(vals_only)[0]

        fd = compute_market_fusion_decision(
            percentile_90d=pct, th=mth,
            zscore_90d=zscore, cycle_phase=cycle_phase,
            micro_th_score=micro_th, is_bear=is_bear,
            rally_decay=rally_decay, sentiment_score=sent,
            cap_triggered=cap_triggered,
            selling_pressure_score=sp_score,
            market_regime=regime,
            prices=vals_only,
        )

        if fd.action not in ("buy", "oversold_buy"):
            continue

        th_score = mth.corrected_score if hasattr(mth, "corrected_score") else mth.score
        if signals and (_dt.strptime(current_date, "%Y-%m-%d") - _dt.strptime(signals[-1]["date"], "%Y-%m-%d")).days < cluster_days:
            continue  # cluster: same 7-day window counts once

        fwd14 = (raw_values[i+14] / current_value - 1) * 100 if i+14 < len(raw_values) else None
        fwd30 = (raw_values[i+30] / current_value - 1) * 100 if i+30 < len(raw_values) else None
        dd = 0
        for j in range(i+1, min(i+15, len(raw_values))):
            dd = min(dd, (raw_values[j] / current_value - 1) * 100)

        signals.append({
            "date": current_date, "idx": i, "pct": round(pct, 1), "zscore": round(zscore, 2),
            "th": round(th_score, 1), "sentiment": round(sent, 1),
            "action": fd.action, "action_label": fd.action_label,
            "position_limit": fd.global_position_limit, "regime": regime,
            "fwd14": round(fwd14, 2) if fwd14 is not None else None,
            "fwd30": round(fwd30, 2) if fwd30 is not None else None,
            "max_dd": round(dd, 2),
        })

    return dates, raw_values, signals


def run(start_date="2025-11-02", end_date=None, cluster_days=3):
    _, _, signals = generate_index_signals(start_date, end_date, cluster_days)
    return signals


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2025-11-02")
    p.add_argument("--warmup", type=int, default=90)
    p.add_argument("--end", default=None)
    p.add_argument("--cluster", type=int, default=3, help="merge signals within N days into one")
    args = p.parse_args()

    signals = run(args.start, args.end, cluster_days=args.cluster)
    print(f"\nSignals: {len(signals)}")
    for s in signals:
        print(f"  {s['date']}: {s['action_label']} | pct={s['pct']:.0f}% z={s['zscore']:.2f} th={s['th']:.0f} "
              f"limit={s['position_limit']:.0%} regime={s['regime']} | fwd14={s['fwd14']}% fwd30={s['fwd30']}%")

    if signals:
        f14 = [s["fwd14"] for s in signals if s["fwd14"] is not None]
        f30 = [s["fwd30"] for s in signals if s["fwd30"] is not None]
        w14 = sum(1 for v in f14 if v > 0)
        w30 = sum(1 for v in f30 if v > 0)
        print(f"\n14d win: {w14}/{len(f14)}={w14/len(f14)*100:.0f}% avg={sum(f14)/len(f14):.1f}%")
        print(f"30d win: {w30}/{len(f30)}={w30/len(f30)*100:.0f}% avg={sum(f30)/len(f30):.1f}%")
