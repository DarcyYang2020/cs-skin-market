# -*- coding: utf-8 -*-
"""黑天鹅事件响应预研（2026-08-17，只读）：大盘单日/3日急跌窗口的前视行为。

回答：急跌发生后 14/30d 大盘自身怎么走——V 型反弹（响应=暂停新开+不砍仓）
还是续跌（响应=组合降杠杆提示）。数据=replay_cycle_win.db 大盘指数全历史。
输出 data/_exp_crash_window_forward.json。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_crash_window_forward.json"

TH_1D = -8.0   # 单日跌幅阈值（黑天鹅指纹）
TH_3D = -12.0  # 3 日累计跌幅阈值


def main():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]

    def fwd(i, h):
        if i + h >= len(mvals) or mvals[i] <= 0:
            return None
        return (mvals[i + h] / mvals[i] - 1) * 100

    def wa(vs):
        n = len(vs)
        if n == 0:
            return None
        return {"n": n, "win": round(100.0 * sum(1 for v in vs if v > 0) / n, 1),
                "avg": round(sum(vs) / n, 2)}

    d1_events, d3_events = [], []
    for i in range(1, len(mvals)):
        r1 = (mvals[i] / mvals[i - 1] - 1) * 100
        if r1 <= TH_1D:
            d1_events.append((mdates[i], i, r1))
        if i >= 3:
            r3 = (mvals[i] / mvals[i - 3] - 1) * 100
            if r3 <= TH_3D:
                d3_events.append((mdates[i], i, r3))

    out = {"probe": "黑天鹅事件响应预研", "th_1d": TH_1D, "th_3d": TH_3D,
           "single_day_events": [], "three_day_events": []}
    print("== 单日急跌（≤%.0f%%）%d 次 ==" % (TH_1D, len(d1_events)))
    for d, i, r in d1_events:
        rec = {"date": d, "chg1d": round(r, 2),
               "fwd14": wa([fwd(i, 14)]), "fwd30": wa([fwd(i, 30)])}
        out["single_day_events"].append(rec)
        print("  %s chg1d=%+.1f%% | 14d %s | 30d %s" % (
            d, r, _f(rec["fwd14"]), _f(rec["fwd30"])))
    print("== 3日累计急跌（≤%.0f%%）%d 次 ==" % (TH_3D, len(d3_events)))
    for d, i, r in d3_events:
        rec = {"date": d, "chg3d": round(r, 2),
               "fwd14": wa([fwd(i, 14)]), "fwd30": wa([fwd(i, 30)])}
        out["three_day_events"].append(rec)
        print("  %s chg3d=%+.1f%% | 14d %s | 30d %s" % (
            d, r, _f(rec["fwd14"]), _f(rec["fwd30"])))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x is None or x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
