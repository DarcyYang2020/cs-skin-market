# -*- coding: utf-8 -*-
"""EXEC-2 自动盯盘链（2026-08-27，decision-log HC，PM 立项交④研发执行）。

链路缺口：18:00 采集后→21:30 之间（及日间）无自动信号重算 → 新 buy 无法及时推送。
本脚本 = 自动重算活跃池/自选+持仓融合决策，新 buy 走 S3 意向单钉钉推送（已闭环：CS 前缀+加签）。

双轨（方案 A + B，均本脚本，--scope 区分）：
  - 方案 A（兜底，18:00 采集收尾挂接）：--scope active —— 活跃池全量重算；
  - 方案 B（覆盖空窗，独立 2h 定时任务）：--scope watchlist —— 自选+持仓增量刷新。
复用：scan_tasks._scan_item（增量，KLINE_FRESH_BATCH 复用窗口）+ paper_trading.create_intention/push_intention（S3）；
红线：不碰引擎参数、不 bump ENGINE_VERSION；推送幂等对齐 M2（settings key，同品同日不重复推）。

用法: python exec2_auto_watch.py [--scope active|watchlist] [--dry-run]
stdout 末行 = RESULT ...（④侧取末行记 log）；退出码 0=成功 / 非 0=失败。
"""
import argparse
import asyncio
import io
import json
import os
import sys
from datetime import datetime

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from pipeline.config import TZ_BJ  # noqa: E402
from pipeline import db  # noqa: E402

# 幂等 key 前缀（对齐 M2 monitor_push_{date}_{slot}）：exec2_push_{date}_{item_id}
_PUSH_KEY_PREFIX = "exec2_push"


def _today():
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")


def _log(msg):
    print(f"[{datetime.now(TZ_BJ).strftime('%H:%M:%S')}] {msg}", flush=True)


def scope_rows(scope):
    """取扫描范围（验收③：仅自选+持仓+活跃池，不扩全池）。"""
    conn = db.get_conn()
    try:
        if scope == "watchlist":
            # 方案 B：自选 + 持仓（in_watchlist=1 OR holding=1）
            rows = conn.execute(
                "SELECT id, name, holding, avg_cost, quantity, in_watchlist FROM items "
                "WHERE (in_watchlist=1 OR holding=1) AND good_id>0 ORDER BY id").fetchall()
        else:  # active（方案 A，与活跃池口径一致：notes 无剔除标记）
            rows = conn.execute(
                "SELECT id, name, holding, avg_cost, quantity, in_watchlist FROM items "
                "WHERE good_id>0 AND (in_watchlist=1 OR holding=1 OR notes IS NULL "
                "OR (notes NOT LIKE '%存世量过低%' AND notes NOT LIKE '%活跃池淘汰%' "
                "AND notes NOT LIKE '%贴纸模块停采%')) ORDER BY id").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def already_pushed(item_id, date):
    """幂等检查（对齐 M2）：同品同日已推送 → 跳过。"""
    conn = db.get_conn()
    try:
        v = db.get_setting(conn, f"{_PUSH_KEY_PREFIX}_{date}_{item_id}", None)
    finally:
        conn.close()
    return bool(v)


def mark_pushed(item_id, date, meta):
    """推送成功留痕（幂等 key，对齐 M2 JSON 值模式）。"""
    conn = db.get_conn()
    try:
        db.set_setting(conn, f"{_PUSH_KEY_PREFIX}_{date}_{item_id}", json.dumps(meta, ensure_ascii=False))
        conn.commit()
    finally:
        conn.close()


async def _scan_one(row, idx, ms, market_th_score, sentiment_score, total_assets):
    from pipeline.scan_tasks import _scan_item
    try:
        res = await _scan_item(row, idx, ms, market_th_score, sentiment_score,
                               total_assets=total_assets, force_refresh=False)
        return res
    except Exception as exc:
        _log(f"  scan FAIL {row['name'][:30]}: {type(exc).__name__}: {str(exc)[:80]}")
        return None


