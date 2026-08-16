# -*- coding: utf-8 -*-
"""审计③：买涨腿结构探针（2026-08-15，只读）。

G3 已发现「供给扩张禁买」拦掉的是最强信号（sc30>5% 桶 avg14 +8.62% vs ≤5% 桶 +3.17%）。
本探针测「价涨×供给」结构与突破结构的前视收益，为「买涨腿」定型。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market')
sys.path.insert(0, str(ROOT))
CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_rise_leg_structures.json"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def main():
    c = sqlite3.connect(CYCLE_DB); c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    c.close()

    buckets = {
        "A_价涨+供缩": [], "B_价涨+供扩": [], "C_价平+供缩": [],
        "D_突破60日高+供缩": [], "E_突破60日高(无供给条件)": [],
        "F_价涨+供缩+30日供给扩张(被G3拦的)": [],
    }
    c = sqlite3.connect(CYCLE_DB); c.row_factory = sqlite3.Row
    for iid in items:
        rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        n = len(prices)
        for i in range(90, n):
            if i + 30 >= n:
                continue
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            rec = {"fwd14": fwd14, "fwd30": fwd30, "date": dates[i], "name": iid}
            chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else 0
            s7v = insale[i - 6:i + 1]
            s30v = insale[i - 29:i + 1]
            if any(x is None for x in s7v) or any(x is None for x in s30v):
                continue
            a7 = sum(s7v) / 7
            a30 = sum(s30v) / 30
            supply_contract = a30 > 0 and a7 <= 0.85 * a30
            s30_ago = insale[i - 59:i - 29]
            sc30 = None
            if all(x is not None for x in s30_ago) and len(s30_ago) == 30:
                a30_ago = sum(s30_ago) / 30
                if a30_ago > 0:
                    sc30 = (a30 / a30_ago - 1) * 100
            price_up = chg7 > 3
            price_flat = -3 <= chg7 <= 3
            hi60 = max(prices[i - 59:i + 1])
            breakout = prices[i] >= hi60 * 0.995 and prices[i - 1] < max(prices[i - 60:i]) * 0.995
            if price_up and supply_contract:
                buckets["A_价涨+供缩"].append(rec)
                if sc30 is not None and sc30 > 5:
                    buckets["F_价涨+供缩+30日供给扩张(被G3拦的)"].append(rec)
            if price_up and not supply_contract and a30 > 0:
                buckets["B_价涨+供扩"].append(rec)
            if price_flat and supply_contract:
                buckets["C_价平+供缩"].append(rec)
            if breakout:
                buckets["E_突破60日高(无供给条件)"].append(rec)
                if supply_contract:
                    buckets["D_突破60日高+供缩"].append(rec)
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

    out = {"probe": "审计③ 买涨腿结构", "buckets": {k: st(v) for k, v in buckets.items()}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k, v in out["buckets"].items():
        print(f"  {k:34s} n={v['n']:6d}  win14={v['win14']}  avg14={v['avg14']}  win30={v['win30']}  avg30={v['avg30']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
