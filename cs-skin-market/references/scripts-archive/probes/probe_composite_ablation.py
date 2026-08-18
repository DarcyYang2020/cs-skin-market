# -*- coding: utf-8 -*-
"""M-2 composite 消融检验（2026-08-11，只读研究）。

检验 composite_score（item_analysis.py:658-690）的乘子/加分在 365d 回放 buy 信号集内的
排序区分力与方向问题：估值折价双计权（P1-5）与 TH 偏移方向（P1-6）。
数据：data/item_backtest_full_2025.json（317 buy 信号，含 value/action/th/pct/data_quality/net14）。
产物：data/_exp_composite_ablation.json。
"""
import json, io
from collections import Counter
from datetime import datetime

D = json.load(io.open("data/item_backtest_full_2025.json", encoding="utf-8"))
SIGS = D["signals"]

DQ = {"good": 1.0, "medium": 0.85, "low": 0.6, "insufficient": 0.2}
ACTION_BONUS = {"buy": 1.0, "watch": 0.5, "hold": 0.0, "reduce": -0.5, "avoid": -1.0, "sell": -1.0}


def composite(score, action, th, pct, dq, use_val=1.0, use_th=1.0, use_action=1.0, th_sign=1.0):
    action_bonus = ACTION_BONUS.get(action, 0.0) if use_action else 0.0
    th_bonus = (float(th) - 50) / 50 * th_sign if use_th else 0.0
    val_disc = max(0.5, 1.0 - pct / 200) if use_val else 1.0
    return (score + action_bonus + th_bonus) * val_disc * dq


def stats(sigs):
    r14 = [s["net14"] for s in sigs if s.get("net14") is not None]
    n = len(r14)
    if not n:
        return {"n": 0, "win14": None, "avg14": None}
    return {"n": n, "win14": round(sum(1 for x in r14 if x > 0) / n * 100, 1),
            "avg14": round(sum(r14) / n, 2)}


def quantile_buckets(rows, key, k=5):
    rows = sorted(rows, key=lambda r: r[key])
    out = []
    for i in range(k):
        lo = i * len(rows) // k
        hi = (i + 1) * len(rows) // k
        bucket = rows[lo:hi]
        if bucket:
            st = stats(bucket)
            st["q"] = f"Q{i+1}"
            st["score_range"] = [round(bucket[0][key], 2), round(bucket[-1][key], 2)]
            out.append(st)
    return out


def main():
    rows = []
    for s in SIGS:
        score = float(s["value"] or 0)
        action = s.get("action") or ""
        th = float(s.get("th") or 50)
        pct = float(s.get("pct") or 50)
        dq = DQ.get(s.get("data_quality") or "low", 0.4)
        rows.append({
            "date": s["date"], "name": s.get("name"), "signal_type": s.get("signal_type"),
            "net14": s.get("net14"), "net30": s.get("net30"),
            "value": score, "action": action, "th": th, "pct": pct, "data_quality": dq,
            "c0": composite(score, action, th, pct, dq, 1, 1, 1),
            "c_no_val": composite(score, action, th, pct, dq, 0, 1, 1),
            "c_no_th": composite(score, action, th, pct, dq, 1, 0, 1),
            "c_base": composite(score, action, th, pct, dq, 0, 0, 0),
            "c_th_rev": composite(score, action, th, pct, dq, 1, 1, 1, th_sign=-1.0),
        })

    out = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "data/item_backtest_full_2025.json (317 buy 信号, net2%)",
        "note": "信号集内 action 全为 buy、data_quality 全为 good（常数）→ 动作加分/数据质量乘子无区分度，不适用消融；聚焦估值折价(双计权)与 TH 偏移方向",
        "total": len(rows),
        "action_dist": dict(Counter(r["action"] for r in rows)),
        "dq_dist": dict(Counter(r["data_quality"] for r in rows)),
        "buckets": {
            "c0": quantile_buckets(rows, "c0"),
            "c_no_val": quantile_buckets(rows, "c_no_val"),
            "c_no_th": quantile_buckets(rows, "c_no_th"),
            "c_base": quantile_buckets(rows, "c_base"),
            "c_th_rev": quantile_buckets(rows, "c_th_rev"),
        },
        "th_buckets": {},
        "pct_buckets": {},
    }

    # TH 方向检验：三分位
    for label, lo, hi in (("TH_low<35", 0, None), ("TH_mid35-55", None, None), ("TH_high>55", None, None)):
        if label == "TH_low<35":
            sub = [r for r in rows if r["th"] < 35]
        elif label == "TH_mid35-55":
            sub = [r for r in rows if 35 <= r["th"] <= 55]
        else:
            sub = [r for r in rows if r["th"] > 55]
        st = stats(sub)
        st["n"] = len(sub)
        out["th_buckets"][label] = st

    # pct 双计权检验：低分位（<=30）vs 中（30-70）vs 高（>70）
    for label, pred in (("pct_low<=30", lambda r: r["pct"] <= 30),
                        ("pct_mid30-70", lambda r: 30 < r["pct"] <= 70),
                        ("pct_high>70", lambda r: r["pct"] > 70)):
        sub = [r for r in rows if pred(r)]
        st = stats(sub)
        st["n"] = len(sub)
        out["pct_buckets"][label] = st

    # 秩相关（net14 vs 各变体）
    def spearman(xs, ys):
        def rank(v):
            order = sorted(v)
            return [order.index(x) + 1 for x in v]
        rx, ry = rank(xs), rank(ys)
        n = len(xs)
        mx, my = sum(rx) / n, sum(ry) / n
        cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
        vx = sum((a - mx) ** 2 for a in rx) ** 0.5
        vy = sum((b - my) ** 2 for b in ry) ** 0.5
        return round(cov / (vx * vy), 3) if vx and vy else None

    rr = [r for r in rows if r.get("net14") is not None]
    out["spearman_vs_net14"] = {
        "c0": spearman([r["c0"] for r in rr], [r["net14"] for r in rr]),
        "c_no_val": spearman([r["c_no_val"] for r in rr], [r["net14"] for r in rr]),
        "c_no_th": spearman([r["c_no_th"] for r in rr], [r["net14"] for r in rr]),
        "c_base": spearman([r["c_base"] for r in rr], [r["net14"] for r in rr]),
        "c_th_rev": spearman([r["c_th_rev"] for r in rr], [r["net14"] for r in rr]),
        "value": spearman([r["value"] for r in rr], [r["net14"] for r in rr]),
        "th": spearman([r["th"] for r in rr], [r["net14"] for r in rr]),
        "pct": spearman([r["pct"] for r in rr], [r["net14"] for r in rr]),
    }

    with io.open("data/_exp_composite_ablation.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("total:", len(rows))
    print("spearman:", out["spearman_vs_net14"])
    for name, b in out["buckets"].items():
        q1 = b[0] if b else {}
        q5 = b[-1] if b else {}
        print(f"{name:10s} Q1 win14={q1.get('win14')} avg={q1.get('avg14')} (n={q1.get('n')}) | "
              f"Q5 win14={q5.get('win14')} avg={q5.get('avg14')} (n={q5.get('n')})")
    for k, v in out["th_buckets"].items():
        print(f"{k}: n={v['n']} win14={v['win14']} avg14={v['avg14']}")
    for k, v in out["pct_buckets"].items():
        print(f"{k}: n={v['n']} win14={v['win14']} avg14={v['avg14']}")
    print("saved data/_exp_composite_ablation.json")


if __name__ == "__main__":
    main()