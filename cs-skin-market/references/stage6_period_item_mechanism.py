# -*- coding: utf-8 -*-
"""阶段6：分时期单品特性机制 + 跨切点验证（2026-08-18，预注册）。

正确框架：单品短期期望 = 时期×时点先验（大方向）× 分时期单品特性（这个品 vs 别的品）。
单品特性分数（分时期，第一性原理预注册）：
  P 恐慌  超跌深度 = -(z_chg7+z_chg3+z_z)/3
  S1/S2   供给收缩 = -z_supply30
  S3 阴跌 趋势强度 = z_th - z_supply30（逆势强势品）
  S4 反弹 无（反抽陷阱，用先验）
机制：时期×时点中位数先验（收缩 k=20），单品特性桶中位数收缩向时期先验。
验证（正确的分时期度量）：多切点 walk-forward，每时期「强特征 Top20% vs Bottom20%」的中位数差，
  跨切点方向是否一致（都 >0 才算单品特性稳定）。
输出 data/_exp_stage6_period_item_mechanism.json。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage6_period_item_mechanism.json"
K = 20
CUTS = ["2025-04-01", "2025-10-01", "2026-03-01"]
FWD14 = 20
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


def item_score(p, r, zp):
    """分时期单品特性分数。zp: {feature: (mean, sd)} train 拟合。r: S 元组 (date,period,day,z,th,supply30,chg7,chg3,fwd14)。"""
    def z(x, key):
        if x is None:
            return 0.0
        m, sd = zp[key]
        return (x - m) / sd
    if p == 0:
        return -(z(r[6], "chg7") + z(r[7], "chg3") + z(r[3], "z")) / 3
    if p in (1, 2):
        return -z(r[5], "supply30")
    if p == 3:
        return z(r[4], "th") - z(r[5], "supply30")
    return -z(r[5], "supply30")


def fit_zparams(train, p):
    sub = [s for s in train if s[1] == p]
    if len(sub) < 30:
        sub = train  # 该时期 train 样本不足时用全 train 参数（无泄漏）
    out = {}
    for key, col in [("chg7", 6), ("chg3", 7), ("z", 3), ("supply30", 5), ("th", 4)]:
        vals = [s[col] for s in sub if s[col] is not None]
        if vals:
            out[key] = zparams(vals)
    return out


def main():
    rows, run_map = load_and_fix()
    S = []
    for r in rows:
        p, day = run_map[r[0]]
        S.append((r[0], p, day, r[7], r[8], r[10], r[11], r[14], r[FWD14]))
    # S: (date, period, day, z, th, supply30, chg7, chg3, fwd14)

    out = {"probe": "阶段6 分时期单品特性", "shrink_k": K, "cuts": CUTS, "periods": {}}
    for p in range(5):
        period_result = {"cuts": []}
        for cut in CUTS:
            train = [s for s in S if s[0] < cut and s[8] is not None]
            test = [s for s in S if s[0] >= cut and s[8] is not None]
            zp = fit_zparams(train, p)
            # test 中该时期的样本，按单品特性分数排序
            tsub = [s for s in test if s[1] == p]
            if len(tsub) < 60:
                period_result["cuts"].append({"cut": cut, "n": len(tsub), "note": "样本不足"})
                continue
            scores = [item_score(p, s, zp) for s in tsub]
            order = sorted(range(len(tsub)), key=lambda i: scores[i], reverse=True)
            k = max(1, len(order) // 5)
            top = [tsub[i] for i in order[:k]]
            bot = [tsub[i] for i in order[-k:]]
            m_top = median([s[8] for s in top])
            m_bot = median([s[8] for s in bot])
            m_all = median([s[8] for s in tsub])
            period_result["cuts"].append({
                "cut": cut, "n": len(tsub),
                "all_med": round(m_all, 2), "top20_med": round(m_top, 2),
                "bot20_med": round(m_bot, 2), "top_bot_diff": round(m_top - m_bot, 2),
            })
        # 跨切点稳定性：top_bot_diff 是否都 > 0
        diffs = [c["top_bot_diff"] for c in period_result["cuts"] if "top_bot_diff" in c]
        period_result["stable"] = (len(diffs) >= 2 and all(d > 0 for d in diffs))
        period_result["diffs"] = diffs
        out["periods"][PNAME[p]] = period_result

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print("\n时期        各切点 Top20%-Bottom20% 中位数差    跨切点稳定")
    for p, v in out["periods"].items():
        diffs = v["diffs"]
        flag = "稳定" if v["stable"] else "不稳定"
        print(f"{p:10s} {diffs}  -> {flag}")


if __name__ == "__main__":
    main()
