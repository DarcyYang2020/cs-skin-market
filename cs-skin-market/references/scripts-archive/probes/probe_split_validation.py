# -*- coding: utf-8 -*-
"""样本划分检验（2026-08-16，只读）：划分本身用测试选，不是拍脑袋。

① 池划分：C 深带结构（牛周期+pct≥70+dd20∈[-30,-20]+龄6-10+承接）在 96 池 vs 全 180 池的期望对照；
② 时间切点：同一结构在 4 个候选切点（2024-07/2024-10/2025-02/2025-08-10）的 fit/val 期望，
   选「fit/val 最接近」的切点（稳定性标准，非 fit 最好看）。
输出 data/_exp_split_validation.json；结论登记 decision-log 作为全系统标准口径。
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

OUT = ROOT / "data" / "_exp_split_validation.json"
CUTS = ("2024-07-01", "2024-10-01", "2025-02-01", "2025-08-10")


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
    items = c.execute("SELECT i.id, i.name, MIN(p.date) first_date "
                      "FROM items i JOIN price_history p ON p.item_id=i.id "
                      "WHERE i.good_id>0 GROUP BY i.id").fetchall()
    c.close()
    names = {r["id"]: r["name"] for r in items}
    train96 = {r["id"] for r in items if r["first_date"] <= "2025-08-10"}
    EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")
    hq180 = {r["id"] for r in items if not any(m in r["name"] for m in EXCL)}

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

    def collect(pool_ids):
        """返回 [(date, fwd30)]：C 深带结构（牛周期+pct≥70+dd20[-30,-20]+龄6-10+承接）。"""
        out = []
        c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
        c.row_factory = sqlite3.Row
        for iid in pool_ids:
            rows = c.execute("SELECT date, price_rmb FROM price_history "
                             "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
            prices = [r["price_rmb"] for r in rows]
            n = len(prices)
            name = names[iid]
            for i in range(90, n):
                if i + 30 >= n:
                    continue
                d = rows[i]["date"]
                cyc = m180.get(d)
                if cyc is None or cyc <= 0:
                    continue
                if pct90(prices, i) < 70:
                    continue
                pk_i = max(range(max(0, i - 20), i), key=lambda j: prices[j])
                dd20 = (prices[i] / prices[pk_i] - 1) * 100
                if not (-30 <= dd20 <= -20):
                    continue
                age = i - pk_i
                if not (6 <= age <= 10):
                    continue
                bpk = bid_at(name, rows[pk_i]["date"])
                bnow = bid_at(name, d)
                if not bpk or not bnow:
                    continue
                if (bnow / bpk - 1) * 100 - dd20 < 0:
                    continue
                fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
                out.append((d, fwd30))
        c.close()
        return out

    def stats(recs):
        if not recs:
            return {"n": 0, "win": None, "avg": None}
        xs = [r[1] for r in recs]
        return {"n": len(xs),
                "win": round(100 * sum(1 for x in xs if x > 0) / len(xs), 1),
                "avg": round(sum(xs) / len(xs), 2)}

    out = {"probe": "样本划分检验（C 深带结构）"}
    # ① 池划分
    c96 = collect(train96)
    c180 = collect(hq180)
    out["pool"] = {"96池": stats(c96), "全180池": stats(c180),
                   "note": "新90品短史无法承载90日口径结构（前已诊断），池检验=96 vs 全180"}
    print("池划分: 96池 %s | 全180池 %s" % (stats(c96), stats(c180)))
    # ② 时间切点（全 180 池）
    print("时间切点（fit/val avg30）:")
    out["time_cuts"] = {}
    for cut in CUTS:
        fit = [r for r in c180 if r[0] < cut]
        val = [r for r in c180 if r[0] >= cut]
        fs, vs = stats(fit), stats(val)
        gap = abs(fs["avg"] - vs["avg"]) if (fs["avg"] is not None and vs["avg"] is not None) else None
        out["time_cuts"][cut] = {"fit": fs, "val": vs, "gap": gap}
        print("  %s: fit n=%d avg=%s | val n=%d avg=%s | gap=%s" % (
            cut, fs["n"], fs["avg"], vs["n"], vs["avg"], gap))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
