# -*- coding: utf-8 -*-
"""P2（H1）：时期特征注入（2026-08-17，预注册判据，第一批③）。

问题：S1 引擎 14d +3.6 vs 等权 +5.8（−2.2pp）。假设 H1：注入时期特征（广度/波动）能救 S1。
数据：官方 v2-T13 产物信号 + market_state_daily.json 逐日 breadth5/vol20 联算。
预注册判据（跑数前锁定，两个变体各自独立判定）：
  变体 G（广度）：F = S1 信号 ∩ breadth5>=50；
    关1：n(F)>=10 且 avg14(F) >= avg14(S1) + 2pp；
    关2：S2∪S3 信号 ∩ breadth5>=50 的 avg14 >= S2∪S3 全部 avg14 − 1pp（不劣化）；
    两关全过 → G 候选（进入发射口径三关流程）；否则 H1 广度版证伪。
  变体 V（波动）：F = S1 信号 ∩ vol20<=0.008（慢牛低波指纹），判据同上（+2pp / −1pp）。
输出 data/_exp_period_feature_injection.json。
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

REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
STATE = ROOT / "data" / "market_state_daily.json"
OUT = ROOT / "data" / "_exp_period_feature_injection.json"


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def load_chg180():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
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


def main():
    st = json.load(open(STATE, encoding="utf-8"))
    m180 = load_chg180()
    d = json.load(open(REPLAY, encoding="utf-8"))
    sigs = []
    for s in d["signals"]:
        s = dict(s)
        s["_period"] = state_bucket(m180.get(s["date"]), s.get("mkt_chg30"))
        day = st.get(s["date"]) or {}
        s["_b5"] = day.get("breadth5")
        s["_v20"] = day.get("vol20")
        sigs.append(s)
    s1 = [s for s in sigs if s["_period"] == "S1牛市上行"]
    s23 = [s for s in sigs if s["_period"] in ("S2牛市回调", "S3弱市阴跌")]
    a14 = lambda ss: wa([s["net14"] for s in ss if s.get("net14") is not None])

    out = {"probe": "P2 时期特征注入", "s1_all": a14(s1), "s23_all": a14(s23), "variants": {}}
    print("S1 全量: %s | S2∪S3 全量: %s" % (_f(a14(s1)), _f(a14(s23))))

    for vname, pred in (("G_breadth>=50", lambda s: (s["_b5"] or 0) >= 50),
                        ("V_vol20<=0.008", lambda s: s["_v20"] is not None and s["_v20"] <= 0.008)):
        f1 = [s for s in s1 if pred(s)]
        f23 = [s for s in s23 if pred(s)]
        r1, r23 = a14(f1), a14(f23)
        ok1 = r1["n"] >= 10 and r1["avg"] is not None and r1["avg"] >= a14(s1)["avg"] + 2.0
        ok2 = r23["n"] >= 10 and r23["avg"] is not None and r23["avg"] >= a14(s23)["avg"] - 1.0
        verdict = "候选（进发射口径三关）" if ok1 and ok2 else "证伪"
        out["variants"][vname] = {"filtered_s1": r1, "filtered_s23": r23,
                                  "gate1": bool(ok1), "gate2": bool(ok2), "verdict": verdict}
        print("%-16s F(S1)=%s | F(S2∪S3)=%s | 关1=%s 关2=%s → %s" % (
            vname, _f(r1), _f(r23), ok1, ok2, verdict))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
