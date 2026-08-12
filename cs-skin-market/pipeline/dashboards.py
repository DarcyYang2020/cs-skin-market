# -*- coding: utf-8 -*-
"""仪表盘数据（P0-3 数据积累进度 / P0-4 组合仓位）——纯展示层，只读 DB + 最近扫描缓存，不触碰信号引擎。"""
import json
from pathlib import Path
from statistics import median


_SCAN_CACHE = Path(__file__).resolve().parent.parent / "data" / "batch_scan_latest.json"
_SIGNAL_EVENTS = Path(__file__).resolve().parent.parent / "data" / "signal_event_counts.json"
_J2_STATUS = Path(__file__).resolve().parent.parent / "data" / "j2_channel_status.json"
_COST_SENS = Path(__file__).resolve().parent.parent / "data" / "cost_sensitivity.json"


def _snapshot_days(conn, table, col):
    """日快照统计：覆盖天数/品数/最新日期（用于数据积累进度卡）。"""
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT date) days, COUNT(DISTINCT {0}) n, MAX(date) latest FROM {1}".format(col, table)
        ).fetchone()
    except Exception:
        return {"days": 0, "n": 0, "latest": None}
    return {"days": row[0] or 0, "n": row[1] or 0, "latest": row[2]}


def _j2_status():
    """J-2 三通道监测（2026-08-10 解除冻结期）：读 data/j2_channel_status.json（j2_channel_monitor.py 生成）。
    返回 {channels, overall, monitor_start, sample_target_days}；文件缺失/损坏返回 None（进度卡隐藏该区块）。
    """
    try:
        return json.loads(_J2_STATUS.read_text(encoding="utf-8"))
    except Exception:
        return None


def _signal_families():
    """信号族样本深度（J-3）：读 data/signal_event_counts.json（去量引擎 v2 回放同源，sync_expectancy_config.py 同步生成）。

    返回 {display_keys, families, total_signals, generated, source}；文件缺失/损坏返回 None（进度卡隐藏该区块）。
    """
    try:
        return json.loads(_SIGNAL_EVENTS.read_text(encoding="utf-8"))
    except Exception:
        return None


def _dedup_monitor():
    """????????????? ??2026-08-12??? data/cost_sensitivity.json ? 2% ??????
    ?? {cost_pct, f14_all, f14_dedup, f30_all}?????/???? None??????????"""
    try:
        d = json.loads(_COST_SENS.read_text(encoding="utf-8"))
        for r in d.get("rows", []):
            if abs(float(r.get("cost_pct", 0)) - 2.0) < 1e-9:
                return {
                    "cost_pct": r["cost_pct"],
                    "f14_all": r.get("14d_all"),
                    "f14_dedup": r.get("14d_dedup"),
                    "f30_all": r.get("30d_all"),
                }
    except Exception:
        return None
    return None


def data_progress(conn):
    """数据积累进度：大盘指数 / 单品价格 K 线 / 在售量 in_sale_count 覆盖度。"""
    def _scalar(sql, args=()):
        row = conn.execute(sql, args).fetchone()
        return row[0] if row else 0

    idx = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM market_index").fetchone()
    ph = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT item_id), MIN(date), MAX(date), "
        "SUM(CASE WHEN in_sale_count IS NOT NULL AND in_sale_count>0 THEN 1 ELSE 0 END) "
        "FROM price_history").fetchone()
    items_total = _scalar("SELECT COUNT(*) FROM items")
    per_item = conn.execute(
        "SELECT COUNT(*) days, "
        "SUM(CASE WHEN in_sale_count IS NOT NULL AND in_sale_count>0 THEN 1 ELSE 0 END) sup "
        "FROM price_history GROUP BY item_id").fetchall()
    days_list = [r["days"] for r in per_item]
    sup_list = [r["sup"] for r in per_item]
    n90 = sum(1 for d in days_list if d >= 90)
    n180 = sum(1 for d in days_list if d >= 180)
    items_sup = sum(1 for v in sup_list if v > 0)
    avg_sup = round(sum(sup_list) / len(sup_list), 1) if sup_list else 0.0
    return {
        "index": {"rows": idx[0] or 0, "start": idx[1], "end": idx[2]},
        "price": {
            "rows": ph[0] or 0, "items": ph[1] or 0,
            "start": ph[2], "end": ph[3],
            "median_days": int(median(days_list)) if days_list else 0,
            "pct_90d": round(100.0 * n90 / items_total, 1) if items_total else 0.0,
            "pct_180d": round(100.0 * n180 / items_total, 1) if items_total else 0.0,
        },
        "supply": {
            "rows": ph[4] or 0,
            "items_with_supply": items_sup,
            "pct_items": round(100.0 * items_sup / items_total, 1) if items_total else 0.0,
            "avg_days_per_item": avg_sup,
            "latest": _scalar("SELECT MAX(date) FROM price_history "
                              "WHERE in_sale_count IS NOT NULL AND in_sale_count>0"),
        },
        # 全市场快照 / 大户集中度 (2026-08-04 开始积累)
        "market_snapshot": _snapshot_days(conn, "market_snapshot", "good_id"),
        "monitor_rank": _snapshot_days(conn, "monitor_rank_snapshot", "item_id"),
        "families": _signal_families(),
        "dedup": _dedup_monitor(),
        "j2": _j2_status(),
    }


