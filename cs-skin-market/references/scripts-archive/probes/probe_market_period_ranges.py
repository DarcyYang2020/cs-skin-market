# -*- coding: utf-8 -*-
"""大盘五时期连续区间清单（2026-08-16，只读）：
按 probe_market_periods.py 同一分类口径，把 market_state_daily.json 逐日标签
压成连续区间，回答「哪段时间处于哪一个时期」。输出 data/_exp_market_period_ranges.json。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_market_period_ranges.json"


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


def main():
    st = json.load(open(ROOT / "data" / "market_state_daily.json", encoding="utf-8"))
    days = sorted(d for d, s in st.items() if "chg180" in s and "chg30" in s)
    runs = []  # (start, end, n, period)
    for d in days:
        p = classify(st[d])
        if runs and runs[-1][3] == p:
            runs[-1] = (runs[-1][0], d, runs[-1][2] + 1, p)
        else:
            runs.append((d, d, 1, p))

    out = {"probe": "大盘五时期连续区间", "runs": []}
    print("== 连续区间（按时期分组，区间内≥3天才列出）==")
    cur = None
    for (s0, s1, n, p) in runs:
        if n < 3:
            continue
        seg = {"period": p, "start": s0, "end": s1, "days": n}
        out["runs"].append(seg)
        if cur != p:
            print("\n[%s]" % p)
            cur = p
        print("  %s ~ %s  (%d天)" % (s0, s1, n))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
