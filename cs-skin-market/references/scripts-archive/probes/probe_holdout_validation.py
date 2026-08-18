# -*- coding: utf-8 -*-
"""品级留出集验证（2026-08-16，只读）：96 训练池 vs 池外新品的结构期望对照。

用户样本问题落地：训练池=pool A（2025-08-10 前有数据的 96 老品，幸存者偏差）；
holdout=replay 库其余品（首价日期>2025-08-10 的新品，从未参与任何探针/训练）。
同口径检验 C 二波结构与 D 震荡吸筹结构在 holdout 上是否仍成立。
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

OUT = ROOT / "data" / "_exp_holdout_validation.json"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def vol7(prices, i):
    w = prices[i - 6:i + 1]
    rets = [(w[j] - w[j - 1]) / w[j - 1] for j in range(1, 7) if w[j - 1] > 0]
    if len(rets) < 3:
        return None
    m = sum(rets) / len(rets)
    return (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5


def main():
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [r["value"] for r in mrows]
    m180 = {}
    for i in range(180, len(mvals)):
        m180[mdates[i]] = (mvals[i] / mvals[i - 180] - 1) * 100
    items = c.execute("SELECT i.id, i.name, MIN(p.date) first_date "
                      "FROM items i JOIN price_history p ON p.item_id=i.id "
                      "WHERE i.good_id>0 GROUP BY i.id").fetchall()
    c.close()
    train_ids = {r["id"] for r in items if r["first_date"] <= "2025-08-10"}
    hold_ids = {r["id"] for r in items if r["first_date"] > "2025-08-10"}
    names = {r["id"]: r["name"] for r in items}
    print("训练池(pool A):", len(train_ids), "| holdout 新品:", len(hold_ids))

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

    def run(pool_ids, label):
        c_cells = {"浅": [], "中": [], "深": []}
        d_all = []
        n_items = 0
        c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
        c.row_factory = sqlite3.Row
        for iid in pool_ids:
            rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                             "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
            if len(rows) < 120:
                continue
            n_items += 1
            dates = [r["date"] for r in rows]
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
            name = names[iid]
            for i in range(90, n):
                if i + 30 >= n:
                    continue
                d = dates[i]
                cyc = m180.get(d)
                if cyc is None or cyc <= 0:
                    continue
                fwd = {}
                for h in (14, 30, 60):
                    fwd[h] = (prices[i + h] / prices[i] - 1) * 100 - 2.0 if i + h < n else None
                pct = pct90(prices, i)
                # C 结构
                if pct >= 70:
                    pk_i = max(range(max(0, i - 20), i), key=lambda j: prices[j])
                    dd20 = (prices[i] / prices[pk_i] - 1) * 100
                    age = i - pk_i
                    if -40 <= dd20 <= -5:
                        bpk = bid_at(name, dates[pk_i])
                        bnow = bid_at(name, d)
                        sup = (bnow / bpk - 1) * 100 - dd20 if (bpk and bnow) else None
                        band = "浅" if dd20 >= -10 else ("深" if dd20 <= -20 else "中")
                        # 口径同 second_wave 族：浅=龄≤5；深=龄≥6 且承接≥0；中=任意
                        ok = (band == "浅" and age <= 5) or (band == "中") or (
                            band == "深" and age >= 6 and sup is not None and sup >= 0)
                        if ok:
                            c_cells[band].append(fwd)
                # D 结构
                chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else None
                vv = vol7(prices, i)
                if (chg7 is not None and 0 < chg7 <= 5 and sc[i] is not None and sc[i] <= -5
                        and vv is not None and vv >= 0.03 and pct > 40):
                    d_all.append(fwd)
        c.close()
        print("\n== %s（n_items=%d）==" % (label, n_items))

        def st(recs, h):
            xs = [r[h] for r in recs if r[h] is not None]
            if len(xs) < 10:
                return "n=%d(少)" % len(xs)
            return "n=%d win=%.0f%% avg=%+.1f" % (len(xs), 100 * sum(1 for x in xs if x > 0) / len(xs), sum(xs) / len(xs))

        out = {"label": label, "n_items": n_items,
               "C_浅": {h: st(c_cells["浅"], h) for h in (14, 30, 60)},
               "C_中": {h: st(c_cells["中"], h) for h in (14, 30, 60)},
               "C_深": {h: st(c_cells["深"], h) for h in (14, 30, 60)},
               "D": {h: st(d_all, h) for h in (14, 30, 60)}}
        for k in ("C_浅", "C_中", "C_深", "D"):
            print("  %-6s 14d %-20s 30d %-20s 60d %s" % (k, out[k][14], out[k][30], out[k][60]))
        return out

    res = {}
    res["train"] = run(train_ids, "训练池 96 老品（对照）")
    res["holdout"] = run(hold_ids, "HOLDOUT 新品（从未训练）")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