def execution_review(conn):
    """执行复盘对照（F-2, 2026-08-08）：真实执行 vs 纸面信号统计，纯展示层只读。

    real 口径：executions 表已结算记录（pnl 由 _settle_expired_executions 按收盘价回填，扣 2% 双边成本）；
    slippage = exec_price / advice_price - 1（advice_price 来自报告建议价）。
    paper 口径：signal_tracking 生产 buy 信号回填（net14/net30，扣 2% 与回放同口径），见 tracking_summary。
    """
    from . import signal_tracking
    rows = conn.execute(
        "SELECT exec_price, advice_price, pnl_14, pnl_30 FROM executions").fetchall()

    def _win(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return {"n": 0, "win": None, "avg": None}
        return {"n": len(vals),
                "win": round(100.0 * sum(1 for v in vals if v > 0) / len(vals), 1),
                "avg": round(sum(vals) / len(vals), 2)}

    p14 = [r["pnl_14"] for r in rows]
    p30 = [r["pnl_30"] for r in rows]
    merged = [(r["pnl_14"] if r["pnl_14"] is not None else r["pnl_30"]) for r in rows]
    slips = []
    for r in rows:
        if r["advice_price"] and r["exec_price"] and r["advice_price"] > 0:
            slips.append((r["exec_price"] / r["advice_price"] - 1) * 100)
    real = {
        "n": len(rows),
        "n_settled": sum(1 for v in merged if v is not None),
        "pnl14": _win(p14),
        "pnl30": _win(p30),
        "merged": _win(merged),
        "slippage": {"n": len(slips), "avg": round(sum(slips) / len(slips), 2) if slips else None},
    }
    return {"real": real, "paper": signal_tracking.tracking_summary(conn)}


def portfolio_dashboard(conn):
    """组合仓位仪表：持仓分布（持仓市值/仓位比例/集中度 + 最近扫描时间）。"""
    assets = 0.0
    row = conn.execute("SELECT value FROM settings WHERE key='total_assets'").fetchone()
    try:
        assets = float(row["value"]) if row else 0.0
    except (TypeError, ValueError):
        assets = 0.0
    holdings = conn.execute(
        "SELECT id, name, avg_cost, quantity FROM items WHERE holding=1 AND quantity>0 AND avg_cost>0").fetchall()
    vals = []
    for h in holdings:
        px = conn.execute("SELECT price_rmb FROM price_history WHERE item_id=? ORDER BY date DESC LIMIT 1",
                          (h["id"],)).fetchone()
        price = px["price_rmb"] if px and px["price_rmb"] else (h["avg_cost"] or 0)
        vals.append({"id": h["id"], "name": h["name"], "qty": h["quantity"], "avg_cost": h["avg_cost"],
                     "price": round(float(price), 2), "value": round(float(price) * h["quantity"], 2)})
    vals.sort(key=lambda v: v["value"], reverse=True)
    holding_value = sum(v["value"] for v in vals)
    ratio = round(100.0 * holding_value / assets, 1) if assets > 0 else 0.0
    scan = {"time": None}
    if _SCAN_CACHE.exists():
        try:
            d = json.loads(_SCAN_CACHE.read_text(encoding="utf-8"))
            scan["time"] = d.get("time")
        except Exception:
            pass
    max_single = round(100.0 * vals[0]["value"] / holding_value, 1) if vals and holding_value > 0 else 0.0
    top3 = round(100.0 * sum(v["value"] for v in vals[:3]) / holding_value, 1) if holding_value > 0 else 0.0
    return {
        "total_assets": round(assets, 2), "holding_value": round(holding_value, 2),
        "position_ratio": ratio, "cash_ratio": round(max(0.0, 100.0 - ratio), 1),
        "holdings": vals, "max_single": max_single, "top3": top3, "scan": scan,
    }