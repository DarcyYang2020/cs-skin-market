def analyze_cycle_sector_recommendation(cycle_phase: str, accumulation_prob: float = 0.0) -> dict:
    """Data-driven sector scoring: capital flow + bottom verification + trend health.

    Four dimensions (no hardcoded phase weights):
    - Capital Flow: 30d slope (30pts) + 7d change (15pts) = 45pts
    - Bottom Verification: 90d percentile + Z-score (25pts)
    - Trend Health: reuse trend_health module (20pts)
    - Cycle context: mild macro modifier (10pts)

    Risk filters (multiplicative):
    - Distribution phase: x0.6
    - Consolidation phase: x0.85
    - Extreme overbought (pct>90% + Z>2): x0.5
    """

    from statistics import mean, stdev

    try:
        from . import db as _sdb
        conn = _sdb.get_conn()
        raw = _sdb.get_setting(conn, "cached_sub_indices", "[]")
        conn.close()
        import json as _json
        sub_indices = {s["name_key"]: s for s in _json.loads(raw)}
    except Exception:
        sub_indices = {}

    if not sub_indices:
        return {"phase_label": cycle_phase, "sectors": [], "error": "no sub_index data"}