def _family_of(action_label):
    try:
        from pipeline.config import assign_fine_family
        return assign_fine_family(action_label or "")
    except Exception:
        return "base"


def push_buy_signal(res, date, dry_run=False, conn=None):
    """新 buy → S3 意向单推送（create_intention + push_intention，复用闭环链路）。返回推送结果或 None。

    conn 可注入（测试/多环境用临时库）；缺省用生产库。幂等 key 走生产 settings（M2 同款）。
    """
    fd = (res.get("fusion_decision") or {})
    if fd.get("action") not in ("buy", "oversold_buy"):
        return None
    item_id = res.get("id")
    if not item_id or already_pushed(item_id, date):
        return {"skipped": "already_pushed"}
    own = conn is None
    if own:
        conn = db.get_conn()
    try:
        from pipeline import paper_trading as pt
        oid = pt.create_intention(
            conn, item_id=item_id, item_name=res["name"],
            family=_family_of(fd.get("action_label") or ""),
            direction="buy", qty=1,
            ref_price=res.get("price_rmb") or 0,
            reason="EXEC-2 自动盯盘: " + (fd.get("action_label") or "buy"),
            expectancy=None,
            risk_tag=f"limit={fd.get('position_limit') or 0.10}")
        r = pt.push_intention(conn, oid, dry_run=dry_run)
        if not dry_run and r.get("pushed"):
            mark_pushed(item_id, date, {"ts": datetime.now(TZ_BJ).isoformat(timespec="minutes"),
                                        "order_id": oid, "label": fd.get("action_label") or ""})
        return r
    finally:
        if own:
            conn.close()


async def main_async(args):
    from pipeline.scan_tasks import _scan_progress, _persist_scan_progress  # noqa: F401（确保模块加载）
    from pipeline.collector import fetch_market_index
    from webapp.analysis_service import market_snapshot

    rows = scope_rows(args.scope)
    date = _today()
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    _log(f"EXEC-2 {mode} scope={args.scope} items={len(rows)} date={date}")

    idx = await asyncio.to_thread(fetch_market_index)
    if idx is None or idx.value == 0:
        idx = type("obj", (object,), {"value": 0, "change_7d": 0})()
    ms = market_snapshot()
    market_th_score = ms["th"]
    sentiment_score = ms["sentiment"]
    conn_r = db.get_conn()
    try:
        total_assets = float(db.get_setting(conn_r, "total_assets", 0) or 0)
    finally:
        conn_r.close()

    pushed, skipped, no_signal, errors = 0, 0, 0, 0
    for row in rows:
        res = await _scan_one(row, idx, ms, market_th_score, sentiment_score, total_assets)
        if res is None or res.get("error"):
            errors += 1
            continue
        r = push_buy_signal(res, date, dry_run=args.dry_run)
        if r is None:
            no_signal += 1
        elif r.get("skipped"):
            skipped += 1
        else:
            pushed += 1
            _log(f"  push buy {res['name'][:30]} limit={res.get('position_limit')}")

    _log(f"EXEC-2 done scope={args.scope} items={len(rows)} pushed={pushed} skipped={skipped} no_signal={no_signal} errors={errors}")
    print(f"RESULT mode={mode} scope={args.scope} items={len(rows)} pushed={pushed} skipped={skipped} no_signal={no_signal} errors={errors}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="EXEC-2 自动盯盘链（活跃池/自选+持仓融合决策重算 + 新 buy S3 推送）")
    ap.add_argument("--scope", default="active", choices=["active", "watchlist"],
                    help="active=活跃池（方案 A，18:00 收尾）/ watchlist=自选+持仓（方案 B，2h 定时）")
    ap.add_argument("--dry-run", action="store_true", help="仅扫描不推送")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR exec2_auto_watch: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
