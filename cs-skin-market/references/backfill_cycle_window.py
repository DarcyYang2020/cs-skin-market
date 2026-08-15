# -*- coding: utf-8 -*-
"""历史扩窗口回填：price + in_sale 回填到新回放库 replay_cycle_win.db（v69，2026-08-15）。

范围/红线基准 = references/cycle-refit-2026-08-15.md。
只回填「回放池 A 96 品」（first_date<=2025-08-10 且排除水栽竹/珊瑚树），非全库。
数据源：csQAQ /info/chart key=sell_price period=1095 → main_data（价格→price_rmb）+ num_data（在售量→in_sale_count）。
落库：新回放库 data/replay_cycle_win.db（由 replay_hybrid.db 拷贝而来，保留 items + market_index）。

用法:
  python references/backfill_cycle_window.py --dry-run --limit 3
  python references/backfill_cycle_window.py --apply
"""
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.collector import _api_call  # noqa: E402
from pipeline.config import TZ_BJ  # noqa: E402

SRC_DB = ROOT / "data" / "replay_hybrid.db"
DST_DB = ROOT / "data" / "replay_cycle_win.db"
EXCLUDED = {"AK-47 | 水栽竹 (崭新出厂)", "AWP | 珊瑚树 (崭新出厂)"}


def log(msg: str):
    print(msg, flush=True)


def fetch_sell(good_id: int):
    resp = _api_call("POST", "/info/chart", {
        "good_id": str(good_id), "key": "sell_price", "platform": 2,
        "period": "1095", "style": "all_style",
    })
    if resp.get("code") != 200 or not isinstance(resp.get("data"), dict):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def parse_daily(data: dict) -> dict:
    """sell_price period=1095 → {date: (price, in_sale)}（日线，每日单值）。"""
    out = {}
    ts = data.get("timestamp") or []
    price = data.get("main_data") or []
    num = data.get("num_data") or []
    n = min(len(ts), len(price), len(num))
    for i in range(n):
        try:
            t = int(ts[i])
            if t < 10 ** 11:
                t *= 1000
            p = float(price[i])
            s = float(num[i])
        except (TypeError, ValueError):
            continue
        if t <= 0 or p <= 0:
            continue
        day = datetime.fromtimestamp(t / 1000, tz=TZ_BJ).strftime("%Y-%m-%d")
        out[day] = (round(p, 2), int(s) if s >= 0 else None)
    return out


def load_pool(conn):
    rows = conn.execute(
        """SELECT i.id AS item_id, i.good_id, i.name, MIN(p.date) first_date
           FROM items i JOIN price_history p ON p.item_id = i.id
           GROUP BY i.id HAVING MIN(p.date) <= '2025-08-10' ORDER BY i.id"""
    ).fetchall()
    return [{"item_id": r["item_id"], "good_id": r["good_id"], "name": r["name"]}
            for r in rows if r["name"] not in EXCLUDED and r["good_id"] > 0]


def audit(conn):
    r = conn.execute("SELECT COUNT(*) n, MIN(date) mn, MAX(date) mx FROM price_history").fetchone()
    bp = conn.execute("SELECT COUNT(*) n FROM price_history WHERE price_rmb IS NOT NULL").fetchone()["n"]
    bs = conn.execute("SELECT COUNT(*) n FROM price_history WHERE in_sale_count IS NOT NULL").fetchone()["n"]
    return {"rows": r["n"], "min_date": r["mn"], "max_date": r["mx"], "price_nonnull": bp, "insale_nonnull": bs}


def apply_backfill(pool):
    if DST_DB.exists():
        DST_DB.unlink()
    shutil.copy2(SRC_DB, DST_DB)
    log(f"created {DST_DB.name} (copy of replay_hybrid.db)")

    conn = sqlite3.connect(DST_DB)
    conn.row_factory = sqlite3.Row
    before = audit(conn)
    updated = inserted = 0
    fail = 0
    for i, it in enumerate(pool, 1):
        data, err = fetch_sell(it["good_id"])
        if data is None:
            fail += 1
            log(f"[{i}/{len(pool)}] good={it['good_id']} FAIL {err}")
            continue
        series = parse_daily(data)
        for day, (price, insale) in series.items():
            row = conn.execute("SELECT date FROM price_history WHERE item_id=? AND date=?",
                               (it["item_id"], day)).fetchone()
            if row:
                conn.execute("UPDATE price_history SET price_rmb=?, in_sale_count=? WHERE item_id=? AND date=?",
                             (price, insale, it["item_id"], day))
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO price_history (item_id, date, price_rmb, volume_day, volume_total, in_sale_count) "
                    "VALUES (?,?,?,?,?,?)", (it["item_id"], day, price, None, None, insale))
                inserted += 1
        if i <= 3 or i % 25 == 0:
            log(f"[{i}/{len(pool)}] good={it['good_id']} days={len(series)} {it['name'][:24]}")
    conn.commit()
    after = audit(conn)
    conn.close()
    return {"updated": updated, "inserted": inserted, "failed": fail, "before": before, "after": after}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    # 用源库读 pool（96 品）
    src = sqlite3.connect(SRC_DB)
    src.row_factory = sqlite3.Row
    pool = load_pool(src)
    src.close()
    if args.limit:
        pool = pool[: args.limit]
    log(f"pool A items: {len(pool)} | dry-run={args.dry_run} apply={args.apply}")

    if args.dry_run:
        total_days = 0
        for i, it in enumerate(pool, 1):
            data, err = fetch_sell(it["good_id"])
            if data is None:
                log(f"[{i}/{len(pool)}] good={it['good_id']} FAIL {err}")
                continue
            s = parse_daily(data)
            total_days += len(s)
            log(f"[{i}/{len(pool)}] good={it['good_id']} days={len(s)} range={min(s)}~{max(s)}")
        log(f"DRY-RUN done: total_days={total_days}")

    if args.apply:
        result = apply_backfill(pool)
        log(f"APPLY done: updated={result['updated']} inserted={result['inserted']} failed={result['failed']}")
        log(f"  before={result['before']}")
        log(f"  after ={result['after']}")


if __name__ == "__main__":
    main()
