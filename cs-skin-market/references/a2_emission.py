# -*- coding: utf-8 -*-
"""A2 第五件套：发射分布复算（2026-08-16，候选族准入硬门槛）。

方法缺陷（decision-log 2026-08-16 条目 D）：数据层 A2 在触发分布（全候选 item-day）上检验，
而引擎只发射「优先级仲裁 + 7 日去重 + 守卫」之后的残留子集，且该残留系统性更差
（rise_accum：数据层验证段 win 51.6%/+13.09 → 引擎发射 21 条 33.3%/−1.55）。

本模块 = 可复用发射侧检验：对「族开」回放产物 vs 「基线」回放产物做——
1. 发射增量：added（族新增信号）/ displaced（被族顶替掉的基线信号）；
2. walk-forward 分段（拟合/验证，默认切点 2025-08-10）统计；
3. 置换检验（零假设 = 新增信号不优于从现存买书同段随机抽样的同规模子集）：
   p_avg = P(随机样本 avg14 ≥ 族 avg14)，500 次无放回抽样；
4. 五门裁定：n_val≥15 / val avg14 超买书 +2pp / val win14 不低于买书 /
   拟合验证方向一致（两段 avg14 均超买书）/ p_avg<0.05。

口径：net14/net30 为回放产物自带净收益（扣 2% 双边成本）；组合级是否落地仍需
「组合级 + 前后半段一致」判据（b1v2.simulate），本工具只做候选族发射侧准入筛选。
"""
import io
import json
import random
from datetime import date

SPLIT = date(2025, 8, 10)  # walk-forward 切点（拟合/验证）


def load_signals(path):
    d = json.load(io.open(path, encoding="utf-8"))
    out = []
    for s in d.get("signals", []):
        if s.get("net14") is None:
            continue
        out.append({
            "date": date.fromisoformat(s["date"]), "name": s["name"],
            "action_label": s.get("action_label") or "",
            "net14": s["net14"], "net30": s.get("net30"),
        })
    return out


def _stats(recs):
    n = len(recs)
    if n == 0:
        return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
    n30 = [r for r in recs if r["net30"] is not None]
    return {
        "n": n,
        "win14": round(100.0 * sum(1 for r in recs if r["net14"] > 0) / n, 1),
        "avg14": round(sum(r["net14"] for r in recs) / n, 2),
        "win30": round(100.0 * sum(1 for r in n30 if r["net30"] > 0) / len(n30), 1) if n30 else None,
        "avg30": round(sum(r["net30"] for r in n30) / len(n30), 2) if n30 else None,
    }


def _perm_p(added, book, n_iter=500, seed=0):
    """零假设：新增信号的 avg14/win14 不优于现存买书同段同规模随机子集。
    买书规模不足时放回抽样（choices），并标注。"""
    if not added or not book:
        return {"p_avg": None, "p_win": None, "book_avg14": None, "book_win14": None,
                "with_replacement": None}
    obs_avg = sum(r["net14"] for r in added) / len(added)
    obs_win = sum(1 for r in added if r["net14"] > 0) / len(added)
    rng = random.Random(seed)
    k = len(added)
    with_rep = len(book) < k
    pick = (lambda: rng.choices(book, k=k)) if with_rep else (lambda: rng.sample(book, k))
    ge_avg = ge_win = 0
    for _ in range(n_iter):
        sample = pick()
        if sum(r["net14"] for r in sample) / k >= obs_avg:
            ge_avg += 1
        if sum(1 for r in sample if r["net14"] > 0) / k >= obs_win:
            ge_win += 1
    book_avg = sum(r["net14"] for r in book) / len(book)
    book_win = sum(1 for r in book if r["net14"] > 0) / len(book)
    return {"p_avg": round(ge_avg / n_iter, 3), "p_win": round(ge_win / n_iter, 3),
            "book_avg14": round(book_avg, 2), "book_win14": round(100.0 * book_win, 1),
            "with_replacement": with_rep}


def analyze(fam_on_path, baseline_path, family_keyword, label, out=None, n_iter=500, seed=0):
    fam_on = load_signals(fam_on_path)
    base = load_signals(baseline_path)
    bkeys = {(s["name"], s["date"]) for s in base}
    # 族的发射足迹 = 全部新增键（含被族去重交互挤出的他族 knock-on 信号，按标签分解报告）
    added = [s for s in fam_on if (s["name"], s["date"]) not in bkeys]
    fkeys = {(s["name"], s["date"]) for s in fam_on}
    displaced = [s for s in base if (s["name"], s["date"]) not in fkeys]
    from collections import Counter
    label_breakdown = dict(Counter(s["action_label"] for s in added))

    seg = {}
    for tag, pred in (("fit", lambda d: d < SPLIT), ("val", lambda d: d >= SPLIT)):
        a = [s for s in added if pred(s["date"])]
        book = [s for s in base if pred(s["date"])]
        perm = _perm_p(a, book, n_iter=n_iter, seed=seed)
        seg[tag] = {"added": _stats(a), "displaced": _stats([s for s in displaced if pred(s["date"])]),
                    "book": _stats(book), **perm}

    val = seg["val"]
    fit = seg["fit"]
    gates = {
        "n_val>=15": val["added"]["n"] >= 15,
        "val_avg14_excess>=2pp": (val["added"]["avg14"] is not None and val["p_avg"] is not None
                                  and val["added"]["avg14"] - val["book_avg14"] >= 2.0),
        "val_win14>=book": (val["added"]["win14"] is not None and val["book_win14"] is not None
                            and val["added"]["win14"] >= val["book_win14"]),
        "fit_val_direction": (fit["added"]["avg14"] is not None and val["added"]["avg14"] is not None
                              and fit["book_avg14"] is not None and val["book_avg14"] is not None
                              and fit["added"]["avg14"] > fit["book_avg14"]
                              and val["added"]["avg14"] > val["book_avg14"]),
        "p_avg<0.05": val["p_avg"] is not None and val["p_avg"] < 0.05,
    }
    res = {
        "probe": "A2 第五件套 发射分布复算",
        "family": label, "split": SPLIT.isoformat(),
        "added_total": len(added), "displaced_total": len(displaced),
        "added_by_label": label_breakdown,
        "segments": seg, "gates": gates, "passed": all(gates.values()),
    }
    if out:
        with io.open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return res


def print_report(res):
    print("== A2 发射侧：%s（added=%d displaced=%d）%s ==" % (
        res["family"], res["added_total"], res["displaced_total"],
        {k.split("·")[0][:8]: v for k, v in res.get("added_by_label", {}).items()}))
    for tag in ("fit", "val"):
        s = res["segments"][tag]
        print("  [%s] added n=%d win14=%s avg14=%s | book n=%d win14=%s avg14=%s | p_avg=%s p_win=%s" % (
            tag, s["added"]["n"], s["added"]["win14"], s["added"]["avg14"],
            s["book"]["n"], s["book"]["win14"], s["book"]["avg14"], s["p_avg"], s["p_win"]))
        d = s["displaced"]
        print("        displaced n=%d win14=%s avg14=%s" % (d["n"], d["win14"], d["avg14"]))
    print("  gates:", {k: v for k, v in res["gates"].items()}, "=> PASSED" if res["passed"] else "=> FAILED")
    return res["passed"]
