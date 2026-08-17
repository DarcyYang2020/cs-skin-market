# -*- coding: utf-8 -*-
"""生产库 market_index 三年历史回填 + 大盘状态基座实盘延伸（2026-08-16，一次性）。

1) replay_cycle_win.db.market_index（2023-11-17 起 997 行，与生产同口径，重叠段数值一致）
   → 生产 market.db.market_index（date UNIQUE，INSERT OR IGNORE 幂等）；只回填生产最早日期之前的行。
2) data/market_state_daily.json（M1 研究基座，止于 2026-08-05）按 probe_market_base 同口径
   用生产库行情延伸至最新日期（TH=compute_market_trend_health 90 窗，与 backtest_common 同源）。
纯数据动作：不触碰引擎参数；运行后可重复执行（幂等）。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PROD = ROOT / "data" / "market.db"
REPLAY = ROOT / "data" / "replay_cycle_win.db"
STATE = ROOT / "data" / "market_state_daily.json"


def backfill_index():
    src = sqlite3.connect(REPLAY)
    dst = sqlite3.connect(PROD)
    try:
        n0, dmin, dmax = dst.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM market_index").fetchone()
        dst.execute("ATTACH DATABASE ? AS rep", (str(REPLAY),))
        cur = dst.execute(
            "INSERT OR IGNORE INTO market_index (date, value, change_7d, mood) "
            "SELECT date, value, change_7d, mood FROM rep.market_index WHERE date < ?", (dmin,))
        added = cur.rowcount
        dst.commit()
        n1, dmin1, dmax1 = dst.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM market_index").fetchone()
        print("market_index: %d ~ %s ~ %s -> %d %s ~ %s (added %d)" % (
            n0, dmin, dmax, n1, dmin1, dmax1, added))
        return added
    finally:
        try:
            dst.execute("DETACH DATABASE rep")
        except Exception:
            pass
        src.close()
        dst.close()


def extend_state_daily():
    st = json.load(open(STATE, encoding="utf-8"))
    last = max(st)
    c = sqlite3.connect(PROD)
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]
    idx = {d: i for i, d in enumerate(mdates)}

    from pipeline.market_th import compute_market_trend_health

    added = 0
    for d in sorted(idx):
        if d <= last:
            continue
        i = idx[d]
        v = mvals[i]
        if i < 30:
            continue
        chg7 = (v / mvals[i - 7] - 1) * 100 if i >= 7 else None
        chg30 = (v / mvals[i - 30] - 1) * 100
        chg90 = (v / mvals[i - 90] - 1) * 100 if i >= 90 else None
        chg180 = (v / mvals[i - 180] - 1) * 100 if i >= 180 else None
        rets = [(mvals[j] - mvals[j - 1]) / mvals[j - 1] for j in range(i - 19, i + 1) if mvals[j - 1] > 0]
        vol20 = (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets)) ** 0.5 if rets else None
        try:
            th = compute_market_trend_health(mvals[i - 90:i + 1]).corrected_score
        except Exception:
            th = 50.0
        st[d] = {
            "th": th,
            "chg7": round(chg7, 2) if chg7 is not None else None,
            "chg30": round(chg30, 2),
            "chg90": round(chg90, 2) if chg90 is not None else None,
            "chg180": round(chg180, 2) if chg180 is not None else None,
            "vol20": round(vol20, 4) if vol20 is not None else None,
            "dist_hi60": round((v / max(mvals[i - 59:i + 1]) - 1) * 100, 2),
            "dist_lo60": round((v / min(mvals[i - 59:i + 1]) - 1) * 100, 2),
            "dist_hi180": round((v / max(mvals[i - 179:i + 1]) - 1) * 100, 2) if i >= 180 else None,
            "dist_lo180": round((v / min(mvals[i - 179:i + 1]) - 1) * 100, 2) if i >= 180 else None,
        }
        added += 1
    if added:
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("market_state_daily: %s -> +%d 天 (newest=%s)" % (last, added, max(st)))
    return added


if __name__ == "__main__":
    backfill_index()
    extend_state_daily()
    print("done")
