# -*- coding: utf-8 -*-
"""每日自动采集脚本（挂 Windows 计划任务）。

- 大盘指数：csQAQ 当日指数落库（复用 collector）
- 贪婪历史：market_macro 写穿透（~60 天全量 upsert）
- 每日全量刷新 90 日 K 线（P3 2026-08-07 去量：全品价格 + 在售量 in_sale_count 日更，补齐非自选品停更缺口）
- 全市场快照/大户集中度：每周一采集（2026-08-08 优化：引擎/决策不消费，仅进度卡+健康检查计数；周度保留数据积累，省 ~9 分钟/天 Playwright 负载）

用法: python run_daily_collect.py [--force-weekly]
"""
import sys, io, os, asyncio
from datetime import datetime

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.config import TZ_BJ
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


def is_weekly_collect_day() -> bool:
    """周度任务判断：全市场快照/大户集中度每周一采集（2026-08-08 优化）。

    引擎/决策不消费这两份数据（仅数据进度卡与健康检查计数），每日采集收益低；
    改每周一执行保留数据积累能力。手动补采：环境变量 CS_WEEKLY_ALWAYS=1 或 --force-weekly。
    """
    if os.environ.get("CS_WEEKLY_ALWAYS") == "1":
        return True
    return datetime.now(TZ_BJ).isoweekday() == 1


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
    # F-3.1 活跃池淘汰：自选/持仓必采集；其余排除「存世量过低 / 活跃池淘汰」标记品（数据保留）
    rows = conn.execute("SELECT id, good_id, name FROM items WHERE good_id > 0 AND (in_watchlist=1 OR holding=1 OR notes IS NULL OR (notes NOT LIKE '%存世量过低%' AND notes NOT LIKE '%活跃池淘汰%')) ORDER BY id").fetchall()
    conn.close()
    ok = 0
    fails = []
    for r in rows:
        try:
            bars, _raw = await collector_csqaq.fetch_kline_90d(r["good_id"])
        except Exception as e:
            log(f"  [{r['id']}] K线异常: {e}")
            fails.append(f"{r['name'][:28]}({str(e)[:40]})")
            continue
        if not bars:
            log(f"  [{r['id']}] K线空: {r['name'][:30]}")
            fails.append(f"{r['name'][:28]}(空)")
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
    log(f"K线全量刷新: {ok}/{len(rows)} 失败={len(fails)}")
    return ok, fails


