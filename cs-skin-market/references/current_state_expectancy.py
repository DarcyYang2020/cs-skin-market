# -*- coding: utf-8 -*-
"""当下进场期望估计 + walk-forward 校验（2026-08-18，预注册）。

消费 data/_exp_universe_panel.json（build_universe_panel.py 产物）。
注意：面板的 period/period_days 列因 _PERIOD_CODE 键名 bug 全错，本脚本从原始
mchg30/mchg180 重算 period + period_days（date 唯一），并过滤 chg180 不可计算的退化日。

方法见 current-state-expectancy-design.md：贪心顺序条件 + 层次收缩（k=20）+ walk-forward。
输出 data/_exp_current_state_expectancy.json。
"""
import json
import math
from collections import defaultdict

SRC = "data/_exp_universe_panel.json"
OUT = "data/_exp_current_state_expectancy.json"
K = 20  # 收缩先验强度（预注册）

# 贪心顺序（预注册）：period → pct → period_days → th → z → cycle → mchg30 → sent
DIMS = ["period", "pct", "period_days", "th", "z", "cycle", "mchg30", "sent"]


def period_code(c180, c30):
    """state_bucket → 0-4 码（与 market_context.state_bucket 同源）。"""
    if c30 <= -15:
        return 0
    if c180 > 0:
        return 1 if c30 > 0 else 2
    return 3 if c30 <= 0 else 4


def load_and_fix():
    """加载面板：过滤 chg180 退化日；重算 period/period_days；返回清洗后的行。

    行 schema（原始）: [date, item_id, period, period_days, mchg30, mchg180, mth, sent,
                       pct, z, th, cycle, supply30, chg7, chg30, fwd14, fwd30]
    返回行 = [date, item_id, period, period_days, mchg30, mth, sent, pct, z, th, cycle,
             fwd14, fwd30]（去掉 mchg180/supply30/chg7/chg30 未用列，period/period_days 已修正）。
    """
    d = json.load(open(SRC, encoding="utf-8"))
    rows = d["rows"]
    # 过滤 chg180 不可计算（market_index 回填起点 2023-11-17，前 180 天 chg180=0 哨兵）
    clean = [r for r in rows if r[5] != 0.0]
    # 重建市场日序列 → (period_code, period_days)
    by_date = {}
    for r in clean:
        by_date.setdefault(r[0], (r[4], r[5]))  # (mchg30, mchg180) 市场级，同日一致
    run_map = {}
    prev = None
    run = 0
    for dt in sorted(by_date):
        c30, c180 = by_date[dt]
        b = period_code(c180, c30)
        run = run + 1 if b == prev else 1
        prev = b
        run_map[dt] = (b, run)
    out = []
    for r in clean:
        b, pd = run_map[r[0]]
        out.append([r[0], r[1], b, pd, r[4], r[6], r[7], r[8], r[9], r[10], r[11],
                    r[15], r[16]])
    return out, len(d["rows"])


def bucketize(r):
    """清洗后行 -> bucketed 维。行 idx: 0 date 1 item 2 period 3 period_days 4 mchg30 5 mth
    6 sent 7 pct 8 z 9 th 10 cycle 11 fwd14 12 fwd30。"""
    period, pd = r[2], r[3]
    mchg30, sent = r[4], r[6]
    pct, z, th, cyc = r[7], r[8], r[9], r[10]
    return {
        "period": period,
        "pct": 0 if pct <= 15 else (1 if pct <= 30 else (2 if pct <= 70 else 3)),
        "period_days": 0 if pd <= 7 else (1 if pd <= 14 else (2 if pd <= 30 else 3)),
        "th": 0 if th < 35 else (1 if th < 55 else 2),
        "z": 0 if z <= -2 else (1 if z <= -0.5 else (2 if z <= 0.5 else 3)),
        "cycle": cyc,
        "mchg30": 0 if mchg30 <= -15 else (1 if mchg30 <= -3 else (2 if mchg30 <= 3 else 3)),
        "sent": 0 if sent <= 40 else (1 if sent <= 70 else 2),
    }


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    def rank(a):
        s = sorted(range(len(a)), key=lambda i: a[i])
        r = [0] * len(a)
        for i, p in enumerate(s):
            r[p] = i
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx = (n - 1) / 2
    cov = sum((rx[i] - mx) * (ry[i] - mx) for i in range(n))
    vx = sum((rx[i] - mx) ** 2 for i in range(n))
    vy = sum((ry[i] - mx) ** 2 for i in range(n))
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def hier_chain(rows, query, dims, fidx=11, item_col=1):
    """层次收缩链：沿 dims 顺序逐层条件 + 向上一层收缩。返回每层统计 + 末层收缩均值。"""
    chain = []
    cur = rows
    for dim in dims:
        v = query[dim]
        sub = [r for r in cur if bucketize(r)[dim] == v]
        parent = [r[fidx] for r in cur if r[fidx] is not None]
        parent_mu = sum(parent) / len(parent) if parent else None
        vals = [r[fidx] for r in sub if r[fidx] is not None]
        n_items = len({r[item_col] for r in sub})
        if vals:
            cell_mean = sum(vals) / len(vals)
            lam = len(vals) / (len(vals) + K)
            shrunk = lam * cell_mean + (1 - lam) * parent_mu if parent_mu is not None else cell_mean
        else:
            cell_mean = shrunk = parent_mu
        chain.append({
            "dim": dim, "value": v,
            "cell_n": len(vals), "cell_items": n_items,
            "cell_mean": round(cell_mean, 2) if cell_mean is not None else None,
            "cell_win": round(sum(1 for x in vals if x > 0) / len(vals) * 100, 1) if vals else None,
            "shrunk_mean": round(shrunk, 2) if shrunk is not None else None,
        })
        cur = sub
    return chain, (chain[-1]["shrunk_mean"] if chain else None)


