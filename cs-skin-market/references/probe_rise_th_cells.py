# -*- coding: utf-8 -*-
"""买涨腿 v3 结构定位探针（2026-08-16，只读）。

交叉：吸筹型上涨结构（v2 条件：3<chg7≤15 + s7≤0.85s30 + sc30>5，供缩样本窗口 60）
      × 市场 TH 三区（<35 / 35-54 / ≥55，引擎 build_market_context 口径）
      × 事件窗口（EVENT_CALENDAR ±30 天）
      × 分位（pct≤40 / >40）
报各格 fwd14/fwd30（扣 2%），回答「v3 环境约束该放哪」。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

from pipeline.backtest_common import build_market_context  # noqa: E402
from pipeline.market_macro import historical_event_impact  # noqa: E402

OUT = ROOT / "data" / "_exp_rise_th_cells.json"
START, END = "2023-11-17", "2026-08-05"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def main():
    ctx = build_market_context(START, end=END)
    print("market ctx days:", len(ctx), flush=True)
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    c.close()

    cells = {}
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    for iid in items:
        rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        n = len(prices)
        for i in range(60, n):
            if i + 30 >= n:
                continue
            d = dates[i]
            m = ctx.get(d)
            if m is None:
                continue
            pct = pct90(prices, i)
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
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            th = m["th"]
            zone = "TH<35" if th < 35 else ("TH35-54" if th < 55 else "TH≥55")
            ev = "事件" if historical_event_impact(d, horizon_days=30) else "正常"
            pb = "pct≤40" if pct <= 40 else "pct>40"
            cells.setdefault(f"{zone}×{ev}×{pb}", []).append({"fwd14": fwd14, "fwd30": fwd30})
            cells.setdefault(f"{zone}×{ev}×全部", []).append({"fwd14": fwd14, "fwd30": fwd30})
    c.close()

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        return {"n": n,
                "win14": round(100.0 * sum(1 for r in recs if r["fwd14"] > 0) / n, 1),
                "avg14": round(sum(r["fwd14"] for r in recs) / n, 2),
                "win30": round(100.0 * sum(1 for r in recs if r["fwd30"] > 0) / n, 1),
                "avg30": round(sum(r["fwd30"] for r in recs) / n, 2)}

    out = {"probe": "买涨腿 v3 结构×TH×事件×分位", "cells": {k: st(v) for k, v in sorted(cells.items())}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k, v in out["cells"].items():
        print(f"  {k:24s} n={v['n']:5d}  win14={v['win14']}  avg14={v['avg14']}  win30={v['win30']}  avg30={v['avg30']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
