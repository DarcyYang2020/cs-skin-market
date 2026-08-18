# -*- coding: utf-8 -*-
"""大盘模块基座 M1+M2（2026-08-16，只读，方案 market-module-first-design.md 落地）。

M1 状态基座：逐日 chg7/30/90/180、TH、20日波动率、距 60/180 日高低点位置、池广度（5日上涨品占比）
  → data/market_state_daily.json
M2 等权基准：HQ 180 品等权买入持有（回放窗口 2023-11-17~2026-08-05，ffill，起点日=1）
  → data/equal_weight_baseline.json（唯一方法论基准）
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

from pipeline.backtest_common import build_market_context  # noqa: E402

OUT1 = ROOT / "data" / "market_state_daily.json"
OUT2 = ROOT / "data" / "equal_weight_baseline.json"
EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")


def main():
    ctx = build_market_context("2023-11-17", end="2026-08-05")
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [r["value"] for r in mrows]
    items = c.execute("SELECT i.id, i.name, MIN(p.date) first_date "
                      "FROM items i JOIN price_history p ON p.item_id=i.id "
                      "WHERE i.good_id>0 GROUP BY i.id").fetchall()
    c.close()
    hq = {r["id"]: r["name"] for r in items if not any(m in r["name"] for m in EXCL)}
    print("HQ 池:", len(hq))

    # ---- M1 状态基座 ----
    state = {}
    for i in range(180, len(mdates)):
        d = mdates[i]
        if d not in ctx:
            continue
        v = mvals[i]
        chg7 = (v / mvals[i - 7] - 1) * 100 if i >= 7 else None
        chg30 = (v / mvals[i - 30] - 1) * 100 if i >= 30 else None
        chg90 = (v / mvals[i - 90] - 1) * 100 if i >= 90 else None
        chg180 = (v / mvals[i - 180] - 1) * 100
        rets = [(mvals[j] - mvals[j - 1]) / mvals[j - 1] for j in range(i - 19, i + 1) if mvals[j - 1] > 0]
        vol20 = (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets)) ** 0.5 if rets else None
        hi60 = max(mvals[i - 59:i + 1])
        lo60 = min(mvals[i - 59:i + 1])
        hi180 = max(mvals[i - 179:i + 1])
        lo180 = min(mvals[i - 179:i + 1])
        state[d] = {
            "th": ctx[d]["th"],
            "chg7": round(chg7, 2) if chg7 is not None else None,
            "chg30": round(chg30, 2) if chg30 is not None else None,
            "chg90": round(chg90, 2) if chg90 is not None else None,
            "chg180": round(chg180, 2),
            "vol20": round(vol20, 4) if vol20 is not None else None,
            "dist_hi60": round((v / hi60 - 1) * 100, 2),
            "dist_lo60": round((v / lo60 - 1) * 100, 2),
            "dist_hi180": round((v / hi180 - 1) * 100, 2),
            "dist_lo180": round((v / lo180 - 1) * 100, 2),
        }

    # 广度（5 日上涨品占比，逐日）
    breadth = {}
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    for iid in hq:
        rows = c.execute("SELECT date, price_rmb FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        for k in range(5, len(rows)):
            if rows[k - 5]["price_rmb"] > 0 and rows[k]["price_rmb"] >= rows[k - 5]["price_rmb"]:
                breadth.setdefault(rows[k]["date"], [0, 0])
                breadth[rows[k]["date"]][0] += 1
            breadth.setdefault(rows[k]["date"], [0, 0])[1] += 1
    c.close()
    for d, (up, tot) in breadth.items():
        if d in state:
            state[d]["breadth5"] = round(100.0 * up / tot, 1) if tot else None
    with open(OUT1, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=0)
    print("M1 状态基座:", len(state), "天 ->", OUT1)

    # ---- M2 等权基准 ----
    base_prices = {}
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    for iid in hq:
        rows = c.execute("SELECT date, price_rmb FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        base_prices[iid] = {r["date"]: r["price_rmb"] for r in rows}
    c.close()
    days = [d for d in mdates if "2023-11-17" <= d <= "2026-08-05"]
    curve = []
    for d in days:
        vals = []
        for iid, mp in base_prices.items():
            keys = [k for k in mp if k <= d]
            if not keys or not mp[min(keys)] or mp[min(keys)] <= 0:
                continue
            vals.append(mp[max(keys)] / mp[min(keys)])
        if vals:
            curve.append((d, round(sum(vals) / len(vals), 6)))
    out2 = {"benchmark": "HQ180等权买入持有", "start": curve[0][0], "end": curve[-1][0],
            "n_days": len(curve), "curve": curve}
    with open(OUT2, "w", encoding="utf-8") as f:
        json.dump(out2, f, ensure_ascii=False)
    total = (curve[-1][1] / curve[0][1] - 1) * 100
    peak = curve[0][1]
    mdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100)
    print("M2 等权基准: total=%.2f%% mdd=%.2f%% -> %s" % (total, mdd, OUT2))


if __name__ == "__main__":
    main()
