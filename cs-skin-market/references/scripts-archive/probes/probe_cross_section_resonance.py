# -*- coding: utf-8 -*-
"""P5（H3）：截面共振度（2026-08-17，预注册判据，第二批⑤）。

问题："P 期大盘深跌+全员超跌"（共振抄底）vs"大盘平稳时单品独跌"（接刀），
引擎现在长得一样。共振度能否作为前置条件？
预注册判据（跑数前锁定）：
  组 R（共振）：大盘 chg30<=-15 且 单品 pct90<=20 且 z<=-1；
  组 I（独跌）：|大盘 chg30|<=5 且 单品 pct90<=20 且 z<=-1；
  判据 1：avg14(R) − avg14(I) >= 10pp（共振显著优于独跌）→ 第一关；
  判据 2（事件一致性）：R 按两大事件簇拆分（2025-10 五合一 / 2026-05 炼金），
     两组各自 fwd14 win>=80% → 第二关（防单事件偶然）；
  两关全过 → 共振前置条件候选（进发射口径三关）；否则 H3 证伪。
输出 data/_exp_cross_section_resonance.json。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_cross_section_resonance.json"
EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def main():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]
    m30 = {}
    for i in range(30, len(mvals)):
        if mvals[i - 30] > 0:
            m30[mdates[i]] = (mvals[i] / mvals[i - 30] - 1) * 100
    items = c.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    hq = [r for r in items if not any(m in r["name"] for m in EXCL)]

    R, I = [], []
    R_2025, R_2026 = [], []
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
            if z > -1:
                continue
            f14 = (px[i + 14] / cur - 1) * 100 - 2.0
            f30 = (px[i + 30] / cur - 1) * 100 - 2.0
            if mk <= -15:
                R.append((f14, f30))
                (R_2025 if d.startswith("2025") else R_2026).append(f14)
            elif abs(mk) <= 5:
                I.append((f14, f30))
    c.close()
    r14, i14 = wa([x[0] for x in R]), wa([x[0] for x in I])
    r30, i30 = wa([x[1] for x in R]), wa([x[1] for x in I])
    w2025, w2026 = wa(R_2025), wa(R_2026)
    ok1 = r14["n"] >= 10 and i14["n"] >= 10 and r14["avg"] - i14["avg"] >= 10
    ok2 = (w2025["n"] >= 5 and w2025["win"] is not None and w2025["win"] >= 80 and
           w2026["n"] >= 5 and w2026["win"] is not None and w2026["win"] >= 80)
    out = {"probe": "P5 截面共振度", "R": {"n14": r14, "n30": r30}, "I": {"n14": i14, "n30": i30},
           "diff14": round(r14["avg"] - i14["avg"], 2) if r14["avg"] is not None and i14["avg"] is not None else None,
           "R_by_event": {"2025_五合一": w2025, "2026_炼金": w2026},
           "verdict": "共振前置条件候选" if ok1 and ok2 else "证伪"}
    print("共振 R: 14d %s | 30d %s" % (_f(r14), _f(r30)))
    print("独跌 I: 14d %s | 30d %s" % (_f(i14), _f(i30)))
    print("差值 14d: %+.2fpp | 事件一致性: 2025 %s / 2026 %s → %s" % (
        out["diff14"], _f(w2025), _f(w2026), out["verdict"]))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
