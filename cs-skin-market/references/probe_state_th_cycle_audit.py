# -*- coding: utf-8 -*-
"""审计④补完：状态桶六态 / TH 三区 / 周期四相 × 事件窗口交叉（2026-08-16，只读）。

与 probe_sent_bucket_audit.py 同口径买点池：pct90≤40 & z≤0（宽口径买点池），扣 2% 双边成本。
市场口径走引擎自身 build_market_context（含真实 TH/sent/chg30，离线确定性）。
回答缺陷4：「状态桶/TH/周期在正常市是否失真」——每格报 fwd14/fwd30。
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
from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.market_macro import historical_event_impact  # noqa: E402
from pipeline.item_analysis import _analyze_cycle  # noqa: E402

OUT = ROOT / "data" / "_exp_state_th_cycle_audit.json"
START, END = "2023-11-17", "2026-08-05"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    return sum(1 for p in w if p <= prices[i]) / len(w) * 100


def zscore(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    if len(w) < 5:
        return None
    mu = sum(w) / len(w)
    var = sum((p - mu) ** 2 for p in w) / len(w)
    sd = var ** 0.5
    return (prices[i] - mu) / sd if sd > 0 else None


def main():
    ctx = build_market_context(START, end=END)
    print("market ctx days:", len(ctx), flush=True)

    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    c.close()

    bucket_cells = {}  # 六态 × 事件/正常
    th_cells = {}      # TH 三区 × 事件/正常
    cycle_cells = {}   # 周期四相 × 事件/正常

    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    for iid in items:
        rows = c.execute("SELECT date, price_rmb FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        n = len(prices)
        for i in range(90, n):
            if i + 30 >= n:
                continue
            d = dates[i]
            m = ctx.get(d)
            if m is None:
                continue
            pct = pct90(prices, i)
            z = zscore(prices, i)
            if pct is None or z is None or pct > 40 or z > 0:
                continue
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            ev = bool(historical_event_impact(d, horizon_days=30))
            tag = "事件" if ev else "正常"
            rec = {"fwd14": fwd14, "fwd30": fwd30}

            bucket_cells.setdefault(f"{state_bucket(m['sentiment'], m['th'], m['chg30'])}×{tag}", []).append(rec)
            th = m["th"]
            zone = "TH<35" if th < 35 else ("TH35-54" if th < 55 else "TH≥55")
            th_cells.setdefault(f"{zone}×{tag}", []).append(rec)
            cyc = _analyze_cycle(prices[max(0, i - 90):i + 1]).phase or "unknown"
            cycle_cells.setdefault(f"{cyc}×{tag}", []).append(rec)
    c.close()

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        return {"n": n,
                "win14": round(sum(1 for r in recs if r["fwd14"] > 0) / n * 100, 1),
                "avg14": round(sum(r["fwd14"] for r in recs) / n, 2),
                "win30": round(sum(1 for r in recs if r["fwd30"] > 0) / n * 100, 1),
                "avg30": round(sum(r["fwd30"] for r in recs) / n, 2)}

    out = {"probe": "审计④ 状态桶/TH/周期 × 事件窗口（买点池 pct≤40&z≤0）",
           "state_bucket": {k: st(v) for k, v in sorted(bucket_cells.items())},
           "th_zone": {k: st(v) for k, v in sorted(th_cells.items())},
           "cycle_phase": {k: st(v) for k, v in sorted(cycle_cells.items())}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for group in ("state_bucket", "th_zone", "cycle_phase"):
        print(f"=== {group} ===")
        for k, v in out[group].items():
            print(f"  {k:20s} n={v['n']:6d}  win14={v['win14']}  avg14={v['avg14']}  win30={v['win30']}  avg30={v['avg30']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
