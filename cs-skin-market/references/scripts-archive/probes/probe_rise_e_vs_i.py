# -*- coding: utf-8 -*-
"""E vs I 逐信号讲解数据（2026-08-16，只读）：对 v4 产物 TH≥55 的 44 条 rise 信号，
逐条算 E（hold21）与 I（跟踪止损 -8%）的净收益、退出日与路径峰值，输出讲解素材。"""
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V4 = ROOT / "data" / "_exp_rise_v4_hold.json"
OUT = ROOT / "data" / "_exp_rise_e_vs_i.json"


def main():
    d = json.load(io.open(V4, encoding="utf-8"))
    rise = [s for s in d["signals"] if "吸筹型上涨" in s["action_label"]]
    th55 = [s for s in rise if (s.get("market_th") or 0) >= 55]
    rows = []
    for s in th55:
        fwd = s.get("fwd_series") or []
        entry = s["entry_price"]
        n = min(21, len(fwd))
        # E: hold21
        ret_e = fwd[n - 1] / entry - 1 if n > 0 else None
        # I: 跟踪止损 -8%（自运行最高价）
        peak = 1.0
        exit_day = None
        ret_i = None
        for k in range(1, n + 1):
            r = fwd[k - 1] / entry - 1
            peak = max(peak, 1 + r)
            if 1 + r <= peak * 0.92:
                exit_day = k
                ret_i = r
                break
        if ret_i is None and n > 0:
            ret_i = fwd[n - 1] / entry - 1
            exit_day = n
        rows.append({
            "date": s["date"], "name": s["name"], "th": s.get("market_th"),
            "entry": entry, "net14": s.get("net14"),
            "E_net": round((ret_e - 0.02) * 100, 2) if ret_e is not None else None,
            "I_net": round((ret_i - 0.02) * 100, 2) if ret_i is not None else None,
            "I_exit_day": exit_day,
            "peak_before_exit": round((peak - 1) * 100, 2),
            "path": [round(p / entry, 3) for p in fwd[:21]] if fwd else [],
        })
    n = len(rows)
    e = [r["E_net"] for r in rows if r["E_net"] is not None]
    i = [r["I_net"] for r in rows if r["I_net"] is not None]
    print("TH≥55 rise n=%d | E avg=%.2f win=%.1f%% | I avg=%.2f win=%.1f%% | I早退=%d（%.0f%%）" % (
        n, sum(e) / n, 100 * sum(1 for x in e if x > 0) / n,
        sum(i) / n, 100 * sum(1 for x in i if x > 0) / n,
        sum(1 for r in rows if r["I_exit_day"] and r["I_exit_day"] < 21),
        100 * sum(1 for r in rows if r["I_exit_day"] and r["I_exit_day"] < 21) / n))
    better = sum(1 for r in rows if r["I_net"] > r["E_net"])
    print("I 优于 E: %d / %d 条" % (better, n))
    # 抽象派 1337 明细
    print("\n== 抽象派1337 TH≥55 rise 信号明细 ==")
    for r in rows:
        if "抽象派" in r["name"]:
            print("%s %s th=%s entry=%.2f | E=%+.2f%% | I=%+.2f%% (退出日%d) 峰值%+.0f%% | 路径=%s" % (
                r["date"], r["name"][:20], r["th"], r["entry"], r["E_net"], r["I_net"],
                r["I_exit_day"], r["peak_before_exit"], r["path"][:21]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"n": n, "avg": {"E": round(sum(e) / n, 2), "I": round(sum(i) / n, 2)},
                   "I_better_count": better, "rows": rows}, f, ensure_ascii=False, indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
