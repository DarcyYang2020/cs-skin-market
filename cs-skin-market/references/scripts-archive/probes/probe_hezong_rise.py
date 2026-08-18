# -*- coding: utf-8 -*-
"""合纵为何从不上涨腿（2026-08-16，只读讲解探针）：对合纵全序列算 TH≥55 且 chg7∈(3,15]
的候选日，看供给条件（s7/s30 收缩、sc30 扩张）差在哪。"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

from pipeline.backtest_common import build_market_context  # noqa: E402

ctx = build_market_context("2023-11-17", end="2026-08-05")
c = sqlite3.connect(os.environ["CS_MODEL_DB"])
c.row_factory = sqlite3.Row
iid = c.execute("SELECT id FROM items WHERE name LIKE '%合纵%'").fetchone()["id"]
rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                 "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
c.close()
dates = [r["date"] for r in rows]
prices = [r["price_rmb"] for r in rows]
ins = [r["in_sale_count"] for r in rows]
print("合纵 series n=%d %s~%s 价格 %.0f -> %.0f" % (len(prices), dates[0], dates[-1], prices[0], prices[-1]))
hits = 0
shown = 0
for i in range(60, len(prices)):
    d = dates[i]
    m = ctx.get(d)
    if not m or m["th"] < 55:
        continue
    chg7 = (prices[i] / prices[i - 7] - 1) * 100
    if not (3 < chg7 <= 15):
        continue
    hits += 1
    ok7 = all(x is not None for x in ins[i - 6:i + 1])
    ok30 = all(x is not None for x in ins[i - 29:i + 1])
    ok30a = all(x is not None for x in ins[i - 59:i - 29])
    s7 = sum(ins[i - 6:i + 1]) / 7 if ok7 else None
    s30 = sum(ins[i - 29:i + 1]) / 30 if ok30 else None
    s30a = sum(ins[i - 59:i - 29]) / 30 if ok30a else None
    sc30 = (s30 / s30a - 1) * 100 if s30 and s30a else None
    ratio = (s7 / s30) if s7 and s30 else None
    if shown < 8:
        shown += 1
        print("%s th=%s chg7=%+.1f%% s7/s30=%s sc30=%s 价格=%.0f" % (
            d, m["th"], chg7, "%.2f" % ratio if ratio else "无", "%+.0f%%" % sc30 if sc30 else "无", prices[i]))
print("TH≥55 且 chg7∈(3,15] 的日数:", hits, "（需 s7/s30≤0.85 且 sc30>5 才能触发）")

# ---- 收缩型上涨缺口量化：chg7∈(3,15] + s7≤0.85s30（去掉 sc30>5 要求）----
from pipeline.market_macro import historical_event_impact  # noqa: E402
recs, recs30 = [], []
for i in range(60, len(prices)):
    d = dates[i]
    m = ctx.get(d)
    if not m or m["th"] < 55:
        continue
    chg7 = (prices[i] / prices[i - 7] - 1) * 100
    if not (3 < chg7 <= 15):
        continue
    ok7 = all(x is not None for x in ins[i - 6:i + 1])
    ok30 = all(x is not None for x in ins[i - 29:i + 1])
    ok30a = all(x is not None for x in ins[i - 59:i - 29])
    if not (ok7 and ok30 and ok30a):
        continue
    s7 = sum(ins[i - 6:i + 1]) / 7
    s30 = sum(ins[i - 29:i + 1]) / 30
    s30a = sum(ins[i - 59:i - 29]) / 30
    sc30 = (s30 / s30a - 1) * 100
    if s7 <= s30 * 0.85:
        f14 = (prices[i + 14] / prices[i] - 1) * 100 - 2 if i + 14 < len(prices) else None
        f30 = (prices[i + 30] / prices[i] - 1) * 100 - 2 if i + 30 < len(prices) else None
        rec = (f14, f30, sc30, historical_event_impact(d, 30), d)
        recs.append(rec)
        if sc30 > 5:
            recs30.append(rec)


def st(rs):
    n = len(rs)
    if n == 0:
        return "n=0"
    w14 = sum(1 for r in rs if r[0] is not None and r[0] > 0)
    n14 = sum(1 for r in rs if r[0] is not None)
    a14 = sum(r[0] for r in rs if r[0] is not None) / max(1, n14)
    return "n=%d win14=%.0f%% avg14=%+.2f" % (n, 100 * w14 / max(1, n14), a14)


print("合纵 收缩型上涨（TH≥55 + chg7∈(3,15] + s7≤0.85s30）:", st(recs))
print("其中 sc30>5（现 rise 族条件）:", st(recs30))
for r in recs[:12]:
    print("   %s sc30=%+.0f%% fwd14=%+.1f%% fwd30=%+.1f%% 事件=%s" % (
        r[4], r[2], r[0] or 0.0, r[1] or 0.0, r[3]))
