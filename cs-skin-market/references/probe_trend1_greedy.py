# -*- coding: utf-8 -*-
"""TREND-1 第一号贪婪禁买实验（只读探针，stage-0）。

范围 = references/v3-engine-enhance-2026-08-15.md §2/§4/§6。
扫 2024-09~2025-05 牛市拟合段，找 TREND-1 回调买点，分 sent<=30 vs sent>30 两组，
报 14d/30d 胜率 + net 期望 + 信号数（对照组增量判定）。

数据源：replay_cycle_win.db（96 品日线价 + 在售量 + market_index）。
sent = 价格近似情绪 approx_sentiment（2024-09~2025-05 无真实贪婪指数，macro_history 只到 2026-02-03）。

TREND-1 预注册条件（本探针的 stage-0 可回测近似）：
  大盘 regime：指数 MA30 > MA90（多头排列）
  单品趋势：price > MA30 且 MA7 > MA30（TH>=55 的 stage-0 代理）
  回调深度：距 30 日高点 -15% <= dd30 <= -8%
  止跌：当日 close 不低于近 3 日最低 close
  供给：在售量 7 日变化 <= +5%（不扩张）
  估值：90 日分位 <= 60%
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.trend_health import compute_trend_health  # noqa: E402

DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_trend1_greedy.json"
START, END = "2024-09-01", "2025-05-31"


def approx_sent(vals, i):
    if i < 14:
        return 50.0
    chg7 = (vals[i] / vals[i - 7] - 1) * 100
    chg14 = (vals[i] / vals[i - 14] - 1) * 100
    return max(10.0, min(90.0, 50 - chg7 * 2 - chg14))


def ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # market_index
    mrows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [r["value"] for r in mrows]
    m_by_date = {r["date"]: r["value"] for r in mrows}

    # 96 品 price + in_sale
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

    # market MA30/MA90 per day
    m_ma30 = {}
    m_ma90 = {}
    for i in range(len(mvals)):
        d = mdates[i]
        if i + 1 >= 30:
            m_ma30[d] = sum(mvals[i - 29:i + 1]) / 30
        if i + 1 >= 90:
            m_ma90[d] = sum(mvals[i - 89:i + 1]) / 90

    groups = {"le30": [], "gt30": []}
    for iid, s in series.items():
        dates, price, insale = s["dates"], s["price"], s["insale"]
        n = len(price)
        for i in range(90, n):
            d = dates[i]
            if not (START <= d <= END):
                continue
            if d not in m_ma30 or d not in m_ma90:
                continue
            # 大盘 regime 门：MA30 > MA90
            if not (m_ma30[d] > m_ma90[d]):
                continue
            mi = mdates.index(d) if d in mdates else -1
            if mi < 0:
                continue
            sent = approx_sent(mvals, mi)
            # 单品趋势：price > MA30（TH>=55 用真 compute_trend_health，便宜过滤后再算）
            p30 = ma(price[:i + 1], 30)
            if p30 is None:
                continue
            if not (price[i] > p30):
                continue
            # 回调深度：距 30 日高点 -15% <= dd30 <= -8%
            hi30 = max(price[max(0, i - 29):i + 1])
            dd30 = (price[i] - hi30) / hi30 * 100 if hi30 > 0 else 0
            if not (-15.0 <= dd30 <= -8.0):
                continue
            # 止跌：近 3 日不创新低（当日 close >= 前 3 日最低 close）
            if i >= 3 and price[i] < min(price[i - 3:i]):
                continue
            # 供给：7 日不扩张 >5%
            if i >= 7 and insale[i] is not None and insale[i - 7] and insale[i - 7] > 0:
                s7 = (insale[i] - insale[i - 7]) / insale[i - 7] * 100
                if s7 > 5.0:
                    continue
            # 估值：90 日分位 <= 60%
            win90 = price[max(0, i - 89):i + 1]
            pct90 = sum(1 for p in win90 if p <= price[i]) / len(win90) * 100
            if pct90 > 60.0:
                continue
            # TH 换真：compute_trend_health >= 55（预注册条件，非 MA7>MA30 代理）
            th_obj = compute_trend_health(price[:i + 1], supply=insale[:i + 1])
            th_score = getattr(th_obj, "score", 0)
            if th_score < 55:
                continue
            # 前向收益（net 2%）
            fwd14 = None
            fwd30 = None
            if i + 14 < n:
                fwd14 = (price[i + 14] / price[i] - 1) * 100 - 2.0
            if i + 30 < n:
                fwd30 = (price[i + 30] / price[i] - 1) * 100 - 2.0
            rec = {"item": iid, "name": s["name"], "date": d, "sent": round(sent, 1),
                   "dd30": round(dd30, 1), "fwd14": round(fwd14, 2) if fwd14 is not None else None,
                   "fwd30": round(fwd30, 2) if fwd30 is not None else None}
            (groups["le30"] if sent <= 30 else groups["gt30"]).append(rec)

    def stats(recs):
        n = len(recs)
        w14 = [r for r in recs if r["fwd14"] is not None]
        w30 = [r for r in recs if r["fwd30"] is not None]
        win14 = sum(1 for r in w14 if r["fwd14"] > 0) / len(w14) * 100 if w14 else None
        avg14 = sum(r["fwd14"] for r in w14) / len(w14) if w14 else None
        win30 = sum(1 for r in w30 if r["fwd30"] > 0) / len(w30) * 100 if w30 else None
        avg30 = sum(r["fwd30"] for r in w30) / len(w30) if w30 else None
        return {"n": n, "n14": len(w14), "win14": round(win14, 1) if win14 is not None else None,
                "avg14": round(avg14, 2) if avg14 is not None else None,
                "n30": len(w30), "win30": round(win30, 1) if win30 is not None else None,
                "avg30": round(avg30, 2) if avg30 is not None else None}

    le = stats(groups["le30"])
    gt = stats(groups["gt30"])
    out = {
        "probe": "TREND-1 第一号贪婪禁买实验",
        "generated": "2026-08-15",
        "window": f"{START}~{END}",
        "sent_caliber": "价格近似情绪 approx_sentiment（无真实贪婪指数，macro_history 只到 2026-02-03）",
        "sent_le30": le, "sent_gt30": gt,
        "verdict_rule": "sent<=30 vs sent>30 对照：无显著差异或 <=30 更差 → 不豁免；<=30 显著不差(阈值内) → 谈豁免",
        "signals_le30": groups["le30"], "signals_gt30": groups["gt30"],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== sent<=30 组 ===")
    print(json.dumps(le, ensure_ascii=False))
    print("=== sent>30 组 ===")
    print(json.dumps(gt, ensure_ascii=False))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
