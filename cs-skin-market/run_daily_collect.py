# -*- coding: utf-8 -*-
"""每日自动采集脚本（挂 Windows 计划任务）。

- 大盘指数：csQAQ 当日指数落库（复用 collector）
- 贪婪历史：market_macro 写穿透（~60 天全量 upsert）
- 单品成交量：悠悠有品近 7 日逐日量，更新 price_history.volume_day（需 yyyp_id）
- 每周日（isoweekday=7）额外全量刷新 90 日 K 线

用法: python run_daily_collect.py
"""
import sys, io, os, asyncio, json
from datetime import datetime, timezone, timedelta

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


async def collect_volume() -> int:
    from pipeline import db
    from pipeline.collector_youpin import fetch_youpin_volume
    conn = db.get_conn()
    rows = conn.execute("SELECT id, yyyp_id FROM items WHERE yyyp_id IS NOT NULL AND yyyp_id != '' ORDER BY id").fetchall()
    conn.close()
    if not rows:
        log("无 yyyp_id 记录，跳过成交量（先跑 backfill_yyyp.py）")
        return 0
    ok = 0
    total_vol = 0
    for r in rows:
        try:
            vol_map = await fetch_youpin_volume(r["yyyp_id"])
        except Exception as e:
            log(f"  [{r['id']}] 悠悠量异常: {e}")
            continue
        if not vol_map:
            continue
        conn = db.get_conn()
        try:
            for date, vol in vol_map.items():
                cur = conn.execute(
                    "UPDATE price_history SET volume_day=? WHERE item_id=? AND date=?",
                    (int(vol), r["id"], date))
                if cur.rowcount:
                    total_vol += int(vol)
            conn.commit()
        finally:
            conn.close()
        ok += 1
    log(f"成交量更新: {ok}/{len(rows)} 个品有量，累计 {total_vol} 件")
    return ok


async def collect_kline_all() -> int:
    from pipeline import collector_csqaq, db
    conn = db.get_conn()
    rows = conn.execute("SELECT id, good_id, name FROM items WHERE good_id > 0 ORDER BY id").fetchall()
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


def main():
    import argparse
    ap = argparse.ArgumentParser(description="每日自动采集")
    ap.add_argument("--kline", action="store_true", help="全量刷新 90 日 K 线（慢，建议单独跑）")
    args = ap.parse_args()
    log("=== 每日采集开始 ===")
    collect_market_index()
    collect_macro()
    try:
        asyncio.run(collect_volume())
    except Exception as e:
        log(f"成交量任务异常: {e}")
    # 每周日额外全量刷新 90 日 K 线（对齐 docstring；--kline 亦可手动触发）
    is_sunday = datetime.now(TZ_BJ).isoweekday() == 7
    if args.kline or is_sunday:
        log("--kline：全量刷新 90 日 K 线")
        try:
            asyncio.run(collect_kline_all())
        except Exception as e:
            log(f"K线任务异常: {e}")
    log("=== 每日采集完成 ===")


if __name__ == "__main__":
    main()