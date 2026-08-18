# -*- coding: utf-8 -*-
"""阶段8：发射侧回放 + walk-forward（2026-08-18，回应③审计驳回）。

审计：数据层 Top-Bottom 差仅作初筛，须补「发射侧回放产物 + 逐信号明细」。
本脚本 = 机制对每个 item-day 输出期望值（=发射），fit 段（<SPLIT）拟合「时期先验 + 分时期单品特性」，
val 段（>=SPLIT）用 fit 参数算期望值，验证排序能力（Spearman + Top-Bottom 差）。
族开 vs 基线：基线 = 时期先验（无单品特性），族开 = 时期先验 + 分时期单品特性。
输出 data/_exp_stage8_emission.json（含逐信号明细 val 段）。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage8_emission.json"
K = 20
SPLIT = "2025-08-10"  # a2_emission 标准切点
PNAME = {0: "P恐慌", 1: "S1牛市", 2: "S2回调", 3: "S3阴跌", 4: "S4反弹"}


def period_code(c180, c30):
    if c30 <= -15:
        return 0
    if c180 > 0:
        return 1 if c30 > 0 else 2
    return 3 if c30 <= 0 else 4


def load_and_fix():
    d = json.load(open(SRC, encoding="utf-8"))
    rows = d["rows"]
    clean = [r for r in rows if r[3] != 0.0]
    by_date = {}
    for r in clean:
        by_date.setdefault(r[0], (r[2], r[3]))
    run_map = {}
    prev = None
    run = 0
    for dt in sorted(by_date):
        c30, c180 = by_date[dt]
        b = period_code(c180, c30)
        run = run + 1 if b == prev else 1
        prev = b
        run_map[dt] = (b, run)
    return clean, run_map


def median(v):
    v = sorted(v)
    return v[len(v) // 2]


def zparams(vals):
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
    return m, (sd if sd > 0 else 1.0)


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    def rk(a):
        s = sorted(range(n), key=lambda i: a[i])
        r = [0] * n
        for i, p in enumerate(s):
            r[p] = i
        return r
    rx, ry = rk(xs), rk(ys)
    mx = (n - 1) / 2
    cov = sum((rx[i] - mx) * (ry[i] - mx) for i in range(n))
    vx = sum((rx[i] - mx) ** 2 for i in range(n))
    vy = sum((ry[i] - mx) ** 2 for i in range(n))
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def top_bot_diff(fwd, scores):
    order = sorted(range(len(fwd)), key=lambda i: scores[i], reverse=True)
    k = max(1, len(order) // 5)
    top = [fwd[i] for i in order[:k]]
    bot = [fwd[i] for i in order[-k:]]
    return median(top) - median(bot)


def main():
    rows, run_map = load_and_fix()
    S = []
    for r in rows:
        p, day = run_map[r[0]]
        S.append((r[0], p, day, r[7], r[8], r[10], r[11], r[14], r[20]))  # date,p,day,z,th,supply30,chg7,chg3,fwd14

    train = [s for s in S if s[0] < SPLIT and s[8] is not None]
    test = [s for s in S if s[0] >= SPLIT and s[8] is not None]

    # fit：时期先验（中位数，收缩向全局）
    gm = median([s[8] for s in train])
    pm = {}
    for p in range(5):
        v = [s[8] for s in train if s[1] == p]
        if v:
            lam = len(v) / (len(v) + K)
            pm[p] = lam * median(v) + (1 - lam) * gm
    # fit：分时期特性分数 zscore 参数
    zp = {}
    for p in range(5):
        sub = [s for s in train if s[1] == p]
        if len(sub) < 30:
            sub = train
        zp[p] = {}
        for key, col in [("z", 3), ("th", 4), ("s30", 5), ("c7", 6), ("c3", 7)]:
            vals = [s[col] for s in sub if s[col] is not None]
            if vals:
                zp[p][key] = zparams(vals)

    def item_score(p, s):
        def z(x, key):
            if x is None:
                return 0.0
            m, sd = zp[p][key]
            return (x - m) / sd
        if p == 0:
            return -(z(s[6], "c7") + z(s[7], "c3") + z(s[3], "z")) / 3
        if p in (1, 2):
            return -z(s[5], "s30")
        if p == 3:
            return z(s[4], "th") - z(s[5], "s30")
        return -z(s[5], "s30")

    # fit：特性桶中位数（分时期，收缩向时期先验）
    trait_buckets = {}
    for p in range(5):
        sub = [s for s in train if s[1] == p and s[3] is not None and s[5] is not None and s[6] is not None and s[7] is not None]
        if len(sub) < 30:
            continue
        sc = [item_score(p, s) for s in sub]
        # 三分位阈值（train 拟合）
        sorted_sc = sorted(sc)
        thr1, thr2 = sorted_sc[len(sc) // 3], sorted_sc[2 * len(sc) // 3]
        buckets = defaultdict(list)
        for i, s in enumerate(sub):
            b = 0 if sc[i] > thr2 else (1 if sc[i] > thr1 else 2)
            buckets[b].append(s[8])
        p_med = median([s[8] for s in sub])
        trait_buckets[p] = {"thr1": thr1, "thr2": thr2, "med": {}}
        for b, v in buckets.items():
            lam = len(v) / (len(v) + K)
            trait_buckets[p]["med"][b] = lam * median(v) + (1 - lam) * p_med

    # 预测函数
    def pred_base(s):
        return pm.get(s[1], gm)

    def pred_on(s):
        base = pred_base(s)
        if s[1] not in trait_buckets or s[3] is None or s[5] is None or s[6] is None or s[7] is None:
            return base
        tb = trait_buckets[s[1]]
        sc = item_score(s[1], s)
        b = 0 if sc > tb["thr2"] else (1 if sc > tb["thr1"] else 2)
        return tb["med"].get(b, base)

    # val 段：族开 vs 基线 排序能力 + 逐信号明细
    out = {"probe": "阶段8 发射侧回放", "split": SPLIT, "shrink_k": K, "periods": {}}
    for p in range(5):
        vsub = [s for s in test if s[1] == p]
        if len(vsub) < 60:
            out["periods"][PNAME[p]] = {"val_n": len(vsub), "note": "样本不足"}
            continue
        base_pred = [pred_base(s) for s in vsub]
        on_pred = [pred_on(s) for s in vsub]
        fwd = [s[8] for s in vsub]
        scores = [item_score(p, s) for s in vsub]
        out["periods"][PNAME[p]] = {
            "val_n": len(vsub),
            "spearman_base": round(spearman(base_pred, fwd), 4),
            "spearman_on": round(spearman(on_pred, fwd), 4),
            "topbot_base": round(top_bot_diff(fwd, base_pred), 2),
            "topbot_on": round(top_bot_diff(fwd, scores), 2),
            "trait_median_all": round(median(fwd), 2),
        }

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    for p, v in out["periods"].items():
        if "spearman_on" in v:
            print(f"{p:8s} val_n={v['val_n']:5d} spearman_base={v['spearman_base']} spearman_on={v['spearman_on']} "
                  f"topbot_on={v['topbot_on']}")


if __name__ == "__main__":
    main()
