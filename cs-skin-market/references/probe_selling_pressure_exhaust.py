# -*- coding: utf-8 -*-
"""M-1 抛压衰竭大盘择时检验（2026-08-11，只读研究）。

检验 compute_selling_pressure_exhaustion（index_analysis.py:876-930）与 market_th.py:527-537
buy 接线（sp>=85）在大盘指数上的择时价值。
数据：market_index 表（366 天，2025-08-11 ~ 2026-08-11）。
口径：逐日复算 sp 分数；触发桶 = sp>=85；对照桶 = drop20<=-7 且 sp<85；
fwd14 = 信号日后第 14 个有 K 线日的指数涨跌 - 2%（net2%）；去簇(±3 天取首)作稳健性。
判定（报告附录 E1）：n>=30；触发桶 win14 >= 对照桶 +10pp 且 >= 基线(317 信号 71.0%) +5pp。
产物：data/_exp_selling_pressure_exhaust.json。
"""
import json, io, sys
from datetime import datetime

sys.path.insert(0, ".")

from pipeline import db
from pipeline.index_analysis import compute_selling_pressure_exhaustion


def load_index():
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT date, value FROM market_index WHERE value > 0 ORDER BY date").fetchall()
    finally:
        conn.close()
    return [(r["date"], r["value"]) for r in rows]


def dedup_cluster(dates, window=3):
    """±3 天簇取首（与回放去簇口径一致）：保留窗口内首个信号日。"""
    out = []
    for d in sorted(dates):
        if not out or (datetime.fromisoformat(d) - datetime.fromisoformat(out[-1])).days > window:
            out.append(d)
    return out


def fwd_ret(series, idx, days=14, cost=0.02):
    """series[idx] 后第 days 个有 K 线日的收益（net 扣 cost）。"""
    n = len(series)
    if idx + days >= n:
        return None
    base = series[idx][1]
    fwd = series[idx + days][1]
    if base <= 0:
        return None
    return (fwd / base - 1) * 100 - cost * 100


def main():
    series = load_index()
    dates = [d for d, _ in series]
    values = [v for _, v in series]
    print(f"指数序列: {len(series)} 天 ({dates[0]} ~ {dates[-1]})")

    trigger, control = [], []
    for i in range(21, len(series)):
        window = values[max(0, i - 89):i + 1]  # 截至信号日 90 天窗口
        sp = compute_selling_pressure_exhaustion(window)
        score = sp["score"]
        drop20 = sp.get("drop20", 0.0)
        if score >= 85:
            trigger.append((dates[i], score, drop20))
        elif drop20 <= -7:
            control.append((dates[i], score, drop20))

    def stats(rows):
        r14 = [fwd_ret(series, dates.index(d)) for d, _, _ in rows]
        r14 = [x for x in r14 if x is not None]
        n = len(r14)
        if not n:
            return {"n": 0, "win14": None, "avg14": None, "n_signals": len(rows)}
        return {"n": n, "n_signals": len(rows),
                "win14": round(sum(1 for x in r14 if x > 0) / n * 100, 1),
                "avg14": round(sum(r14) / n, 2)}

    t_all = stats(trigger)
    c_all = stats(control)
    t_dedup = stats([r for r in trigger if r[0] in dedup_cluster([r[0] for r in trigger])])

    out = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "market_index (366d)",
        "params": {"sp_trigger": 85, "control_drop20": -7, "fwd_days": 14, "cost_pct": 2.0,
                   "dedup_window_days": 3},
        "index_range": [dates[0], dates[-1]],
        "trigger_dates": [r[0] for r in trigger],
        "trigger": t_all,
        "control": c_all,
        "trigger_dedup": t_dedup,
        "baseline": {"note": "317 buy 信号 win14 71.0% (item_backtest_full_2025.json, net2%)"},
        "verdict": None,
    }
    # 判定（仅当 n>=30）
    if t_all["n"] >= 30 and c_all["n"] >= 30:
        d_ctrl = t_all["win14"] - c_all["win14"]
        d_base = t_all["win14"] - 71.0
        out["verdict"] = {
            "n_ok": True,
            "win14_vs_control_pp": round(d_ctrl, 1),
            "win14_vs_baseline_pp": round(d_base, 1),
            "pass": d_ctrl >= 10 and d_base >= 5,
        }
    else:
        out["verdict"] = {"n_ok": False, "note": "n<30 只报告不判定"}

    with io.open("data/_exp_selling_pressure_exhaust.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("trigger(sp>=85):", t_all)
    print("trigger dedup :", t_dedup)
    print("control(drop20<=-7 & sp<85):", c_all)
    print("verdict:", out["verdict"])
    print("saved data/_exp_selling_pressure_exhaust.json")


if __name__ == "__main__":
    main()