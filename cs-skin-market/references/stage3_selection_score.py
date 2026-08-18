# -*- coding: utf-8 -*-
"""阶段3：超跌深度选品分数 + 排序 vs 阈值对比（2026-08-18，预注册）。

承接 AT/AU：构造「超跌深度选品分数」= -(z_pct+z_z+z_chg3)/3（等权），
输出 P 期内的排序选品（Top10%/20%）vs panic 硬阈值（pct≤15&z≤-1.5）的 fwd14 对照。
输出 data/_exp_stage3_selection_score.json。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage3_selection_score.json"


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


def zscore(vals):
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
    return [(x - m) / sd if sd > 0 else 0.0 for x in vals]


def stat(sub):
    if not sub:
        return None
    m = sum(r[20] for r in sub) / len(sub)
    win = sum(1 for r in sub if r[20] > 0) / len(sub) * 100
    big = sum(1 for r in sub if r[20] > 10) / len(sub) * 100
    return {"n": len(sub), "fwd14_mean": round(m, 2), "win_pct": round(win, 1),
            "big_win_pct": round(big, 1)}


def main():
    rows, run_map = load_and_fix()
    p_rows = [r for r in rows if r[20] is not None and run_map[r[0]] == 0]
    valid = [r for r in p_rows if r[6] is not None and r[7] is not None and r[14] is not None]
    pz = zscore([r[6] for r in valid])
    zz = zscore([r[7] for r in valid])
    cz = zscore([r[14] for r in valid])
    score = [-(pz[i] + zz[i] + cz[i]) / 3 for i in range(len(valid))]
    order = sorted(range(len(valid)), key=lambda i: score[i], reverse=True)

    out = {
        "probe": "阶段3 超跌深度选品分数",
        "score_def": "-(z_pct+z_z+z_chg3)/3 等权",
        "n_valid": len(valid),
        "全量_不选品": stat(valid),
        "超跌Top20": stat([valid[i] for i in order[:len(order) // 5]]),
        "超跌Top10": stat([valid[i] for i in order[:len(order) // 10]]),
        "panic阈值_pct15_z15": stat([r for r in valid if r[6] <= 15 and r[7] <= -1.5]),
        "pct15": stat([r for r in valid if r[6] <= 15]),
        "事件_组合分数增量": {
            "五合一": stat([valid[i] for i in range(len(valid)) if "2025-10-23" <= valid[i][0] <= "2025-11-21"]),
            "炼金": stat([valid[i] for i in range(len(valid)) if "2026-05-24" <= valid[i][0] <= "2026-06-02"]),
        },
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    for k, v in out.items():
        if isinstance(v, dict) and "fwd14_mean" in v:
            print(f"  {k:24s} n={v['n']:5d} fwd14={v['fwd14_mean']:+.1f}% 翻正={v['win_pct']:.0f}% 大涨={v['big_win_pct']:.0f}%")


if __name__ == "__main__":
    main()
