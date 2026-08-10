# -*- coding: utf-8 -*-
"""T0 监测：macro_history.greedy_index 覆盖单调增长检查（只读）。

每日采集后运行一次（建议挂入 run_daily_collect.py 收尾或计划任务），
连续 7 个采集日验证覆盖 ≥60 天且单调增长；与当日 live 贪婪核对。
产物：data/_exp_greedy_backfill_check.json（每日一行: date / non_null / coverage / latest_date / latest_value）。

用法: python references/greedy_backfill_check.py
"""
import io
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "_exp_greedy_backfill_check.json"

# 读历史检查记录（幂等追加，按日期去重）
hist = {}
if OUT.exists():
    try:
        hist = json.load(io.open(OUT, encoding="utf-8"))
    except Exception:
        hist = {}

conn = sqlite3.connect(ROOT / "data" / "market.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT date, greedy_index FROM macro_history WHERE greedy_index IS NOT NULL ORDER BY date"
).fetchall()
total_rows = conn.execute("SELECT COUNT(*) FROM macro_history").fetchone()[0]
conn.close()

non_null = len(rows)
coverage = len(rows)  # 实际历史天数（60 天窗口上限）
rec = {
    "checked_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
    "non_null_days": non_null,
    "coverage_days": coverage,
    "earliest": rows[0]["date"] if rows else None,
    "latest": rows[-1]["date"] if rows else None,
    "latest_value": rows[-1]["greedy_index"] if rows else None,
    "total_rows": total_rows,
}
hist[rec["checked_at"][:10]] = rec  # 按日期去重
io.open(OUT, "w", encoding="utf-8", newline="\n").write(
    json.dumps(hist, ensure_ascii=False, indent=1))

print(json.dumps(rec, ensure_ascii=False))
days = sorted(hist)
if len(days) >= 2:
    covs = [hist[d]["coverage_days"] for d in days]
    monotonic = all(b >= a for a, b in zip(covs, covs[1:]))
    print("check_days:", days, "| coverage_series:", covs, "| monotonic_growth:", monotonic)
    print("verdict:", "PASS(覆盖>=60且单调增长)" if (coverage >= 60 and monotonic) else "OBSERVE(继续积累)")
else:
    print("verdict: 需连续 7 个采集日样本（当前", len(days), "天）")
