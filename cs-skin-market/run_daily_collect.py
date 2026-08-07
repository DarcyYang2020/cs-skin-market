# -*- coding: utf-8 -*-
"""每日自动采集脚本（挂 Windows 计划任务）。

- 大盘指数：csQAQ 当日指数落库（复用 collector）
- 贪婪历史：market_macro 写穿透（~60 天全量 upsert）
- 每日全量刷新 90 日 K 线（P3 2026-08-07 去量：全品价格 + 在售量 in_sale_count 日更，补齐非自选品停更缺口）

用法: python run_daily_collect.py
"""
import sys, io, os, asyncio, json
from datetime import datetime, timezone, timedelta

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TZ_BJ = timezone(timedelta(hours=8))
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "daily_collect.log")


def log(msg: str):
    line = f"[{datetime.now(TZ_BJ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def collect_bind_ip() -> bool:
    """重绑 csQAQ IP 白名单（直连 API 依赖；动态运营商 IP 可能变化，每天重绑一次）。"""
    from pipeline import collector
    try:
        info = collector.bind_local_ip()
        if info:
            log(f"csQAQ IP 绑定: {info}")
            return True
        log("csQAQ IP 绑定失败（后续直连接口可能 401）")
        return False
    except Exception as e:
        log(f"csQAQ IP 绑定异常: {e}")
        return False


def collect_market_index() -> bool:
    from pipeline import collector, db
    try:
        idx = collector.fetch_market_index()
    except Exception as e:
        log(f"大盘指数获取异常: {e}")
        return False
    if idx is None or idx.value <= 0:
        log("大盘指数为空")
        return False
    today = datetime.now(TZ_BJ).strftime("%Y-%m-%d")
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT id FROM market_index WHERE date=?", (today,)).fetchone()
        if row:
            conn.execute("UPDATE market_index SET value=?, change_7d=?, mood=? WHERE date=?",
                         (idx.value, idx.change_7d, idx.mood, today))
        else:
            conn.execute("INSERT INTO market_index (date, value, change_7d, mood) VALUES (?,?,?,?)",
                         (today, idx.value, idx.change_7d, idx.mood))
        conn.commit()
    finally:
        conn.close()
    log(f"大盘指数: {idx.value} ({idx.change_7d:+.1f}%) mood={idx.mood}")
    return True


def collect_macro() -> bool:
    try:
        from pipeline.market_macro import _fetch_macro
        d = _fetch_macro()
        n_greedy = len(d.get("greedy") or [])
        n_card = len(d.get("card_price") or [])
        log(f"贪婪历史: greedy {n_greedy} 点 / card {n_card} 点（写穿透落库）")
        return n_greedy > 0
    except Exception as e:
        log(f"贪婪历史异常: {e}")
        return False


async def collect_kline_all() -> int:
    from pipeline import collector_csqaq, db
    conn = db.get_conn()
    rows = conn.execute("SELECT id, good_id, name FROM items WHERE good_id > 0 AND (notes IS NULL OR notes NOT LIKE '%存世量过低%') ORDER BY id").fetchall()
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
        await asyncio.sleep(1.5)
        conn = db.get_conn()
        try:
            db.save_price_history_batch(conn, r["id"], bars)
            conn.commit()
        finally:
            conn.close()
        ok += 1
    log(f"K线全量刷新: {ok}/{len(rows)}")
    return ok


async def collect_market_snapshot(max_pages: int = 25) -> int:
    """全市场快照采集（get_page_list 翻页，悠悠锚价+在售数，存 market_snapshot）。"""
    from pipeline import db
    from pipeline.collector_snapshot import fetch_market_snapshot
    try:
        rows = await fetch_market_snapshot(max_pages=max_pages)
    except Exception as e:
        log(f"全市场快照异常: {e}")
        return 0
    if not rows:
        log("全市场快照为空")
        return 0
    today = datetime.now(TZ_BJ).strftime("%Y-%m-%d")
    conn = db.get_conn()
    try:
        db.save_market_snapshot(conn, today, rows)
    finally:
        conn.close()
    log(f"全市场快照: {len(rows)} 品 ({today})")
    return len(rows)


