# -*- coding: utf-8 -*-
"""仪表盘数据（P0-3 数据积累进度 / P0-4 组合仓位）——纯展示层，只读 DB + 最近扫描缓存，不触碰信号引擎。"""
import json
from pathlib import Path
from statistics import median

from .config import PORTFOLIO_CAP_CONCURRENT

_SCAN_CACHE = Path(__file__).resolve().parent.parent / "data" / "batch_scan_latest.json"
_SIGNAL_EVENTS = Path(__file__).resolve().parent.parent / "data" / "signal_event_counts.json"
_J2_STATUS = Path(__file__).resolve().parent.parent / "data" / "j2_channel_status.json"
_ADD_ACTIONS = ("\u53ef\u5206\u6279\u5efa\u4ed3", "\u53ef\u5206\u6279\u8865\u4ed3")  # 可分批建仓/可分批补仓


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
    """J-2 重拟合三通道（2026-08-07 修订）：读 data/j2_channel_status.json（j2_channel_monitor.py 生成）。
    返回 {channels, overall, frozen_at, oos_revalidate_after}；文件缺失/损坏返回 None（进度卡隐藏该区块）。
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
        "j2": _j2_status(),
    }


def portfolio_dashboard(conn):
    """组合仓位仪表：持仓分布 + 最近扫描的并发建议仓位占用（P2 口径 Σposition_limit vs 0.8 上限）。"""
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
    scan = {"time": None, "demand": 0.0, "cap": PORTFOLIO_CAP_CONCURRENT,
            "utilization": 0.0, "over_cap": False}
    if _SCAN_CACHE.exists():
        try:
            d = json.loads(_SCAN_CACHE.read_text(encoding="utf-8"))
            scan["time"] = d.get("time")
            demand = sum(float(r.get("position_limit") or 0) for r in d.get("results", [])
                         if (r.get("portfolio_advice") or {}).get("action") in _ADD_ACTIONS)
            scan["demand"] = round(demand, 3)
            scan["utilization"] = round(100.0 * demand / PORTFOLIO_CAP_CONCURRENT, 1)
            scan["over_cap"] = demand > PORTFOLIO_CAP_CONCURRENT + 1e-9
        except Exception:
            pass
    max_single = round(100.0 * vals[0]["value"] / holding_value, 1) if vals and holding_value > 0 else 0.0
    top3 = round(100.0 * sum(v["value"] for v in vals[:3]) / holding_value, 1) if holding_value > 0 else 0.0
    return {
        "total_assets": round(assets, 2), "holding_value": round(holding_value, 2),
        "position_ratio": ratio, "cash_ratio": round(max(0.0, 100.0 - ratio), 1),
        "holdings": vals, "max_single": max_single, "top3": top3, "scan": scan,
    }