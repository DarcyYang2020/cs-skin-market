# -*- coding: utf-8 -*-
"""审计②：三道反牛市闸门收益损失量化（2026-08-15，只读探针）。

在 cycle 3 年干净数据上，对每道闸门算「被拦候选池」的前视收益 vs「放行池」：
- G1 贪婪禁买 sent≤30（价格近似 sent=50-2*chg7-chg14）
- G2 I-13 上涨段禁买 mchg30≥3（对深值候选 pct≤20 & z≤-0.5）
- G3 供给扩张>5% 禁买（对供给收缩 s7≤0.85s30 候选）
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market')
sys.path.insert(0, str(ROOT))
CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_gate_impact.json"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def zscore(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    if len(w) < 5:
        return None
    mu = sum(w) / len(w)
    var = sum((p - mu) ** 2 for p in w) / len(w)
    sd = var ** 0.5
    return (prices[i] - mu) / sd if sd > 0 else None


def main():
    c = sqlite3.connect(CYCLE_DB); c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    mkt = {r["date"]: r["value"] for r in c.execute("SELECT date, value FROM market_index ORDER BY date")}
    mkt_dates = sorted(mkt)
    c.close()

    c = sqlite3.connect(CYCLE_DB); c.row_factory = sqlite3.Row
    g1_blocked, g1_passed = [], []
    g2_blocked, g2_passed = [], []
    g3_blocked, g3_passed = [], []
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
            d = dates[i]
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            pct = pct90(prices, i)
            z = zscore(prices, i)
            if pct is None or z is None:
                continue
            # 大盘 30 日变化（对齐信号日）
            mkeys = [k for k in mkt_dates if k <= d]
            if len(mkeys) < 31:
                continue
            m30 = (mkt[mkeys[-1]] / mkt[mkeys[-31]] - 1) * 100
            # 价格近似情绪
            chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else 0
            chg14 = (prices[i] / prices[i - 14] - 1) * 100 if i >= 14 else 0
            sent = 50 - 2 * chg7 - chg14
            # 供给 30 日变化
            s7 = sum(insale[i - 6:i + 1]) / 7 if all(x is not None for x in insale[i - 6:i + 1]) else None
            s30 = sum(insale[i - 29:i + 1]) / 30 if all(x is not None for x in insale[i - 29:i + 1]) else None
            s30_ago = sum(insale[i - 59:i - 29]) / 30 if all(x is not None for x in insale[i - 59:i - 29]) else None
            sc30 = (s30 / s30_ago - 1) * 100 if (s30 is not None and s30_ago not in (None, 0)) else None
            rec = {"fwd14": fwd14, "fwd30": fwd30}
            # G2：深值候选池（pct≤20 & z≤-0.5）
            if pct <= 20 and z <= -0.5:
                (g2_blocked if m30 >= 3 else g2_passed).append(rec)
            # G1：贪婪禁买（宽候选池 pct≤40 & z≤0）
            if pct <= 40 and z <= 0:
                (g1_blocked if sent <= 30 else g1_passed).append(rec)
            # G3：供给收缩候选
            if s7 is not None and s30 is not None and s30 > 0 and s7 <= 0.85 * s30:
                if sc30 is not None:
                    (g3_blocked if sc30 > 5 else g3_passed).append(rec)
    c.close()

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        return {"n": n,
                "win14": round(sum(1 for r in recs if r["fwd14"] > 0) / n * 100, 1),
                "avg14": round(sum(r["fwd14"] for r in recs) / n, 2),
                "win30": round(sum(1 for r in recs if r["fwd30"] > 0) / n * 100, 1),
                "avg30": round(sum(r["fwd30"] for r in recs) / n, 2)}

    out = {
        "probe": "审计② 三道反牛市闸门收益损失",
        "G1_贪婪禁买": {"被拦(sent<=30)": st(g1_blocked), "放行(sent>30)": st(g1_passed)},
        "G2_I13上涨段": {"被拦(mchg30>=3)": st(g2_blocked), "放行(mchg30<=-3)": st(g2_passed)},
        "G3_供给扩张": {"被拦(sc30>5%)": st(g3_blocked), "放行(sc30<=5%)": st(g3_passed)},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for g in ("G1_贪婪禁买", "G2_I13上涨段", "G3_供给扩张"):
        print(f"=== {g} ===")
        for k, v in out[g].items():
            print(f"  {k:22s} n={v['n']:6d}  win14={v['win14']}  avg14={v['avg14']}  win30={v['win30']}  avg30={v['avg30']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
