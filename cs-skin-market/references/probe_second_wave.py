# -*- coding: utf-8 -*-
"""二波行情指纹池级检验（2026-08-16，第一性原理探索，防单品过拟合）。

指纹候选（来自合纵五窗口归纳）：
  A 大周期：大盘指数 180d 涨幅 > 0（牛市）
  B 强势位：pct90 ≥ 70
  C 真实回调：20 日高点回撤 ∈ [-30%, -8%]
  D 承接：回调期间求购价跌幅 < 价格跌幅 +2pp（bid 抗跌）
报 2×2（回调×承接）在牛/非牛周期下的 fwd14/30/60/90/180。只登记，不落地。
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

OUT = ROOT / "data" / "_exp_second_wave.json"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def main():
    # 大盘指数 180d 序列
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

    # 求购序列（market.db，按 item_name）
    cb = sqlite3.connect(ROOT / "data" / "market.db")
    cb.row_factory = sqlite3.Row
    bids = {}
    for r in cb.execute("SELECT item_name, date, buy_price_last FROM bid_history "
                        "WHERE buy_price_last IS NOT NULL ORDER BY date"):
        bids.setdefault(r["item_name"], []).append((r["date"], r["buy_price_last"]))
    cb.close()

    def bid_at(name, d, span=3):
        seq = bids.get(name)
        if not seq:
            return None
        ds = [x[0] for x in seq]
        i = bisect.bisect_right(ds, d)
        if i == 0:
            return None
        lo = max(0, i - span)
        cand = [x[1] for x in seq[lo:i]]
        return cand[-1] if cand else None

    cells = {}
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    n_checked = 0
    for it in items:
        iid, name = it["id"], it["name"]
        rows = c.execute("SELECT date, price_rmb FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
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
            pct = pct90(prices, i)
            if pct < 70:
                continue
            pk_i = max(range(max(0, i - 20), i), key=lambda j: prices[j])
            dd20 = (prices[i] / prices[pk_i] - 1) * 100
            if not (-30 <= dd20 <= -8):
                continue
            n_checked += 1
            bpk = bid_at(name, dates[pk_i])
            bnow = bid_at(name, d)
            sup = None
            if bpk and bnow:
                sup = (bnow / bpk - 1) * 100 - dd20  # >-2pp = 承接（bid 抗跌）
            fwd = {}
            for h in (14, 30, 60, 90, 180):
                fwd[h] = (prices[i + h] / prices[i] - 1) * 100 - 2.0 if i + h < n else None
            tag = ("承接" if (sup is not None and sup > -2) else
                   ("无承接" if sup is not None else "无求购数据"))
            reg = "牛市" if cyc > 0 else "非牛"
            cells.setdefault(f"{reg}×{tag}", []).append(fwd)
    c.close()
    print("高位+回调 样本数（有前视）:", n_checked)

    def st(recs, h):
        xs = [r[h] for r in recs if r[h] is not None]
        if not xs:
            return "n=0"
        return "n=%d win=%.0f%% avg=%+.2f" % (len(xs), 100 * sum(1 for x in xs if x > 0) / len(xs), sum(xs) / len(xs))

    out = {"probe": "二波行情指纹池级检验"}
    for k in sorted(cells):
        row = {h: st(cells[k], h) for h in (14, 30, 60, 90, 180)}
        out[k] = row
        print("%-12s | 14d %s | 30d %s | 60d %s | 90d %s | 180d %s" % (
            k, row[14], row[30], row[60], row[90], row[180]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