def main():
    rows, raw_n = load_and_fix()
    fidx = 11  # fwd14
    date_i = 0
    item_i = 1

    # ---- 例：S3弱市阴跌(3) + 低估区 pct≤30(1) + 进入第44天(31+ → 3) + th<35(0) ----
    # 严格按预注册顺序 period → pct → period_days → th
    query = {"period": 3, "pct": 1, "period_days": 3, "th": 0}
    chain, _ = hier_chain(rows, query, ["period", "pct", "period_days", "th"])

    # ---- 对照：同样 S3 但 th≥55（趋势确认带） vs th<35（黄金坑带） ----
    alt_high = hier_chain(rows, {"period": 3, "pct": 1, "period_days": 3, "th": 2},
                          ["period", "pct", "period_days", "th"])[0]
    alt_early = hier_chain(rows, {"period": 3, "pct": 1, "period_days": 0, "th": 0},
                           ["period", "pct", "period_days", "th"])[0]

    # ---- walk-forward 校验 ----
    TRAIN_END = "2026-03-01"
    train = [r for r in rows if r[date_i] < TRAIN_END and r[fidx] is not None]
    test = [r for r in rows if r[date_i] >= TRAIN_END and r[fidx] is not None]
    cell_dims = ("period", "pct", "th", "period_days")

    def ckey(r):
        b = bucketize(r)
        return tuple(b[d] for d in cell_dims)

    agg = defaultdict(list)
    for r in train:
        agg[ckey(r)].append(r[fidx])
    cell_mean = {k: sum(v) / len(v) for k, v in agg.items()}
    global_mean = sum(r[fidx] for r in train) / len(train)

    def predict(r):
        vals = agg.get(ckey(r))
        if not vals:
            return global_mean
        lam = len(vals) / (len(vals) + K)
        return lam * cell_mean[ckey(r)] + (1 - lam) * global_mean

    pred = [predict(r) for r in test]
    actual = [r[fidx] for r in test]
    rho = spearman(pred, actual)
    rmse_pred = math.sqrt(sum((p - a) ** 2 for p, a in zip(pred, actual)) / len(test))
    rmse_base = math.sqrt(sum((global_mean - a) ** 2 for a in actual) / len(test))
    tcell = defaultdict(list)
    for r in test:
        tcell[ckey(r)].append(r[fidx])
    sign_agree = sign_tot = 0
    for k, v in tcell.items():
        if k in cell_mean and len(v) >= 5:
            sign_tot += 1
            if (cell_mean[k] > 0) == (sum(v) / len(v) > 0):
                sign_agree += 1

    result = {
        "method": {"shrink_k": K, "dims": list(DIMS), "train_end": TRAIN_END,
                   "target": "fwd14", "raw_rows": raw_n, "clean_rows": len(rows)},
        "example_S3_low_zone_chain": chain,
        "contrast_S3_th_high": alt_high,
        "contrast_S3_early_days": alt_early,
        "walk_forward": {
            "n_train": len(train), "n_test": len(test),
            "spearman_pred_vs_actual": round(rho, 4) if rho is not None else None,
            "rmse_pred": round(rmse_pred, 2), "rmse_global_mean": round(rmse_base, 2),
            "rmse_improve_pct": round((1 - rmse_pred / rmse_base) * 100, 1) if rmse_base else None,
            "sign_agree_cells": sign_agree, "sign_total_cells": sign_tot,
        },
    }
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
