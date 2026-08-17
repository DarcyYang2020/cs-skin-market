# -*- coding: utf-8 -*-
"""P12（H12）：market_weak 独立强势豁免（2026-08-17，预注册判据，第二批③）。

问题：守卫1 大盘走弱（TH<45 且 chg30<0）一刀切禁买——逆市强势品是否该豁免？
数据：大盘走弱日（M1 状态：th<45 且 chg30<0）× 全量 item-day 分层。
预注册判据（跑数前锁定）：
  组 S（强势）= 大盘走弱日 ∩ 单品 chg30>+5；
  组 A（全体）= 大盘走弱日全部 item-day（引擎无关朴素池）；
  判据：n(S)>=10 且 (avg14(S) − avg14(A)) >= 10pp 且 avg30 同方向 ≥5pp → 豁免候选；
  否则 H12 证伪（维持一刀切）。
输出 data/_exp_market_weak_exemption.json。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_market_weak_exemption.json"
EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def main():
    st = json.load(open(ROOT / "data" / "market_state_daily.json", encoding="utf-8"))
    weak_days = {d for d, s in st.items()
                 if "chg30" in s and "chg180" in s and (s.get("th") or 100) < 45 and s["chg30"] < 0}
    print("大盘走弱日（th<45 & chg30<0）:", len(weak_days))

    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = c.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    hq = [r for r in items if not any(m in r["name"] for m in EXCL)]
    strong, allp = [], []
    for r in hq:
        rows = c.execute(
            "SELECT date, price_rmb FROM price_history WHERE item_id=? AND price_rmb IS NOT NULL "
            "ORDER BY date", (r["id"],)).fetchall()
        dts = [x["date"] for x in rows]
        px = [float(x["price_rmb"]) for x in rows]
        n = len(px)
        for i in range(30, n):
            if dts[i] not in weak_days or i + 30 >= n or px[i - 30] <= 0 or px[i] <= 0:
                continue
            cur = px[i]
            c30 = (cur / px[i - 30] - 1) * 100
            f14 = (px[i + 14] / cur - 1) * 100 - 2.0
            f30 = (px[i + 30] / cur - 1) * 100 - 2.0
            allp.append((f14, f30))
            if c30 > 5:
                strong.append((f14, f30))
    c.close()
    ra, rs = wa([x[0] for x in allp]), wa([x[0] for x in strong])
    ta, ts = wa([x[1] for x in allp]), wa([x[1] for x in strong])
    ok = (rs["n"] >= 10 and rs["avg"] is not None and ra["avg"] is not None and
          rs["avg"] - ra["avg"] >= 10 and ts["avg"] is not None and ta["avg"] is not None and
          ts["avg"] - ta["avg"] >= 5)
    out = {"probe": "P12 market_weak 豁免", "weak_days": len(weak_days),
           "all": {"n14": ra, "n30": ta}, "strong": {"n14": rs, "n30": ts},
           "diff14": round(rs["avg"] - ra["avg"], 2) if rs["avg"] is not None and ra["avg"] is not None else None,
           "diff30": round(ts["avg"] - ta["avg"], 2) if ts["avg"] is not None and ta["avg"] is not None else None,
           "verdict": "豁免候选（进发射口径三关）" if ok else "证伪：维持一刀切"}
    print("全体(A): 14d %s | 30d %s" % (_f(ra), _f(ta)))
    print("强势(S): 14d %s | 30d %s" % (_f(rs), _f(ts)))
    print("差值: 14d %+.2fpp | 30d %+.2fpp → %s" % (
        out["diff14"], out["diff30"], out["verdict"]))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
