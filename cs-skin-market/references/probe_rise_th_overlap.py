# -*- coding: utf-8 -*-
"""买涨腿 v3 支撑探针（2026-08-16，只读）：TH≥55×正常×pct>40 正期望格（n=226, avg14 +8.56）
与现存族（186 基线）信号的时空重叠——验证「好日子被现存族抢先覆盖」假设。
口径：同 probe_rise_th_cells.py 的候选条件；重叠 = 基线信号同品 ±7 天内。"""
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

from pipeline.backtest_common import build_market_context  # noqa: E402
from pipeline.market_macro import historical_event_impact  # noqa: E402

OUT = ROOT / "data" / "_exp_rise_th_overlap.json"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def main():
    ctx = build_market_context("2023-11-17", end="2026-08-05")
    base = json.load(open(ROOT / "data" / "_exp_cycle_replay_2026.json", encoding="utf-8"))
    by_item = {}
    for s in base["signals"]:
        by_item.setdefault(s["name"], []).append(datetime.strptime(s["date"], "%Y-%m-%d"))

    def covered(name, d):
        ds = by_item.get(name, [])
        return any(abs((d - x).days) <= 7 for x in ds)

    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    c.close()

    cell_all, cell_cov, cell_free = [], [], []
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    for iid in items:
        rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        name = c.execute("SELECT name FROM items WHERE id=?", (iid,)).fetchone()["name"]
        n = len(prices)
        for i in range(60, n):
            if i + 30 >= n:
                continue
            d = dates[i]
            m = ctx.get(d)
            if m is None or m["th"] < 55 or historical_event_impact(d, horizon_days=30):
                continue
            pct = pct90(prices, i)
            if pct <= 40:
                continue
            chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else None
            if chg7 is None or not (3 < chg7 <= 15):
                continue
            s7 = sum(insale[i - 6:i + 1]) / 7 if all(x is not None for x in insale[i - 6:i + 1]) else None
            s30 = sum(insale[i - 29:i + 1]) / 30 if all(x is not None for x in insale[i - 29:i + 1]) else None
            s30_ago = sum(insale[i - 59:i - 29]) / 30 if all(x is not None for x in insale[i - 59:i - 29]) else None
            if s7 is None or s30 is None or s30 <= 0 or s7 > s30 * 0.85:
                continue
            sc30 = (s30 / s30_ago - 1) * 100 if s30_ago else None
            if sc30 is None or sc30 <= 5:
                continue
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            dt = datetime.strptime(d, "%Y-%m-%d")
            rec = {"fwd14": fwd14}
            cell_all.append(rec)
            (cell_cov if covered(name, dt) else cell_free).append(rec)
    c.close()

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None}
        return {"n": n,
                "win14": round(100.0 * sum(1 for r in recs if r["fwd14"] > 0) / n, 1),
                "avg14": round(sum(r["fwd14"] for r in recs) / n, 2)}

    out = {"probe": "TH≥55×正常×pct>40 正期望格 × 现存族覆盖重叠",
           "all": st(cell_all), "covered_7d": st(cell_cov), "free_7d": st(cell_free)}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k, v in out.items():
        if k != "probe":
            print(f"  {k:12s} n={v['n']:4d}  win14={v['win14']}  avg14={v['avg14']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
