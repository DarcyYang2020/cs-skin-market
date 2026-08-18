# -*- coding: utf-8 -*-
"""TREND-1 逐层漏斗分析（只读，真 TH）。

窗口 2024-09~2025-05 牛市拟合段，同 96 品池，逐层报每层砍掉的信号数，
定位七层条件 AND 叠加的结构性矛盾瓶颈（TH≥55 / 回调 8~15% / 分位≤60%）。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.trend_health import compute_trend_health  # noqa: E402

DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_trend1_funnel.json"
START, END = "2024-09-01", "2025-05-31"


def ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


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

    # 漏斗计数器（顺序：L0 全量 → L1 regime → L2 TH+MA30 → L3 回调 → L4 3日不新低 → L5 供给 → L6 分位 → L7 sent>30）
    cnt = {"L0_all": 0, "L1_regime": 0, "L2a_above_ma30": 0, "L2b_th55": 0,
           "L3_drawdown": 0, "L4_no_new_low": 0, "L5_supply": 0, "L6_pct60": 0,
           "L7_sent_gt30": 0, "L7_sent_le30": 0}

    for iid, s in series.items():
        dates, price, insale = s["dates"], s["price"], s["insale"]
        n = len(price)
        for i in range(90, n):
            d = dates[i]
            if not (START <= d <= END):
                continue
            if i + 30 >= n:
                continue
            cnt["L0_all"] += 1
            if not regime.get(d):
                continue
            cnt["L1_regime"] += 1
            p30 = ma(price[:i + 1], 30)
            if p30 is None or not (price[i] > p30):
                continue
            cnt["L2a_above_ma30"] += 1
            th_obj = compute_trend_health(price[:i + 1], supply=insale[:i + 1])
            if getattr(th_obj, "score", 0) < 55:
                continue
            cnt["L2b_th55"] += 1
            hi30 = max(price[max(0, i - 29):i + 1])
            dd30 = (price[i] - hi30) / hi30 * 100 if hi30 > 0 else 0
            if not (-15.0 <= dd30 <= -8.0):
                continue
            cnt["L3_drawdown"] += 1
            if i >= 3 and price[i] < min(price[i - 3:i]):
                continue
            cnt["L4_no_new_low"] += 1
            if i >= 7 and insale[i] is not None and insale[i - 7] and insale[i - 7] > 0:
                if (insale[i] - insale[i - 7]) / insale[i - 7] * 100 > 5.0:
                    continue
            cnt["L5_supply"] += 1
            win90 = price[max(0, i - 89):i + 1]
            pct90 = sum(1 for p in win90 if p <= price[i]) / len(win90) * 100
            if pct90 > 60.0:
                continue
            cnt["L6_pct60"] += 1
            # sent（近似口径）
            mi = mdates.index(d) if d in mdates else -1
            if mi < 0:
                continue
            chg7 = (mvals[mi] / mvals[mi - 7] - 1) * 100
            chg14 = (mvals[mi] / mvals[mi - 14] - 1) * 100
            sent = max(10.0, min(90.0, 50 - chg7 * 2 - chg14))
            if sent > 30:
                cnt["L7_sent_gt30"] += 1
            else:
                cnt["L7_sent_le30"] += 1

    out = {"probe": "TREND-1 逐层漏斗", "window": f"{START}~{END}", "funnel": cnt}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== TREND-1 逐层漏斗（2024-09~2025-05）===")
    labels = [
        ("L0 全量牛市基线", "L0_all"),
        ("L1 regime 门(多头排列)", "L1_regime"),
        ("L2a 站上 MA30", "L2a_above_ma30"),
        ("L2b TH≥55(真)", "L2b_th55"),
        ("L3 回调 8~15%", "L3_drawdown"),
        ("L4 3日不新低", "L4_no_new_low"),
        ("L5 供给 7日不扩张>5%", "L5_supply"),
        ("L6 90日分位≤60%", "L6_pct60"),
        ("L7 sent>30", "L7_sent_gt30"),
        ("L7 sent≤30", "L7_sent_le30"),
    ]
    prev = None
    for lab, key in labels:
        v = cnt[key]
        cut = "" if prev is None else f"（砍 {prev - v}）"
        print(f"  {lab:26s} {v:>7}{cut}")
        prev = v
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
