# -*- coding: utf-8 -*-
"""TREND-TIGHT-1 regime 门加严复验（只读，真 TH，最后一发子弹）。

regime 门加严：现价>MA30 且 MA30>MA90 且 mchg30>0 且 距60日高点回撤<=10%。
只回答一个问题：加严后「真趋势回调腿」还是不是正期望。不落地、不改引擎。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.trend_health import compute_trend_health  # noqa: E402

DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_trend_tight_1.json"
START, END = "2025-08-10", "2026-08-05"

WINDOWS = [
    ("W1_真趋势", "2025-08-10", "2025-10-24"),
    ("W2_V反弹", "2025-11-01", "2025-12-31"),
    ("W3_陷阱", "2026-02-01", "2026-03-31"),
    ("W4_恐慌反弹", "2026-05-27", "2026-06-10"),
]


def ma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def decluster(signals, day_gap=3):
    from datetime import datetime
    ss = sorted(signals, key=lambda x: x["date"])
    clusters = []
    for s in ss:
        if clusters and (datetime.fromisoformat(s["date"]) -
                         datetime.fromisoformat(clusters[-1][-1]["date"])).days <= day_gap:
            clusters[-1].append(s)
        else:
            clusters.append([s])
    return clusters


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    mrows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [r["value"] for r in mrows]
    regime = {}
    for i in range(90, len(mvals)):
        ma30 = sum(mvals[i - 29:i + 1]) / 30
        ma90 = sum(mvals[i - 89:i + 1]) / 90
        mchg30 = (mvals[i] - mvals[i - 30]) / mvals[i - 30] * 100
        hi60 = max(mvals[max(0, i - 59):i + 1])
        dd60 = (mvals[i] - hi60) / hi60 * 100 if hi60 > 0 else 0
        # 加严：现价>MA30 且 MA30>MA90 且 mchg30>0 且 距60日高点回撤<=10%
        regime[mdates[i]] = (mvals[i] > ma30 and ma30 > ma90 and mchg30 > 0 and dd60 >= -10.0)

    items = conn.execute("SELECT id, name, good_id FROM items WHERE good_id > 0 ORDER BY id").fetchall()
    series = {}
    for it in items:
        rows = conn.execute(
            "SELECT date, price_rmb, in_sale_count FROM price_history WHERE item_id=? "
            "AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
        series[it["id"]] = {"name": it["name"], "dates": [r["date"] for r in rows],
                            "price": [r["price_rmb"] for r in rows],
                            "insale": [r["in_sale_count"] for r in rows]}
    conn.close()

    sigs = []
    for iid, s in series.items():
        dates, price, insale = s["dates"], s["price"], s["insale"]
        n = len(price)
        for i in range(90, n):
            d = dates[i]
            if not (START <= d <= END):
                continue
            if i + 14 >= n:
                continue
            if not regime.get(d):
                continue
            p30 = ma(price[:i + 1], 30)
            if p30 is None or not (price[i] > p30):
                continue
            th_obj = compute_trend_health(price[:i + 1], supply=insale[:i + 1])
            if getattr(th_obj, "score", 0) < 55:
                continue
            hi30 = max(price[max(0, i - 29):i + 1])
            dd30 = (price[i] - hi30) / hi30 * 100 if hi30 > 0 else 0
            if not (-20.0 <= dd30 <= -5.0):
                continue
            if i >= 3 and price[i] < min(price[i - 3:i]):
                continue
            if i >= 7 and insale[i] is not None and insale[i - 7] and insale[i - 7] > 0:
                if (insale[i] - insale[i - 7]) / insale[i - 7] * 100 > 5.0:
                    continue
            win90 = price[max(0, i - 89):i + 1]
            pct90 = sum(1 for p in win90 if p <= price[i]) / len(win90) * 100
            if pct90 > 75.0:
                continue
            mi = mdates.index(d) if d in mdates else -1
            if mi < 0:
                continue
            chg7 = (mvals[mi] / mvals[mi - 7] - 1) * 100
            chg14 = (mvals[mi] / mvals[mi - 14] - 1) * 100
            sent = max(10.0, min(90.0, 50 - chg7 * 2 - chg14))
            if sent <= 30:
                continue
            fwd14 = (price[i + 14] / price[i] - 1) * 100 - 2.0
            fwd30 = (price[i + 30] / price[i] - 1) * 100 - 2.0 if i + 30 < n else None
            sigs.append({"item": iid, "name": s["name"], "date": d, "sent": round(sent, 1),
                         "dd30": round(dd30, 1), "pct90": round(pct90, 1),
                         "fwd14": round(fwd14, 2), "fwd30": round(fwd30, 2) if fwd30 is not None else None})

    def st(rs):
        n = len(rs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        w14 = [r for r in rs if r["fwd14"] is not None]
        w30 = [r for r in rs if r["fwd30"] is not None]
        return {"n": n,
                "win14": round(sum(1 for r in w14 if r["fwd14"] > 0) / len(w14) * 100, 1) if w14 else None,
                "avg14": round(sum(r["fwd14"] for r in w14) / len(w14), 2) if w14 else None,
                "win30": round(sum(1 for r in w30 if r["fwd30"] > 0) / len(w30) * 100, 1) if w30 else None,
                "avg30": round(sum(r["fwd30"] for r in w30) / len(w30), 2) if w30 else None}

    by_win = {wn: st([s for s in sigs if ws <= s["date"] <= we]) for wn, ws, we in WINDOWS}
    w1w2 = [s for s in sigs if s["date"] >= "2025-08-10" and s["date"] <= "2025-12-31"]
    w1w2_clusters = decluster(w1w2)
    w3_n = by_win["W3_陷阱"]["n"]
    w1_n = by_win["W1_真趋势"]["n"]

    criteria = {
        "W3 陷阱归零": w3_n == 0,
        "W1 保留(>=4)": w1_n >= 4,
        "W1+W2 14d net 正期望": st(w1w2)["avg14"] is not None and st(w1w2)["avg14"] > 0,
        "去簇后 W1+W2 >=5": len(w1w2_clusters) >= 5,
    }
    verdict = "真趋势腿复活（立项 TREND-TIGHT-1）" if all(criteria.values()) else "收益增强器本轮收口（回风控器）"

    out = {
        "probe": "TREND-TIGHT-1 regime 门加严复验", "window": f"{START}~{END}",
        "regime": "现价>MA30 且 MA30>MA90 且 mchg30>0 且 距60日高点回撤<=10%",
        "n_signals": len(sigs), "by_window": by_win,
        "w1w2": st(w1w2), "w1w2_clusters": len(w1w2_clusters),
        "criteria": criteria, "verdict": verdict, "signals": sigs,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== TREND-TIGHT-1 regime 门加严复验 ===")
    print("总信号:", len(sigs))
    for wn, ws, we in WINDOWS:
        print(f"  {wn}: {json.dumps(by_win[wn], ensure_ascii=False)}")
    print("W1+W2 合计:", json.dumps(st(w1w2), ensure_ascii=False), "| 去簇:", len(w1w2_clusters))
    for k, v in criteria.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print("判定:", verdict)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
