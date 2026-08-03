"""Shared helpers for offline backtests (market + item) - one consistent 口径.

- approx_sentiment(): price-action proxy used when real greedy history is missing.
- real_greedy_sentiment(): persisted greedy index (macro_history) if collected.
- patch_sentiment(): make sentiment deterministic during replay (item + index engines).
- build_market_context(): date -> {pct, z, cycle, th, sentiment} for item backtest.
"""
import sys
sys.path.insert(0, ".")


def approx_sentiment(values, idx):
    """Approximate sentiment from price action: big drops = fear (high score)."""
    if idx < 14:
        return 50
    chg7 = (values[idx] / values[idx - 7] - 1) * 100 if idx >= 7 else 0
    chg14 = (values[idx] / values[idx - 14] - 1) * 100 if idx >= 14 else 0
    return max(10, min(90, 50 - chg7 * 2 - chg14))


def sentiment_factor_from_score(s):
    if s >= 85:
        return 0.6
    if s >= 70:
        return 0.3
    if s >= 50:
        return 0.0
    if s >= 30:
        return -0.3
    return -0.6


def patch_sentiment(value):
    """Make item + index engines use a fixed sentiment during replay (offline deterministic)."""
    import pipeline.market_macro as mm
    import pipeline.item_analysis as ia
    ia.compute_sentiment_score = lambda: value
    ia.compute_sentiment_factor = lambda: sentiment_factor_from_score(value)
    mm.compute_sentiment_score = lambda: value


def real_greedy_sentiment(start=None):
    """{date: sentiment_score} from persisted greedy index; empty until daily collection."""
    try:
        from pipeline.market_macro import get_greedy_history, greedy_to_sentiment
        hist = get_greedy_history(start=start)
        return {d: greedy_to_sentiment(v) for d, v in hist}
    except Exception:
        return {}


def build_market_context(start="2025-11-02", end=None):
    """date -> dict(pct, z, cycle, th, sentiment).

    Prefers persisted real greedy index; falls back to price approximation so
    the replay stays fully offline and deterministic.
    """
    from pipeline import db
    from pipeline.index_analysis import analyze_index
    from pipeline.market_th import compute_market_trend_health, derive_market_cycle

    real_sent = real_greedy_sentiment()
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT date, value FROM market_index ORDER BY date"
    ).fetchall()
    conn.close()
    dates = [r["date"] for r in rows]
    values = [r["value"] for r in rows]
    ctx = {}
    for i in range(90, len(values)):
        d = dates[i]
        if d < start:
            continue
        if end and d > end:
            break
        window = values[i - 90:i + 1]
        result = analyze_index([(dates[j], values[j]) for j in range(i - 90, i + 1)])
        if not result.get("has_data"):
            continue
        pos = result["position"]
        pct = pos.get("percentile_90d", 50)
        z = pos.get("zscore_90d", 0)
        mth = compute_market_trend_health(window, volumes=None)
        th = mth.corrected_score if hasattr(mth, "corrected_score") else mth.score
        # Live-identical cycle label (fix: analyze_cycle_probability returns probs, no phase)
        phase = derive_market_cycle(values, i)
        sent = real_sent.get(d, approx_sentiment(values, i))
        chg30 = (values[i] / values[i - 30] - 1) * 100 if i >= 30 and values[i - 30] > 0 else 0.0
        drop21 = (values[i] / values[i - 21] - 1) * 100 if i >= 21 and values[i - 21] > 0 else 0.0
        ctx[d] = {"pct": pct, "z": z, "cycle": phase, "th": th, "sentiment": sent, "chg30": chg30, "drop21": drop21}
    return ctx
