# -*- coding: utf-8 -*-
"""第一性原理审计第一枪（2026-08-15）：动量因子存在性——强势品是否延续强势。

用户示例：抽象派1337（+1266%）、合纵（+1088%）全年单调上涨，远超等权 +610%。
引擎漏掉它们的结构性原因 = 引擎只有「买跌」路径（pct≤20~40 + z<0 + 深跌回调），
从无「买涨」腿。本探针验证：CS 饰品市场是否存在可持续的动量 alpha。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market')
sys.path.insert(0, str(ROOT))
CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_momentum_alpha.json"


def main():
    c = sqlite3.connect(CYCLE_DB); c.row_factory = sqlite3.Row
    ph = {}
    for r in c.execute("SELECT item_id, date, price_rmb FROM price_history WHERE price_rmb IS NOT NULL ORDER BY date"):
        ph.setdefault(r["item_id"], {})[r["date"]] = r["price_rmb"]
    c.close()

    # 月度截面动量：每月底按过去 90 日收益排序分 5 档，看次月前视 30 日收益
    months = sorted({d[:7] for m in ph.values() for d in m})
    quint = {"Q1_最弱": [], "Q2": [], "Q3": [], "Q4": [], "Q5_最强": []}
    import datetime as dt
    for mi in range(1, len(months) - 1):
        m_end = months[mi]
        # 月末最后一个交易日
        month_days = [d for m in ph.values() for d in m if d[:7] == m_end]
        end_day = max(month_days)
        # 月初 90 日前
        start = (dt.date.fromisoformat(end_day[:8] + "01") - dt.timedelta(days=100)).isoformat()
        scores = []
        for iid, m in ph.items():
            keys = sorted(m)
            end_p = None
            for k in keys:
                if k <= end_day:
                    end_p = m[k]
            past_p = None
            for k in keys:
                if k >= start:
                    past_p = m[k]
                    break
            if end_p and past_p and past_p > 0:
                ret90 = (end_p / past_p - 1) * 100
                # 前视 30 日
                fwd_p = None
                for k in keys:
                    if k > end_day:
                        fwd_p = m[k]
                        break
                if fwd_p:
                    scores.append((iid, ret90, (fwd_p / end_p - 1) * 100))
        if len(scores) < 25:
            continue
        scores.sort(key=lambda x: x[1])
        k = len(scores) // 5
        for qi, q in enumerate(["Q1_最弱", "Q2", "Q3", "Q4", "Q5_最强"]):
            for _, _, fwd in scores[qi * k:(qi + 1) * k if qi < 4 else len(scores)]:
                quint[q].append(fwd)

    out = {}
    print("=== 动量因子存在性（月度截面：90 日动量 → 次月 30 日前视）===")
    for q in ["Q1_最弱", "Q2", "Q3", "Q4", "Q5_最强"]:
        v = quint[q]
        if not v:
            continue
        win = sum(1 for x in v if x > 0) / len(v) * 100
        avg = sum(v) / len(v)
        out[q] = {"n": len(v), "win30_pct": round(win, 1), "avg30_pct": round(avg, 2)}
        print(f"  {q:8s} n={len(v):5d}  win30={win:5.1f}%  avg30={avg:+6.2f}%")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"probe": "动量因子存在性", "quintiles": out}, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