def prune_inactive(min_avg_sale: int = 10, days: int = 7) -> int:
    """活跃池淘汰（F-3.1, 2026-08-08）：非自选/非持仓品最近 days 天平均在售量 < min_avg_sale，
    标记 notes「活跃池淘汰:在售量过低」，退出每日采集（数据保留；加回自选即恢复采集）。
    纯数据层标记，不触碰引擎参数。"""
    from pipeline import db
    conn = db.get_conn()
    try:
        rows = conn.execute(f"""
            SELECT i.id FROM items i WHERE i.good_id>0 AND i.in_watchlist=0 AND COALESCE(i.holding,0)=0
            AND (i.notes IS NULL OR (i.notes NOT LIKE '%存世量过低%' AND i.notes NOT LIKE '%活跃池淘汰%'))
            AND (SELECT AVG(in_sale_count) FROM (SELECT in_sale_count FROM price_history p
                 WHERE p.item_id=i.id ORDER BY p.date DESC LIMIT {int(days)})) < {int(min_avg_sale)}
        """).fetchall()
        mark = f"活跃池淘汰:在售量过低(<{min_avg_sale})"
        for r in rows:
            conn.execute("UPDATE items SET notes=?, updated_at=datetime('now','localtime') WHERE id=?",
                         (mark, r["id"]))
        conn.commit()
        if rows:
            log(f"活跃池淘汰: {len(rows)} 品（最近{int(days)}天平均在售量 <{min_avg_sale}，已标记退出每日采集）")
        return len(rows)
    finally:
        conn.close()


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
        items = conn.execute("SELECT id, good_id, name FROM items WHERE good_id > 0 AND (in_watchlist=1 OR holding=1 OR notes IS NULL OR (notes NOT LIKE '%存世量过低%' AND notes NOT LIKE '%活跃池淘汰%')) ORDER BY id").fetchall()
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
    ap.add_argument("--force-weekly", action="store_true", help="强制本周执行周度任务（全市场快照+大户集中度）")
    args = ap.parse_args()
    from pipeline.pool_log import append_pool_log
    _health = None
    _kline_ok = 0
    _kline_fails = []
    log("=== 每日采集开始 ===")
    collect_bind_ip()
    collect_market_index()
    collect_macro()
    # 浏览器任务合并到同一个 event loop（Playwright 实例绑定 loop，多次 asyncio.run 会导致后续任务拿到已失效浏览器）
    _weekly = args.force_weekly or is_weekly_collect_day()
    async def _playwright_tasks():
        # 全市场快照/大户集中度降为每周（2026-08-08 优化）：引擎/决策不消费这两份数据，
        # 仅数据进度卡与健康检查计数；周度采集保留数据积累能力，省 ~9 分钟/天 Playwright 负载。
        # K 线全量刷新（价格+在售量，引擎唯一数据源）仍每日无条件执行。
        if _weekly:
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
            nonlocal _kline_ok, _kline_fails
            _kline_ok, _kline_fails = await collect_kline_all()
        except Exception as e:
            log(f"K线任务异常: {e}")
    # 活跃池淘汰 (F-3.1, 2026-08-08): K线刷新后评估流动性，淘汰品退出每日采集（数据保留）
    try:
        prune_inactive()
    except Exception as e:
        log(f"活跃池淘汰异常（不中断采集）: {e}")
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
        _health = res
        log(f"数据健康: status={res['status']} FAIL={res['fail_count']}（已写入 health_checks）")
    except Exception as e:
        log(f"数据健康检查异常（不中断采集）: {e}")
    # 池维护台账 (F-3.2, 2026-08-08): 每日采集收尾写一行，260 品完整链路留痕
    try:
        from pipeline import db as _db
        _c = _db.get_conn()
        _pool_size = _c.execute("SELECT COUNT(*) FROM items WHERE good_id>0").fetchone()[0]
        _active = _c.execute(
            "SELECT COUNT(*) FROM items WHERE good_id>0 AND (in_watchlist=1 OR holding=1 OR notes IS NULL "
            "OR (notes NOT LIKE '%存世量过低%' AND notes NOT LIKE '%活跃池淘汰%'))").fetchone()[0]
        _pruned = _c.execute("SELECT COUNT(*) FROM items WHERE notes LIKE '%活跃池淘汰%'").fetchone()[0]
        _new = _c.execute(
            "SELECT COUNT(*) FROM items WHERE good_id>0 AND date(created_at)=date('now','localtime')").fetchone()[0]
        _c.close()
        append_pool_log({
            "type": "daily",
            "date": datetime.now(TZ_BJ).strftime("%Y-%m-%d"),
            "pool_size": _pool_size,
            "active_pool": _active,
            "pruned": _pruned,
            "kline_ok": _kline_ok,
            "kline_fail_count": len(_kline_fails),
            "kline_fail_names": _kline_fails[:10],  # G-4（2026-08-10）失败品入台账，便于告警排查
            "new_items_today": _new,
            "health": (_health or {}).get("status"),
            "health_fail": (_health or {}).get("fail_count"),
        })
    except Exception as e:
        log(f"池维护台账异常（不中断采集）: {e}")
    # 数据质量定期复核（2026-08-10）：距上次复核 >=7 天且今天是周日 → 抽样联网实拉对比（只读）
    # 三层机制：日常健康检查(上面) / 每周抽样复核(本块) / 全库审计 SOP（data-layer.md §8，触发式）
    try:
        import subprocess, sys as _sys
        _today_w = datetime.now(TZ_BJ)
        _last_review = ""
        try:
            from pipeline import db as _db2
            _c2 = _db2.get_conn()
            _last_review = (_db2.get_setting(_c2, "data_review_last", "") or "")
            _c2.close()
        except Exception:
            pass
        _due = _today_w.weekday() == 6  # 周日
        if _last_review:
            try:
                _gap = (_today_w.date() - datetime.strptime(_last_review, "%Y-%m-%d").date()).days
                _due = _due and _gap >= 7
            except ValueError:
                _due = True
        if _due:
            _review_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "references", "data_quality_review.py")
            _rr = subprocess.run([_sys.executable, _review_script, "--sample", "15"],
                                 capture_output=True, text=True, timeout=900)
            log(f"数据质量复核: exit={_rr.returncode} {( _rr.stdout or '').strip()[-400:]}")
            if _rr.returncode == 2:
                log("数据质量复核发现 ISSUE：查看 data/data_review_latest.json，按 §8 SOP 确认后 --fix 回填")
        else:
            log(f"数据质量复核: 未到周期（上次 {_last_review or '从未'}，每周日且间隔>=7天触发）")
    except Exception as e:
        log(f"数据质量复核异常（不中断采集）: {e}")
    # J-2 三通道监测刷新 (2026-08-07): 重跑 j2_channel_monitor.py 更新 data/j2_channel_status.json（B 通道天数每日变化）
    try:
        import subprocess, sys as _sys
        _r = subprocess.run([_sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "references", "j2_channel_monitor.py")],
                            capture_output=True, text=True, timeout=60)
        log(f"J-2 三通道监测刷新: exit={_r.returncode} {(_r.stdout or '').strip()}")
    except Exception as e:
        log(f"J-2 三通道监测刷新异常（不中断采集）: {e}")
    # T0 greedy 覆盖监测 (2026-08-10): 采集后记录 greedy_index 覆盖天数，连续 7 个采集日验证单调增长（第一性原理审计 P-0/T0）
    try:
        import subprocess, sys as _sys
        _r = subprocess.run([_sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "references", "greedy_backfill_check.py")],
                            capture_output=True, text=True, timeout=60)
        log(f"T0 greedy 覆盖监测: exit={_r.returncode} {(_r.stdout or '').strip()[-200:]}")
    except Exception as e:
        log(f"T0 greedy 覆盖监测异常（不中断采集）: {e}")
    # 生产实盘信号跟踪回填 (2026-08-07 C 通道实盘化): 14/30 交易日后按真实价格回填 buy 信号收益
    try:
        from pipeline.signal_tracking import run_backfill_once
        _sig = run_backfill_once()
        _s = _sig["summary"]
        log(f"信号跟踪回填: 更新 {_sig['updated']} 条, 累计 {_s['n_total']} 信号 / 已回填14d {_s['n_filled14']} / 30d {_s['n_filled30']}")
    except Exception as e:
        log(f"信号跟踪回填异常（不中断采集）: {e}")
    # M1 监控模式 (2026-08-08): 自选品异动事件生成 + 日报 (纯提醒层, 只读引擎输出, 不触碰引擎参数)
    # 2026-08-08 采集提前至 18:00: 收尾仅生成事件+日报, 推送由独立任务 run_night_push.py 在 21:30 执行
    try:
        from pipeline.monitor import run_daily_monitor
        _mon = run_daily_monitor(slot="night", push=False)
        log(f"监控事件: 生成 {_mon['generated']} / 新增 {_mon['saved']} 条 (大盘 {_mon['bucket']}, 分析 {_mon['analyzed']} 品, 推送延至21:30)")
    except Exception as e:
        log(f"监控事件生成异常（不中断采集）: {e}")

    # 数据保留清理（365/90/7 天 + VACUUM，口径 references/data-layer.md）
    try:
        from pipeline.db import run_retention_cleanup
        _rc = run_retention_cleanup(vacuum=True)
        log(f"数据保留清理: deleted={_rc['deleted']} files={_rc['files']} vacuum={_rc['vacuum']}")
    except Exception as e:
        log(f"数据保留清理异常（不中断采集）: {e}")
    # 每日备份 (Phase 4): SQLite online backup -> data/backup/, 保留最近 14 份
    try:
        from backup_db import backup as _daily_backup
        from pipeline.config import DB_PATH as _db_path
        _daily_backup(_db_path, keep=14)
    except Exception as e:
        log(f"每日备份异常（不中断采集）: {e}")
    log("=== 每日采集完成 ===")


if __name__ == "__main__":
    main()
