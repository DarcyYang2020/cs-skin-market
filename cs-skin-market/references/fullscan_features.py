# -*- coding: utf-8 -*-
"""引擎独立全量扫描 · 特征构建器（2026-08-20，②算法研究专家）

只读 data/replay_cycle_win.db，对最终研究池（240 品 − 贴纸/角色 − 2 污染 = 232 品）
3 年所有 item-day 计算 9 个单品特征 + 3 个大盘特征 + fwd14/fwd30 净收益，落盘 columnar JSON。
不经旧引擎信号发射（引擎独立）。产物 = data/_exp_fullscan_features_2026-08-20.json。

特征（预注册 §二）：
  pct=90d 价格分位(0-100)  z=90d z-score
  chg7/30/90=价格 7/30/90 日涨跌%  sc7/30=在售量 7/30 日变化%
  vol7/30=日收益 7/30 日年化波动%
  mchg7/21/30=大盘指数 7/21/30 日涨跌%
前向（§三）：fwd14/fwd30 = 扣 2% 双边成本后净收益%。
注：regime（五时期路由）本版未纳入——market_index.mood 稀疏无用、宏观情绪仅 2026-02 起，
    大盘语境由 mchg7/21/30 承载；regime 留作后续细化。
"""
import json
import math
import sqlite3

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

DB = "data/replay_cycle_win.db"
OUT = "data/_exp_fullscan_features_2026-08-20.json"
POLLUTED = {"AK-47 | 流金王朝 (崭新出厂)", "挂件 | 丁烷拍档"}
EXCLUDE = ("印花", "贴纸", "游击队", "军刀勇士", "特警", "指挥官", "亚诺")
COST = 2.0
WARMUP = 90
FEATURES = ["pct", "z", "chg7", "chg30", "chg90", "sc7", "sc30", "vol7", "vol30"]


def _f(x):
    if x is None:
        return None
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return round(float(x), 4)


def compute_item(prices, in_sales):
    n = len(prices)
    p = np.asarray(prices, dtype=float)
    s = np.asarray([0.0 if x is None else float(x) for x in in_sales], dtype=float)
    feat = {f: np.full(n, np.nan) for f in FEATURES}
    if n < WARMUP + 1:
        return feat, False
    # pct / z：90d 滚动
    win = sliding_window_view(p, WARMUP)          # (n-89, 90)
    cur = p[WARMUP - 1:]
    feat["pct"][WARMUP - 1:] = (win < cur[:, None]).mean(axis=1) * 100.0
    mu = win.mean(axis=1)
    sd = win.std(axis=1)
    feat["z"][WARMUP - 1:] = np.where(sd > 1e-9, (cur - mu) / sd, 0.0)
    # 涨跌幅
    for k, key in [(7, "chg7"), (30, "chg30"), (90, "chg90")]:
        feat[key][k:] = (p[k:] / p[:-k] - 1.0) * 100.0
    # 在售量变化率
    for k, key in [(7, "sc7"), (30, "sc30")]:
        denom = s[:-k]
        num = s[k:]
        with np.errstate(divide="ignore", invalid="ignore"):
            c = np.where(denom > 0, (num / np.where(denom > 0, denom, np.nan) - 1.0) * 100.0, np.nan)
        feat[key][k:] = c
    # 波动率：日收益 std 年化
    ret = np.full(n, np.nan)
    ret[1:] = p[1:] / p[:-1] - 1.0
    for k, key in [(7, "vol7"), (30, "vol30")]:
        rw = sliding_window_view(ret, k)
        # ret[0]=nan；vol_k[t]=std(ret[t-k+1..t])，对应 rw[t-k+1]=rw[1:] 起
        feat[key][k:] = rw[1:].std(axis=1) * math.sqrt(252) * 100.0
    return feat, True


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    items = [dict(r) for r in conn.execute("SELECT id, name FROM items ORDER BY id")]
    items = [r for r in items if not any(m in r["name"] for m in EXCLUDE) and r["name"] not in POLLUTED]

    mrows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = np.array([r["value"] for r in mrows], dtype=float)
    mchg = {}
    for i, d in enumerate(mdates):
        def chg(k):
            return None if i - k < 0 else round((mvals[i] / mvals[i - k] - 1.0) * 100.0, 4)
        mchg[d] = (chg(7), chg(21), chg(30))

    cols = {f: [] for f in FEATURES}
    cols.update({"mchg7": [], "mchg21": [], "mchg30": []})
    fwd14_l, fwd30_l = [], []
    item_ids, dates = [], []
    item_name = {}

    for it in items:
        rows = conn.execute(
            "SELECT date, price_rmb, in_sale_count FROM price_history WHERE item_id=? ORDER BY date",
            (it["id"],)).fetchall()
        if len(rows) < WARMUP + 1:
            continue
        prices = [r["price_rmb"] for r in rows]
        in_sales = [r["in_sale_count"] for r in rows]
        feat, ok = compute_item(prices, in_sales)
        if not ok:
            continue
        item_name[it["id"]] = it["name"]
        n = len(rows)
        for t in range(n):
            if t < WARMUP - 1:            # pct/z 需 90d 窗口
                continue
            d = rows[t]["date"]
            f14 = (prices[t + 14] / prices[t] - 1) * 100 - COST if t + 14 < n else None
            f30 = (prices[t + 30] / prices[t] - 1) * 100 - COST if t + 30 < n else None
            item_ids.append(it["id"])
            dates.append(d)
            for f in FEATURES:
                cols[f].append(_f(feat[f][t]))
            m7, m21, m30 = mchg.get(d, (None, None, None))
            cols["mchg7"].append(m7)
            cols["mchg21"].append(m21)
            cols["mchg30"].append(m30)
            fwd14_l.append(_f(f14))
            fwd30_l.append(_f(f30))
    conn.close()

    out = {
        "meta": {
            "date": "2026-08-20", "db": DB, "n_items": len(items), "n_records": len(item_ids),
            "features": FEATURES + ["mchg7", "mchg21", "mchg30"],
            "targets": ["fwd14", "fwd30"], "cost": COST, "warmup": WARMUP,
            "date_range": [min(dates), max(dates)] if dates else None,
            "item_name": item_name,
            "note": "regime 未纳入（mood 稀疏/情绪仅 2026-02 起）；大盘语境由 mchg7/21/30 承载",
        },
        "item_id": item_ids, "date": dates,
        "X": cols, "fwd14": fwd14_l, "fwd30": fwd30_l,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"saved {OUT}")
    print(f"  n_items={len(items)}  n_records={len(item_ids)}  range={out['meta']['date_range']}")


if __name__ == "__main__":
    main()
