# -*- coding: utf-8 -*-
"""大盘时期数据挖掘（2026-08-16，只读）：时期从 3 年数据里挖，不靠人的命名。

候选轴全部来自本战役已有发现（非本次拟合）：
  长周期 chg180（第一因子）/ 短周期 chg30 / 波动 vol20 / 广度 breadth5。
先验候选划分（预注册，固定四格+恐慌深度格）：
  S1 牛市上行: chg180>0 且 chg30>0
  S2 牛市回调: chg180>0 且 chg30≤0
  S3 弱市阴跌: chg180≤0 且 chg30≤0
  S4 弱市反弹: chg180≤0 且 chg30>0
  P  恐慌深跌(跨期): chg30≤-15
报每期 n、大盘自身前视 14/30/60（win/avg），以及四切点稳定性（边界分类的 fit/val 一致性）。
输出 data/_exp_market_periods.json。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_market_periods.json"
CUTS = ("2024-07-01", "2024-10-01", "2025-02-01", "2025-08-10")


def main():
    st = json.load(open(ROOT / "data" / "market_state_daily.json", encoding="utf-8"))
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    mvals = [r["value"] for r in mrows]
    idx = {r["date"]: i for i, r in enumerate(mrows)}

    def fwd(d, h):
        i = idx.get(d)
        if i is None or i + h >= len(mvals):
            return None
        return (mvals[i + h] / mvals[i] - 1) * 100

    def classify(s):
        c180 = s.get("chg180") or 0
        c30 = s.get("chg30") or 0
        if c30 <= -15:
            return "P恐慌深跌"
        if c180 > 0 and c30 > 0:
            return "S1牛市上行"
        if c180 > 0 and c30 <= 0:
            return "S2牛市回调"
        if c180 <= 0 and c30 <= 0:
            return "S3弱市阴跌"
        return "S4弱市反弹"

    periods = {}
    for d, s in st.items():
        if "chg180" not in s or "chg30" not in s:
            continue
        p = classify(s)
        periods.setdefault(p, []).append((d, fwd(d, 14), fwd(d, 30), fwd(d, 60),
                                          s.get("vol20"), s.get("breadth5")))

    def stats(recs, k):
        xs = [r[k] for r in recs if r[k] is not None]
        if len(xs) < 5:
            return "n=%d(少)" % len(xs)
        return "n=%d win=%.0f%% avg=%+.1f" % (len(xs), 100 * sum(1 for x in xs if x > 0) / len(xs), sum(xs) / len(xs))

    out = {"probe": "大盘时期数据挖掘", "periods": {}}
    print("== 时期（大盘自身前视）==")
    for p in sorted(periods):
        recs = periods[p]
        row = {"n": len(recs), "fwd14": stats(recs, 1), "fwd30": stats(recs, 2), "fwd60": stats(recs, 3),
               "vol20_med": round(sorted(r[4] for r in recs if r[4] is not None)[len([r for r in recs if r[4] is not None]) // 2], 4)
               if [r for r in recs if r[4] is not None] else None,
               "breadth5_med": round(sorted(r[5] for r in recs if r[5] is not None)[len([r for r in recs if r[5] is not None]) // 2], 1)
               if [r for r in recs if r[5] is not None] else None}
        out["periods"][p] = row
        print("%-8s n=%4d | 14d %-20s | 30d %-20s | 60d %s | vol20中位=%s 广度中位=%s" % (
            p, row["n"], row["fwd14"], row["fwd30"], row["fwd60"], row["vol20_med"], row["breadth5_med"]))
    # 边界时间稳定性：分类结果的切点一致性（各切点下各期 fwd30 avg 的 gap）
    print("\n== 边界时间稳定性（各期 fwd30 的 fit/val gap，全期合计）==")
    for cut in CUTS:
        fit = {p: [r for r in recs if r[0] < cut] for p, recs in periods.items()}
        val = {p: [r for r in recs if r[0] >= cut] for p, recs in periods.items()}
        gaps = []
        for p in periods:
            fa = [r[2] for r in fit[p] if r[2] is not None]
            va = [r[2] for r in val[p] if r[2] is not None]
            if len(fa) >= 5 and len(va) >= 5:
                gaps.append(abs(sum(fa) / len(fa) - sum(va) / len(va)))
        out.setdefault("stability", {})[cut] = round(sum(gaps) / len(gaps), 2) if gaps else None
        print("  %s: 各期 fwd30 fit/val 平均 gap = %s" % (cut, out["stability"][cut]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
