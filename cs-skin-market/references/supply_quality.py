# -*- coding: utf-8 -*-
"""在售量数据质量验证（Phase 1b，2026-08-07）。

只读诊断 data/market.db 的 in_sale_count 覆盖/新鲜度/死值，输出 data/supply_quality.json。
发现: 2026-08-03 起每日有在售量单品从 ~92 骤降至 ~25（仅自选品被 web 端刷新），
健康检查按自选品基线(25)判定导致回归未被发现；已同步修复 run_data_health.py 基线
（改为全量可采集品 ~103，90% 阈值），并确认去量引擎(32dbe2b)已把 collect_kline_all 纳入每日任务。

运行:
    python references/supply_quality.py
"""
import io
import json
import sqlite3
import statistics
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "market.db"
OUT = BASE / "data" / "supply_quality.json"

COLLECTABLE = "good_id>0 AND (notes IS NULL OR notes NOT LIKE '%存世量过低%')"


def main():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    today = date.today().isoformat()

    n_items = conn.execute("SELECT COUNT(*) n FROM items").fetchone()["n"]
    n_collect = conn.execute(f"SELECT COUNT(*) n FROM items WHERE {COLLECTABLE}").fetchone()["n"]
    n_watch = conn.execute("SELECT COUNT(*) n FROM items WHERE in_watchlist=1").fetchone()["n"]

    per_item = conn.execute("""
        SELECT item_id, COUNT(*) n,
               SUM(CASE WHEN in_sale_count IS NOT NULL AND in_sale_count>0 THEN 1 ELSE 0 END) sup,
               MAX(date) maxd
        FROM price_history GROUP BY item_id""").fetchall()
    items_sup = [r for r in per_item if r["sup"] > 0]
    total_sup_rows = sum(r["sup"] for r in items_sup)

    def _age(d):
        return (date.fromisoformat(today) - date.fromisoformat(d)).days

    ages = sorted(_age(r["maxd"]) for r in items_sup)
    freshness = {
        "items_with_supply": len(items_sup),
        "rows": total_sup_rows,
        "le1d": sum(1 for a in ages if a <= 1),
        "le3d": sum(1 for a in ages if a <= 3),
        "le7d": sum(1 for a in ages if a <= 7),
        "max_age_days": ages[-1] if ages else None,
    }

    # 死值: 每品 in_sale_count 连续相同最长段
    worst = []
    for r in items_sup:
        vals = [x["in_sale_count"] for x in conn.execute(
            "SELECT in_sale_count FROM price_history WHERE item_id=? AND in_sale_count>0 ORDER BY date",
            (r["item_id"],))]
        run = mx = 1
        for a, b in zip(vals, vals[1:]):
            run = run + 1 if a == b else 1
            mx = max(mx, run)
        worst.append(mx)
    dead_value = {
        "max_run_days": max(worst) if worst else 0,
        "p90_run_days": round(sorted(worst)[int(len(worst) * 0.9) - 1], 1) if worst else 0,
    }

    # 每日有在售量单品数（近 14 天）→ 暴露 08-03 回归
    daily = [dict(r) for r in conn.execute("""
        SELECT date, COUNT(DISTINCT item_id) items, COUNT(*) rows
        FROM price_history
        WHERE in_sale_count IS NOT NULL AND in_sale_count > 0 AND date >= date('now','-14 day')
        GROUP BY date ORDER BY date""")]
    reg = [d for d in daily if d["date"] >= "2026-08-03" and d["items"] < 40]
    value_stats = [r["in_sale_count"] for r in conn.execute(
        "SELECT in_sale_count FROM price_history WHERE in_sale_count IS NOT NULL AND in_sale_count>0")]
    out = {
        "meta": "在售量数据质量验证(Phase 1b): 只读诊断。结论: 数据本身无死值/量级正常; 但 2026-08-03 起日覆盖从~92品骤降至~25品(仅自选品), 健康检查盲区已修复。",
        "generated": today,
        "universe": {"items_total": n_items, "collectable": n_collect, "watchlist": n_watch},
        "freshness": freshness,
        "dead_value": dead_value,
        "in_sale_count_stats": {
            "min": min(value_stats), "median": round(statistics.median(value_stats)),
            "max": max(value_stats), "mean": round(statistics.mean(value_stats)),
        },
        "daily_items_last14d": daily,
        "regression_found": bool(reg),
        "regression_dates": [d["date"] for d in reg],
        "recommendation": "每日 collect_kline_all(去量 P3)已覆盖全量可采集品; 健康检查基线已改为全量口径; 建议今夜采集后复查覆盖恢复。",
    }
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written:", OUT)
    print("freshness:", freshness)
    print("dead_value:", dead_value)
    print("regression dates:", [d["date"] for d in reg])
    conn.close()


if __name__ == "__main__":
    main()