async def collect_monitor_rank(top_n: int = 50) -> int:
    """大户集中度快照采集(monitor/rank, 每品顶头大户 Top N, 存 monitor_rank_snapshot)。"""
    from pipeline import db
    from pipeline.collector_monitor import fetch_monitor_rank
    conn = db.get_conn()
    try:
        items = conn.execute("SELECT id, good_id, name FROM items WHERE good_id > 0 AND (notes IS NULL OR notes NOT LIKE '%存世量过低%') ORDER BY id").fetchall()
    finally:
        conn.close()
    if not items:
        log("大户集中度快照: 无可采集品")
        return 0
    today = datetime.now(TZ_BJ).strftime("%Y-%m-%d")
    total = 0
    ok = 0
    for r in items:
        try:
            rows = await fetch_monitor_rank(r["good_id"], top_n=top_n)
        except Exception as e:
            log(f"  [{r['id']}] 大户排行异常: {e}")
            continue
        if not rows:
            continue
        conn = db.get_conn()
        try:
            db.save_monitor_rank_snapshot(conn, today, r["id"], r["good_id"], rows)
        finally:
            conn.close()
        total += len(rows)
        ok += 1
        if ok % 20 == 0:
            log(f"  大户快照进度 {ok}/{len(items)}")
    log(f"大户集中度快照: {ok}/{len(items)} 品, 累计 {total} 行 ({today})")
    return total

def main():
    import argparse
    ap = argparse.ArgumentParser(description="每日自动采集")
    ap.add_argument("--kline", action="store_true", help="兼容保留：每日已自动全量刷新 K 线")
    args = ap.parse_args()
    log("=== 每日采集开始 ===")
    collect_bind_ip()
    collect_market_index()
    collect_macro()
    # 浏览器任务合并到同一个 event loop（Playwright 实例绑定 loop，多次 asyncio.run 会导致后续任务拿到已失效浏览器）
    async def _playwright_tasks():
        try:
            await collect_market_snapshot(max_pages=25)
        except Exception as e:
            log(f"全市场快照任务异常: {e}")
        try:
            await collect_monitor_rank(top_n=50)
        except Exception as e:
            log(f"大户集中度快照任务异常: {e}")
        # P3 (2026-08-07 去量)：每日全量刷新 90 日 K 线（全品价格+在售量日更，补齐非自选品停更缺口）
        try:
            await collect_kline_all()
        except Exception as e:
            log(f"K线任务异常: {e}")
    try:
        asyncio.run(_playwright_tasks())
    except Exception as e:
        log(f"浏览器采集任务异常: {e}")
    # ---- 数据源健康监控 (A1, 2026-08-05) ----
    # 采集收尾自动体检：复用 run_health_monitor（写 health_checks 表，退出码 0/2）。
    # 失败仅记录，不中断采集主流程。
    # 定时接入说明：本项目由 Windows 计划任务每日调用本脚本，健康检查随收尾自动执行；
    # 如需独立告警调度，可另建计划任务运行 `python run_health_monitor.py`（退出码 0/2 供告警系统判定）。
    try:
        from run_health_monitor import run_monitor
        res = run_monitor()
        log(f"数据健康: status={res['status']} FAIL={res['fail_count']}（已写入 health_checks）")
    except Exception as e:
        log(f"数据健康检查异常（不中断采集）: {e}")
    # J-2 三通道监测刷新 (2026-08-07): 重跑 j2_channel_monitor.py 更新 data/j2_channel_status.json（B 通道天数每日变化）
    try:
        import subprocess, sys as _sys
        _r = subprocess.run([_sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "references", "j2_channel_monitor.py")],
                            capture_output=True, text=True, timeout=60)
        log(f"J-2 三通道监测刷新: exit={_r.returncode} {(_r.stdout or '').strip()}")
    except Exception as e:
        log(f"J-2 三通道监测刷新异常（不中断采集）: {e}")
    # 生产实盘信号跟踪回填 (2026-08-07 C 通道实盘化): 14/30 交易日后按真实价格回填 buy 信号收益
    try:
        from pipeline.signal_tracking import run_backfill_once
        _sig = run_backfill_once()
        _s = _sig["summary"]
        log(f"信号跟踪回填: 更新 {_sig['updated']} 条, 累计 {_s['n_total']} 信号 / 已回填14d {_s['n_filled14']} / 30d {_s['n_filled30']}")
    except Exception as e:
        log(f"信号跟踪回填异常（不中断采集）: {e}")
    log("=== 每日采集完成 ===")


if __name__ == "__main__":
    main()
