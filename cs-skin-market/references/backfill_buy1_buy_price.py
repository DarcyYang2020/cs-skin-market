# -*- coding: utf-8 -*-
"""BUY-1 buy_price 直连回填（有条件通过裁定：buy_price 用 period=1095 日线，buy_num 不动）。

范围/红线基准 = references/optimization-initiation-2026-08-15.md + 外审裁定：
  - buy_price 用直连 1095 日线回填 bid_history（buy_price_last/min/max/mean + point_count=1）
  - buy_num 维持现有 period=90 十分钟点口径，一律不写
  - 只进研究层（bid_history），不碰 items / price_history / 引擎
回填前备份 bid_history（data/*.bak-buy1-*）。

用法:
  python references/backfill_buy1_buy_price.py --dry-run --limit 5
  python references/backfill_buy1_buy_price.py --apply
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db  # noqa: E402
from pipeline.collector import _api_call  # noqa: E402
from pipeline.config import TZ_BJ  # noqa: E402

DB_PATH = ROOT / "data" / "market.db"
WRITE_LOG = ROOT / "data" / "price_history_write_log.jsonl"  # 复用 B-1 审计（bid_history 变更也记）


def log(msg: str):
    print(msg, flush=True)


def fetch_buy_price(good_id: int):
    resp = _api_call("POST", "/info/chart", {
        "good_id": str(good_id), "key": "buy_price", "platform": 2,
        "period": "1095", "style": "all_style",
    })
    if resp.get("code") != 200 or not isinstance(resp.get("data"), dict):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def daily_value(data: dict) -> dict:
    """main_data -> {date: value}（period=1095 日线：每日单值）。"""
    out = {}
    ts = data.get("timestamp") or []
    vals = data.get("main_data") or []
    for i in range(min(len(ts), len(vals))):
        try:
            t = int(ts[i])
            if t < 10 ** 11:
                t *= 1000
            v = float(vals[i])
        except (TypeError, ValueError):
            continue
        if t <= 0 or v <= 0:
            continue
        day = datetime.fromtimestamp(t / 1000, tz=TZ_BJ).strftime("%Y-%m-%d")
        out[day] = v
    return out


def load_target_goods(conn):
    rows = conn.execute(
        "SELECT DISTINCT good_id, item_id, item_name FROM bid_history "
        "WHERE good_id > 0 ORDER BY good_id").fetchall()
    return [{"good_id": r["good_id"], "item_id": r["item_id"], "item_name": r["item_name"]} for r in rows]


def audit(conn):
    """回填前后审计：bid_history 行数 / 日期范围 / buy_price 非空 / buy_num 非空。"""
    r = conn.execute("SELECT COUNT(*) n, MIN(date) mn, MAX(date) mx FROM bid_history").fetchone()
    bp = conn.execute("SELECT COUNT(*) n FROM bid_history WHERE buy_price_last IS NOT NULL").fetchone()["n"]
    bn = conn.execute("SELECT COUNT(*) n FROM bid_history WHERE buy_num_last IS NOT NULL").fetchone()["n"]
    return {"rows": r["n"], "min_date": r["mn"], "max_date": r["mx"], "buy_price_nonnull": bp, "buy_num_nonnull": bn}


def apply_backfill(targets, backup: bool):
    if backup:
        ts = datetime.now(TZ_BJ).strftime("%Y%m%d-%H%M%S")
        bak = DB_PATH.with_name(f"market.bak-buy1-{ts}")
        import shutil
        shutil.copy2(DB_PATH, bak)
        log(f"backup: {bak}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    before = audit(conn)
    updated = inserted = 0
    fail = 0
    for i, t in enumerate(targets, 1):
        gid = t["good_id"]
        data, err = fetch_buy_price(gid)
        if data is None:
            fail += 1
            log(f"[{i}/{len(targets)}] good={gid} FAIL {err}")
            continue
        series = daily_value(data)
        n_upd = n_ins = 0
        for day, v in series.items():
            row = conn.execute("SELECT date FROM bid_history WHERE good_id=? AND date=?", (gid, day)).fetchone()
            if row:
                conn.execute(
                    "UPDATE bid_history SET buy_price_last=?, buy_price_min=?, buy_price_max=?, "
                    "buy_price_mean=?, point_count=1 WHERE good_id=? AND date=?",
                    (v, v, v, v, gid, day))
                n_upd += 1
            else:
                conn.execute(
                    "INSERT INTO bid_history (date, item_id, good_id, item_name, source, platform, "
                    "buy_price_last, buy_price_min, buy_price_max, buy_price_mean, point_count) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                    (day, t["item_id"], gid, t["item_name"], "csqaq_direct", 2, v, v, v, v))
                n_ins += 1
        updated += n_upd
        inserted += n_ins
        if i <= 3 or i % 50 == 0:
            log(f"[{i}/{len(targets)}] good={gid} upd={n_upd} ins={n_ins} days={len(series)} {t['item_name'][:24]}")
    conn.commit()
    after = audit(conn)
    conn.close()

    # 写审计日志（B-1 同款，标记 mode）
    try:
        with WRITE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(TZ_BJ).isoformat(timespec="seconds"),
                "mode": "backfill-buy1-buy-price",
                "n_update": updated, "n_insert": inserted, "n_fail": fail,
                "before": before, "after": after,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"updated": updated, "inserted": inserted, "failed": fail, "before": before, "after": after}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="fetch + report, no write")
    parser.add_argument("--apply", action="store_true", help="backup bid_history + write buy_price")
    parser.add_argument("--limit", type=int, default=0, help="limit first N goods")
    args = parser.parse_args()

    conn = db.get_conn()
    targets = load_target_goods(conn)
    conn.close()
    if args.limit:
        targets = targets[: args.limit]
    log(f"target goods: {len(targets)} | dry-run={args.dry_run} apply={args.apply}")

    if args.dry_run:
        total_days = 0
        for i, t in enumerate(targets, 1):
            data, err = fetch_buy_price(t["good_id"])
            if data is None:
                log(f"[{i}/{len(targets)}] good={t['good_id']} FAIL {err}")
                continue
            s = daily_value(data)
            total_days += len(s)
            log(f"[{i}/{len(targets)}] good={t['good_id']} days={len(s)} range={min(s)}~{max(s)}")
        log(f"DRY-RUN done: total_days={total_days}")

    if args.apply:
        result = apply_backfill(targets, backup=True)
        log(f"APPLY done: updated={result['updated']} inserted={result['inserted']} failed={result['failed']}")
        log(f"  before={result['before']}")
        log(f"  after ={result['after']}")


if __name__ == "__main__":
    main()
