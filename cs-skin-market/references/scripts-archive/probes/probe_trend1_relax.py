# -*- coding: utf-8 -*-
"""TREND-1 放宽实验（只读，真 TH，参数化回调带宽 + 分位上限）。

逐层放宽：默认 L3 回调 8~15% / L6 分位 60%；--dd-lo/--dd-hi/--pct 可调。
报 sent>30 组的 参与度（条/月）/ 14d net / 30d net / vs 多头门内基线超额（基线 avg14 +0.98%）。
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.trend_health import compute_trend_health  # noqa: E402

DB = ROOT / "data" / "replay_cycle_win.db"
START, END = "2024-09-01", "2025-05-31"
BASELINE_AVG14 = 0.98  # 多头门内无条件买入基线 14d net


def ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dd-lo", type=float, default=8.0, help="回撤下限 %（正数，如 8 表示距高点 -8%）")
    ap.add_argument("--dd-hi", type=float, default=15.0, help="回撤上限 %（正数，如 15 表示距高点 -15%）")
    ap.add_argument("--pct", type=float, default=60.0, help="90 日分位上限 %")
    ap.add_argument("--out", default=str(ROOT / "data" / "_exp_trend1_relax.json"))
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    mrows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [r["value"] for r in mrows]
    regime = {}
    for i in range(90, len(mvals)):
        ma30 = sum(mvals[i - 29:i + 1]) / 30
        ma90 = sum(mvals[i - 89:i + 1]) / 90
        regime[mdates[i]] = ma30 > ma90

    items = conn.execute("SELECT id, name, good_id FROM items WHERE good_id > 0 ORDER BY id").fetchall()
    series = {}
    for it in items:
        rows = conn.execute(
            "SELECT date, price_rmb, in_sale_count FROM price_history WHERE item_id=? "
            "AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
        series[it["id"]] = {
            "name": it["name"],
            "dates": [r["date"] for r in rows],
            "price": [r["price_rmb"] for r in rows],
            "insale": [r["in_sale_count"] for r in rows],
        }
    conn.close()

    recs = []
    for iid, s in series.items():
        dates, price, insale = s["dates"], s["price"], s["insale"]
        n = len(price)
        for i in range(90, n):
            d = dates[i]
            if not (START <= d <= END):
                continue
            if i + 30 >= n:
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
            if not (-args.dd_hi <= dd30 <= -args.dd_lo):
                continue
            if i >= 3 and price[i] < min(price[i - 3:i]):
                continue
            if i >= 7 and insale[i] is not None and insale[i - 7] and insale[i - 7] > 0:
                if (insale[i] - insale[i - 7]) / insale[i - 7] * 100 > 5.0:
                    continue
            win90 = price[max(0, i - 89):i + 1]
            pct90 = sum(1 for p in win90 if p <= price[i]) / len(win90) * 100
            if pct90 > args.pct:
                continue
            mi = mdates.index(d) if d in mdates else -1
            if mi < 0:
                continue
            chg7 = (mvals[mi] / mvals[mi - 7] - 1) * 100
            chg14 = (mvals[mi] / mvals[mi - 14] - 1) * 100
            sent = max(10.0, min(90.0, 50 - chg7 * 2 - chg14))
            fwd14 = (price[i + 14] / price[i] - 1) * 100 - 2.0
            fwd30 = (price[i + 30] / price[i] - 1) * 100 - 2.0
            recs.append({"date": d, "name": s["name"], "sent": round(sent, 1),
                         "dd30": round(dd30, 1), "pct90": round(pct90, 1),
                         "fwd14": round(fwd14, 2), "fwd30": round(fwd30, 2)})

    gt = [r for r in recs if r["sent"] > 30]
    le = [r for r in recs if r["sent"] <= 30]
    months = 9.0

    def st(rs):
        n = len(rs)
        if n == 0:
            return {"n": 0, "per_month": 0.0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        win14 = sum(1 for r in rs if r["fwd14"] > 0) / n * 100
        avg14 = sum(r["fwd14"] for r in rs) / n
        win30 = sum(1 for r in rs if r["fwd30"] > 0) / n * 100
        avg30 = sum(r["fwd30"] for r in rs) / n
        return {"n": n, "per_month": round(n / months, 1), "win14": round(win14, 1),
                "avg14": round(avg14, 2), "win30": round(win30, 1), "avg30": round(avg30, 2)}

    gts = st(gt)
    les = st(le)
    excess = round(gts["avg14"] - BASELINE_AVG14, 2) if gts["avg14"] is not None else None
    out = {
        "probe": "TREND-1 放宽实验", "dd_range": f"{args.dd_lo}~{args.dd_hi}%", "pct_cap": args.pct,
        "sent_gt30": gts, "sent_le30": les, "baseline_avg14": BASELINE_AVG14,
        "excess_vs_baseline_pp": excess,
        "verdict": "达标 = 参与度>=8条/月 且 excess>=+2pp",
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== 放宽 dd={args.dd_lo}~{args.dd_hi}% pct<={args.pct}% ===")
    print("sent>30:", json.dumps(gts, ensure_ascii=False), "| 超额 vs 基线:", excess, "pp")
    print("sent<=30:", json.dumps(les, ensure_ascii=False))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
