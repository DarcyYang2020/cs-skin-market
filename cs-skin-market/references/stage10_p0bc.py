# -*- coding: utf-8 -*-
"""阶段10：P0-B 供给×求购共振 + P0-C 横截面超跌止跌（2026-08-18，预注册）。

背景：当前实盘 S3 弱市阴跌（2026-07，翻正率仅 13%），S3 期单品特性被审计判失效（趋势 th 样本外失效）。
第一性原理：S3 期赚钱只有「逆势强势」或「见底反转」两条路；本探针验「见底反转」的两个微观信号：
  P0-B 供给×求购共振 = 供给收缩(supply30<0) + 价差收窄(spread_chg5<0) → 买家收货+买盘进场，见底。
  P0-C 横截面超跌止跌 = 横截面超跌(同日同池 pct 秩 ≤20%) + 止跌(no_new_low2=1) → 相对超跌但已止跌，反弹。
预注册判据：S3 期，信号子集 fwd14 中位数 显著高于对照组（差 ≥ +3pp），且跨「好 S3(2024-10~2026-02) / 坏 S3(2026-03~07)」方向一致。
输出 data/_exp_stage10_p0bc.json。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage10_p0bc.json"
FWD7, FWD14 = 19, 20
# v2 列：pct=6 z=7 th=8 supply30=10 chg7=11 chg30=12 rs30=13 chg3=14 no_new_low2=15 decay3=16 spread_chg5=17 volreg=18


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


def median(v):
    v = sorted(v)
    return v[len(v) // 2]


def stat(sub):
    if len(sub) < 20:
        return None
    f7 = [r[FWD7] for r in sub if r[FWD7] is not None]
    f14 = [r[FWD14] for r in sub if r[FWD14] is not None]
    return {
        "n": len(sub),
        "fwd7_med": round(median(f7), 2) if f7 else None,
        "fwd7_win": round(sum(1 for x in f7 if x > 0) / len(f7) * 100, 1) if f7 else None,
        "fwd14_med": round(median(f14), 2) if f14 else None,
        "fwd14_win": round(sum(1 for x in f14 if x > 0) / len(f14) * 100, 1) if f14 else None,
    }


def main():
    rows, run_map = load_and_fix()
    # S3 期样本
    s3 = [r for r in rows if r[FWD14] is not None and run_map[r[0]] == 3]
    # 横截面超跌秩：同日同池 pct 秩（0=最超跌）
    by_date = defaultdict(list)
    for r in s3:
        by_date[r[0]].append(r)
    rank_pct = {}
    for d, rs in by_date.items():
        order = sorted(rs, key=lambda r: r[6])  # pct 升序 = 最超跌在前
        n = len(order)
        for i, r in enumerate(order):
            rank_pct[(d, r[1])] = i / (n - 1)  # 0=最超跌

    # 分段：好 S3（2024-10~2026-02）/ 坏 S3（2026-03~07）
    def seg(r):
        return "good" if r[0] < "2026-03-01" else "bad"

    out = {"probe": "阶段10 P0-B/P0-C", "s3_total": len(s3), "signals": {}}

    for seg_name in ["all", "good", "bad"]:
        sub = s3 if seg_name == "all" else [r for r in s3 if seg(r) == seg_name]
        # P0-C 横截面超跌止跌
        c_deep_stop = [r for r in sub if (r[0], r[1]) in rank_pct and rank_pct[(r[0], r[1])] <= 0.2 and r[15] == 1]
        c_deep_nostop = [r for r in sub if (r[0], r[1]) in rank_pct and rank_pct[(r[0], r[1])] <= 0.2 and r[15] == 0]
        c_all = sub
        # P0-B 供给×求购共振
        b_supply_bid = [r for r in sub if r[10] is not None and r[10] < 0 and r[17] is not None and r[17] < 0]
        b_supply_nobid = [r for r in sub if r[10] is not None and r[10] < 0 and r[17] is not None and r[17] >= 0]
        out["signals"][seg_name] = {
            "P0C_超跌止跌": stat(c_deep_stop),
            "P0C_超跌未止跌": stat(c_deep_nostop),
            "P0C_全体": stat(c_all),
            "P0B_供缩价差收窄": stat(b_supply_bid),
            "P0B_供缩价差未收窄": stat(b_supply_nobid),
        }

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    for seg_name in ["all", "good", "bad"]:
        s = out["signals"][seg_name]
        print(f"\n=== {seg_name} ===")
        for k in ["P0C_超跌止跌", "P0C_超跌未止跌", "P0C_全体", "P0B_供缩价差收窄", "P0B_供缩价差未收窄"]:
            v = s.get(k)
            if v:
                print(f"  {k:18s} n={v['n']:5d} fwd7_med={v['fwd7_med']} fwd14_med={v['fwd14_med']} fwd14_win={v['fwd14_win']}")


if __name__ == "__main__":
    main()
