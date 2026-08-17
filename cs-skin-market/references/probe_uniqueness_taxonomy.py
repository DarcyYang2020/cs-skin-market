# -*- coding: utf-8 -*-
"""P13（H13）：独特性全景挖掘（2026-08-17，预注册判据，第二批①）。

操作定义：独特性 = 大盘序列无法解释的价格行为（单品收益 − β×大盘收益的显著残差，
β=60 日滚动）。种子两种 + 预注册候选七种，全部引擎无关（HQ 池全量 item-day）。
预注册判据（跑数前锁定）：
  升格标准：n>=30 且至少一个期限 fwd avg 显著非零（|avg| >= 2×SE，SE=std/sqrt(n)）
    → 升格为正式假设（排探针）；未达标 → 登记证伪，不再提。
  形式清单（预注册）：
    F1 逆市走强(种子): mkt30<0 且 item30>+5
    F2 逆市抗跌(种子): mkt30<-5 且 |item30|<=3
    F3 低相关独立: corr60<0.2 且 |item30|>8
    F4 领先见底: 单品60日低点早于大盘60日低点>=7天 且 大盘近14日见底
    F5 平静期异动: 大盘vol20<=0.008 且 |item_chg7|>=8
    F6 供给锁仓: pct90>70 且 sc30<=-10 且 item_chg7>=-2
    F7 新品价格发现: 品龄<90天 且 |item30|>10
输出 data/_exp_uniqueness_taxonomy.json。
"""
import json
import os
import sqlite3
import sys
import statistics
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

from pipeline.market_macro import historical_event_impact  # noqa: E402

OUT = ROOT / "data" / "_exp_uniqueness_taxonomy.json"
EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")
HORIZONS = (14, 30, 60)


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None, "se": None}
    mu = sum(vals) / n
    sd = (sum((v - mu) ** 2 for v in vals) / n) ** 0.5
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(mu, 2), "se": round(sd / (n ** 0.5), 2)}


