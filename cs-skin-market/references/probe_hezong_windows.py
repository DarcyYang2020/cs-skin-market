# -*- coding: utf-8 -*-
"""合纵求购覆盖检查 + 五个用户买点窗口的回调/承接画像（第一性原理探索）。"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

# ---- 合纵求购覆盖 ----
c = sqlite3.connect(ROOT / "data" / "market.db")
c.row_factory = sqlite3.Row
r = c.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM bid_history WHERE item_name LIKE '%合纵%'").fetchone()
print("合纵 bid_history 行数/范围:", r[0], r[1], "~", r[2])
rows = c.execute("SELECT date, buy_price_last, buy_num_last FROM bid_history "
                 "WHERE item_name LIKE '%合纵%' AND date BETWEEN '2025-02-01' AND '2025-02-15' ORDER BY date").fetchall()
print("2025-02-01~15 求购样本数:", len(rows))
for x in rows[:8]:
    print("  ", x["date"], "bid=%.2f num=%s" % (x["buy_price_last"], x["buy_num_last"]))
c.close()

# ---- 合纵价格序列（replay DB）+ 用户买点窗口 ----
c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
c.row_factory = sqlite3.Row
iid = c.execute("SELECT id FROM items WHERE name LIKE '%合纵%'").fetchone()["id"]
rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                 "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
c.close()
dates = [r["date"] for r in rows]
prices = [r["price_rmb"] for r in rows]
ins = [r["in_sale_count"] for r in rows]

WINDOWS = [
    ("W1 2025/2/6-3/7", "2025-02-06", "2025-03-07"),
    ("W2 2025/3/22-4/30", "2025-03-22", "2025-04-30"),
    ("W3 2025/5/14-6/15", "2025-05-14", "2025-06-15"),
    ("W4 2025/7/21-9/21", "2025-07-21", "2025-09-21"),
    ("W5 2025/10/25-12/31", "2025-10-25", "2025-12-31"),
    ("F1 2024/2/20-3/15(失败对照)", "2024-02-20", "2024-03-15"),
]
print("\n== 窗口画像（窗口首日入场口径；回调=窗口前 20 日内高点→窗口首日） ==")
# 大盘 TH（引擎口径，replay DB）
from pipeline.backtest_common import build_market_context  # noqa: E402
ctx = build_market_context("2023-11-17", end="2026-08-05")
print("market ctx days:", len(ctx))
bid_rows = {}
cb = sqlite3.connect(ROOT / "data" / "market.db")
cb.row_factory = sqlite3.Row
for r in cb.execute("SELECT date, buy_price_last FROM bid_history WHERE item_name LIKE '%合纵%' ORDER BY date"):
    bid_rows[r["date"]] = r["buy_price_last"]
cb.close()

def bid_near(d, before=True, span=3):
    """窗口首日 d 附近最近求购价（向前 span 天内最后一条）。"""
    import bisect
    ks = sorted(bid_rows)
    i = bisect.bisect_right(ks, d)
    lo = i - span
    if lo < 0:
        lo = 0
    return [(k, bid_rows[k]) for k in ks[lo:i]]
for name, w0, w1 in WINDOWS:
    i0 = next((i for i, d in enumerate(dates) if d >= w0), None)
    if i0 is None:
        print(name, "无数据")
        continue
    # 窗口前 20 日内高点（回调起点）
    lo = max(0, i0 - 20)
    pk_i = max(range(lo, i0), key=lambda j: prices[j])
    dd = (prices[i0] / prices[pk_i] - 1) * 100
    chg7 = (prices[i0] / prices[i0 - 7] - 1) * 100 if i0 >= 7 else None
    chg14 = (prices[i0] / prices[i0 - 14] - 1) * 100 if i0 >= 14 else None
    dd30 = (prices[i0] / max(prices[max(0, i0 - 30):i0 + 1]) - 1) * 100
    pct90 = sum(1 for p in prices[max(0, i0 - 89):i0 + 1] if p <= prices[i0]) / min(90, i0 + 1) * 100
    ok7 = all(x is not None for x in ins[i0 - 6:i0 + 1])
    ok30 = all(x is not None for x in ins[i0 - 29:i0 + 1])
    s7 = sum(ins[i0 - 6:i0 + 1]) / 7 if ok7 else None
    s30 = sum(ins[i0 - 29:i0 + 1]) / 30 if ok30 else None
    s_pk = ins[pk_i] if ins[pk_i] is not None else None
    s_chg = (s7 / s30 - 1) * 100 if (s7 and s30) else None
    sup_pull = ((ins[i0] / s_pk - 1) * 100) if (ins[i0] is not None and s_pk) else None
    fwd = {}
    for h in (14, 30, 60, 90, 180):
        fwd[h] = (prices[i0 + h] / prices[i0] - 1) * 100 if i0 + h < len(prices) else None
    # 求购行为：回调高点日 vs 窗口首日的求购价变化（承接指纹）
    bids = bid_near(dates[pk_i], before=True)
    bid_pk = bids[-1][1] if bids else None
    bids0 = bid_near(dates[i0], before=True)
    bid_now = bids0[-1][1] if bids0 else None
    bid_chg = ((bid_now / bid_pk - 1) * 100) if (bid_pk and bid_now) else None
    mkt = ctx.get(dates[i0], {})
    # 大盘指数 90/180 日趋势（大周期信号候选）
    cm = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    cm.row_factory = sqlite3.Row
    mv = [r["value"] for r in cm.execute("SELECT value FROM market_index ORDER BY date")]
    md = [r["date"] for r in cm.execute("SELECT date FROM market_index ORDER BY date")]
    cm.close()
    mi = next((j for j, dd in enumerate(md) if dd >= dates[i0]), None)
    m90 = (mv[mi] / mv[mi - 90] - 1) * 100 if mi is not None and mi >= 90 else None
    m180 = (mv[mi] / mv[mi - 180] - 1) * 100 if mi is not None and mi >= 180 else None
    print("%s | %s 价%.0f 回调%.1f%% chg7%+.1f dd30%.1f pct90%.0f | 求购: 高点%.0f→入场%.0f (%+.1f%%) | 大盘TH %.0f 指90d%+.0f%% 指180d%+.0f%% | fwd14%+.0f 30%+.0f 60%+.0f 90%+.0f 180%+.0f" % (
        name, dates[i0], prices[i0], dd, chg7, dd30, pct90,
        bid_pk or 0, bid_now or 0, bid_chg or 0, mkt.get("th", -1),
        m90 or 0, m180 or 0,
        fwd[14] or 0, fwd[30] or 0, fwd[60] or 0, fwd[90] or 0, fwd[180] or 0))
