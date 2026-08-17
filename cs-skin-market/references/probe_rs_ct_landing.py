# -*- coding: utf-8 -*-
"""落地(2) 对比：RS+CT 长持族 发射口径三关 + 独特性护栏（2026-08-17，预注册判据）。

基线：官方 v2-T13（189 信号，exit_sim hold21，total 397.02/maxDD −14.09 口径）；
变体：_exp_cycle_replay_rs_ct.json（rs_accum/ct_accum 开），exit_sim family_period
（rs/ct hold 180，其余 hold21；长持族不套 S4-14d）。
预注册判据（跑数前锁定）：
  关1 组合级：total(V) >= total(B) 且 maxDD(V) <= maxDD(B) + 1.0pp；
  关2 前后半段（2026-03-02）：两段 total 均 >= 基线同段 − 2pp；
  关3 发射质量：变体新增 rs/ct 信号 avg net14 >= +2pp 且 net60（fwd_series 扣2%）> 0；
  护栏（独特性）：(a) 变体 fixture 品（霸意大名/异星世界/抽象派/合纵）信号数 >= 基线；
                  (b) rs/ct 合计发射 >= 10 条（发声通道实质存在）；
                  (c) fixture 品被 rs/ct 命中 >= 1 条。
全过 → 候选默认开（ENGINE_VERSION bump + C 通道监测）；任一不过 → 维持默认关并登记。
输出 data/_exp_rs_ct_landing.json。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exit_sim as es  # noqa: E402
from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.signal_tracking import family_key_for_label  # noqa: E402

BASE = ROOT / "data" / "_exp_cycle_replay_2026.json"
VAR = ROOT / "data" / "_exp_cycle_replay_rs_ct.json"
OUT = ROOT / "data" / "_exp_rs_ct_landing.json"
CUT = "2026-03-02"
FIXTURE = ("M4A4 | 合纵 (崭新出厂)", "AK-47 | 抽象派 1337 (崭新出厂)",
           "FN57 | 霸意大名 (崭新出厂)", "格洛克 18 型 | 异星世界 (崭新出厂)")


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def load_sigs(path):
    raw = json.load(open(path, encoding="utf-8"))
    m180 = es.load_chg180()
    fam_of, per_of = {}, {}
    for s in raw["signals"]:
        k = (s["date"], s["name"])
        fam_of[k] = family_key_for_label(s.get("action_label") or "")
        per_of[k] = state_bucket(m180.get(s["date"]), s.get("mkt_chg30"))
    sigs, _ = es.bc.load_signals(path)
    for s in sigs:
        k = (s["date"].isoformat(), s["item"])
        s["fam"] = fam_of.get(k, "base")
        s["period"] = per_of.get(k, "S3弱市阴跌")
        s["hold"] = es.hold_for(s["fam"], s["period"])
    return sigs


def main():
    if not VAR.exists():
        print("变体产物缺失:", VAR, "——重放未完成")
        return
    sigs_b = load_sigs(BASE)
    sigs_v = load_sigs(VAR)
    res_b = es.simulate(sigs_b, "hold21")
    res_v = es.simulate(sigs_v, "family_period")
    mb = es.metrics(res_b["curve"])
    mv = es.metrics(res_v["curve"])
    fb, fv = es.seg(res_b["curve"], None, CUT), es.seg(res_v["curve"], None, CUT)
    bb, bv = es.seg(res_b["curve"], CUT, None), es.seg(res_v["curve"], CUT, None)

    keys_b = {(s["date"].isoformat(), s["item"]) for s in sigs_b}
    added = [s for s in sigs_v if (s["date"].isoformat(), s["item"]) not in keys_b]
    rs_ct_added = [s for s in added if s["fam"] in ("rs_accum", "ct_accum")]
    net60 = []
    for s in rs_ct_added:
        fwd = s["fwd"]
        if len(fwd) >= 60 and s["entry"] > 0:
            net60.append((fwd[59] / s["entry"] - 1) * 100 - 2.0)
    r14 = wa([s["net14"] for s in rs_ct_added if s.get("net14") is not None])
    r60 = wa(net60)

    fix_b = sum(1 for s in sigs_b if s["item"] in FIXTURE)
    fix_v = sum(1 for s in sigs_v if s["item"] in FIXTURE)
    fix_hit = sum(1 for s in rs_ct_added if s["item"] in FIXTURE)

    ok1 = mv["total_return_pct"] >= mb["total_return_pct"] and \
        mv["max_drawdown_pct"] <= mb["max_drawdown_pct"] + 1.0
    ok2 = (fv["total_return_pct"] is not None and fv["total_return_pct"] >= fb["total_return_pct"] - 2.0 and
           bv["total_return_pct"] is not None and bv["total_return_pct"] >= bb["total_return_pct"] - 2.0)
    ok3 = r14["avg"] is not None and r14["avg"] >= 2.0 and r60["avg"] is not None and r60["avg"] > 0
    guard = (fix_v >= fix_b and len(rs_ct_added) >= 10 and fix_hit >= 1)

    out = {
        "probe": "落地(2) RS+CT 三关+护栏", "cut": CUT,
        "base": {"signals": len(sigs_b), **mb},
        "variant": {"signals": len(sigs_v), **mv},
        "front": {"base": fb, "variant": fv}, "back": {"base": bb, "variant": bv},
        "added": {"n": len(added), "rs_ct": len(rs_ct_added), "net14": r14, "net60": r60},
        "guard": {"fixture_base": fix_b, "fixture_variant": fix_v, "fixture_rs_ct_hits": fix_hit},
        "verdict": {"gate1_combo": bool(ok1), "gate2_frontback": bool(ok2),
                    "gate3_emission": bool(ok3), "guard_uniqueness": bool(guard),
                    "land": bool(ok1 and ok2 and ok3 and guard)},
    }
    print("== 组合级 == 基线 %+.2f%%/%.2f → 变体 %+.2f%%/%.2f" % (
        mb["total_return_pct"], mb["max_drawdown_pct"], mv["total_return_pct"], mv["max_drawdown_pct"]))
    print("== 前后半段 == front %+.2f→%+.2f | back %+.2f→%+.2f" % (
        fb["total_return_pct"], fv["total_return_pct"], bb["total_return_pct"], bv["total_return_pct"]))
    print("== 新增发射 == n=%d (rs/ct=%d) net14=%s net60=%s" % (
        len(added), len(rs_ct_added), _f(r14), _f(r60)))
    print("== 护栏 == fixture 基线%d→变体%d，rs/ct 命中 fixture %d 条" % (fix_b, fix_v, fix_hit))
    print("== 判定 == 关1:%s 关2:%s 关3:%s 护栏:%s → %s" % (
        ok1, ok2, ok3, guard, "落地（默认开）" if out["verdict"]["land"] else "维持默认关"))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
