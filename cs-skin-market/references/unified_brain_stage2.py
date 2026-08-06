# -*- coding: utf-8 -*-
"""统一大脑研究 · 阶段2：决策函数原型 walk-forward 对比（2026-08-06）。

输入：data/item_backtest_full_2025.json（581 信号，现引擎串行链产物）。
方法：按日期 anchor=0.7 切 train/test；train 估计「族×状态桶」net14 期望表（n>=3）；
test 段应用期望表做决策层改造（只改仓位/排序，不改触发条件），对比现引擎基线。

方案：
  baseline  原 position_limit（现引擎）
  planA     期望分档仓位（train 表 net14 映射档位）
  planB     planA + deep_value@中性企稳 exp<5 再降至 0.05
  planC     planA + 同日并发 cap0.8 排序（低期望剔除）
输出：data/unified_brain_stage2.json + 控制台对比。
"""
import sys, io, json, statistics
from datetime import datetime
sys.path.insert(0, ".")
from collections import defaultdict
from pipeline.backtest_common import build_market_context
from pipeline.backtest_methodology import signal_cluster_report

SRC = "data/item_backtest_full_2025.json"
ANCHOR = 0.7


def family_of(label):
    lab = label or ""
    if "\u6050\u614c" in lab: return "panic"
    if "\u8d85\u8dcc" in lab: return "oversold"
    if "\u6df1\u503c" in lab: return "deep_value"
    if "\u4f9b\u7ed9\u6536\u7f29" in lab: return "supply_accum"
    if "\u5438\u7b79" in lab: return "accumulate"
    return "base"


def bucket_of(sent, chg30, mth):
    s = float(sent) if sent is not None else 50.0
    c = float(chg30) if chg30 is not None else 0.0
    t = float(mth) if mth is not None else 50.0
    # 引擎口径：恐慌 = sent>=75（与 P0-7 一致），非展示层 80
    if s <= 30: return "\u8d2a\u5a6a\u7981\u5165"
    if s >= 75 and c <= -15: return "\u6050\u614c\u6df1\u8dccV\u578b\u5e95"
    if s >= 75 and -15 < c <= -5: return "\u6050\u614c\u4e2d\u8dcc\u9634\u8dcc\u4e2d\u7ee7"
    if s >= 75: return "\u6050\u614c\u6d45\u8dcc"
    if t >= 45: return "\u4e2d\u6027\u4f01\u7a33"
    return "\u5f31\u5e02\u89c2\u671b"


def wavg(vals, limits):
    ws = [l for l, v in zip(limits, vals) if v is not None]
    vs = [v for v in vals if v is not None]
    if not ws: return None
    return sum(w * v for w, v in zip(ws, vs)) / sum(ws)


def tier(exp):
    if exp is None: return None
    if exp >= 40: return 0.30
    if exp >= 20: return 0.20
    if exp >= 10: return 0.10
    if exp >= 3: return 0.07
    if exp >= 0: return 0.05
    return 0.02


def stats_of(recs):
    out = {"n": len(recs)}
    if not recs:
        return out
    for f, wf in (("net14", "wavg14"), ("net30", "wavg30")):
        v = [r[f] for r in recs if r.get(f) is not None]
        out[f + "_n"] = len(v)
        if v:
            out["win" + f[-2:]] = round(sum(1 for x in v if x > 0) / len(v) * 100, 1)
            out["avg" + f[-2:]] = round(statistics.mean(v), 2)
    limits = [r.get("limit_used") or 0 for r in recs]
    n14 = [r["net14"] for r in recs if r.get("net14") is not None]
    n30 = [r["net30"] for r in recs if r.get("net30") is not None]
    if n14: out["wavg14"] = round(wavg(n14, limits[:len(n14)]), 2)
    if n30: out["wavg30"] = round(wavg(n30, limits[:len(n30)]), 2)
    cl = signal_cluster_report([r["date"] for r in recs], window=3)
    out["cluster"] = {"events": cl["event_count"], "unique_dates": cl["unique_dates"],
                       "max_cluster_share": round(cl["max_cluster_share"], 3), "flagged": cl["flagged"]}
    return out


def main():
    ctx = build_market_context("2025-01-01", end="2026-08-05")
    d = json.load(io.open(SRC, encoding="utf-8"))
    sigs = d["signals"]
    for s in sigs:
        s["family"] = family_of(s.get("action_label", ""))
        mc = ctx.get(s["date"], {})
        s["bucket"] = bucket_of(s.get("sentiment", 50), mc.get("chg30", 0), s.get("market_th", 50))
    sigs.sort(key=lambda x: x["date"])
    dates = sorted(set(s["date"] for s in sigs))
    cut = dates[int(len(dates) * ANCHOR)]
    train = [s for s in sigs if s["date"] < cut]
    test = [s for s in sigs if s["date"] >= cut]
    print("cut:", cut, "| train:", len(train), "test:", len(test))

    tab = defaultdict(list)
    for s in train:
        if s.get("net14") is not None:
            tab[(s["family"], s["bucket"])].append(s["net14"])
    exp_tab = {}
    for k, v in tab.items():
        if len(v) >= 3:
            exp_tab[k] = statistics.mean(v)
    print("train exp table cells:", len(exp_tab))

    def apply_plan(recs, mode):
        out = []
        for s in recs:
            r = dict(s)
            exp = exp_tab.get((s["family"], s["bucket"]))
            if mode == "baseline":
                r["limit_used"] = s.get("position_limit") or 0
            else:
                t = tier(exp) if exp is not None else (s.get("position_limit") or 0)
                if mode == "planB" and s["family"] == "deep_value" and s["bucket"] == "\u4e2d\u6027\u4f01\u7a33" and exp is not None and exp < 5:
                    t = min(t, 0.05)
                r["limit_used"] = t
                r["_exp"] = exp
            out.append(r)
        if mode == "planC":
            by_day = defaultdict(list)
            for r in out:
                by_day[r["date"]].append(r)
            kept = []
            for day, recs_day in sorted(by_day.items()):
                recs_day.sort(key=lambda r: (r.get("_exp") if r.get("_exp") is not None else -99), reverse=True)
                acc = 0.0
                for r in recs_day:
                    if acc + r["limit_used"] <= 0.8:
                        kept.append(r)
                        acc += r["limit_used"]
                    else:
                        r["limit_used"] = 0.0  # 被 cap 剔除（不参与加权）
                        kept.append(r)
            return kept
        return out

    res = {"cut": cut, "train_n": len(train), "test_n": len(test)}
    for mode in ("baseline", "planA", "planB", "planC"):
        recs = apply_plan(test, mode)
        res[mode] = stats_of(recs)
        st = res[mode]
        print(f"{mode:9s} n={st['n']:3d} ev={st.get('cluster',{}).get('events')} "
              f"14d win={st.get('win14')} avg={st.get('avg14')} wavg={st.get('wavg14')} | "
              f"30d win={st.get('win30')} avg={st.get('avg30')} wavg={st.get('wavg30')}")
    with open("data/unified_brain_stage2.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("saved: data/unified_brain_stage2.json")


if __name__ == "__main__":
    main()
