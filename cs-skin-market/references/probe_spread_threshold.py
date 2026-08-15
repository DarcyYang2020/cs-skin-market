# -*- coding: utf-8 -*-
"""spread 走阔阈值扫描（只读，7,206 供缩×求购事件）。

把 5 日 Δspread（价差变化 pp）分 8 档，每档报事件数 / 14d net / 负期望占比，
找「14d net 转负」的真正分界线（不是只比均值）。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
MARKET_DB = ROOT / "data" / "market.db"
OUT = ROOT / "data" / "_exp_spread_threshold.json"


def buy_at(bdates, bprices, target):
    best = None
    for d, p in zip(bdates, bprices):
        if d <= target:
            best = p
        else:
            break
    return best


def main():
    cyc = sqlite3.connect(CYCLE_DB)
    cyc.row_factory = sqlite3.Row
    mkt = sqlite3.connect(MARKET_DB)
    mkt.row_factory = sqlite3.Row
    items = cyc.execute("SELECT id, good_id FROM items WHERE good_id > 0 ORDER BY id").fetchall()
    good_cache = {}
    events = []  # (dspread, fwd14, fwd30)
    for it in items:
        iid, gid = it["id"], it["good_id"]
        rows = cyc.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                           "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        if gid not in good_cache:
            r2 = mkt.execute("SELECT date, buy_price_last FROM bid_history "
                             "WHERE good_id=? AND buy_price_last IS NOT NULL ORDER BY date", (gid,)).fetchall()
            good_cache[gid] = {"dates": [x["date"] for x in r2], "price": [x["buy_price_last"] for x in r2]}
        g = good_cache[gid]
        n = len(prices)
        for i in range(30, n):
            if i + 30 >= n:
                continue
            s7 = insale[i - 6:i + 1]
            s30 = insale[i - 29:i + 1]
            if any(x is None for x in s7) or any(x is None for x in s30):
                continue
            if sum(s7) / 7 > 0.85 * (sum(s30) / 30):
                continue
            buy_now = buy_at(g["dates"], g["price"], dates[i])
            buy_5d = buy_at(g["dates"], g["price"], dates[i - 5]) if i >= 5 else buy_now
            if buy_now is None or buy_5d is None or prices[i - 5] is None or prices[i - 5] <= 0:
                continue
            spread_now = (prices[i] - buy_now) / prices[i] * 100 if prices[i] else None
            spread_5d = (prices[i - 5] - buy_5d) / prices[i - 5] * 100
            if spread_now is None:
                continue
            dspread = spread_now - spread_5d
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            events.append((dspread, fwd14, fwd30))
    cyc.close()
    mkt.close()

    # 8 分位档
    ds = sorted(e[0] for e in events)
    qs = [ds[int(len(ds) * i / 8)] for i in range(1, 8)]
    edges = [None] + qs + [None]
    bins = []
    for k in range(8):
        lo = edges[k]
        hi = edges[k + 1]
        if lo is None:
            sel = [e for e in events if e[0] < hi]
        elif hi is None:
            sel = [e for e in events if e[0] >= lo]
        else:
            sel = [e for e in events if lo <= e[0] < hi]
        if not sel:
            bins.append({"range": f"[{lo},{hi})", "n": 0, "avg14": None, "neg_share": None})
            continue
        n = len(sel)
        avg14 = sum(e[1] for e in sel) / n
        avg30 = sum(e[2] for e in sel) / n
        neg14 = sum(1 for e in sel if e[1] < 0) / n * 100
        neg30 = sum(1 for e in sel if e[2] < 0) / n * 100
        bins.append({"range": f"[{lo},{hi})", "n": n, "avg14": round(avg14, 2),
                     "avg30": round(avg30, 2), "neg14_pct": round(neg14, 1), "neg30_pct": round(neg30, 1)})

    out = {"probe": "spread 走阔阈值扫描", "n_events": len(events), "bins": bins}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== spread 阈值扫描（n={len(events)}）===")
    print(f"{'档位':<20}{'n':>6}{'avg14':>8}{'avg30':>8}{'负期望14%':>10}{'负期望30%':>10}")
    for b in bins:
        print(f"{b['range']:<20}{b['n']:>6}{str(b['avg14']):>8}{str(b['avg30']):>8}{str(b['neg14_pct']):>10}{str(b['neg30_pct']):>10}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
