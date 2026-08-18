# -*- coding: utf-8 -*-
"""DISPLAY-2 单品短期期望 · 离线查表构建器（2026-08-18，审计通过后落地）。

落地条件（③审计#2）逐条兑现：
  (1) 纯展示，不 bump ENGINE_VERSION（本脚本只产表，不改引擎）；
  (2) 单品特性仅 P/S1/S2 启用，S3/S4 只用时期×时点先验（S3 趋势特性样本外失效已剔除、S4 无）；
  (3) walk-forward train（SPLIT 前）拟合 + 版本化（schema_version + 数据截止日）；
      base 口径与 stage8/9 一致（时期先验=median[fwd|period] 收缩向全局，train 拟合）；
  (4) base_definition 字段说明 pred_base 定义（统一 stage8/9 的 pred_base 口径）；
  (5) P 期 2 事件外推限制（数据截止日 + split 记录，外推交 B 通道/live pilot）。

机制（层次收缩 k=20）：
  先验  = 时期×时点中位数（收缩向时期中位数，再向全局中位数）；时点超界 → 该时期末 5 日中位数。
  特性（仅 P/S1/S2，特征分数分时期预注册）：
    P 恐慌  超跌深度 = -(z_chg7+z_chg3+z_z)/3
    S1/S2   供给收缩 = -z_supply30
  特性桶 = 三分位（train 拟合阈值），桶中位数收缩向时期先验。
  E_item(P/S1/S2) = 特性桶中位数；E_base(S3/S4) = 时期×时点先验。

输出 data/_exp_shortterm_table.json（时期×时点×特性桶 → fwd7/fwd14 中位数 + 翻正率 + n）。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_shortterm_table.json"
K = 20
SPLIT = "2025-08-10"
PNAME = {0: "P恐慌深跌", 1: "S1牛市上行", 2: "S2牛市回调", 3: "S3弱市阴跌", 4: "S4弱市反弹"}
# 特性启用期（落地条件 2）：仅 P/S1/S2
TRAIT_FEATURE = {0: "超跌深度", 1: "供给收缩", 2: "供给收缩"}


def period_code(c180, c30):
    if c30 <= -15:
        return 0
    if c180 > 0:
        return 1 if c30 > 0 else 2
    return 3 if c30 <= 0 else 4


def median(v):
    v = sorted(v)
    return v[len(v) // 2]


def zparams(vals):
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
    return m, (sd if sd > 0 else 1.0)


def shrink(m_leaf, m_parent, n_leaf):
    """层次收缩：leaf 中位数向 parent 中位数收缩（k=K）。"""
    lam = n_leaf / (n_leaf + K)
    return lam * m_leaf + (1 - lam) * m_parent


def cell(vals):
    """fwd 列表 → {med, win, n}。win=翻正率=fwd>0 占比（百分数）。"""
    if not vals:
        return None
    return {
        "med": round(median(vals), 2),
        "win": round(sum(1 for x in vals if x > 0) / len(vals) * 100, 1),
        "n": len(vals),
    }


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    rows = d["rows"]
    clean = [r for r in rows if r[3] != 0.0]
    # 时期 + 连续天数（与 stage6/8/9 同口径）
    by_date = {}
    for r in clean:
        by_date.setdefault(r[0], (r[2], r[3]))  # (c30, c180)
    run_map = {}
    prev, run = None, 0
    for dt in sorted(by_date):
        c30, c180 = by_date[dt]
        b = period_code(c180, c30)
        run = run + 1 if b == prev else 1
        prev = b
        run_map[dt] = (b, run)

    # S = (date, period, day, z, th, supply30, chg7, chg3, fwd7, fwd14)
    S = []
    for r in clean:
        p, day = run_map[r[0]]
        S.append((r[0], p, day, r[7], r[8], r[10], r[11], r[14], r[19], r[20]))

    train = [s for s in S if s[0] < SPLIT and s[9] is not None and s[8] is not None]
    data_cutoff = max((s[0] for s in train), default="")

    # ---- 全局先验（fwd7/fwd14） ----
    gm7 = median([s[8] for s in train])
    gm14 = median([s[9] for s in train])
    gm7_w = cell([s[8] for s in train])
    gm14_w = cell([s[9] for s in train])

    # ---- 时期先验（收缩向全局） ----
    pm7, pm14, pm7_w, pm14_w = {}, {}, {}, {}
    for p in range(5):
        v7 = [s[8] for s in train if s[1] == p]
        v14 = [s[9] for s in train if s[1] == p]
        if v7:
            pm7[p] = shrink(median(v7), gm7, len(v7))
            pm14[p] = shrink(median(v14), gm14, len(v14))
            pm7_w[p] = cell(v7)
            pm14_w[p] = cell(v14)
        else:
            pm7[p] = gm7
            pm14[p] = gm14
            pm7_w[p] = gm7_w
            pm14_w[p] = gm14_w

    # ---- 时期×时点先验（收缩向时期先验）+ 末5日 tail ----
    by_pd7 = defaultdict(list)
    by_pd14 = defaultdict(list)
    for s in train:
        by_pd7[(s[1], s[2])].append(s[8])
        by_pd14[(s[1], s[2])].append(s[9])

    # ---- 特性 z 参数 + 桶（仅 P/S1/S2） ----
    def trait_score(p, s, zp):
        def z(x, key):
            if x is None:
                return 0.0
            m, sd = zp[key]
            return (x - m) / sd
        if p == 0:
            return -(z(s[6], "c7") + z(s[7], "c3") + z(s[3], "z")) / 3
        return -z(s[5], "s30")

    periods = {}
    for p in range(5):
        # prior_by_day（仅 fwd14 存储 day 维度；fwd7 同构）
        days = sorted({s[2] for s in train if s[1] == p})
        max_day = max(days) if days else 0
        prior_by_day = {}
        for day in days:
            v7 = by_pd7.get((p, day), [])
            v14 = by_pd14.get((p, day), [])
            prior_by_day[str(day)] = {
                "fwd7": cell(v7) or {"med": round(pm7[p], 2), "win": None, "n": 0},
                "fwd14": cell(v14) or {"med": round(pm14[p], 2), "win": None, "n": 0},
            }
            # 收缩向时期先验
            if prior_by_day[str(day)]["fwd7"]["n"] > 0:
                prior_by_day[str(day)]["fwd7"]["med"] = round(
                    shrink(median(v7), pm7[p], len(v7)), 2)
            if prior_by_day[str(day)]["fwd14"]["n"] > 0:
                prior_by_day[str(day)]["fwd14"]["med"] = round(
                    shrink(median(v14), pm14[p], len(v14)), 2)
        # 时点超界 tail = 末 5 日中位数
        tail_days = days[-5:] if len(days) >= 5 else days
        tail7 = [s[8] for s in train if s[1] == p and s[2] in tail_days]
        tail14 = [s[9] for s in train if s[1] == p and s[2] in tail_days]
        tail = {
            "max_day": max_day,
            "fwd7": cell(tail7) or {"med": round(pm7[p], 2), "win": None, "n": 0},
            "fwd14": cell(tail14) or {"med": round(pm14[p], 2), "win": None, "n": 0},
        }

        # 特性（仅 P/S1/S2）
        trait = None
        if p in TRAIT_FEATURE:
            sub = [s for s in train if s[1] == p
                   and s[3] is not None and s[5] is not None and s[6] is not None and s[7] is not None]
            if len(sub) >= 30:
                zp_src = [s for s in train if s[1] == p] if len([s for s in train if s[1] == p]) >= 30 else train
                zp = {}
                for key, col in [("z", 3), ("s30", 5), ("c7", 6), ("c3", 7)]:
                    vals = [s[col] for s in zp_src if s[col] is not None]
                    if vals:
                        zp[key] = zparams(vals)
                sc = [trait_score(p, s, zp) for s in sub]
                ssc = sorted(sc)
                thr1, thr2 = ssc[len(sc) // 3], ssc[2 * len(sc) // 3]
                buckets = defaultdict(list)
                for i, s in enumerate(sub):
                    b = 0 if sc[i] > thr2 else (1 if sc[i] > thr1 else 2)
                    buckets[b].append(s)
                trait = {
                    "feature": TRAIT_FEATURE[p],
                    "z_params": {k: [round(v[0], 4), round(v[1], 4)] for k, v in zp.items()},
                    "thr1": round(thr1, 4), "thr2": round(thr2, 4),
                    "buckets": {},
                }
                for b in sorted(buckets):
                    v7 = [s[8] for s in buckets[b]]
                    v14 = [s[9] for s in buckets[b]]
                    c7 = cell(v7)
                    c14 = cell(v14)
                    if c7 and c7["n"] > 0:
                        c7["med"] = round(shrink(median(v7), pm7[p], len(v7)), 2)
                    if c14 and c14["n"] > 0:
                        c14["med"] = round(shrink(median(v14), pm14[p], len(v14)), 2)
                    trait["buckets"][str(b)] = {"fwd7": c7, "fwd14": c14}

        periods[str(p)] = {
            "name": PNAME[p],
            "prior": {"fwd7": pm7_w[p], "fwd14": pm14_w[p]},
            "prior_by_day": prior_by_day,
            "tail": tail,
            "trait": trait,
        }

    out = {
        "probe": "DISPLAY-2 单品短期期望查表",
        "schema_version": 1,
        "table_version": "2026-08-18",
        "data_cutoff": data_cutoff,
        "split": SPLIT,
        "shrink_k": K,
        "base_definition": ("时期先验=median[fwd|period]收缩向全局(train,SPLIT前)；"
                            "时期×时点先验=median[fwd|period,day]收缩向时期先验；"
                            "trait=median[fwd|period,bucket]收缩向时期先验(仅P/S1/S2)；"
                            "S3/S4 无 trait 只用时期×时点先验；时点超界=末5日中位数"),
        "trait_enabled": TRAIT_FEATURE,
        "global": {"fwd7": gm7_w, "fwd14": gm14_w},
        "periods": periods,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT, "| train_n=", len(train), "| data_cutoff=", data_cutoff)
    for p in range(5):
        pp = periods[str(p)]
        t = pp["trait"]
        print(f"{PNAME[p]:8s} prior14_med={pp['prior']['fwd14']['med']:+.2f} "
              f"tail14_med={pp['tail']['fwd14']['med']:+.2f} "
              f"trait={'Y' if t else '-'}")


if __name__ == "__main__":
    main()
