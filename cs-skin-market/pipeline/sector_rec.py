"""Data-driven sector recommendation engine.

Scores sectors based on:
1. Capital Flow (45%): 30d linear regression slope + 7d change
2. Bottom Verification (25%): 90-day percentile + Z-score
3. Trend Health (20%): reuse trend_health module
4. Cycle Context (10%): mild macro phase modifier

Risk filters: distribution x0.6, consolidation x0.85, extreme overbought x0.5
"""

from statistics import mean, stdev


def recommend(cycle_phase: str, accumulation_prob: float = 0.0) -> dict:
    """Main entry: score all sectors and return ranked recommendations."""

    # Load sub_index data from DB cache
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

    # Fetch K-line for all sub-indices
    sector_kline = {}
    try:
        from . import collector as _col
        for key in sub_indices:
            try:
                kline = _col.fetch_sub_kline(key)
                if kline and len(kline) >= 20:
                    sector_kline[key] = kline
            except Exception:
                pass
    except Exception:
        pass

    # Macro risk multiplier
    macro_mult = 1.0
    macro_label = ""
    if cycle_phase == "distribution":
        macro_mult = 0.6
        macro_label = "出货期折价 x0.6"
    elif cycle_phase == "consolidation":
        macro_mult = 0.85
        macro_label = "洗盘期折价 x0.85"

    recommendations = []

    for key, si in sub_indices.items():
        if key == "init":
            continue

        name = si.get("name", key)
        change_7d = float(si.get("change_7d", 0) or 0)
        kline = sector_kline.get(key, [])

        # Defaults
        pct_90d, z_90d, slope_30d = 50.0, 0.0, 0.0
        flow_30d_score, flow_7d_score = 15, 8
        flow_detail, verify_detail, trend_label = "", "", ""
        verify_score, trend_norm, cycle_context = 0, 10.0, 5

        if kline and len(kline) >= 30:
            values = [v for _, v in kline]
            current = values[-1]
            window = values[-min(90, len(values)):]

            # Percentile + Z-score
            pct_90d = round(sum(1 for v in window if v < current) / len(window) * 100, 1)
            if len(window) >= 5:
                mv = mean(window)
                sv = stdev(window)
                if sv > 0:
                    z_90d = round((current - mv) / sv, 2)

            # --- DIM 1a: 30d slope (0-30) ---
            n30 = min(30, len(values))
            vals30 = values[-n30:]
            nf = len(vals30)
            if nf >= 5:
                xm = (nf - 1) / 2.0
                ym = mean(vals30)
                num = sum((i - xm) * (vals30[i] - ym) for i in range(nf))
                den = sum((i - xm) ** 2 for i in range(nf))
                if den > 0 and ym > 0:
                    slope_30d = round((num / den) / ym * 100 * 30, 2)

            if slope_30d > 5:
                flow_30d_score = 30
                flow_detail = f"持续强势流入({slope_30d:.1f}%/30d)"
            elif slope_30d > 2:
                flow_30d_score = 25
                flow_detail = f"持续温和流入({slope_30d:.1f}%/30d)"
            elif slope_30d > 0.5:
                flow_30d_score = 20
                flow_detail = f"缓慢流入({slope_30d:.1f}%/30d)"
            elif slope_30d > -0.5:
                flow_30d_score = 15
                flow_detail = f"资金横盘({slope_30d:.1f}%/30d)"
            elif slope_30d > -2:
                flow_30d_score = 10
                flow_detail = f"缓慢流出({slope_30d:.1f}%/30d)"
            elif slope_30d > -5:
                flow_30d_score = 5
                flow_detail = f"持续流出({slope_30d:.1f}%/30d)"
            else:
                flow_30d_score = 2
                flow_detail = f"强势流出({slope_30d:.1f}%/30d)"

            # --- DIM 1b: 7d change (0-15) ---
            recent7 = values[-7:] if len(values) >= 7 else values
            c7k = (recent7[-1] - recent7[0]) / max(recent7[0], 1) * 100 if recent7[0] > 0 else 0
            c7 = (change_7d + c7k) / 2 if change_7d != 0 else c7k
            if c7 > 3: flow_7d_score = 15
            elif c7 > 1.5: flow_7d_score = 12
            elif c7 > 0.5: flow_7d_score = 10
            elif c7 > -0.5: flow_7d_score = 8
            elif c7 > -1.5: flow_7d_score = 5
            elif c7 > -3: flow_7d_score = 3
            else: flow_7d_score = 1

            # --- DIM 2: Bottom Verification (0-25) ---
            if pct_90d <= 10 and z_90d <= -1.5:
                verify_score = 25
                verify_detail = f"深度低估({pct_90d}% Z{z_90d})"
            elif pct_90d <= 20 and z_90d <= -0.5:
                verify_score = 20
                verify_detail = f"低估区({pct_90d}% Z{z_90d})"
            elif pct_90d <= 30:
                verify_score = 15
                verify_detail = f"偏低({pct_90d}%)"
            elif pct_90d <= 50:
                verify_score = 10
                verify_detail = f"中位({pct_90d}%)"
            elif pct_90d >= 90 and z_90d >= 2.0:
                verify_score = 0
                verify_detail = f"极度泡沫({pct_90d}% Z{z_90d})"
            elif pct_90d >= 70:
                verify_score = 3
                verify_detail = f"偏高({pct_90d}%)"
            else:
                verify_score = 8
                verify_detail = f"中位偏高({pct_90d}%)"

            # --- DIM 3: Trend Health (0-20) ---
            try:
                from .trend_health import compute_trend_health
                th = compute_trend_health(values[-90:], None)
                th_score_val = th.score if th else 50
                if th_score_val >= 60:
                    trend_label = "趋势向上"
                elif th_score_val >= 40:
                    trend_label = "趋势震荡"
                else:
                    trend_label = "趋势向下"
            except Exception:
                th_score_val = 50
            trend_norm = round(th_score_val / 100 * 20, 1)

            # --- DIM 4: Cycle Context (0-10) ---
            if cycle_phase == "accumulation":
                if pct_90d <= 30 and flow_30d_score >= 20:
                    cycle_context = 10
                elif pct_90d <= 50:
                    cycle_context = 7
                else:
                    cycle_context = 4
            elif cycle_phase == "markup":
                if flow_30d_score >= 20 and pct_90d <= 60:
                    cycle_context = 8
                else:
                    cycle_context = 5
            elif cycle_phase == "distribution":
                cycle_context = 2

        # --- Risk multipliers ---
        risk_mult = macro_mult
        risk_labels = []
        if macro_label:
            risk_labels.append(macro_label)
        if pct_90d >= 90 and z_90d >= 2.0:
            risk_mult *= 0.5
            risk_labels.append("极度泡沫 x0.5")

        raw_total = flow_30d_score + flow_7d_score + verify_score + trend_norm + cycle_context
        final_score = round(raw_total * risk_mult, 1)

        # --- Opportunity classification ---
        if flow_30d_score >= 20 and pct_90d <= 30:
            opp_type, opp_label = "底部吸筹", "钱进场+低价=最佳窗口"
        elif flow_30d_score >= 20 and pct_90d <= 70 and trend_label == "趋势向上":
            opp_type, opp_label = "第二波行情", "资金持续涌入+趋势确认"
        elif flow_30d_score >= 20 and pct_90d >= 70:
            opp_type, opp_label = "高位追涨", "有钱但贵，谨慎参与"
        elif flow_30d_score < 15 and pct_90d <= 30:
            opp_type, opp_label = "无人问津", "便宜但无资金，等待信号"
        elif flow_30d_score < 15 and pct_90d >= 70:
            opp_type, opp_label = "资金出逃", "贵+跑钱，回避"
        else:
            opp_type, opp_label = "震荡观望", "方向不明，等待突破"

        recommendations.append({
            "key": key, "name": name, "score": final_score,
            "opp_type": opp_type, "opp_label": opp_label,
            "flow_30d_score": flow_30d_score, "flow_7d_score": flow_7d_score,
            "flow_detail": flow_detail, "verify_score": verify_score,
            "verify_detail": verify_detail, "trend_score": round(trend_norm, 1),
            "trend_label": trend_label, "cycle_context": cycle_context,
            "change_7d": round(change_7d, 2), "slope_30d": round(slope_30d, 2),
            "pct_90d": pct_90d, "z_90d": z_90d, "risk_labels": risk_labels,
        })

    recommendations.sort(key=lambda x: x["score"], reverse=True)

    for r in recommendations:
        if r["score"] >= 70:
            r["tier"], r["tier_label"] = "core", "核心配置"
        elif r["score"] >= 45:
            r["tier"], r["tier_label"] = "secondary", "次级关注"
        elif r["score"] >= 25:
            r["tier"], r["tier_label"] = "watch", "观望"
        else:
            r["tier"], r["tier_label"] = "avoid", "回避"

    phase_labels = {
        "accumulation": ("吸筹期", "资金流向+触底验证+趋势健康 三维驱动"),
        "consolidation": ("洗盘期", "关注持续流入+低估板块，等待方向确认"),
        "markup": ("拉升期", "跟随资金主线，谨慎追高"),
        "distribution": ("出货期", "全局折价x0.6，减仓为主"),
    }
    pl = phase_labels.get(cycle_phase, ("未知", ""))

    return {
        "cycle_phase": cycle_phase,
        "phase_label": pl[0],
        "phase_advice": pl[1],
        "accumulation_prob": round(accumulation_prob, 1),
        "macro_mult": macro_mult,
        "macro_label": macro_label,
        "sectors": recommendations,
        "core_sectors": [r for r in recommendations if r["tier"] == "core"],
        "secondary_sectors": [r for r in recommendations if r["tier"] == "secondary"],
        "avoid_sectors": [r for r in recommendations if r["tier"] == "avoid"],
    }
