# -*- coding: utf-8 -*-
"""阶段2：单品选品验证（2026-08-18，预注册）。

方向1（承接 AS）：既然「涨不涨」是时期定的，验证「涨多少」（fwd14 幅度）是否单品可预测。
  - 各时期 fwd14 幅度分布
  - P 期内单品特征 vs fwd14 幅度 Spearman（选品 = 超跌越深反弹越猛？）
  - 跨事件验证（五合一 vs 炼金）：「最超跌 20%」vs 全体的 fwd14 增量
输出 data/_exp_stage2_selection.json。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage2_selection.json"
PNAME = {0: "P恐慌深跌", 1: "S1牛市上行", 2: "S2牛市回调", 3: "S3弱市阴跌", 4: "S4弱市反弹"}


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
        run_map[dt] = b
    return clean, run_map


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


def main():
    rows, run_map = load_and_fix()

    # 1. 各时期 fwd14 幅度分布
    byp = defaultdict(list)
    for r in rows:
        if r[20] is not None:
            byp[run_map[r[0]]].append(r[20])
    period_dist = {}
    for p in range(5):
        v = sorted(byp.get(p, []))
        if not v:
            continue
        n = len(v)
        period_dist[PNAME[p]] = {
            "n": n, "mean": round(sum(v) / n, 2), "median": round(v[n // 2], 2),
            "p25": round(v[n // 4], 2), "p75": round(v[3 * n // 4], 2),
            "big_win_pct": round(sum(1 for x in v if x > 10) / n * 100, 1),
        }

    # 2. P 期内单品特征 vs fwd14 Spearman
    FEATS = {"pct": 6, "z": 7, "supply30": 10, "rs30": 13, "chg3": 14, "chg30": 12}
    p_rows = [r for r in rows if r[20] is not None and run_map[r[0]] == 0]
    corr = {}
    for fn, col in FEATS.items():
        xs = [r[col] for r in p_rows if r[col] is not None]
        ys = [r[20] for r in p_rows if r[col] is not None]
        if len(xs) > 50:
            corr[fn] = round(spearman(xs, ys), 3)

    # 3. 跨事件验证（最超跌 20% vs 全体）
    def event_stat(sub):
        sub2 = [r for r in sub if r[6] is not None]
        if not sub2:
            return None
        sub2.sort(key=lambda r: r[6])
        k = max(1, len(sub2) // 5)
        top = sub2[:k]
        allm = sum(r[20] for r in sub2) / len(sub2)
        topm = sum(r[20] for r in top) / len(top)
        xs = [r[6] for r in sub2]
        ys = [r[20] for r in sub2]
        return {"n": len(sub2), "rho": round(spearman(xs, ys), 3),
                "top20_mean": round(topm, 2), "all_mean": round(allm, 2),
                "delta_pp": round(topm - allm, 2)}

    ev = {
        "五合一": event_stat([r for r in p_rows if "2025-10-23" <= r[0] <= "2025-11-21"]),
        "炼金": event_stat([r for r in p_rows if "2026-05-24" <= r[0] <= "2026-06-02"]),
        "P期全体": event_stat(p_rows),
    }

    out = {"probe": "阶段2 单品选品验证", "period_fwd14_dist": period_dist,
           "P_期_特征_相关": corr, "事件_选品_增量": ev}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
