# -*- coding: utf-8 -*-
"""宇宙面板构建器（2026-08-18，预注册）：180 品 × 3 年每个 (item, day) 的特征 + fwd14/fwd30。

只读；输出 columnar JSON data/_exp_universe_panel.json。
特征集（见 current-state-expectancy-design.md 第二节，存原始值，分桶在分析层做）：
  市场：period / period_days / mchg30 / mchg180 / mth / sent
  单品：pct / z / th / cycle / supply30 / chg7 / chg30
  结果：fwd14 / fwd30
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = os.environ.get("CS_MODEL_DB") or str(ROOT / "data" / "replay_cycle_win.db")

sys.path.insert(0, str(ROOT))
import importlib.util

_ARCHIVED_RUNNER = ROOT / "references" / "scripts-archive" / "run_item_backtest.py"
spec = importlib.util.spec_from_file_location("rib_panel", str(_ARCHIVED_RUNNER))
rib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rib)

from pipeline import db  # noqa: E402
import pipeline.item_analysis as ia  # noqa: E402
from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.backtest_common import build_market_context  # noqa: E402

OUT = ROOT / "data" / "_exp_universe_panel.json"

HQ_EXCLUDE_MARKERS = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")

# 周期阶段编码（单品 res.cycle.phase）
_CYCLE_CODE = {"吸筹": 0, "拉升": 1, "出货": 2, "洗盘": 3}
# state_bucket 返回全称中文标签，须用全称键（勿用短码 "P"/"S1" 等）
_PERIOD_CODE = {"P恐慌深跌": 0, "S1牛市上行": 1, "S2牛市回调": 2, "S3弱市阴跌": 3, "S4弱市反弹": 4}

SCHEMA = ["date", "item_id", "period", "period_days", "mchg30", "mchg180", "mth", "sent",
          "pct", "z", "th", "cycle", "supply30", "chg7", "chg30", "fwd14", "fwd30"]


def pool_a_items():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT i.id, i.name, MIN(p.date) first_date
           FROM items i JOIN price_history p ON p.item_id = i.id
           GROUP BY i.id""").fetchall()
    conn.close()
    return {r["id"]: r["name"] for r in rows
            if r["name"] not in rib.EXCLUDED_ITEMS
            and not any(m in r["name"] for m in HQ_EXCLUDE_MARKERS)}


def period_runs(market_ctx):
    """date -> (period_code, period_days)：当前桶连续运行天数（日历天）。"""
    dates = sorted(market_ctx.keys())
    out = {}
    prev_bucket = None
    run = 0
    for d in dates:
        mc = market_ctx[d]
        b = state_bucket(mc.get("chg180"), mc.get("chg30"))
        if b == prev_bucket:
            run += 1
        else:
            run = 1
            prev_bucket = b
        out[d] = (_PERIOD_CODE.get(b, 4), run)
    return out


def build():
    START, END, WARMUP = "2023-11-17", "2026-08-05", 30
    rib.patch_sentiment(50.0)
    market_ctx = build_market_context(START, end=END)
    runs = period_runs(market_ctx)
    items = pool_a_items()
    print("market ctx:", len(market_ctx), "| items:", len(items), flush=True)

    rows = []
    t0 = datetime.now()
    n_days = 0
    for n_i, (iid, iname) in enumerate(sorted(items.items()), 1):
        dates, prices, in_sale, raw_sale = rib.load_item_series(iid)
        n = len(prices)
        if n < WARMUP + 1:
            continue
        bid = rib._load_bid_series().get(iname)
        for i in range(WARMUP, n):
            d = dates[i]
            if d < START or (END and d > END) or d not in market_ctx:
                continue
            mc = market_ctx[d]
            prefix = prices[:i + 1]
            try:
                res = ia.run_item_analysis(
                    name=iname, prices=prefix,
                    supply_hist=in_sale[:i + 1],
                    supply_depth_missing=db.supply_depth_missing(raw_sale[i], d),
                    market_history=None,
                    market_pct_90d=mc["pct"], market_cycle=mc["cycle"],
                    market_zscore=mc["z"], market_th_score=mc["th"],
                    market_30d_change=mc.get("chg30", 0),
                    market_drop21=mc.get("drop21", 0),
                    market_180d_change=mc.get("chg180", 0),
                    bid_history=bid,
                    recent_buy_dates=[], signal_date=d,
                )
            except Exception:
                continue
            pcode, pdays = runs[d]
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 if i + 14 < n else None
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 if i + 30 < n else None
            chg7 = (prices[i] / prices[i - 8] - 1) * 100 if i >= 8 else None
            chg30 = (prices[i] / prices[i - 30] - 1) * 100 if i >= 30 else None
            cyc = _CYCLE_CODE.get(getattr(res.cycle, "phase", "unknown"), 4)
            rows.append([
                d, iid, pcode, pdays,
                round(mc.get("chg30", 0.0), 2), round(mc.get("chg180", 0.0), 2),
                round(mc.get("th", 0.0), 1), round(mc.get("sentiment", 50.0), 1),
                round(getattr(res.position, "percentile_90d", None) or 0.0, 1),
                round(getattr(res.position, "zscore_90d", None) or 0.0, 3),
                round((res.trend_health or {}).get("score") or 0, 0),
                cyc,
                round((res.supply_analysis or {}).get("supply_change_30d") or 0.0, 2),
                round(chg7, 2) if chg7 is not None else None,
                round(chg30, 2) if chg30 is not None else None,
                round(fwd14, 2) if fwd14 is not None else None,
                round(fwd30, 2) if fwd30 is not None else None,
            ])
            n_days += 1
        if n_i % 20 == 0:
            print(f"[{n_i}/{len(items)}] {iname[:24]:26s} rows={len(rows)} "
                  f"elapsed={str(datetime.now()-t0)[:8]}", flush=True)

    out = {"schema": SCHEMA, "period_legend": _PERIOD_CODE,
           "cycle_legend": {"吸筹": 0, "拉升": 1, "出货": 2, "洗盘": 3, "unknown": 4},
           "args": {"start": START, "end": END, "warmup": WARMUP, "items": len(items)},
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "n_rows": len(rows), "rows": rows}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"saved {OUT} | rows={len(rows)} | item-days={n_days}", flush=True)


if __name__ == "__main__":
    build()
