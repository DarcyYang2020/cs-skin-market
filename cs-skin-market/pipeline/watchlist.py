"""
Batch watchlist scanner (v4).
Migrated to csQAQ Playwright for item search/detail/K-line.
"""

from __future__ import annotations

import sys
import glob
import os
import time
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import config, db, collector, scorer, reporter, valuation, regime, portfolio, item_analysis

TZ_BJ = timezone(timedelta(hours=8))
RETENTION_DAYS = 90


def _now_str() -> str:
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")


def _generate_item_report_md(result) -> str:
    """Generate Markdown summary from ItemAnalysisResult or dict."""
    if hasattr(result, "name"):
        n = result.name; p = result.price_rmb; vd = result.volume_day
        vt = result.volume_total; g = result.value.grade; s = result.value.score
        pos = result.position; cyc = result.cycle; prob = result.probability
        val = result.value; wh = result.whale; th = result.trend_health or {}
        fd = result.fusion_decision or {}
        dq = result.data_quality
    else:
        n = result.get("name",""); p = result.get("price",0); g = result.get("grade","")
        s = result.get("score",0); vd = result.get("volume_day",0); vt = result.get("volume_total",0)
        pos = type("P",(),{"percentile_90d":50,"zscore_90d":0,"tier_label":""})()
        cyc = type("C",(),{"phase_label":"","phase_description":"","phase_strategy":""})()
        prob = type("B",(),{"prob_up_7d":50,"expected_return_7d":0})()
        val = type("V",(),{"score":s,"grade":g,"position_advice":"","recommendation":""})()
        wh = type("W",(),{"level":"natural","level_label":"","probability":0,"trading_rule":""})()
        th = {}; fd = {}; dq = "low"

    ts = th.get("score",50); tr = th.get("raw_score",50)
    td = th.get("direction","flat")
    tdl = {"up":"\u2606\u2606 \u5411\u4e0a","flat":"\u2796 \u8d70\u5e73","down":"\u2606\u2606 \u5411\u4e0b"}.get(td,td)
    deductions = th.get("deduction_sources",[])
    ded_str = " | ".join(deductions) if deductions else "\u65e0"
    
    fa = fd.get("action_label",""); fz = fd.get("zone_label","")
    fd_detail = fd.get("action_detail","")
    anomaly_str = "\u26a0\ufe0f " + str(th.get("anomaly_count",0)) + "\u6b21" if th.get("has_anomaly") else "\u2705 \u65e0"

    report = f"""# {n}

**\u4ef7\u683c**: \u00a5{p:,.2f} | **\u65e5\u6210\u4ea4**: {vd}\u4ef6 | **\u5728\u552e**: {vt}\u4ef6 | **\u6570\u636e\u8d28\u91cf**: {dq}

## \u2606\u2606 \u878d\u5408\u51b3\u7b56
- **{fa}** ({fz})
- {fd_detail}
- \u6263\u5206\u6765\u6e90: {ded_str}

## \u2606\u2606 \u8d8b\u52bf\u5065\u5eb7\u5ea6
- \u4fee\u6b63\u540e: **{ts}/100** {th.get("level_label","")} | \u539f\u59cb: {tr}/100
- \u65b9\u5411: {tdl} (\u7f6e\u4fe1\u5ea6: {th.get("direction_confidence",0):.0%})
- \u6301\u7eed\u6027(24%): {th.get("persistence_score",0)}/100 | \u5747\u7ebf(19%): {th.get("ma_structure","-")} | \u9661\u5ea6(24%): {th.get("steepness_signal","-")}
- \u91cf\u4ef7(18%): {th.get("volume_signal","-")} | \u7f3a\u53e3(13%): {anomaly_str}

## \u2606\u2606 90\u65e5\u4f30\u503c\u5b9a\u4f4d
- 90\u65e5\u767e\u5206\u4f4d: **{pos.percentile_90d:.1f}%** | Z-Score: {pos.zscore_90d:+.2f}
- \u4f30\u503c\u5224\u5b9a: {pos.tier_label}

## \u2606\u2606 \u5468\u671f\u5224\u5b9a
{cyc.phase_label}: {cyc.phase_description}
> \u2606\u2606 {cyc.phase_strategy}

## \u2606\u2606 \u6da8\u8dcc\u6982\u7387
- 7\u65e5\u4e0a\u6da8\u6982\u7387: {prob.prob_up_7d:.0f}% | \u9884\u671f\u6536\u76ca: {prob.expected_return_7d:+.2f}%

## \u2606\u2606 \u5e84\u76d8\u8bc6\u522b
- \u5e84\u76d8\u6982\u7387: {wh.probability:.0f}% | \u7b49\u7ea7: {wh.level_label}
- {wh.trading_rule}

## \u2606\u2606 \u6295\u8d44\u4ef7\u503c
- \u603b\u8bc4\u5206: {val.score:.1f}/10 | \u8bc4\u7ea7: **{val.grade}**
- \u64cd\u4f5c\u5efa\u8bae: {val.position_advice}
- {val.recommendation}
"""
    return report

    """View the latest analysis report for a specific watchlist item."""
    conn = db.get_conn()
    item = db.find_item(conn, name)
    if not item:
        print(f"Item not found: {name}")
        conn.close()
        return

    row = conn.execute(
        "SELECT * FROM snapshots WHERE item_id=? ORDER BY date DESC LIMIT 1",
        (item["id"],)
    ).fetchone()
    conn.close()

    if not row or not row["report_md"]:
        print(f"No analysis report found for: {name}")
        print("  Run 'watchlist scan' or 'analyze' first.")
        return

    print()
    print(f"=== Analysis Report: {name} ===")
    print(f"Date: {row['date']}  |  Grade: {row['grade']}  |  Score: {row['total_score']}")
    print()
    print(row["report_md"])
