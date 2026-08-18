# -*- coding: utf-8 -*-
"""扩展宇宙面板 v2（2026-08-18，预注册）：补领先特征，复用 v1 面板的引擎特征。

只读。输出 data/_exp_universe_panel_v2.json。

背景：v1（build_universe_panel.py 产物）只有 fwd14/fwd30 + chg7/chg30，且 period/period_days
列有 chg180 哨兵日退化 bug（消费时须重算）。本脚本不重跑 run_item_analysis（31 分钟），
只 load price/bid 系列重算领先特征，引擎特征（pct/z/th/cycle/supply30）复用 v1 按 (item_id,date) 索引。

领先特征口径（与引擎同源）：
  fwd7        = (prices[i+7]/prices[i]-1)*100 - 2（扣 2% 双边，与 fwd14/fwd30 同口径）
  chg3        = (prices[i]/prices[i-3]-1)*100           （3 日动量，trend_health chg3d 同分母）
  no_new_low2 = min(prices[i-1:i+1]) > min(prices[i-2:i+1])   （最后2日低点>最后3日低点，trend_health 同源）
  decay3      = chg3 - (prices[i-3]/prices[i-6]-1)*100  （3 日动量变化，正=跌速衰减/转涨加速）
  spread_chg5 = spread_now - spread_5d                  （5 日价差变化，probe_supply_conf_4state 同源）
  rs30        = chg30(单品) - mchg30(大盘)               （相对强度，item_analysis rs_accum 同源）
  volreg      = analyze_probability(prices[:i+1]).volatility_regime 编码
"""
import os
import sys
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = os.environ.get("CS_MODEL_DB") or str(ROOT / "data" / "replay_cycle_win.db")

sys.path.insert(0, str(ROOT))
import importlib.util

_ARCHIVED_RUNNER = ROOT / "references" / "scripts-archive" / "run_item_backtest.py"
spec = importlib.util.spec_from_file_location("rib_panel_v2", str(_ARCHIVED_RUNNER))
rib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rib)

import pipeline.item_analysis as ia  # noqa: E402

V1 = ROOT / "data" / "_exp_universe_panel.json"
OUT = ROOT / "data" / "_exp_universe_panel_v2.json"

_VOLREG_CODE = {"stable": 0, "normal": 1, "volatile": 2, "high_volatile": 3}

SCHEMA = ["date", "item_id", "mchg30", "mchg180", "mth", "sent",
          "pct", "z", "th", "cycle", "supply30", "chg7", "chg30", "rs30",
          "chg3", "no_new_low2", "decay3", "spread_chg5", "volreg",
          "fwd7", "fwd14", "fwd30"]


def _buy_at(bdates, bprices, target):
    best = None
    for d, p in zip(bdates, bprices):
        if d <= target:
            best = p
        else:
            break
    return best


def build():
    # ---- 1. 加载 v1 面板，建 (item_id, date) -> 引擎特征 索引 ----
    v1 = json.load(open(V1, encoding="utf-8"))
    v1_rows = v1["rows"]
    # v1 schema: [date, item_id, period, period_days, mchg30, mchg180, mth, sent,
    #             pct, z, th, cycle, supply30, chg7, chg30, fwd14, fwd30]
    idx = {}
    for r in v1_rows:
        idx[(r[1], r[0])] = r  # (item_id, date) -> row
    items_in_v1 = sorted({r[1] for r in v1_rows})

    # ---- 2. 名称映射（bid 按 name）+ bid 系列 ----
    names = rib.load_items()
    bid_series = rib._load_bid_series()

    # ---- 3. 按 item 遍历，load prices/bid，算领先特征 ----
    out_rows = []
    for iid in items_in_v1:
        name = names.get(iid)
        dates, prices, in_sale, raw_sale = rib.load_item_series(iid)
        n = len(prices)
        if n < 7:
            continue
        date_pos = {d: k for k, d in enumerate(dates)}
        bid = bid_series.get(name) if name else None
        bid_dates = [b[0] for b in bid] if bid else []
        bid_prices = [b[1] for b in bid] if bid else []

        # 该 item 在 v1 里的所有行（按 date 排序）
        item_v1 = [idx[(iid, d)] for d in dates if (iid, d) in idx]
        item_v1_by_date = {r[0]: r for r in item_v1}

        for k in range(0, n):
            d = dates[k]
            r1 = item_v1_by_date.get(d)
            if r1 is None:
                continue
            # 前视（扣 2% 双边）
            fwd7 = round((prices[k + 7] / prices[k] - 1) * 100 - 2.0, 2) if k + 7 < n else None
            # 反转
            chg3 = round((prices[k] / prices[k - 3] - 1) * 100, 2) if k >= 3 else None
            nnl = None
            if k >= 2:
                low2 = min(prices[k - 1], prices[k])
                low3 = min(prices[k - 2], prices[k - 1], prices[k])
                nnl = 1.0 if low2 > low3 else 0.0
            decay3 = None
            if k >= 6 and prices[k - 6] > 0:
                chg3_prev = (prices[k - 3] / prices[k - 6] - 1) * 100
                decay3 = round((chg3 - chg3_prev) if chg3 is not None else None, 2) if chg3 is not None else None
            # 求购价差（5 日价差变化）
            spread_chg5 = None
            if bid and k >= 5 and prices[k] > 0 and prices[k - 5] > 0:
                buy_now = _buy_at(bid_dates, bid_prices, d)
                buy_5d = _buy_at(bid_dates, bid_prices, dates[k - 5])
                if buy_now is not None and buy_5d is not None:
                    s_now = (prices[k] - buy_now) / prices[k] * 100
                    s_5d = (prices[k - 5] - buy_5d) / prices[k - 5] * 100
                    spread_chg5 = round(s_now - s_5d, 2)
            # 相对强度 + 波动率 regime
            rs30 = None
            chg30_v1 = r1[14]
            mchg30_v1 = r1[4]
            if chg30_v1 is not None and mchg30_v1 is not None:
                rs30 = round(chg30_v1 - mchg30_v1, 2)
            volreg = None
            if k >= 14:
                try:
                    volreg = _VOLREG_CODE.get(
                        ia.analyze_probability(prices[:k + 1]).volatility_regime, 3)
                except Exception:
                    volreg = None

            out_rows.append([
                d, iid,
                r1[4], r1[5], r1[6], r1[7],       # mchg30/mchg180/mth/sent
                r1[8], r1[9], r1[10], r1[11], r1[12],  # pct/z/th/cycle/supply30
                r1[13], r1[14], rs30,              # chg7/chg30/rs30
                chg3, nnl, decay3, spread_chg5, volreg,
                fwd7, r1[15], r1[16],              # fwd7/fwd14/fwd30
            ])

    out = {"schema": SCHEMA,
           "volreg_legend": _VOLREG_CODE,
           "source_v1": str(V1),
           "generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
           "n_rows": len(out_rows), "rows": out_rows}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"saved {OUT} | rows={len(out_rows)}", flush=True)


if __name__ == "__main__":
    build()
