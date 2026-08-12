# -*- coding: utf-8 -*-
"""M-2 扩展：评级线 th_boost 方向探针（2026-08-12，只读，落地 km1 的依据）。

背景：item_analysis.py run_item_analysis 的 value.score 后处理含 th_boost=(TH-50)/50*2.0（TH 高加分，
评级线），与 M-5（composite_score th_bonus 反向 -1.0）方向相反；两者在 composite 内对冲（TH 净影响≈0）。
M-5 只修了 composite 函数本身，value.score 的 th_boost 是同源漏改点（与 main.py:1539 同性质）。

候选（k = TH 在展示层的净系数，含 value 内 th_boost 与 composite th_bonus）：
  k=0  线上现状（对冲，M-5 已验证 Q5 73.4%）
  k=+1 c_no_th（仅 value 正向）
  k=+2 c0（M-5 前正向双计）
  k=-1 移除 th_boost（评级无 TH 修正；composite th_bonus 反向单计）→ 落地
  k=-2 th_boost 反向（评级低 TH 加分）+ composite 反向双计 → 不落地（与 km1 差异微小，引入评级反向大改）

数据：data/item_backtest_full_2025.json（317 buy 信号，net14 口径）。产物：data/_exp_th_boost_grade.json。
"""
import io
import json
import random
from datetime import date, datetime

D = json.load(io.open("data/item_backtest_full_2025.json", encoding="utf-8"))
DQ = {"good": 1.0, "medium": 0.85, "low": 0.6, "insufficient": 0.2}
ACTION_BONUS = {"buy": 1.0, "watch": 0.5, "hold": 0.0, "reduce": -0.5, "avoid": -1.0, "sell": -1.0}


def build():
    rows = []
    for s in D["signals"]:
        if s.get("net14") is None:
            continue
        val = float(s.get("value") or 0)
        th = float(s.get("th") or 50)
        thb = round((th - 50) / 50 * 2.0, 1)  # 引擎内 th_boost（item_analysis.py:1803，已移除）
        score_raw = val - thb  # 还原无 TH 修正的 value（近似：action 修正/事件折扣/whale cap 与 th 无关保留）
        pct = float(s.get("pct") or 50)
        dq = DQ.get(s.get("data_quality") or "low", 0.4)
        ab = ACTION_BONUS.get(s.get("action") or "", 0.0)
        vd = max(0.5, 1.0 - pct / 200)
        off = (th - 50) / 50
        rows.append({"date": s["date"], "net14": s["net14"], "th": th,
                     "k0": (score_raw + ab) * vd * dq,
                     "kp1": (score_raw + off + ab) * vd * dq,
                     "kp2": (score_raw + 2.0 * off + ab) * vd * dq,
                     "km1": (score_raw - off + ab) * vd * dq,
                     "km2": (score_raw - 2.0 * off + ab) * vd * dq})
    return rows


def stats(rs):
    n = len(rs)
    if not n:
        return {"n": 0, "win14": None, "avg14": None}
    w = sum(1 for r in rs if r["net14"] > 0)
    return {"n": n, "win14": round(100.0 * w / n, 1), "avg14": round(sum(r["net14"] for r in rs) / n, 2)}


def buckets(key, rows):
    rs = sorted(rows, key=lambda r: r[key])
    out = []
    for i in range(5):
        seg = rs[i * len(rs) // 5:(i + 1) * len(rs) // 5]
        if seg:
            st = stats(seg)
            st["q"] = "Q%d" % (i + 1)
            out.append(st)
    return out


def spearman(key, rows):
    rs = sorted(rows, key=lambda r: r["net14"])
    n = len(rs)
    rank_net = {id(r): i for i, r in enumerate(rs)}
    rs2 = sorted(rows, key=lambda r: r[key])
    d2 = sum((rank_net[id(r)] - i) ** 2 for i, r in enumerate(rs2))
    return round(1 - 6 * d2 / (n * (n * n - 1)), 4)


def q_diff(key, rs):
    rs = sorted(rs, key=lambda r: r[key])
    q1, q5 = rs[:len(rs) // 5], rs[4 * len(rs) // 5:]
    w1 = 100.0 * sum(1 for r in q1 if r["net14"] > 0) / len(q1)
    w5 = 100.0 * sum(1 for r in q5 if r["net14"] > 0) / len(q5)
    return w5 - w1


def permutation(rows, keys, n_iter=200, seed=42):
    random.seed(seed)
    n = len(rows)
    obs = {k: q_diff(k, rows) for k in keys}
    pvals = {k: 0 for k in keys}
    for _ in range(n_iter):
        net = [r["net14"] for r in rows]
        random.shuffle(net)
        perm = [dict(r, net14=net[i]) for i, r in enumerate(rows)]
        for k in keys:
            if q_diff(k, perm) >= obs[k]:
                pvals[k] += 1
    return obs, {k: round(v / n_iter, 3) for k, v in pvals.items()}


def main():
    rows = build()
    half = date.fromisoformat("2026-01-01")
    pre = [r for r in rows if date.fromisoformat(r["date"]) < half]
    post = [r for r in rows if date.fromisoformat(r["date"]) >= half]
    obs, pvals = permutation(rows, ("km1", "km2"))
    out = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "data/item_backtest_full_2025.json (317 buy 信号, net14, 365d v2-T4)",
        "question": "value.score 后处理 th_boost(TH 高加分) 与 M-5 composite 反向定论矛盾；候选 k=-1(移除)/k=-2(反向)",
        "conclusion": "km1(移除 th_boost, TH 由 composite th_bonus 反向单计) 落地：全样本 spearman +0.087→+0.142、"
                      "Q5 win14 73.4→76.6%、Q5-Q1 差 +8.4→+11.5pp(置换 p=0.10)，前后半段无反转；km2 排序略优但差异微小不落地",
        "n": len(rows), "n_pre": len(pre), "n_post": len(post),
        "buckets": {k: buckets(k, rows) for k in ("k0", "kp1", "kp2", "km1", "km2")},
        "spearman": {k: spearman(k, rows) for k in ("k0", "kp1", "kp2", "km1", "km2")},
        "spearman_pre": {k: spearman(k, pre) for k in ("k0", "kp2", "km1", "km2")},
        "spearman_post": {k: spearman(k, post) for k in ("k0", "kp2", "km1", "km2")},
        "q_diff_obs": {k: round(v, 1) for k, v in obs.items()},
        "permutation_p_200": pvals,
    }
    io.open("data/_exp_th_boost_grade.json", "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1))
    print("written data/_exp_th_boost_grade.json")
    print("spearman:", out["spearman"])
    print("Q5 win14:", {k: b[-1]["win14"] for k, b in out["buckets"].items()})
    print("q_diff:", out["q_diff_obs"], "p:", out["permutation_p_200"])
    print("pre/post spearman km1/km2:", out["spearman_pre"]["km1"], out["spearman_post"]["km1"],
          out["spearman_pre"]["km2"], out["spearman_post"]["km2"])


if __name__ == "__main__":
    main()
