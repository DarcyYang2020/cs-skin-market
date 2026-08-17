# -*- coding: utf-8 -*-
"""P14（时点条件化）：进入时期第 N 天的剩余期望（2026-08-18，预注册判据，研究版）。

问题：时期级单值（如"S3 base 14d 78%"）把"过去该时期所有信号"压成一个数，
40 天阴跌期内每天都一样——需回答「进入时期第 N 天进场的剩余期望是否衰减」。
数据：官方 v2-T13 189 信号 × 时期 × 期内天数 N（日历天，连续段起点=第 1 天）。
预注册判据（跑数前锁定）：
  1. 衰减存在性：同一时期不同 N 桶的 fwd14/30 均值，最大最小差 >= 5pp 或存在单调趋势
     → 时点条件化有信息量 → 立项做「时点条件期望表」替代时期级单值；
  2. 单调衰减假设：S3/S4（阴跌/反抽期）N 越大剩余期望越低——检验是否成立；
  3. 若各桶无显著差异 → 时点条件化证伪，时期级单值并非主要误导源（重新诊断 fire_note 问题）。
输出 data/_exp_point_conditioned_expectancy.json。
"""
import json
import os
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

from pipeline.market_context import state_bucket  # noqa: E402

REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
STATE = ROOT / "data" / "market_state_daily.json"
OUT = ROOT / "data" / "_exp_point_conditioned_expectancy.json"

BUCKETS = (("1-7", 1, 7), ("8-14", 8, 14), ("15-21", 15, 21),
           ("22-30", 22, 30), ("31-40", 31, 40), ("41+", 41, 10 ** 9))
PERIODS = ("P恐慌深跌", "S1牛市上行", "S2牛市回调", "S3弱市阴跌", "S4弱市反弹")


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def main():
    d = json.load(open(REPLAY, encoding="utf-8"))
    st = json.load(open(STATE, encoding="utf-8"))
    # 逐日时期 + 连续段起点（第 N 天 = date - run_start + 1）
    days = sorted(st)
    run_start = {}
    prev_period = None
    for dd in days:
        s = st[dd]
        if "chg180" not in s or "chg30" not in s:
            continue
        p = state_bucket(s["chg180"], s["chg30"])
        if p != prev_period:
            run_start[dd] = dd
            prev_period = p
        else:
            run_start[dd] = None  # 延续段
    # 补齐延续段的 run_start（向前找最近的非 None 起点）
    cur_start = None
    start_of = {}
    for dd in days:
        if run_start.get(dd) is not None:
            cur_start = dd
        start_of[dd] = cur_start

    from datetime import datetime as _dt
    cells = OrderedDict((p, {b[0]: {"f14": [], "f30": []} for b in BUCKETS}) for p in PERIODS)
    for s in d["signals"]:
        sd = s["date"]
        if sd not in st or "chg180" not in st[sd]:
            continue
        p = state_bucket(st[sd]["chg180"], st[sd]["chg30"])
        if p not in cells or sd not in start_of or start_of[sd] is None:
            continue
        n_day = (_dt.strptime(sd, "%Y-%m-%d") - _dt.strptime(start_of[sd], "%Y-%m-%d")).days + 1
        for bname, lo, hi in BUCKETS:
            if lo <= n_day <= hi:
                if s.get("net14") is not None:
                    cells[p][bname]["f14"].append(s["net14"])
                if s.get("net30") is not None:
                    cells[p][bname]["f30"].append(s["net30"])
                break

    out = {"probe": "P14 时点条件化", "periods": {}}
    print("== 进入时期第 N 天 × fwd14/30（net 扣2%，n>=5 才列）==")
    verdicts = {}
    for p in PERIODS:
        row = {}
        print("\n[%s]" % p)
        for bname, _, _ in BUCKETS:
            r14 = wa(cells[p][bname]["f14"])
            r30 = wa(cells[p][bname]["f30"])
            row[bname] = {"n14": r14, "n30": r30}
            if r14["n"] >= 5:
                print("  %-6s n=%3d | 14d %s | 30d %s" % (bname, r14["n"], _f(r14), _f(r30)))
        # 衰减存在性：有 n>=5 的桶的 fwd14 均值极差
        avgs = [row[b]["n14"]["avg"] for b, _, _ in BUCKETS if row[b]["n14"]["n"] >= 5]
        spread = (max(avgs) - min(avgs)) if len(avgs) >= 2 else 0.0
        # 单调衰减检验（N 越大 fwd14 越低，用 Spearman 近似：比较相邻桶）
        verdicts[p] = {"n_buckets": len(avgs), "spread14": round(spread, 2),
                       "decay_signal": bool(spread >= 5.0)}
        print("  → 桶间 fwd14 极差 %+.1fpp，衰减信号=%s" % (spread, verdicts[p]["decay_signal"]))
        out["periods"][p] = row
    any_decay = any(v["decay_signal"] for v in verdicts.values())
    out["verdict"] = {
        "decay_any": bool(any_decay),
        "conclusion": ("时点条件化有信息量 → 立项时点条件期望表"
                       if any_decay else "时点条件化证伪 → 时期级单值非主要误导源，重新诊断")}
    print("\n判定:", out["verdict"]["conclusion"])
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
