# -*- coding: utf-8 -*-
"""阶段4：分时期选品（全市场状态预测框架）（2026-08-18，预注册）。

用户纠正：功能 = 实时 7d/14d 预测覆盖全市场状态，抄底（P期）是大头但平稳/牛市也有。
本脚本 = 五时期各自的上涨驱动特征（Spearman）+ 分时期选品增量（Top20% vs 全体）。
选品分数（第一性原理预注册）：
  P期 超跌深度 = -(z_chg7+z_chg3+z_z)；S1/S2 供给收缩 = -(z_supply30+z_spread)；
  S3 逆势强势 = z_th - z_supply30；S4 无信号（供缩近似）。
输出 data/_exp_stage4_period_selection.json。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage4_period_selection.json"
PNAME = {0: "P恐慌", 1: "S1牛市上行", 2: "S2牛市回调", 3: "S3阴跌", 4: "S4反弹"}
FEATS = {"pct": 6, "z": 7, "th": 8, "supply30": 10, "chg7": 11, "chg30": 12,
         "rs30": 13, "chg3": 14, "no_new_low2": 15, "decay3": 16, "spread_chg5": 17}


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


def zscore(vals):
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
    return [(x - m) / sd if sd > 0 else 0.0 for x in vals]


def stat(sub):
    if len(sub) < 20:
        return None
    return {"n": len(sub), "fwd14": round(sum(r[20] for r in sub) / len(sub), 2),
            "win_pct": round(sum(1 for r in sub if r[20] > 0) / len(sub) * 100, 1)}


def main():
    rows, run_map = load_and_fix()
    period_corr = {}
    period_selection = {}
    for p in range(5):
        sub = [r for r in rows if r[20] is not None and run_map[r[0]] == p]
        if len(sub) < 200:
            continue
        # 特征相关性
        corrs = {}
        for fn, col in FEATS.items():
            xs = [r[col] for r in sub if r[col] is not None]
            ys = [r[20] for r in sub if r[col] is not None]
            if len(xs) > 100:
                corrs[fn] = round(spearman(xs, ys), 3)
        period_corr[PNAME[p]] = corrs
        # 分时期选品
        sub = [r for r in sub if r[8] is not None and r[10] is not None and r[7] is not None
               and r[11] is not None and r[14] is not None]
        if p == 0:
            c7 = zscore([r[11] for r in sub]); c3 = zscore([r[14] for r in sub]); zz = zscore([r[7] for r in sub])
            score = [-(c7[i] + c3[i] + zz[i]) / 3 for i in range(len(sub))]
        elif p in (1, 2):
            s = zscore([r[10] for r in sub]); sp = zscore([r[17] if r[17] is not None else 0 for r in sub])
            score = [-(s[i] + sp[i]) / 2 for i in range(len(sub))]
        elif p == 3:
            th = zscore([r[8] for r in sub]); s = zscore([r[10] for r in sub])
            score = [th[i] - s[i] for i in range(len(sub))]
        else:
            s = zscore([r[10] for r in sub]); score = [-x for x in s]
        order = sorted(range(len(sub)), key=lambda i: score[i], reverse=True)
        k = max(1, len(order) // 5)
        top = [sub[i] for i in order[:k]]
        period_selection[PNAME[p]] = {"all": stat(sub), "top20": stat(top),
                                      "delta_pp": round(stat(top)["fwd14"] - stat(sub)["fwd14"], 2)}
    out = {"probe": "阶段4 分时期选品", "period_feature_corr": period_corr,
           "period_selection": period_selection}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print("\n=== 分时期选品增量（Top20% vs 全体）===")
    for p, v in period_selection.items():
        print(f"  {p:10s} 全体 {v['all']['fwd14']:+.1f}%  Top20% {v['top20']['fwd14']:+.1f}%  (+{v['delta_pp']}pp)")


if __name__ == "__main__":
    main()
