# -*- coding: utf-8 -*-
"""HQ 官方回放产物 × 大盘五时期 × 信号族分层（2026-08-16，只读，路由层预注册证据）。

数据源：data/_exp_cycle_replay_2026.json（HQ 180 品官方回放，v2-T12，233 信号）。
时期：pipeline.market_context.state_bucket（chg180×chg30）——chg30 用信号自带 mkt_chg30，
      chg180 按信号日从回放库 market_index 联算（与 expectancy_by_regime.py 同模式）。
族键：signal_tracking.family_key_for_label（单一事实源，8 族）。
统计：net14/net30（回放内已扣 2%），win = net > 0。
输出：data/_exp_period_family_hq.json。
"""
import json
import sqlite3
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.signal_tracking import family_key_for_label  # noqa: E402

REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_period_family_hq.json"

PERIODS = ["P恐慌深跌", "S1牛市上行", "S2牛市回调", "S3弱市阴跌", "S4弱市反弹"]
FAM_ORDER = ["panic_resonance", "deep_value", "panic_easing", "supply_accum",
             "rise_accum", "rise_contract", "volatile_accum", "second_wave", "base", "oversold"]


def load_chg180_by_date():
    c = sqlite3.connect(REPLAY_DB)
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]
    out = {}
    for i in range(180, len(mvals)):
        if mvals[i - 180] > 0:
            out[mdates[i]] = (mvals[i] / mvals[i - 180] - 1) * 100
    return out


def win_avg(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def main():
    d = json.load(open(REPLAY, encoding="utf-8"))
    signals = d["signals"]
    m180 = load_chg180_by_date()

    cells = OrderedDict()
    for p in PERIODS:
        cells[p] = OrderedDict()
    miss = 0
    for s in signals:
        period = state_bucket(m180.get(s.get("date")), s.get("mkt_chg30"))
        key = family_key_for_label(s.get("action_label"))
        cells[period].setdefault(key, []).append(s)
        if m180.get(s.get("date")) is None:
            miss += 1

    out = {"probe": "HQ 回放产物 × 五时期 × 族（net14/net30 已扣2%）",
           "source": str(REPLAY), "n_signals": len(signals), "chg180_miss": miss,
           "periods": {}}
    for p in PERIODS:
        fam = OrderedDict()
        for k in FAM_ORDER:
            if k not in cells[p]:
                continue
            ss = cells[p][k]
            fam[k] = {
                "n": len(ss),
                "n14": win_avg([s["net14"] for s in ss if s.get("net14") is not None]),
                "n30": win_avg([s["net30"] for s in ss if s.get("net30") is not None]),
            }
        tot14 = win_avg([s["net14"] for s in sum(cells[p].values(), []) if s.get("net14") is not None])
        tot30 = win_avg([s["net30"] for s in sum(cells[p].values(), []) if s.get("net30") is not None])
        out["periods"][p] = {"signals": sum(len(v) for v in cells[p].values()),
                             "total14": tot14, "total30": tot30, "family": fam}

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("== HQ 五时期×族（net 已扣2%）==")
    for p in PERIODS:
        row = out["periods"][p]
        print("%-8s n=%d | 14d %s | 30d %s" % (p, row["signals"],
                                               _f(row["total14"]), _f(row["total30"])))
        for k, v in row["family"].items():
            if v["n"] >= 3:
                print("    %-18s n=%3d | 14d %s | 30d %s" % (k, v["n"], _f(v["n14"]), _f(v["n30"])))
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