def main():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]
    items = c.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    hq = [r for r in items if not any(m in r["name"] for m in EXCL)]
    print("HQ 品:", len(hq))

    # 大盘日特征：chg7/30/60、vol20、60日低点日期
    mkt = {}
    for i in range(len(mvals)):
        f = {}
        if i >= 7 and mvals[i - 7] > 0:
            f["chg7"] = (mvals[i] / mvals[i - 7] - 1) * 100
        if i >= 30 and mvals[i - 30] > 0:
            f["chg30"] = (mvals[i] / mvals[i - 30] - 1) * 100
        if i >= 60 and mvals[i - 60] > 0:
            f["chg60"] = (mvals[i] / mvals[i - 60] - 1) * 100
        if i >= 20:
            rets = [(mvals[j] - mvals[j - 1]) / mvals[j - 1] for j in range(i - 19, i + 1) if mvals[j - 1] > 0]
            if rets:
                mu = sum(rets) / len(rets)
                f["vol20"] = (sum((r - mu) ** 2 for r in rets) / len(rets)) ** 0.5
        if i >= 59:
            lo = min(range(i - 59, i + 1), key=lambda j: mvals[j])
            f["low60_days_ago"] = i - lo
        mkt[mdates[i]] = f
    mret = [None] + [(mvals[i] / mvals[i - 1] - 1) if mvals[i - 1] > 0 else None
                     for i in range(1, len(mvals))]
    mret_by_date = dict(zip(mdates, mret))

    forms = OrderedDict((k, {h: [] for h in HORIZONS}) for k in
                        ("F1逆市走强", "F2逆市抗跌", "F3低相关独立", "F4领先见底",
                         "F5平静期异动", "F6供给锁仓", "F7新品价格发现"))
    ev_share = {k: [0, 0] for k in forms}

    for r in hq:
        rows = c.execute(
            "SELECT date, price_rmb, in_sale_count FROM price_history "
            "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (r["id"],)).fetchall()
        dts = [x["date"] for x in rows]
        px = [float(x["price_rmb"]) for x in rows]
        sup = [x["in_sale_count"] for x in rows]
        first_dt = dts[0]
        n = len(px)
        for i in range(90, n):
            d = dts[i]
            mf = mkt.get(d)
            if mf is None or i + 60 >= n:
                continue
            cur = px[i]
            c7 = (cur / px[i - 7] - 1) * 100 if i >= 7 and px[i - 7] > 0 else None
            c30 = (cur / px[i - 30] - 1) * 100 if i >= 30 and px[i - 30] > 0 else None
            if c7 is None or c30 is None:
                continue
            # pct90 / z / sc30 / corr60 / beta60
            w = px[i - 89:i + 1]
            pct = sum(1 for p in w if p <= cur) / 90 * 100
            mu = sum(w) / 90
            sd = (sum((p - mu) ** 2 for p in w) / 90) ** 0.5
            z = (cur - mu) / sd if sd > 0 else 0.0
            sc30 = None
            if sup[i] is not None and sup[i - 30] is not None:
                s7 = sum(x for x in sup[i - 6:i + 1] if x is not None) / 7
                s30 = sum(x for x in sup[i - 29:i + 1] if x is not None) / 30
                sc30 = (s7 / s30 - 1) * 100 if s30 > 0 else None
            irets = [(px[j] / px[j - 1] - 1) for j in range(i - 59, i + 1) if px[j - 1] > 0]
            mrets = [mret_by_date.get(dts[j]) for j in range(i - 59, i + 1)]
            pairs = [(a, b) for a, b in zip(irets, mrets) if a is not None and b is not None]
            corr60 = beta60 = None
            if len(pairs) >= 30:
                ia_ = [a for a, _ in pairs]
                ib_ = [b for _, b in pairs]
                if statistics.pstdev(ia_) > 0 and statistics.pstdev(ib_) > 0:
                    corr60 = statistics.correlation(ia_, ib_)
                    beta60 = corr60 * statistics.pstdev(ia_) / statistics.pstdev(ib_)
            # 60 日低点（单品）
            lo_i = min(range(i - 59, i + 1), key=lambda j: px[j])
            item_low60_days_ago = i - lo_i
            age_days = (__import__("datetime").date.fromisoformat(d) -
                        __import__("datetime").date.fromisoformat(first_dt)).days
            fwd = {}
            for h in HORIZONS:
                fwd[h] = (px[i + h] / cur - 1) * 100 - 2.0

            hit = None
            if mf.get("chg30", 0) < 0 and c30 > 5:
                hit = "F1逆市走强"
            elif mf.get("chg30", 0) < -5 and abs(c30) <= 3:
                hit = "F2逆市抗跌"
            elif corr60 is not None and corr60 < 0.2 and abs(c30) > 8:
                hit = "F3低相关独立"
            elif mf.get("low60_days_ago") is not None and mf["low60_days_ago"] <= 14 \
                    and item_low60_days_ago >= mf["low60_days_ago"] + 7:
                hit = "F4领先见底"
            elif mf.get("vol20") is not None and mf["vol20"] <= 0.008 and abs(c7) >= 8:
                hit = "F5平静期异动"
            elif pct > 70 and sc30 is not None and sc30 <= -10 and c7 >= -2:
                hit = "F6供给锁仓"
            elif age_days < 90 and abs(c30) > 10:
                hit = "F7新品价格发现"
            if hit:
                for h in HORIZONS:
                    forms[hit][h].append(fwd[h])
                ev_share[hit][1] += 1
                if historical_event_impact(d, horizon_days=30):
                    ev_share[hit][0] += 1
    c.close()

    out = {"probe": "P13 独特性全景挖掘", "forms": {}}
    print("== 独特性形式表（升格标准：n>=30 且 |avg|>=2SE）==")
    for k in forms:
        row = {str(h): wa(forms[k][h]) for h in HORIZONS}
        n = row["14"]["n"]
        up = any(row[str(h)]["n"] >= 30 and row[str(h)]["avg"] is not None and row[str(h)]["se"]
                 and abs(row[str(h)]["avg"]) >= 2 * row[str(h)]["se"] for h in HORIZONS)
        ev = ev_share[k]
        out["forms"][k] = {"horizons": row,
                           "event_share_pct": round(100.0 * ev[0] / ev[1], 1) if ev[1] else None,
                           "verdict": "升格" if up else "证伪"}
        print("%-12s n=%4d | 14d %s | 30d %s | 60d %s | 事件占比=%s → %s" % (
            k, n, _f(row["14"]), _f(row["30"]), _f(row["60"]),
            out["forms"][k]["event_share_pct"], out["forms"][k]["verdict"]))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s se=%s" % (x["n"], x["win"], x["avg"], x["se"])


if __name__ == "__main__":
    main()
