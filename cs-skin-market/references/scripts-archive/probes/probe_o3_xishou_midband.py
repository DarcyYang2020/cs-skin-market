# -*- coding: utf-8 -*-
"""O3 惜售中段腿阶段 0（2026-08-15，做厚收益端第 3 步）。

背景：A2-1 证伪「供缩+价跌+深值(pct≤20)」，但附带发现「惜售强度在 pct 20~60 中段，
接近超跌反弹语义」。本探针在 3 年干净数据上对惜售事件按 90 日分位分带，
并设中段无条件基线对照，回答「惜售中段腿是否有 alpha」。

只报分布，不判定（阶段 0）；判定（A2）需 walk-forward + 去簇 + 置换。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_o3_xishou_midband.json"


def pct90(prices, i):
    """当前价在最近 90 天窗口的百分位（0-100）。"""
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    cur = prices[i]
    below = sum(1 for p in w if p <= cur)
    return below / len(w) * 100


def main():
    cyc = sqlite3.connect(CYCLE_DB)
    cyc.row_factory = sqlite3.Row
    items = cyc.execute("SELECT id, name FROM items WHERE good_id > 0 ORDER BY id").fetchall()

    xishou_bands = {"deep_<=20": [], "mid_20_60": [], "high_>60": []}
    base_mid = []  # 中段无条件基线（pct 20~60 全事件，与供缩无关）

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
            pct = pct90(prices, i)
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            if 20 < pct <= 60:
                base_mid.append({"date": dates[i], "name": it["name"], "pct": round(pct, 1),
                                 "fwd14": round(fwd14, 2), "fwd30": round(fwd30, 2)})
            # 惜售 = 供缩(s7<=0.85*s30) + 价跌(5日<-3)
            if i < 30:
                continue
            s7 = insale[i - 6:i + 1]
            s30 = insale[i - 29:i + 1]
            if any(x is None for x in s7) or any(x is None for x in s30):
                continue
            a7 = sum(s7) / 7
            a30 = sum(s30) / 30
            if a30 <= 0 or a7 > 0.85 * a30:
                continue
            chg5 = (prices[i] - prices[i - 5]) / prices[i - 5] * 100 if prices[i - 5] else 0
            if chg5 >= -3:
                continue
            band = "deep_<=20" if pct <= 20 else ("mid_20_60" if pct <= 60 else "high_>60")
            xishou_bands[band].append({"date": dates[i], "name": it["name"], "pct": round(pct, 1),
                                       "chg5": round(chg5, 1), "fwd14": round(fwd14, 2), "fwd30": round(fwd30, 2)})
    cyc.close()

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        return {"n": n,
                "win14": round(sum(1 for r in recs if r["fwd14"] > 0) / n * 100, 1),
                "avg14": round(sum(r["fwd14"] for r in recs) / n, 2),
                "win30": round(sum(1 for r in recs if r["fwd30"] > 0) / n * 100, 1),
                "avg30": round(sum(r["fwd30"] for r in recs) / n, 2)}

    dist = {k: st(v) for k, v in xishou_bands.items()}
    base = st(base_mid)

    def dedup(recs, gap=4):
        from datetime import date as D
        by_item = {}
        for r in recs:
            by_item.setdefault(r["name"], []).append(r)
        kept = []
        for name, rs in by_item.items():
            rs.sort(key=lambda x: x["date"])
            last = None
            for r in rs:
                d = D.fromisoformat(r["date"])
                if last is None or (d - last).days >= gap:
                    kept.append(r)
                    last = d
        return kept

    dedup_dist = {k: st(dedup(v)) for k, v in xishou_bands.items()}
    out = {"probe": "O3 惜售中段腿阶段0", "xishou_by_pct": dist,
           "xishou_by_pct_dedup4d": dedup_dist,
           "baseline_mid_unconditional": base}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== O3 惜售按 pct 分带 ===")
    for k, v in dist.items():
        dd = dedup_dist[k]
        print(f"  {k:12s} n={v['n']:>6}  win14={v['win14']}  avg14={v['avg14']}  win30={v['win30']}  avg30={v['avg30']} "
              f"| 去簇4d n={dd['n']} win14={dd['win14']} avg14={dd['avg14']}")
    print(f"  中段无条件基线 n={base['n']}  win14={base['win14']}  avg14={base['avg14']}  win30={base['win30']}  avg30={base['avg30']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
