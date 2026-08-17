# -*- coding: utf-8 -*-
"""时期边界季度重验台账（2026-08-17，模块 C；只读+追加台账）。

重算四切点（2024-07-01 / 2024-10-01 / 2025-02-01 / 2025-08-10）下五时期 fwd30 的
fit/val 平均 gap（与 probe_market_periods.py 同口径），追加一行到
data/period_boundary_recheck.jsonl（{date, gaps, note}）。
只监测不调参：gap 超过 6.5pp 警戒时 note 标 WATCH。
运行：python references/period_boundary_recheck.py（季度手动或接每日任务均可，幂等按日期）。
"""
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STATE = ROOT / "data" / "market_state_daily.json"
_LEDGER_DEFAULT = ROOT / "data" / "period_boundary_recheck.jsonl"
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"
CUTS = ("2024-07-01", "2024-10-01", "2025-02-01", "2025-08-10")
WARN_GAP = 6.5

from pipeline.market_context import state_bucket  # noqa: E402


def main():
    ledger = Path(os.environ.get("PERIOD_RECHECK_LEDGER", str(_LEDGER_DEFAULT)))
    st = json.load(open(STATE, encoding="utf-8"))
    c = sqlite3.connect(REPLAY_DB)
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    mvals = [float(r["value"]) for r in mrows]
    idx = {r["date"]: i for i, r in enumerate(mrows)}

    def fwd30(d):
        i = idx.get(d)
        if i is None or i + 30 >= len(mvals) or mvals[i] <= 0:
            return None
        return (mvals[i + 30] / mvals[i] - 1) * 100

    periods = {}
    for d, s in st.items():
        if "chg180" not in s or "chg30" not in s:
            continue
        periods.setdefault(state_bucket(s["chg180"], s["chg30"]), []).append((d, fwd30(d)))

    gaps = {}
    warn = False
    for cut in CUTS:
        fit = {p: [r[1] for r in recs if r[0] < cut and r[1] is not None]
               for p, recs in periods.items()}
        val = {p: [r[1] for r in recs if r[0] >= cut and r[1] is not None]
               for p, recs in periods.items()}
        gs = []
        for p in periods:
            if len(fit[p]) >= 5 and len(val[p]) >= 5:
                gs.append(abs(sum(fit[p]) / len(fit[p]) - sum(val[p]) / len(val[p])))
        gaps[cut] = round(sum(gs) / len(gs), 2) if gs else None
        if gaps[cut] is not None and gaps[cut] > WARN_GAP:
            warn = True
    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "gaps": gaps,
        "note": "WATCH: gap>%.1fpp" % WARN_GAP if warn else "OK",
    }
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("gaps:", gaps, "->", row["note"])
    print("appended to", ledger)


if __name__ == "__main__":
    main()
