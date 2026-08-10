# -*- coding: utf-8 -*-
"""T1 只读探针：回放近似情绪 vs 真实贪婪映射一致性（P0-1 证据链）。

数据源：macro_history.greedy_index（2026-06-11 起 60 天）+ market_index。
方法：对每个有真实贪婪的日期，对比 greedy_to_sentiment(real) vs approx_sentiment(market_index)。
输出：data/_exp_greedy_vs_approx.json（相关性/平均绝对差/恐慌桶一致性/逐日表）。
"""
import json, statistics, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.market_macro import greedy_to_sentiment
from pipeline.backtest_common import approx_sentiment

conn = __import__("sqlite3").connect(ROOT / "data" / "market.db")
conn.row_factory = __import__("sqlite3").Row

greedy = [(r["date"], float(r["greedy_index"])) for r in conn.execute(
    "SELECT date, greedy_index FROM macro_history WHERE greedy_index IS NOT NULL ORDER BY date")]
idx = [(r["date"], float(r["value"])) for r in conn.execute(
    "SELECT date, value FROM market_index ORDER BY date")]
conn.close()

idx_dates = [d for d, _ in idx]
idx_vals = [v for _, v in idx]
i_by_date = {d: i for i, d in enumerate(idx_dates)}

rows = []
for d, g in greedy:
    i = i_by_date.get(d)
    if i is None or i < 14:
        continue
    real = greedy_to_sentiment(g)
    approx = approx_sentiment(idx_vals, i)
    rows.append({"date": d, "greedy_raw": g, "sent_real": round(real, 1),
                 "sent_approx": round(approx, 1), "diff": round(real - approx, 1)})

if len(rows) < 20:
    print("样本不足:", len(rows)); sys.exit(0)

diffs = [r["diff"] for r in rows]
sr = [r["sent_real"] for r in rows]
sa = [r["sent_approx"] for r in rows]
mean_r, mean_a = statistics.mean(sr), statistics.mean(sa)
var_r, var_a = statistics.pstdev(sr), statistics.pstdev(sa)
cov = sum((a - mean_a) * (b - mean_r) for a, b in zip(sa, sr)) / len(sr)
corr = cov / (var_r * var_a) if var_r * var_a else 0
mad = statistics.mean(abs(x) for x in diffs)

# 恐慌桶一致性（sent>=70 为恐慌口径：panic 族生产触发 sent>=75）
fear_real = {r["date"]: r for r in rows if r["sent_real"] >= 70}
fear_approx = {r["date"] for r in rows if r["sent_approx"] >= 70}
agree = sum(1 for d in fear_real if d in fear_approx)
panic_thresh = 75
pr = {r["date"]: r for r in rows if r["sent_real"] >= panic_thresh}
pa = {d for d in rows if d["sent_approx"] >= panic_thresh}
pagree = sum(1 for d in pr if d in pa)

out = {
    "n": len(rows),
    "date_range": [rows[0]["date"], rows[-1]["date"]],
    "corr": round(corr, 3),
    "mad": round(mad, 1),
    "mean_real": round(mean_r, 1), "mean_approx": round(mean_a, 1),
    "real_std": round(var_r, 1), "approx_std": round(var_a, 1),
    "fear70": {"real": len(fear_real), "approx": len(fear_approx), "overlap": agree},
    "panic75": {"real": len(pr), "approx": len(pa), "overlap": pagree},
    "max_abs_diff": max(abs(x) for x in diffs),
    "rows": rows,
}
json.dump(out, open(ROOT / "data" / "_exp_greedy_vs_approx.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False, indent=1))
