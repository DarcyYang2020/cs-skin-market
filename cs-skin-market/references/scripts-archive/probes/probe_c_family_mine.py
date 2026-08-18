# -*- coding: utf-8 -*-
"""第二批 探针1：C 族（二波）结构挖掘（2026-08-16，只读、描述性分桶，零拟合）。

问题：高位(pct90≥70)+回调后，买点质量随「回调深度带 × 回调龄（距20日高点天数）× 承接(bid抗跌)」
如何分布？拐点从数据里看（报告档固定，不择优）。
口径：前视 14/30/60 扣 2%；牛市=指180d>0；承接=回调期 bid 跌幅≥价格跌幅（bid抗跌）；spread=(价-求购)/价。
"""
import bisect
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_c_family_mine.json"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def main():
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [r["value"] for r in mrows]
    m180 = {}
    for i in range(180, len(mvals)):
        m180[mdates[i]] = (mvals[i] / mvals[i - 180] - 1) * 100
    items = c.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    c.close()

    cb = sqlite3.connect(ROOT / "data" / "market.db")
    cb.row_factory = sqlite3.Row
    bids = {}
    for r in cb.execute("SELECT item_name, date, buy_price_last FROM bid_history "
                        "WHERE buy_price_last IS NOT NULL ORDER BY date"):
        bids.setdefault(r["item_name"], []).append((r["date"], r["buy_price_last"]))
    cb.close()

    def bid_at(name, d, span=4):
        seq = bids.get(name)
        if not seq:
            return None
        ds = [x[0] for x in seq]
        i = bisect.bisect_right(ds, d)
        lo = max(0, i - span)
        cand = [x[1] for x in seq[lo:i]]
        return cand[-1] if cand else None

    cells = {}
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    for it in items:
        rows = c.execute("SELECT date, price_rmb FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        n = len(prices)
        for i in range(90, n):
            if i + 30 >= n:
                continue
            d = dates[i]
            cyc = m180.get(d)
            if cyc is None:
                continue
            if pct90(prices, i) < 70:
                continue
            pk_i = max(range(max(0, i - 20), i), key=lambda j: prices[j])
            dd20 = (prices[i] / prices[pk_i] - 1) * 100
            if dd20 > -5 or dd20 < -40:
                continue
            age = i - pk_i  # 回调龄（距 20 日高点交易日数）
            bpk = bid_at(it["name"], dates[pk_i])
            bnow = bid_at(it["name"], d)
            sup = None
            if bpk and bnow:
                sup = (bnow / bpk - 1) * 100 - dd20
            fwd = {}
            for h in (14, 30, 60):
                fwd[h] = (prices[i + h] / prices[i] - 1) * 100 - 2.0 if i + h < n else None
            band = ("-5~-10" if dd20 >= -10 else ("-10~-20" if dd20 >= -20
                    else ("-20~-30" if dd20 >= -30 else "-30~-40")))
            ab = ("1-2d" if age <= 2 else ("3-5d" if age <= 5 else ("6-10d" if age <= 10 else "11-20d")))
            sg = ("承接" if (sup is not None and sup >= 0) else
                  ("无承接" if sup is not None else "无数据"))
            reg = "牛" if cyc > 0 else "非牛"
            key = f"{band}×{ab}×{sg}×{reg}"
            cells.setdefault(key, []).append(fwd)
    c.close()

    def st(recs, h):
        xs = [r[h] for r in recs if r[h] is not None]
        if len(xs) < 10:
            return "n=%d(少)" % len(xs)
        return "n=%d win=%.0f%% avg=%+.1f" % (len(xs), 100 * sum(1 for x in xs if x > 0) / len(xs), sum(xs) / len(xs))

    out = {"probe": "C族二波结构挖掘（描述性分桶）", "cells": {}}
    for k in sorted(cells):
        row = {h: st(cells[k], h) for h in (14, 30, 60)}
        out["cells"][k] = row
        print("%-28s | 14d %-22s | 30d %-22s | 60d %s" % (k, row[14], row[30], row[60]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
