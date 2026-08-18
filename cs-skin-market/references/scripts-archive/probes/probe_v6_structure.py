# -*- coding: utf-8 -*-
"""v6 课题结构探针（2026-08-16，只读）：合纵型收缩慢涨腿候选结构定位。

交叉：收缩型上涨（TH≥55 + chg7∈(3,15] + s7≤0.85s30，不要求 sc30>5）
      × sc30 分桶（≤-10 / -10~0 / 0~5 / >5）× 分位（pct≤40/>40）× 事件窗口
报各格 fwd14/fwd30（扣 2%）。对照：supply_accum 域（|chg7|≤3 + s7≤0.85s30）的合纵样本数，
诊断「合纵 3 年 0 发射」落在哪。
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

OUT = ROOT / "data" / "_exp_v6_structure.json"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def main():
    ctx = build_market_context("2023-11-17", end="2026-08-05")
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    c.close()

    cells = {}
    hezong_supply = []   # 合纵在 supply_accum 域（|chg7|≤3 + s7≤0.85s30）的样本
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    for iid in items:
        rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        name = c.execute("SELECT name FROM items WHERE id=?", (iid,)).fetchone()["name"]
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
            chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else None
            ok7 = all(x is not None for x in insale[i - 6:i + 1])
            ok30 = all(x is not None for x in insale[i - 29:i + 1])
            ok30a = all(x is not None for x in insale[i - 59:i - 29])
            if not (ok7 and ok30 and ok30a):
                continue
            s7 = sum(insale[i - 6:i + 1]) / 7
            s30 = sum(insale[i - 29:i + 1]) / 30
            s30a = sum(insale[i - 59:i - 29]) / 30
            if not (s30 > 0 and s7 <= s30 * 0.85):
                continue
            sc30 = (s30 / s30a - 1) * 100
            if chg7 is None or chg7 <= 3:
                continue  # 本探针只看上涨域；supply_accum 域另计
            if chg7 > 15:
                continue
            if m["th"] < 55:
                continue
            pct = pct90(prices, i)
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            ev = "事件" if historical_event_impact(d, horizon_days=30) else "正常"
            pb = "pct≤40" if pct <= 40 else "pct>40"
            if sc30 <= -10:
                sb = "sc30≤-10"
            elif sc30 <= 0:
                sb = "sc30-10~0"
            elif sc30 <= 5:
                sb = "sc300~5"
            else:
                sb = "sc30>5"
            cells.setdefault(f"{sb}×{ev}×{pb}", []).append({"fwd14": fwd14, "fwd30": fwd30})
            cells.setdefault(f"{sb}×{ev}×全部", []).append({"fwd14": fwd14, "fwd30": fwd30})
        # supply_accum 域诊断（合纵）
        if "合纵" in name:
            for i in range(30, n):
                if i + 30 >= n:
                    continue
                chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else None
                if chg7 is None or abs(chg7) > 3:
                    continue
                ok7 = all(x is not None for x in insale[i - 6:i + 1])
                ok30 = all(x is not None for x in insale[i - 29:i + 1])
                if not (ok7 and ok30):
                    continue
                s7 = sum(insale[i - 6:i + 1]) / 7
                s30 = sum(insale[i - 29:i + 1]) / 30
                if s30 > 0 and s7 <= s30 * 0.85:
                    hezong_supply.append(dates[i])
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

    out = {"probe": "v6 收缩型上涨结构定位", "cells": {k: st(v) for k, v in sorted(cells.items())},
           "hezong_supply_domain_days": len(hezong_supply),
           "hezong_supply_domain_sample": hezong_supply[:10]}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k, v in out["cells"].items():
        print(f"  {k:26s} n={v['n']:5d}  win14={v['win14']}  avg14={v['avg14']}  win30={v['win30']}  avg30={v['avg30']}")
    print("合纵 supply_accum 域(|chg7|≤3+s7≤0.85s30) 天数:", len(hezong_supply), hezong_supply[:10])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
