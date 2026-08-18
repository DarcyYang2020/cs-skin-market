# -*- coding: utf-8 -*-
"""午间监控入口（Windows 计划任务 CS_Skin_NoonMonitor，每日 12:00）。

流程：重绑 csQAQ IP → 刷新大盘指数 → 自选/持仓品 K 线刷新（轻量，仅自选品，
不跑全市场快照/大户集中度）→ 监控分析 + 钉钉推送（slot=noon）。

晚间推送由独立入口 run_night_push.py 执行（slot=night）。
用法: python run_daily_monitor.py [--noon] [--skip-kline]
"""
import sys, io, os, asyncio
from datetime import datetime

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.config import TZ_BJ
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "noon_monitor.log")


def log(msg: str):
    line = f"[{datetime.now(TZ_BJ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


async def refresh_watchlist_kline() -> int:
    """自选/持仓品 90 日 K 线刷新（轻量；监控分析的数据输入，仅当日新增/更新 bar）。"""
    from pipeline import collector_csqaq, db
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT id, good_id, name FROM items WHERE good_id > 0 AND (in_watchlist=1 OR holding=1) "
            "AND (notes IS NULL OR notes NOT LIKE '%存世量过低%') ORDER BY id").fetchall()
    finally:
        conn.close()
    ok = 0
    for r in rows:
        try:
            bars, _raw = await collector_csqaq.fetch_kline_90d(r["good_id"])
        except Exception as e:
            log(f"  [{r['id']}] K线异常: {e}")
            continue
        if not bars:
            log(f"  [{r['id']}] K线空: {r['name'][:30]}")
            await asyncio.sleep(2)
            continue
        await asyncio.sleep(1.0)
        conn = db.get_conn()
        try:
            db.save_price_history_batch(conn, r["id"], bars)
            conn.commit()
        finally:
            conn.close()
        ok += 1
    return ok


def main():
    import argparse
    ap = argparse.ArgumentParser(description="午间监控推送（每日 12:00 计划任务）")
    ap.add_argument("--noon", action="store_true", help="午间模式（默认）：大盘+自选品K线刷新后推送")
    ap.add_argument("--skip-kline", action="store_true", help="跳过自选品 K 线刷新（仅推送）")
    args = ap.parse_args()
    log("=== 午间监控开始 ===")
    import run_daily_collect as rdc
    try:
        rdc.collect_bind_ip()
    except Exception as e:
        log(f"IP 绑定异常（继续）: {e}")
    try:
        rdc.collect_market_index()
    except Exception as e:
        log(f"大盘指数刷新异常（继续）: {e}")
    if not args.skip_kline:
        try:
            n = asyncio.run(refresh_watchlist_kline())
            log(f"自选品K线刷新: {n} 品")
        except Exception as e:
            log(f"自选品K线异常: {e}")
    try:
        from pipeline.monitor import run_daily_monitor
        _mon = run_daily_monitor(slot="noon")
        log(f"监控事件: 生成 {_mon['generated']} / 新增 {_mon['saved']} 条 "
            f"(大盘 {_mon['bucket']}, 分析 {_mon['analyzed']} 品)")
    except Exception as e:
        log(f"监控事件生成异常: {e}")
    log("=== 午间监控完成 ===")


if __name__ == "__main__":
    main()