# -*- coding: utf-8 -*-
"""单品历史价格深度回填（simple/chartAll，2025-01-01 起）。

背景：现有 price_history 覆盖 2025-08-04 起（chart period=365），缺口为
2025-01-01 ~ 2025-08-03。本脚本用 simple/chartAll(plat=2 悠悠价) 多窗口翻页补缺失日期，
仅补价格、不覆盖已有 volume_day/in_sale_count（backfill_price_missing）。

用法:
    python run_backfill_history.py            # 全量（已覆盖品自动跳过）
    python run_backfill_history.py --limit 5  # 只跑前 5 个未覆盖品（试运行）

"""
import sys, io, os, asyncio, argparse
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TZ_BJ = timezone(timedelta(hours=8))
MIN_DATE = "2025-01-01"   # 用户判定：2024 及更早市场逻辑已过时，不纳入
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "backfill_history.log")


def log(msg: str):
    line = f"[{datetime.now(TZ_BJ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


async def backfill_item(conn, item_id, good_id, name):
    from pipeline import db
    from pipeline.collector_csqaq import fetch_history_deep
    start = db.item_history_start(conn, item_id)
    cnt = conn.execute("SELECT COUNT(*) c FROM price_history WHERE item_id=?", (item_id,)).fetchone()["c"]
    if start and start <= MIN_DATE and cnt >= 540:
        return 0  # 已完整覆盖（起点+行数双条件，避免带缺口被跳过）
    try:
        points = await fetch_history_deep(good_id, MIN_DATE, start_date=start)
    except Exception as e:
        log(f"  [{item_id}] {name[:28]} 抓取异常: {e}")
        return 0
    if not points:
        log(f"  [{item_id}] {name[:28]} 无数据")
        return 0
    db.backfill_price_missing(conn, item_id, points)
    log(f"  [{item_id}] {name[:28]} 回填 {len(points)} 点")
    return len(points)


async def main(limit: int):
    from pipeline import db
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, good_id, name FROM items WHERE good_id > 0 ORDER BY id").fetchall()
    conn.close()
    todo = []
    for r in rows:
        conn = db.get_conn()
        try:
            start = db.item_history_start(conn, r["id"])
            cnt = conn.execute("SELECT COUNT(*) c FROM price_history WHERE item_id=?", (r["id"],)).fetchone()["c"]
        finally:
            conn.close()
        if start and start <= MIN_DATE and cnt >= 540:
            continue  # 已完整覆盖（起点+行数双条件）
        todo.append(r)
    log(f"=== 历史回填开始: 待处理 {len(todo)}/{len(rows)} 品（起点 {MIN_DATE}） ===")
    if limit:
        todo = todo[:limit]
    total = 0
    for i, r in enumerate(todo, 1):
        conn = db.get_conn()
        try:
            n = await backfill_item(conn, r["id"], r["good_id"], r["name"] or "")
        finally:
            conn.close()
        total += n
        if i % 5 == 0:
            log(f"  进度 {i}/{len(todo)}")
    log(f"=== 历史回填完成: {len(todo)} 品, 累计 {total} 点 ===")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="单品历史价格深度回填")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个未覆盖品（试运行）")
    args = ap.parse_args()
    asyncio.run(main(args.limit))
