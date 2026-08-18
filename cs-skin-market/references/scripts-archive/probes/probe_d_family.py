# -*- coding: utf-8 -*-
"""第二批 探针3：D 启动前指纹（2026-08-16，只读，描述性分桶）。

问题：启动前/温和上涨结构 = 慢涨（0<chg7≤5）+ 供给收缩（sc30≤-5）+ 低波动，
在池级的前视表现如何？波动档用全池 7 日波动率的描述性分位（非拟合参数），
分位带（pct90）作观察维度。前视 14/30/60 扣 2%。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_d_family.json"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def main():
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    items = c.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    c.close()

    # 第一遍：收集全池 7 日波动率，取描述性三分位
    vols = []
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    for it in items:
        rows = c.execute("SELECT price_rmb FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
        prices = [r["price_rmb"] for r in rows]
        n = len(prices)
        for i in range(90, n - 30):
            if i + 30 >= n:
                continue
            w = prices[i - 6:i + 1]
            if len(w) < 7:
                continue
            rets = [(w[j] - w[j - 1]) / w[j - 1] for j in range(1, 7) if w[j - 1] > 0]
            if rets:
                vols.append((sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets)) ** 0.5)
    c.close()
    vols.sort()
    q1 = vols[len(vols) // 3]
    q2 = vols[2 * len(vols) // 3]
    print("全池 7 日波动率三分位: q1=%.4f q2=%.4f（描述性，非拟合参数）" % (q1, q2))

    cells = {}
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    for it in items:
        rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
        prices = [r["price_rmb"] for r in rows]
        ins = [r["in_sale_count"] for r in rows]
        n = len(prices)
        sc = [None] * n
        for i in range(59, n):
            ok30 = all(x is not None for x in ins[i - 29:i + 1])
            ok30a = all(x is not None for x in ins[i - 59:i - 29])
            if ok30 and ok30a:
                s30 = sum(ins[i - 29:i + 1]) / 30
                s30a = sum(ins[i - 59:i - 29]) / 30
                if s30a > 0:
                    sc[i] = (s30 / s30a - 1) * 100
        for i in range(90, n):
            if i + 30 >= n:
                continue
            chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else None
            if chg7 is None or not (0 < chg7 <= 5):
                continue  # 慢涨
            if sc[i] is None or sc[i] > -5:
                continue  # 供给收缩
            w = prices[i - 6:i + 1]
            rets = [(w[j] - w[j - 1]) / w[j - 1] for j in range(1, 7) if w[j - 1] > 0]
            if len(rets) < 3:
                continue
            vol = (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets)) ** 0.5
            vb = "低波" if vol <= q1 else ("中波" if vol <= q2 else "高波")
            pct = pct90(prices, i)
            pb = "pct≤40" if pct <= 40 else ("pct40-70" if pct <= 70 else "pct>70")
            fwd = {}
            for h in (14, 30, 60):
                fwd[h] = (prices[i + h] / prices[i] - 1) * 100 - 2.0 if i + h < n else None
            key = "%s×%s" % (vb, pb)
            cells.setdefault(key, []).append(fwd)
    c.close()

    def st(recs, h):
        xs = [r[h] for r in recs if r[h] is not None]
        if len(xs) < 20:
            return "n=%d(少)" % len(xs)
        return "n=%d win=%.0f%% avg=%+.1f" % (len(xs), 100 * sum(1 for x in xs if x > 0) / len(xs), sum(xs) / len(xs))

    out = {"probe": "D 启动前指纹（慢涨+供给收缩+波动分档×分位带）",
           "vol_terciles": {"q1": q1, "q2": q2}, "cells": {}}
    for k in sorted(cells):
        row = {h: st(cells[k], h) for h in (14, 30, 60)}
        out["cells"][k] = row
        print("%-16s | 14d %-20s | 30d %-20s | 60d %s" % (k, row[14], row[30], row[60]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
