# -*- coding: utf-8 -*-
"""O3 惜售中段腿 A2 阶段 1（2026-08-15，做厚收益端候选族正式验证）。

预注册（decision-log O3 条目）：
- 候选族条件（固定，来自阶段0）：供缩 s7≤0.85×s30 且 s30>0 且 5 日价跌<-3% 且 pct90∈(20,60]
  （中段=引擎当前无覆盖带）；加引擎级守卫：在售深度≥200/100 地板、survive≥3000（有值则查）、
  排除 sent<40 且大盘TH<45（用价格近似情绪近似）。
- walk-forward：拟合段 2023-06~2025-08、验证段 2025-08~2026-08（切点 2025-08-10）。
- 事件级去簇：每品 ±3 天。
- 对照：同段「中段无条件基线」（pct 20~60 全事件）。
- 置换：在中段全事件上随机打乱「供缩+价跌」标签 500 次，报实际 alpha 的 p 值。
- 门槛：验证段去簇后 n≥15；验证段 win14 ≥ 基线+8pp 或 avg14 ≥ 基线+3pp；拟合/验证方向一致。
- 落地（全过才谈）：新增 SignalFamily（默认经 CS_ENGINE_XISHOU_MID=0 关闭，A2 通过后开会），
  bump ENGINE_VERSION v2-T11 + 全链路 sync。否则登记候选不落地。
"""
import json
import random
import sqlite3
import sys
from pathlib import Path
from datetime import date as D

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_o3_a2.json"
SPLIT = "2025-08-10"


def pct90(prices, i):
    lo = max(0, i - 89)
    w = prices[lo:i + 1]
    cur = prices[i]
    return sum(1 for p in w if p <= cur) / len(w) * 100


def main():
    random.seed(20260815)
    cyc = sqlite3.connect(CYCLE_DB)
    cyc.row_factory = sqlite3.Row
    items = cyc.execute("SELECT id, name FROM items WHERE good_id > 0 ORDER BY id").fetchall()

    cand = []       # 候选族事件（含守卫后）
    mid_all = []    # 中段全事件（置换池）
    for it in items:
        rows = cyc.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                           "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        n = len(prices)
        for i in range(90, n):
            if i + 30 >= n:
                continue
            pct = pct90(prices, i)
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            rec = {"date": dates[i], "name": it["name"], "fwd14": round(fwd14, 2), "fwd30": round(fwd30, 2)}
            if 20 < pct <= 60:
                mid_all.append(rec)
            # 候选族条件
            s7 = insale[i - 6:i + 1]
            s30 = insale[i - 29:i + 1]
            if any(x is None for x in s7) or any(x is None for x in s30):
                continue
            a7 = sum(s7) / 7
            a30 = sum(s30) / 30
            if a30 <= 0 or a7 > 0.85 * a30:
                continue
            chg5 = (prices[i] - prices[i - 5]) / prices[i - 5] * 100 if prices[i - 5] else 0
            if chg5 >= -3:
                continue
            if not (20 < pct <= 60):
                continue
            # 地板：最新在售量 >= 200/100 分档（单价<1万→200，≥1万→100）
            floor = 200 if prices[i] < 10000 else 100
            if insale[i] is not None and 0 < insale[i] < floor:
                continue
            cand.append(rec)
    cyc.close()

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
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        return {"n": n,
                "win14": round(sum(1 for r in recs if r["fwd14"] > 0) / n * 100, 1),
                "avg14": round(sum(r["fwd14"] for r in recs) / n, 2),
                "win30": round(sum(1 for r in recs if r["fwd30"] > 0) / n * 100, 1),
                "avg30": round(sum(r["fwd30"] for r in recs) / n, 2)}

    cand_fit = dedup(seg(cand, "2023-06-01", SPLIT))
    cand_val = dedup(seg(cand, SPLIT, "2026-08-06"))
    base_fit = seg(mid_all, "2023-06-01", SPLIT)
    base_val = seg(mid_all, SPLIT, "2026-08-06")

    # 置换：验证段中段全事件里打乱候选标签 500 次，看 win14/avg14 增量
    rng = random.Random(20260815)
    n_cand_val = len(cand_val)
    obs_w = (st(cand_val)["win14"] or 0) - (st(base_val)["win14"] or 0)
    obs_a = (st(cand_val)["avg14"] or 0) - (st(base_val)["avg14"] or 0)
    base_pool = seg(mid_all, SPLIT, "2026-08-06")
    cnt_w = cnt_a = 0
    N = 500
    for _ in range(N):
        rng.shuffle(base_pool)
        fake = base_pool[:n_cand_val]
        fw = (st(fake)["win14"] or 0) - (st(base_val)["win14"] or 0)
        fa = (st(fake)["avg14"] or 0) - (st(base_val)["avg14"] or 0)
        if fw >= obs_w:
            cnt_w += 1
        if fa >= obs_a:
            cnt_a += 1
    p_w = cnt_w / N
    p_a = cnt_a / N

    gates = {
        "n_val_dedup>=15": len(cand_val) >= 15,
        "win14_val>=base+8pp": (st(cand_val)["win14"] or 0) >= (st(base_val)["win14"] or 0) + 8,
        "avg14_val>=base+3pp": (st(cand_val)["avg14"] or 0) >= (st(base_val)["avg14"] or 0) + 3,
        "fit_val_direction": ((st(cand_fit)["win14"] or 0) >= (st(base_fit)["win14"] or 0)) and
                             ((st(cand_val)["win14"] or 0) >= (st(base_val)["win14"] or 0)),
        "perm_p<0.05": (p_w < 0.05) or (p_a < 0.05),
    }
    passed = all(gates.values())
    out = {
        "probe": "O3 惜售中段腿 A2 阶段1",
        "candidate_conditions": "供缩 s7<=0.85*s30 且 s30>0 且 5日价跌<-3% 且 pct90∈(20,60]，地板200/100",
        "cand_fit": st(cand_fit), "cand_val": st(cand_val),
        "base_fit": st(base_fit), "base_val": st(base_val),
        "permutation": {"obs_win_pp": round(obs_w, 1), "obs_avg_pp": round(obs_a, 2),
                        "p_win": p_w, "p_avg": p_a, "n_perm": N},
        "gates": gates, "passed": passed,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== O3 惜售中段腿 A2 ===")
    print(f"  拟合段: cand {st(cand_fit)} | base {st(base_fit)}")
    print(f"  验证段: cand {st(cand_val)} | base {st(base_val)}")
    print(f"  验证段超额: win +{obs_w}pp, avg +{obs_a}pp; 置换 p_win={p_w}, p_avg={p_a}")
    print(f"  门槛: {gates}")
    print(f"  PASSED = {passed}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
