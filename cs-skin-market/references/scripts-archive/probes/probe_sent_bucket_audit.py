# -*- coding: utf-8 -*-
"""审计④：情绪分档 × 事件窗口交叉（2026-08-15，只读）。

候选池 = pct≤40 & z≤0（宽口径买点池）。交叉：
- sent 三档（≤30 贪婪 / 30~75 中性 / ≥75 恐惧）
- 事件窗口（historical_event_impact 命中 = 黑天鹅影响期）
报各格 fwd14/fwd30，回答「sent 分档在正常市是否失真」。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market')
sys.path.insert(0, str(ROOT))

from pipeline.market_macro import historical_event_impact

CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_sent_bucket_audit.json"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def zscore(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    if len(w) < 5:
        return None
    mu = sum(w) / len(w)
    var = sum((p - mu) ** 2 for p in w) / len(w)
    sd = var ** 0.5
    return (prices[i] - mu) / sd if sd > 0 else None


def main():
    c = sqlite3.connect(CYCLE_DB); c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    c.close()

    cells = {
        "贪婪(≤30)×事件": [], "贪婪(≤30)×正常": [],
        "中性(30~75)×事件": [], "中性(30~75)×正常": [],
        "恐惧(≥75)×事件": [], "恐惧(≥75)×正常": [],
    }
    c = sqlite3.connect(CYCLE_DB); c.row_factory = sqlite3.Row
    for iid in items:
        rows = c.execute("SELECT date, price_rmb FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        n = len(prices)
        for i in range(90, n):
            if i + 30 >= n:
                continue
            pct = pct90(prices, i)
            z = zscore(prices, i)
            if pct is None or z is None or pct > 40 or z > 0:
                continue
            chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else 0
            chg14 = (prices[i] / prices[i - 14] - 1) * 100 if i >= 14 else 0
            sent = 50 - 2 * chg7 - chg14
            ev = bool(historical_event_impact(dates[i], horizon_days=30))
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            rec = {"fwd14": fwd14, "fwd30": fwd30}
            band = "贪婪(≤30)" if sent <= 30 else ("恐惧(≥75)" if sent >= 75 else "中性(30~75)")
            cells[f"{band}×{'事件' if ev else '正常'}"].append(rec)
    c.close()

    def st(recs):
        nn = len(recs)
        if nn == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        return {"n": nn,
                "win14": round(sum(1 for r in recs if r["fwd14"] > 0) / nn * 100, 1),
                "avg14": round(sum(r["fwd14"] for r in recs) / nn, 2),
                "win30": round(sum(1 for r in recs if r["fwd30"] > 0) / nn * 100, 1),
                "avg30": round(sum(r["fwd30"] for r in recs) / nn, 2)}

    out = {"probe": "审计④ 情绪分档×事件窗口", "cells": {k: st(v) for k, v in cells.items()}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k, v in out["cells"].items():
        print(f"  {k:22s} n={v['n']:6d}  win14={v['win14']}  avg14={v['avg14']}  win30={v['win30']}  avg30={v['avg30']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
