# -*- coding: utf-8 -*-
"""P4（H2）：相对强度因子（2026-08-17，预注册判据，第二批④）。

问题：单品 vs 大盘的超额动量（相对强度）能否判别长持结构（抽象派/合纵类）？
预注册判据（跑数前锁定）：
  1. 桶：RS30=单品30d−大盘30d>10；RS90=单品90d−大盘90d>20；RS30&RS90 双条件；
     各桶再按供给（sc30≤0 供稳/收缩）拆一层；
  2. 长持结构成立标准：桶 n>=30 且 fwd60 与 fwd180 同时 |avg|>=2SE 为正；
  3. 互补性：RS30 桶中不满足 rise_contract 指纹（sc30<=-5 且 chg7 3~15 且 pct>40）的子集
     fwd60 仍显著为正 → RS 有独立增量；否则 RS 被 rise_contract 覆盖，无增量。
输出 data/_exp_relative_strength.json。
"""
import json
import os
import sqlite3
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_relative_strength.json"
EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")


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
    m30, m90 = {}, {}
    for i in range(90, len(mvals)):
        if mvals[i - 30] > 0:
            m30[mdates[i]] = (mvals[i] / mvals[i - 30] - 1) * 100
        if mvals[i - 90] > 0:
            m90[mdates[i]] = (mvals[i] / mvals[i - 90] - 1) * 100
    items = c.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    hq = [r for r in items if not any(m in r["name"] for m in EXCL)]

    buckets = OrderedDict((k, {"f60": [], "f180": [], "complement": []}) for k in
                          ("RS30>10", "RS90>20", "RS30>10&RS90>20"))
    for r in hq:
        rows = c.execute(
            "SELECT date, price_rmb, in_sale_count FROM price_history "
            "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (r["id"],)).fetchall()
        dts = [x["date"] for x in rows]
        px = [float(x["price_rmb"]) for x in rows]
        sup = [x["in_sale_count"] for x in rows]
        n = len(px)
        for i in range(90, n):
            d = dts[i]
            if d not in m30 or d not in m90 or i + 180 >= n or px[i - 90] <= 0 or px[i] <= 0:
                continue
            cur = px[i]
            i30 = (cur / px[i - 30] - 1) * 100
            i90 = (cur / px[i - 90] - 1) * 100
            rs30, rs90 = i30 - m30[d], i90 - m90[d]
            f60 = (px[i + 60] / cur - 1) * 100 - 2.0
            f180 = (px[i + 180] / cur - 1) * 100 - 2.0
            chg7 = (cur / px[i - 7] - 1) * 100 if i >= 7 and px[i - 7] > 0 else None
            pct = sum(1 for p in px[i - 89:i + 1] if p <= cur) / 90 * 100
            sc30 = None
            if i >= 29 and sup[i] is not None:
                s7 = sum(x for x in sup[i - 6:i + 1] if x is not None) / 7
                s30 = sum(x for x in sup[i - 29:i + 1] if x is not None) / 30
                sc30 = (s7 / s30 - 1) * 100 if s30 > 0 else None
            is_rc = (sc30 is not None and sc30 <= -5 and chg7 is not None and 3 < chg7 <= 15
                     and pct > 40)
            for k in buckets:
                hit = (k == "RS30>10" and rs30 > 10) or \
                      (k == "RS90>20" and rs90 > 20) or \
                      (k == "RS30>10&RS90>20" and rs30 > 10 and rs90 > 20)
                if hit:
                    buckets[k]["f60"].append(f60)
                    buckets[k]["f180"].append(f180)
                    if not is_rc:
                        buckets[k]["complement"].append(f60)

    out = {"probe": "P4 相对强度", "buckets": {}}
    print("== 相对强度桶（fwd60/fwd180，扣2%）==")
    for k in buckets:
        b = buckets[k]
        r60, r180 = wa(b["f60"]), wa(b["f180"])
        sig = (r60["n"] >= 30 and r60["avg"] is not None and r60["se"] and
               abs(r60["avg"]) >= 2 * r60["se"] and
               r180["n"] >= 30 and r180["avg"] is not None and r180["se"] and
               abs(r180["avg"]) >= 2 * r180["se"])
        comp = wa(b["complement"])
        out["buckets"][k] = {"n60": r60, "n180": r180,
                             "complement_60": comp, "long_structure": bool(sig)}
        print("%-18s 60d %s | 180d %s | 长持成立=%s | 互补子集60d %s" % (
            k, _f(r60), _f(r180), sig, _f(comp)))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s se=%s" % (x["n"], x["win"], x["avg"], x["se"])


if __name__ == "__main__":
    main()
