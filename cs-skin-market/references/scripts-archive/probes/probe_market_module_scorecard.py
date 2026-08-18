# -*- coding: utf-8 -*-
"""大盘模块表现卡（2026-08-17，只读）：官方 v2-T13 回放产物 × 五时期 × 族
+ 大盘自身前视（_exp_market_periods.json）+ 等权基准腿。
输出 data/_exp_market_module_scorecard.json。
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
PERIODS_JSON = ROOT / "data" / "_exp_market_periods.json"
EW = ROOT / "data" / "equal_weight_baseline.json"
OUT = ROOT / "data" / "_exp_market_module_scorecard.json"
PERIODS = ["P恐慌深跌", "S1牛市上行", "S2牛市回调", "S3弱市阴跌", "S4弱市反弹"]


def load_chg180():
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


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def main():
    d = json.load(open(REPLAY, encoding="utf-8"))
    m180 = load_chg180()
    cells = OrderedDict((p, []) for p in PERIODS)
    fam_cells = OrderedDict()
    for s in d["signals"]:
        p = state_bucket(m180.get(s["date"]), s.get("mkt_chg30"))
        cells[p].append(s)
        fam_cells.setdefault(p, OrderedDict()).setdefault(
            family_key_for_label(s.get("action_label") or ""), []).append(s)

    mk = json.load(open(PERIODS_JSON, encoding="utf-8"))["periods"]
    periods = {}
    for p in PERIODS:
        ss = cells[p]
        fam = {}
        for k, v in fam_cells.get(p, {}).items():
            if len(v) >= 3:
                fam[k] = {"n": len(v),
                          "n14": wa([s["net14"] for s in v if s.get("net14") is not None]),
                          "n30": wa([s["net30"] for s in v if s.get("net30") is not None])}
        periods[p] = {
            "engine": {"n": len(ss),
                       "n14": wa([s["net14"] for s in ss if s.get("net14") is not None]),
                       "n30": wa([s["net30"] for s in ss if s.get("net30") is not None])},
            "market_fwd": mk[p],
            "family": fam,
        }
    ew = json.load(open(EW, encoding="utf-8"))
    ew_total = (ew["curve"][-1][1] / ew["curve"][0][1] - 1) * 100
    peak, mdd = ew["curve"][0][1], 0.0
    for _, v in ew["curve"]:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100)
    out = {
        "probe": "大盘模块表现卡（官方 v2-T13 回放 189 信号 × 五时期 × 族；net 已扣 2%）",
        "equal_weight": {"total_pct": round(ew_total, 2), "max_dd_pct": round(mdd, 2)},
        "periods": periods,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("== 大盘模块表现卡 ==")
    print("等权基准: total=%.2f%% mdd=%.2f%%" % (out["equal_weight"]["total_pct"], out["equal_weight"]["max_dd_pct"]))
    for p in PERIODS:
        e = periods[p]["engine"]
        m = periods[p]["market_fwd"]
        print("%-8s 引擎 n=%3d | 14d n=%d win=%s avg=%s | 30d n=%d win=%s avg=%s | 大盘自身 fwd14=%s fwd30=%s" % (
            p, e["n"], e["n14"]["n"], e["n14"]["win"], e["n14"]["avg"],
            e["n30"]["n"], e["n30"]["win"], e["n30"]["avg"], m["fwd14"], m["fwd30"]))
        for k, v in periods[p]["family"].items():
            print("    %-16s n=%2d | 14d %s | 30d %s" % (k, v["n"], _f(v["n14"]), _f(v["n30"])))
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "win=%s avg=%s" % (x["win"], x["avg"])


if __name__ == "__main__":
    main()
