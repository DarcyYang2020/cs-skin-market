# -*- coding: utf-8 -*-
"""v6b 合纵捕捉条件对比探针（2026-08-16，只读，用户决策「哪个能更好捕捉合纵选哪个」）。

候选条件（均在 TH≥55 + s7≤0.85s30 + pct>40 + 正常窗 下）：
  C1: 3<chg7≤15 + sc30≤-5（v6 阈值放松）
  C2: C1 + 连续收缩≥14 天（前 14 个交易日 sc30 连续 ≤-5）
  C3: 0≤chg7≤5 + sc30≤-5（慢速收缩）
  C4: C3 + 连续收缩≥14 天
报：池级 fit/val（win14/avg14/win30/avg30）+ 合纵触发天数与前视。
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

OUT = ROOT / "data" / "_exp_v6b_capture.json"


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

    cond = {k: [] for k in ("C1", "C2", "C3", "C4")}
    hezong = {k: [] for k in ("C1", "C2", "C3", "C4")}
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
        # 每日 sc30（滚动）
        sc30_series = [None] * n
        for i in range(59, n):
            ok30 = all(x is not None for x in insale[i - 29:i + 1])
            ok30a = all(x is not None for x in insale[i - 59:i - 29])
            if ok30 and ok30a:
                s30 = sum(insale[i - 29:i + 1]) / 30
                s30a = sum(insale[i - 59:i - 29]) / 30
                if s30a > 0:
                    sc30_series[i] = (s30 / s30a - 1) * 100
        for i in range(60, n):
            if i + 30 >= n:
                continue
            d = dates[i]
            m = ctx.get(d)
            if m is None or m["th"] < 55 or historical_event_impact(d, 30):
                continue
            pct = pct90(prices, i)
            if pct <= 40:
                continue
            chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else None
            if chg7 is None:
                continue
            ok7 = all(x is not None for x in insale[i - 6:i + 1])
            ok30 = all(x is not None for x in insale[i - 29:i + 1])
            if not (ok7 and ok30):
                continue
            s7 = sum(insale[i - 6:i + 1]) / 7
            s30 = sum(insale[i - 29:i + 1]) / 30
            if s30 <= 0 or s7 > s30 * 0.85:
                continue
            sc30 = sc30_series[i]
            if sc30 is None or sc30 > -5:
                continue
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            cont14 = all(sc30_series[j] is not None and sc30_series[j] <= -5
                         for j in range(i - 13, i + 1))
            rec = (fwd14, fwd30, d)
            hits = []
            if 3 < chg7 <= 15:
                hits.append("C1")
                if cont14:
                    hits.append("C2")
            if 0 <= chg7 <= 5:
                hits.append("C3")
                if cont14:
                    hits.append("C4")
            for k in hits:
                cond[k].append(rec)
                if "合纵" in name:
                    hezong[k].append(rec)
    c.close()

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        return {"n": n,
                "win14": round(100.0 * sum(1 for r in recs if r[0] > 0) / n, 1),
                "avg14": round(sum(r[0] for r in recs) / n, 2),
                "win30": round(100.0 * sum(1 for r in recs if r[1] > 0) / n, 1),
                "avg30": round(sum(r[1] for r in recs) / n, 2)}

    out = {"probe": "v6b 合纵捕捉条件对比"}
    for k in ("C1", "C2", "C3", "C4"):
        # fit/val 切 2025-08-10
        fit = [r for r in cond[k] if r[2] < "2025-08-10"]
        val = [r for r in cond[k] if r[2] >= "2025-08-10"]
        hz = st(hezong[k])
        print(f"{k}: 池 fit {st(fit)} | val {st(val)} | 合纵 {hz}")
        out[k] = {"fit": st(fit), "val": st(val), "hezong": hz,
                  "hezong_dates": [r[2] for r in hezong[k]][:12]}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)

    # ---- 长持有视野：合纵收益最高方案（2026-08-16 用户追问）——C1 条件 fwd60/90/180 ----
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    iid = c.execute("SELECT id FROM items WHERE name LIKE '%合纵%'").fetchone()["id"]
    rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                     "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
    c.close()
    dates = [r["date"] for r in rows]
    prices = [r["price_rmb"] for r in rows]
    insale = [r["in_sale_count"] for r in rows]
    n = len(prices)
    sc30_series = [None] * n
    for i in range(59, n):
        ok30 = all(x is not None for x in insale[i - 29:i + 1])
        ok30a = all(x is not None for x in insale[i - 59:i - 29])
        if ok30 and ok30a:
            s30 = sum(insale[i - 29:i + 1]) / 30
            s30a = sum(insale[i - 59:i - 29]) / 30
            if s30a > 0:
                sc30_series[i] = (s30 / s30a - 1) * 100
    print("\n== 合纵 C1 条件日（TH≥55+chg7∈(3,15]+s7≤0.85s30+sc30≤-5+pct>40+正常）长持有视野 ==")
    cnt = 0
    for i in range(60, n):
        d = dates[i]
        m = ctx.get(d)
        if not m or m["th"] < 55 or historical_event_impact(d, 30):
            continue
        pct = pct90(prices, i)
        if pct <= 40:
            continue
        chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else None
        if chg7 is None or not (3 < chg7 <= 15):
            continue
        ok7 = all(x is not None for x in insale[i - 6:i + 1])
        ok30 = all(x is not None for x in insale[i - 29:i + 1])
        if not (ok7 and ok30):
            continue
        s7 = sum(insale[i - 6:i + 1]) / 7
        s30 = sum(insale[i - 29:i + 1]) / 30
        if s30 <= 0 or s7 > s30 * 0.85:
            continue
        sc30 = sc30_series[i]
        if sc30 is None or sc30 > -5:
            continue
        fwd = {}
        for h in (14, 30, 60, 90, 180):
            fwd[h] = (prices[i + h] / prices[i] - 1) * 100 - 2.0 if i + h < n else None
        cnt += 1
        print("  %s chg7=%+.1f sc30=%+.0f%% fwd14=%+.0f fwd30=%+.0f fwd60=%+.0f fwd90=%+.0f fwd180=%+.0f" % (
            d, chg7, sc30, fwd[14] or 0, fwd[30] or 0, fwd[60] or 0, fwd[90] or 0, fwd[180] or 0))
    print("合纵 C1 触发天数:", cnt)


if __name__ == "__main__":
    main()
