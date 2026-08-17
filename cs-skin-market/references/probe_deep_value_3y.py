# -*- coding: utf-8 -*-
"""P6（H5）：deep_value 闸门 3 年重验 + 时期化（2026-08-17，预注册判据，第二批⑥）。

问题：I-13 闸门 mchg30<=-3 是 365d 96 池口径；HQ 3 年是否维持？S2 期是否可放宽？
预注册判据（跑数前锁定）：
  基础结构（引擎无关近似）：pct90<=20 且 z<=-0.5 且 drop21>=-5（不复制 th/sent 引擎量）；
  桶 U（上涨段 mchg30>=3，I-13 禁）、桶 F（横盘段 -3<=mchg30<3，I-6 禁）、桶 D（修复段 <=-3，允许）；
  判据：
    1. U 桶 fwd14 win>=55% 且 avg>=+3pp 且 n>=30，且该表现由 S2 期主导（S2 子集 win>=60%）
       → S2 放宽候选（进 A2 流程）；
    2. 否则 I-13 维持（3 年复验通过）；F 桶同规则复验 I-6。
输出 data/_exp_deep_value_3y.json。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

from pipeline.market_context import state_bucket  # noqa: E402

OUT = ROOT / "data" / "_exp_deep_value_3y.json"
EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def load_mkt():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]
    m30, m180, m21 = {}, {}, {}
    for i in range(30, len(mvals)):
        if mvals[i - 30] > 0:
            m30[mdates[i]] = (mvals[i] / mvals[i - 30] - 1) * 100
        if mvals[i - 21] > 0:
            m21[mdates[i]] = (mvals[i] / mvals[i - 21] - 1) * 100
    for i in range(180, len(mvals)):
        if mvals[i - 180] > 0:
            m180[mdates[i]] = (mvals[i] / mvals[i - 180] - 1) * 100
    return m30, m180, m21


def main():
    m30, m180, m21 = load_mkt()
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = c.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    hq = [r for r in items if not any(m in r["name"] for m in EXCL)]

    buckets = {"U_mchg>=3": {"all": [], "s2": []},
               "F_mchg(-3,3)": {"all": [], "s2": []},
               "D_mchg<=-3": {"all": [], "s2": []}}
    for r in hq:
        rows = c.execute(
            "SELECT date, price_rmb FROM price_history WHERE item_id=? AND price_rmb IS NOT NULL "
            "ORDER BY date", (r["id"],)).fetchall()
        dts = [x["date"] for x in rows]
        px = [float(x["price_rmb"]) for x in rows]
        n = len(px)
        for i in range(90, n):
            d = dts[i]
            mk = m30.get(d)
            if mk is None or i + 30 >= n or px[i] <= 0:
                continue
            w = px[i - 89:i + 1]
            cur = px[i]
            pct = sum(1 for p in w if p <= cur) / 90 * 100
            if pct > 20:
                continue
            mu = sum(w) / 90
            sd = (sum((p - mu) ** 2 for p in w) / 90) ** 0.5
            z = (cur - mu) / sd if sd > 0 else 0
            if z > -0.5 or (m21.get(d, -99) or -99) < -5:
                continue
            f14 = (px[i + 14] / cur - 1) * 100 - 2.0
            f30 = (px[i + 30] / cur - 1) * 100 - 2.0
            period = state_bucket(m180.get(d), mk)
            if mk >= 3:
                key = "U_mchg>=3"
            elif mk > -3:
                key = "F_mchg(-3,3)"
            else:
                key = "D_mchg<=-3"
            buckets[key]["all"].append((f14, f30))
            if period == "S2牛市回调":
                buckets[key]["s2"].append((f14, f30))
    c.close()

    out = {"probe": "P6 deep_value 3y 重验", "buckets": {}}
    print("== deep_value 结构 × mchg30 桶（fwd14/30，扣2%）==")
    for k in buckets:
        a14, a30 = wa([x[0] for x in buckets[k]["all"]]), wa([x[1] for x in buckets[k]["all"]])
        s14 = wa([x[0] for x in buckets[k]["s2"]])
        out["buckets"][k] = {"all14": a14, "all30": a30, "s2_14": s14}
        print("%-14s 全量 14d %s | 30d %s | S2 子集 14d %s" % (k, _f(a14), _f(a30), _f(s14)))
    u = out["buckets"]["U_mchg>=3"]
    ok_u = (u["all14"]["n"] >= 30 and u["all14"]["win"] is not None and u["all14"]["win"] >= 55
            and u["all14"]["avg"] is not None and u["all14"]["avg"] >= 3
            and u["s2_14"]["n"] >= 15 and u["s2_14"]["win"] is not None and u["s2_14"]["win"] >= 60)
    out["verdict"] = "S2 放宽候选（进 A2 流程）" if ok_u else "I-13 维持（3 年复验通过）"
    print("判定:", out["verdict"])
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
