# -*- coding: utf-8 -*-
"""P7（H7）：单品级时期风险折让（2026-08-17，预注册判据，第三批①）。

问题：族 limit 是否该带时期系数（如 S4 rise 0.05→0.03）？与已证伪的组合层乘子不同命题。
预注册判据（跑数前锁定）：
  变体 V1：S4 期全部信号 limit × 0.6（rise 0.05→0.03，base 0.2→0.12）；
  判据 1（加权期望）：wavg14(V1) >= wavg14(基线) + 1.0pp（wavg=Σlimit×net14/Σlimit）；
  判据 2（组合级不劣化）：exit_sim hold21 cap0.8 下 total(V1) >= total(基线) − 1.0pp
    且 maxDD(V1) <= maxDD(基线) + 0.5pp；
  两关全过 → 候选（进发射口径三关）；否则证伪（先验：组合层乘子已证伪，预期大概率证伪）。
输出 data/_exp_item_limit_period.json。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exit_sim as es  # noqa: E402
from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.signal_tracking import family_key_for_label  # noqa: E402

OUT = ROOT / "data" / "_exp_item_limit_period.json"


def wavg(sigs):
    num = sum(s["limit"] * s["net14"] for s in sigs if s.get("net14") is not None)
    den = sum(s["limit"] for s in sigs if s.get("net14") is not None)
    return num / den if den > 0 else None


def main():
    raw = json.load(open(es.REPLAY, encoding="utf-8"))
    m180 = es.load_chg180()
    fam_of, per_of = {}, {}
    for s in raw["signals"]:
        k = (s["date"], s["name"])
        fam_of[k] = family_key_for_label(s.get("action_label") or "")
        per_of[k] = state_bucket(m180.get(s["date"]), s.get("mkt_chg30"))

    sigs, _ = es.bc.load_signals(es.REPLAY)
    for s in sigs:
        k = (s["date"].isoformat(), s["item"])
        s["fam"] = fam_of.get(k, "base")
        s["period"] = per_of.get(k, "S3弱市阴跌")
        s["hold"] = es.hold_for(s["fam"], s["period"])

    w_base = wavg(sigs)
    v1 = []
    for s in sigs:
        s2 = dict(s)
        if s2["period"] == "S4弱市反弹":
            s2["limit"] = round(s2["limit"] * 0.6, 4)
        v1.append(s2)
    w_v1 = wavg(v1)

    mb = es.metrics(es.simulate(sigs, "hold21")["curve"])
    m1 = es.metrics(es.simulate(v1, "hold21")["curve"])
    ok1 = w_v1 is not None and w_base is not None and w_v1 >= w_base + 1.0
    ok2 = (m1["total_return_pct"] >= mb["total_return_pct"] - 1.0 and
           m1["max_drawdown_pct"] <= mb["max_drawdown_pct"] + 0.5)
    out = {"probe": "P7 单品级时期折让", "baseline": {"wavg14": round(w_base, 2) if w_base else None, **mb},
           "v1_s4x06": {"wavg14": round(w_v1, 2) if w_v1 else None, **m1},
           "verdict": "候选（进发射口径三关）" if ok1 and ok2 else "证伪"}
    print("基线 wavg14=%.2f%% | V1(S4×0.6) wavg14=%.2f%% | 组合 total %+.2f→%+.2f maxDD %+.2f→%+.2f → %s" % (
        w_base, w_v1, mb["total_return_pct"], m1["total_return_pct"],
        mb["max_drawdown_pct"], m1["max_drawdown_pct"], out["verdict"]))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
