# -*- coding: utf-8 -*-
"""黑天鹅事件日历 + 趋势腿重估（2026-08-06，用户市场知识修正）。

背景：trend_leg_research 把 10-14~18 的 S3 簇判为「崩盘前夜陷阱」；用户指出这是五合一
黑天鹅（2025-10-24，10-27 单日 -41%）外生冲击导致，非策略判断错误。同理黄盾（7月中）、
纪念品炼金（5-25）也是事件日。本脚本给每个信号的 fwd30 窗口标注事件影响，重估 S3/S2
剔除事件影响后的净期望，输出 data/trend_leg_event_study.json。
"""
import sys, io, json, os
from datetime import datetime, timedelta
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

COST = 0.02
BULL_START, BULL_END = "2025-01-01", "2025-10-31"

# 黑天鹅事件日历（用户 2026-08-06 提供；黄盾 2025-07-16 已校准）
EVENTS = [
    {"name": "纪念品炼金", "date": "2025-05-25", "impact_days": 30},
    {"name": "黄盾", "date": "2025-07-16", "impact_days": 30},
    {"name": "五合一崩盘", "date": "2025-10-24", "impact_days": 35},
]

def impact_events(dstr):
    """信号日 d 的 fwd30 窗口 [d, d+30] 与哪些事件影响期重叠 → 事件名列表"""
    d = datetime.strptime(dstr[:10], "%Y-%m-%d")
    d_end = d + timedelta(days=30)
    hits = []
    for ev in EVENTS:
        e0 = datetime.strptime(ev["date"], "%Y-%m-%d")
        e1 = e0 + timedelta(days=ev["impact_days"])
        if d <= e1 and d_end >= e0:  # 窗口重叠
            hits.append(ev["name"])
    return hits

def load_series(item_id):
    from pipeline import db
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT p.date, p.price_rmb, p.in_sale_count
           FROM price_history p WHERE p.item_id = ? AND p.id IN (
               SELECT MAX(id) FROM price_history WHERE item_id = ? GROUP BY date
           ) ORDER BY p.date""", (item_id, item_id)).fetchall()
    conn.close()
    return [r["date"] for r in rows], [r["price_rmb"] for r in rows], [r["in_sale_count"] or 0 for r in rows]

def load_items():
    from run_item_backtest import load_items as _li
    return _li()

def ma(vals, i, n):
    if i + 1 < n: return None
    s = vals[i - n + 1:i + 1]
    return sum(s) / n if len(s) == n and all(x is not None and x > 0 for x in s) else None

def chg(vals, i, n):
    if i < n or vals[i - n] <= 0: return None
    return (vals[i] / vals[i - n] - 1) * 100

def roll_mean(vals, i, n):
    s = vals[max(0, i - n + 1):i + 1]
    return sum(s) / len(s) if s else None

def s2_cond(prices, i):
    m30 = ma(prices, i, 30)
    if not m30: return False
    m7 = ma(prices, i, 7)
    c10 = chg(prices, i, 10)
    return (m7 and m7 > m30 and prices[i] >= m30 * 0.97 and prices[i] <= m30 * 1.03
            and c10 is not None and c10 >= 4)

def s3_cond(prices, in_sale, i):
    s7, s30 = roll_mean(in_sale, i, 7), roll_mean(in_sale, i, 30)
    c7 = chg(prices, i, 7)
    return (s7 is not None and s30 is not None and s30 > 0 and s7 <= s30 * 0.85
            and c7 is not None and abs(c7) <= 3)

def gate_s2(mkt):
    s = mkt["sentiment"]
    return not (s < 40) and (mkt["th"] >= 45 or s >= 60) and mkt.get("chg30", 0) > -8

def gate_s3(mkt):
    return not (mkt["sentiment"] < 40 and mkt["th"] < 45)

def build_ctx():
    from pipeline.backtest_common import build_market_context
    return build_market_context("2025-01-01", BULL_END)

def main():
    ctx = build_ctx()
    items = load_items()
    recs = {"S2": [], "S3": []}
    for iid, iname in sorted(items.items()):
        dates, prices, in_sale = load_series(iid)
        if len(prices) < 60: continue
        idx = {d: k for k, d in enumerate(dates)}
        for d in dates:
            if d < BULL_START or d > BULL_END or d not in ctx: continue
            k = idx[d]
            if k < 31: continue
            mkt = ctx[d]
            fwd14 = (prices[k+14]/prices[k]-1)*100 if k+14 < len(prices) else None
            fwd30 = (prices[k+30]/prices[k]-1)*100 if k+30 < len(prices) else None
            row = {"date": d, "item": iname, "fwd14": fwd14, "fwd30": fwd30,
                   "events": impact_events(d)}
            if s2_cond(prices, k) and gate_s2(mkt):
                recs["S2"].append(dict(row))
            if s3_cond(prices, in_sale, k) and gate_s3(mkt):
                recs["S3"].append(dict(row))
    return recs

def stats(recs, field="fwd30"):
    v = [r[field] for r in recs if r.get(field) is not None]
    if not v: return {"n": 0}
    return {"n": len(v), "win%": round(sum(1 for x in v if x > 0)/len(v)*100, 1),
            "avg%": round(sum(v)/len(v), 2), "net%": round(sum(v)/len(v) - COST*100, 2)}

def cluster(recs):
    """±3 天去簇（同 J-1 口径）"""
    ds = sorted(set(r["date"] for r in recs))
    cl = []
    for d in ds:
        dd = datetime.strptime(d, "%Y-%m-%d")
        if cl and (dd - cl[-1]["end"]).days <= 3:
            cl[-1]["end"] = dd
            cl[-1]["dates"].append(d)
        else:
            cl.append({"start": dd, "end": dd, "dates": [d]})
    out = []
    for c in cl:
        sub = [r for r in recs if r["date"] in c["dates"]]
        s = stats(sub)
        out.append({"span": f"{c['start'].strftime('%m-%d')}~{c['end'].strftime('%m-%d')}",
                    "n": s["n"], "win30": s["win%"], "avg30": s["avg%"],
                    "events": sorted(set(e for r in sub for e in r["events"]))})
    return out

if __name__ == "__main__":
    recs = main()
    out = {"generated": "2026-08-06", "events": EVENTS,
           "note": "fwd30窗口与事件影响期重叠→标 events；剔除事件影响后的净期望=策略自身贡献"}
    for k in ["S2", "S3"]:
        r = recs[k]
        clean = [x for x in r if not x["events"]]
        impacted = [x for x in r if x["events"]]
        out[k] = {
            "all": stats(r),
            "clean(剔除事件影响)": stats(clean),
            "impacted(事件影响)": stats(impacted),
            "clusters": cluster(r),
            "impacted_detail": [{"date": x["date"], "item": x["item"][:22],
                                 "fwd30": round(x["fwd30"],1) if x["fwd30"] is not None else None,
                                 "events": x["events"]} for x in impacted][:40],
        }
    json.dump(out, io.open("data/trend_leg_event_study.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:4500])