# -*- coding: utf-8 -*-
"""买涨腿（吸筹型上涨族）数据级 A2（2026-08-15）。

条件（预注册，来自审计③ F 桶）：价涨(chg7>3%) + 供缩(s7≤0.85s30) + 30日供给扩张(sc30>5%)
+ 地板 200/100 + survive≥3000（有值则查）。
walk-forward：拟合 2023-06~2025-08 / 验证 2025-08~2026-08；去簇 ±3 天；
对照 = 同段「价涨全事件」基线；置换 = 价涨事件打乱供缩标签 500 次。
门槛：验证段去簇 n≥15；win14 ≥ 基线+5pp 或 avg14 ≥ 基线+2pp；方向一致；p<0.05。
"""
import json
import random
import sqlite3
import sys
from datetime import date as D
from pathlib import Path

ROOT = Path(r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market')
sys.path.insert(0, str(ROOT))
CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_rise_leg_a2.json"
SPLIT = "2025-08-10"


def main():
    random.seed(20260815)
    c = sqlite3.connect(CYCLE_DB); c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    cand = []
    rise_all = []
    for iid in items:
        rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        n = len(prices)
        for i in range(90, n):
            if i + 30 >= n:
                continue
            chg7 = (prices[i] / prices[i - 7] - 1) * 100 if i >= 7 else 0
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            rec = {"date": dates[i], "name": iid, "fwd14": round(fwd14, 2), "fwd30": round(fwd30, 2)}
            if chg7 <= 3:
                continue
            rise_all.append(rec)
            s7v = insale[i - 6:i + 1]
            s30v = insale[i - 29:i + 1]
            s30_ago = insale[i - 59:i - 29]
            if any(x is None for x in s7v) or any(x is None for x in s30v) or any(x is None for x in s30_ago):
                continue
            a7 = sum(s7v) / 7
            a30 = sum(s30v) / 30
            a30_ago = sum(s30_ago) / 30
            if a30 <= 0 or a30_ago <= 0 or a7 > 0.85 * a30:
                continue
            sc30 = (a30 / a30_ago - 1) * 100
            if sc30 <= 5:
                continue
            # 地板
            floor = 200 if prices[i] < 10000 else 100
            if 0 < insale[i] < floor:
                continue
            cand.append(rec)
    c.close()

    def seg(recs, lo, hi):
        return [r for r in recs if lo <= r["date"] < hi]

    def dedup(recs, gap=4):
        by = {}
        for r in recs:
            by.setdefault(r["name"], []).append(r)
        kept = []
        for name, rs in by.items():
            rs.sort(key=lambda x: x["date"])
            last = None
            for r in rs:
                d = D.fromisoformat(r["date"])
                if last is None or (d - last).days >= gap:
                    kept.append(r)
                    last = d
        return kept

    def st(recs):
        nn = len(recs)
        if nn == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        return {"n": nn,
                "win14": round(sum(1 for r in recs if r["fwd14"] > 0) / nn * 100, 1),
                "avg14": round(sum(r["fwd14"] for r in recs) / nn, 2),
                "win30": round(sum(1 for r in recs if r["fwd30"] > 0) / nn * 100, 1),
                "avg30": round(sum(r["fwd30"] for r in recs) / nn, 2)}

    cand_fit = dedup(seg(cand, "2023-06-01", SPLIT))
    cand_val = dedup(seg(cand, SPLIT, "2026-08-06"))
    base_fit = seg(rise_all, "2023-06-01", SPLIT)
    base_val = seg(rise_all, SPLIT, "2026-08-06")

    rng = random.Random(20260815)
    n_cand_val = len(cand_val)
    obs_w = (st(cand_val)["win14"] or 0) - (st(base_val)["win14"] or 0)
    obs_a = (st(cand_val)["avg14"] or 0) - (st(base_val)["avg14"] or 0)
    pool = seg(rise_all, SPLIT, "2026-08-06")
    cnt_w = cnt_a = 0
    N = 500
    for _ in range(N):
        rng.shuffle(pool)
        fake = pool[:n_cand_val]
        fw = (st(fake)["win14"] or 0) - (st(base_val)["win14"] or 0)
        fa = (st(fake)["avg14"] or 0) - (st(base_val)["avg14"] or 0)
        if fw >= obs_w:
            cnt_w += 1
        if fa >= obs_a:
            cnt_a += 1

    gates = {
        "n_val_dedup>=15": len(cand_val) >= 15,
        "win14_val>=base+5pp": (st(cand_val)["win14"] or 0) >= (st(base_val)["win14"] or 0) + 5,
        "avg14_val>=base+2pp": (st(cand_val)["avg14"] or 0) >= (st(base_val)["avg14"] or 0) + 2,
        "fit_val_direction": ((st(cand_fit)["win14"] or 0) >= (st(base_fit)["win14"] or 0)) and
                             ((st(cand_val)["win14"] or 0) >= (st(base_val)["win14"] or 0)),
        "perm_p<0.05": (cnt_w / N < 0.05) or (cnt_a / N < 0.05),
    }
    passed = all(gates.values())
    out = {"probe": "买涨腿 A2", "cand_fit": st(cand_fit), "cand_val": st(cand_val),
           "base_fit": st(base_fit), "base_val": st(base_val),
           "obs_win_pp": round(obs_w, 1), "obs_avg_pp": round(obs_a, 2),
           "p_win": cnt_w / N, "p_avg": cnt_a / N, "gates": gates, "passed": passed}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"拟合段: cand {st(cand_fit)} | base {st(base_fit)}")
    print(f"验证段: cand {st(cand_val)} | base {st(base_val)}")
    print(f"验证段超额: win +{obs_w}pp avg +{obs_a}pp; p_win={cnt_w/N:.3f} p_avg={cnt_a/N:.3f}")
    print("门槛:", gates)
    print("PASSED =", passed)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
