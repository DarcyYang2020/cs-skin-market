# -*- coding: utf-8 -*-
"""H4 急跌型恐慌探针（2026-08-20）：全历史识别两类恐慌事件，统计其后大盘反弹。

预注册判据（family-repartition-prereg-2026-08-20.md H4）：
  深跌型恐慌 = 大盘 chg21 <= -18（panic_resonance 的 drop21 门槛）
  急跌型恐慌 = 大盘 chg7 <= -10 且 chg21 > -18（2025-05-14/07-21 漏掉的那类）
  统计两类事件日其后 14d/30d 大盘反弹胜率+均值，对照判断急跌型是否正期望。
红线：只做事件级探针，不直接放宽 drop21 阈值。
"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "replay_cycle_win.db"
OUT = ROOT / "data" / "_exp_h4_panic_event_probe_2026-08-20.json"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
conn.close()
dates = [r["date"] for r in rows]
vals = [r["value"] for r in rows]
idx = {d: i for i, d in enumerate(dates)}


def chg(day, n):
    i = idx.get(day)
    if i is None or i - n < 0:
        return None
    return (vals[i] / vals[i - n] - 1) * 100


def fwd(day, n):
    i = idx.get(day)
    if i is None or i + n >= len(dates):
        return None
    return (vals[i + n] / vals[i] - 1) * 100


deep, sharp = [], []
for d in dates:
    c7 = chg(d, 7)
    c21 = chg(d, 21)
    if c21 is None:
        continue
    if c21 <= -18:
        deep.append(d)
    elif c7 is not None and c7 <= -10:
        sharp.append(d)


def stats(event_days, n):
    xs = [fwd(d, n) for d in event_days if fwd(d, n) is not None]
    if not xs:
        return {"n_days": len(event_days), "n_valid": 0}
    return {"n_days": len(event_days), "n_valid": len(xs),
            "win": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1),
            "avg": round(sum(xs) / len(xs), 2),
            "median": round(sorted(xs)[len(xs) // 2], 2)}


out = {
    "meta": {"date": "2026-08-20", "db": str(DB),
             "deep_trigger": "chg21<=-18", "sharp_trigger": "chg7<=-10 且 chg21>-18"},
    "deep_days": sorted(set(deep)),
    "sharp_days": sorted(set(sharp)),
    "deep": {"fwd14": stats(deep, 14), "fwd30": stats(deep, 30)},
    "sharp": {"fwd14": stats(sharp, 14), "fwd30": stats(sharp, 30)},
}
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved", OUT)
print(json.dumps(out, ensure_ascii=False, indent=1))
