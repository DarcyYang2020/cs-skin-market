# -*- coding: utf-8 -*-
"""A2-1 惜售线（只读）：供缩+价跌+深值(pct90<=20) 事件 → 深值触发候选。

假设：惜售深值事件 14d net 显著优于同段深值族基线 >=3pp。
walk-forward：拟合 2023-06~2025-08-09 / 验证 2025-08-10~2026-08。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
OUT = ROOT / "data" / "_exp_a2_1_xishou.json"
FIT_END = "2025-08-09"


def decluster(dates, day_gap=3):
    from datetime import datetime
    ds = sorted(dates)
    n = 0
    last = None
    for d in ds:
        if last is None or (datetime.fromisoformat(d) - datetime.fromisoformat(last)).days > day_gap:
            n += 1
        last = d
    return n


def main():
    cyc = sqlite3.connect(CYCLE_DB)
    cyc.row_factory = sqlite3.Row
    items = cyc.execute("SELECT id, name FROM items WHERE good_id > 0 ORDER BY id").fetchall()
    fit = []
    val = []
    for it in items:
        rows = cyc.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                           "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        n = len(prices)
        for i in range(90, n):
            if i + 30 >= n:
                continue
            s7 = insale[i - 6:i + 1]
            s30 = insale[i - 29:i + 1]
            if any(x is None for x in s7) or any(x is None for x in s30):
                continue
            if sum(s7) / 7 > 0.85 * (sum(s30) / 30):
                continue  # 非供缩
            price_chg = (prices[i] - prices[i - 5]) / prices[i - 5] * 100 if prices[i - 5] else 0
            if price_chg >= -3:
                continue  # 非价跌
            win90 = prices[i - 89:i + 1]
            pct90 = sum(1 for p in win90 if p <= prices[i]) / len(win90) * 100
            if pct90 > 20:
                continue  # 非深值
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            rec = {"name": it["name"], "date": dates[i], "price_chg": round(price_chg, 1),
                   "pct90": round(pct90, 1), "fwd14": round(fwd14, 2), "fwd30": round(fwd30, 2)}
            (fit if dates[i] <= FIT_END else val).append(rec)
    cyc.close()

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "clusters": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        win14 = sum(1 for r in recs if r["fwd14"] > 0) / n * 100
        avg14 = sum(r["fwd14"] for r in recs) / n
        win30 = sum(1 for r in recs if r["fwd30"] > 0) / n * 100
        avg30 = sum(r["fwd30"] for r in recs) / n
        return {"n": n, "clusters": decluster([r["date"] for r in recs]),
                "win14": round(win14, 1), "avg14": round(avg14, 2),
                "win30": round(win30, 1), "avg30": round(avg30, 2)}

    fit_s = st(fit)
    val_s = st(val)

    # 深值族基线（cycle replay 的 deep_value 信号）
    rep = json.load(open(REPLAY, encoding="utf-8"))
    dv_fit = [s for s in rep["signals"] if "深值" in (s.get("action_label") or "") and s["date"] <= FIT_END]
    dv_val = [s for s in rep["signals"] if "深值" in (s.get("action_label") or "") and s["date"] > FIT_END]

    def dv_st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None}
        win14 = sum(1 for s in recs if s.get("fwd14") is not None and s["fwd14"] > 0) / n * 100
        avg14 = sum(s["fwd14"] for s in recs if s.get("fwd14") is not None) / max(1, sum(1 for s in recs if s.get("fwd14") is not None))
        return {"n": n, "win14": round(win14, 1), "avg14": round(avg14, 2)}

    dv_fit_s = dv_st(dv_fit)
    dv_val_s = dv_st(dv_val)

    out = {"probe": "A2-1 惜售线", "xishou_fit": fit_s, "xishou_val": val_s,
           "deep_value_baseline_fit": dv_fit_s, "deep_value_baseline_val": dv_val_s}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== A2-1 惜售线 ===")
    print("惜售深值 拟合段:", json.dumps(fit_s, ensure_ascii=False), "| 深值基线:", json.dumps(dv_fit_s, ensure_ascii=False))
    print("惜售深值 验证段:", json.dumps(val_s, ensure_ascii=False), "| 深值基线:", json.dumps(dv_val_s, ensure_ascii=False))
    if fit_s["avg14"] is not None and dv_fit_s["avg14"] is not None:
        print(f"拟合段超额: {round(fit_s['avg14']-dv_fit_s['avg14'],2)}pp")
    if val_s["avg14"] is not None and dv_val_s["avg14"] is not None:
        print(f"验证段超额: {round(val_s['avg14']-dv_val_s['avg14'],2)}pp")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
