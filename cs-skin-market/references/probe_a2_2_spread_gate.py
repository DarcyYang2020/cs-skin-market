# -*- coding: utf-8 -*-
"""A2-2 spread 走阔硬闸门（只读，walk-forward + 标签置换 + 去簇）。

拟合段(2023-06~2025-08-09)定阈值 T；验证段(2025-08-10~2026-08)用 T 测三组。
五条门槛逐条打钩。
"""
import json
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
MARKET_DB = ROOT / "data" / "market.db"
OUT = ROOT / "data" / "_exp_a2_2_spread_gate.json"
FIT_END = "2025-08-09"
random.seed(20260815)


def buy_at(bdates, bprices, target):
    best = None
    for d, p in zip(bdates, bprices):
        if d <= target:
            best = p
        else:
            break
    return best


def decluster(dates, gap=3):
    ds = sorted(dates)
    n, last = 0, None
    for d in ds:
        if last is None or (datetime.fromisoformat(d) - datetime.fromisoformat(last)).days > gap:
            n += 1
        last = d
    return n


def main():
    cyc = sqlite3.connect(CYCLE_DB)
    cyc.row_factory = sqlite3.Row
    mkt = sqlite3.connect(MARKET_DB)
    mkt.row_factory = sqlite3.Row
    items = cyc.execute("SELECT id, good_id FROM items WHERE good_id > 0 ORDER BY id").fetchall()
    good_cache = {}
    events = []  # (date, dspread, fwd14, fwd30)
    for it in items:
        iid, gid = it["id"], it["good_id"]
        rows = cyc.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                           "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        if gid not in good_cache:
            r2 = mkt.execute("SELECT date, buy_price_last FROM bid_history "
                             "WHERE good_id=? AND buy_price_last IS NOT NULL ORDER BY date", (gid,)).fetchall()
            good_cache[gid] = {"dates": [x["date"] for x in r2], "price": [x["buy_price_last"] for x in r2]}
        g = good_cache[gid]
        n = len(prices)
        for i in range(30, n):
            if i + 30 >= n:
                continue
            s7 = insale[i - 6:i + 1]
            s30 = insale[i - 29:i + 1]
            if any(x is None for x in s7) or any(x is None for x in s30):
                continue
            if sum(s7) / 7 > 0.85 * (sum(s30) / 30):
                continue
            price_chg = (prices[i] - prices[i - 5]) / prices[i - 5] * 100 if prices[i - 5] else 0
            if price_chg <= 3:
                continue  # 供缩+价涨（>+3%）
            buy_now = buy_at(g["dates"], g["price"], dates[i])
            buy_5d = buy_at(g["dates"], g["price"], dates[i - 5]) if i >= 5 else buy_now
            if buy_now is None or buy_5d is None or prices[i - 5] is None or prices[i - 5] <= 0 or prices[i] <= 0:
                continue
            dspread = (prices[i] - buy_now) / prices[i] * 100 - (prices[i - 5] - buy_5d) / prices[i - 5] * 100
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            events.append({"date": dates[i], "dspread": dspread, "fwd14": fwd14, "fwd30": fwd30})
    cyc.close()
    mkt.close()

    fit = [e for e in events if e["date"] <= FIT_END]
    val = [e for e in events if e["date"] > FIT_END]

    # 拟合段定 T：8 分位找 avg14 转负的顶档边界
    fit_ds = sorted(e["dspread"] for e in fit)
    q7 = fit_ds[int(len(fit_ds) * 7 / 8)] if len(fit_ds) >= 8 else None
    # 顶档（>q7）avg14
    top = [e for e in fit if e["dspread"] > q7]
    top_avg14 = sum(e["fwd14"] for e in top) / len(top) if top else None
    T = q7

    def grp(recs, T):
        le = [e for e in recs if e["dspread"] <= T]
        gt = [e for e in recs if e["dspread"] > T]
        return le, gt

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "neg14_pct": None}
        return {"n": n, "win14": round(sum(1 for e in recs if e["fwd14"] > 0) / n * 100, 1),
                "avg14": round(sum(e["fwd14"] for e in recs) / n, 2),
                "neg14_pct": round(sum(1 for e in recs if e["fwd14"] < 0) / n * 100, 1)}

    val_le, val_gt = grp(val, T)
    le_s, gt_s, all_s = st(val_le), st(val_gt), st(val)

    # 标签置换 500 次：打乱 val 的 dspread 标签，重算 effect = avg14(gt) - avg14(le)
    obs_effect = (gt_s["avg14"] - le_s["avg14"]) if (gt_s["avg14"] is not None and le_s["avg14"] is not None) else None
    n_val = len(val)
    fwd14s = [e["fwd14"] for e in val]
    labels = [e["dspread"] for e in val]
    shuffled_more_extreme = 0
    trials = 500
    for _ in range(trials):
        shuffled = labels[:]
        random.shuffle(shuffled)
        gt_avg = sum(f for f, l in zip(fwd14s, shuffled) if l > T)
        le_avg = sum(f for f, l in zip(fwd14s, shuffled) if l <= T)
        n_gt = sum(1 for l in shuffled if l > T)
        n_le = n_val - n_gt
        if n_gt and n_le:
            eff = gt_avg / n_gt - le_avg / n_le
            if eff <= obs_effect:
                shuffled_more_extreme += 1
    p_value = shuffled_more_extreme / trials

    gt_clusters = decluster([e["date"] for e in val_gt])

    gates = {
        "① 验证段 >T 组 14d net <=0": gt_s["avg14"] is not None and gt_s["avg14"] <= 0,
        "② >T 显著低于 <=T 组 >=3pp": (gt_s["avg14"] is not None and le_s["avg14"] is not None
                                        and gt_s["avg14"] <= le_s["avg14"] - 3.0),
        "③ >T 负期望占比>=70% 且 <=T <=60%": (gt_s["neg14_pct"] is not None and le_s["neg14_pct"] is not None
                                               and gt_s["neg14_pct"] >= 70 and le_s["neg14_pct"] <= 60),
        "④ 置换 p<0.05": p_value < 0.05,
        "⑤ 去簇后 >T 组 n>=15": gt_clusters >= 15,
    }
    verdict = "spread 硬闸门落地" if all(gates.values()) else "维持候选登记"

    out = {"probe": "A2-2 spread 硬闸门", "fit_n": len(fit), "val_n": len(val),
           "T_fit": round(T, 3) if T is not None else None, "fit_top_avg14": round(top_avg14, 2) if top_avg14 is not None else None,
           "val_le": le_s, "val_gt": gt_s, "val_all": all_s, "obs_effect": round(obs_effect, 2) if obs_effect is not None else None,
           "permutation_p": round(p_value, 4), "gt_clusters": gt_clusters, "gates": gates, "verdict": verdict}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== A2-2 spread 硬闸门 ===")
    print(f"拟合段 n={len(fit)} 定 T={round(T,3) if T else None} 顶档avg14={round(top_avg14,2) if top_avg14 else None}")
    print(f"验证段: <=T 组 {json.dumps(le_s, ensure_ascii=False)}")
    print(f"验证段: >T 组  {json.dumps(gt_s, ensure_ascii=False)}")
    print(f"验证段: 全事件 {json.dumps(all_s, ensure_ascii=False)}")
    print(f"effect(>T-<=T)={round(obs_effect,2) if obs_effect else None} | 置换 p={round(p_value,4)} | 去簇> T n={gt_clusters}")
    for k, v in gates.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print("判定:", verdict)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
