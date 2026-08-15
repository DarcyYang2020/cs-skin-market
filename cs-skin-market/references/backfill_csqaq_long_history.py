# -*- coding: utf-8 -*-
"""Backfill NULL `price_history.in_sale_count` from csQAQ long-window chart.

2026-08-15 probe:
  - csQAQ /info/chart accepts period=365 and period=1095.
  - period=365 returns 364 daily bars (2025-08-16..2026-08-14).
  - period=1095 returns 1171 daily bars (2023-06-01..2026-08-14).
  - key=sell_price returns num_data alongside main_data; the 2026-02~04
    gap is fully populated (good_id=1290: 89/89 non-null in gap).

This script updates only rows where in_sale_count IS NULL. Existing values
(including real 0) are never overwritten, so the missing/zero distinction
used by DECISION-6 is preserved.

2026-08-15 0-value gap mode (--zero-gap):
  2026-02-01~04-30 was persisted as in_sale_count = 0 (pseudo-zero), not NULL.
  The NULL-only pass above left those fake zeros in place, polluting v2-T9.
  --zero-gap backfills ONLY rows with date IN [GAP_START, GAP_END] AND
  in_sale_count = 0, aligning each row to the API num_data for the exact same
  day (no range-fill, no nearest-nonzero). Three branches per date:
    - API value > 0  -> write it back
    - API value == 0 -> keep DB 0 (real zero)
    - API date missing -> keep DB 0, record missing_still
  Rows with in_sale_count != 0 in the gap, and all rows outside the gap, are
  never touched. Changes are appended to data/price_history_write_log.jsonl.

Usage:
  python references/backfill_csqaq_long_history.py --dry-run --limit 3
  python references/backfill_csqaq_long_history.py --dry-run
  python references/backfill_csqaq_long_history.py --apply --period 1095
  python references/backfill_csqaq_long_history.py --zero-gap --dry-run
  python references/backfill_csqaq_long_history.py --zero-gap --apply --period 1095
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.collector import _api_call  # noqa: E402

TZ_BJ = timezone(timedelta(hours=8))
DB_PATHS = [
    ROOT / "data" / "market.db",
    ROOT / "data" / "replay_v2t6_win.db",
]
OUT = ROOT / "data" / "_exp_csqaq_long_history_backfill.json"
OUT_ZERO_GAP = ROOT / "data" / "_exp_csqaq_0gap_backfill.json"
WRITE_LOG = ROOT / "data" / "price_history_write_log.jsonl"

# 0-value gap window（与 pipeline/db.py SUPPLY_GAP_START/END 同值）
GAP_START = "2026-02-01"
GAP_END = "2026-04-30"


def log(msg: str):
    print(msg, flush=True)


def fetch_series(good_id: int, period: str) -> tuple[dict[str, int] | None, str]:
    """Fetch date -> in_sale_count map for one good_id."""
    resp = _api_call(
        "POST",
        "/info/chart",
        {
            "good_id": str(good_id),
            "key": "sell_price",
            "platform": 2,
            "period": period,
            "style": "all_style",
        },
    )
    if resp.get("code") != 200 or not isinstance(resp.get("data"), dict):
        return None, f"code={resp.get('code')} msg={resp.get('msg')}"

    data = resp["data"]
    ts = data.get("timestamp") or []
    nums = data.get("num_data") or []
    series: dict[str, int] = {}
    for i in range(min(len(ts), len(nums))):
        raw_ts = ts[i]
        raw_num = nums[i]
        if raw_ts in (None, "") or raw_num in (None, ""):
            continue
        try:
            ts_ms = int(raw_ts)
            if ts_ms < 10**11:
                ts_ms *= 1000
            day = datetime.fromtimestamp(ts_ms / 1000, TZ_BJ).strftime("%Y-%m-%d")
            value = int(float(raw_num))
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        series[day] = value
    if not series:
        return None, "empty series"
    return series, ""


def load_null_rows() -> dict[int, dict]:
    """Return good_id -> item info and per-DB null rows.

    keyed by good_id so one API response can update both production and replay DBs.
    """
    targets: dict[int, dict] = {}
    for db_path in DB_PATHS:
        if not db_path.exists():
            continue
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT i.id AS item_id, i.good_id, i.name, p.date
                FROM items i
                JOIN price_history p ON p.item_id = i.id
                WHERE i.good_id > 0 AND p.in_sale_count IS NULL
                ORDER BY i.good_id, i.id, p.date
                """
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            good_id = row["good_id"]
            target = targets.setdefault(good_id, {"name": row["name"], "dbs": {}})
            db_target = target["dbs"].setdefault(str(db_path), {"item_ids": set(), "dates": {}})
            db_target["item_ids"].add(row["item_id"])
            db_target["dates"].setdefault(row["item_id"], set()).add(row["date"])

    for target in targets.values():
        for db_target in target["dbs"].values():
            db_target["item_ids"] = sorted(db_target["item_ids"])
            db_target["null_count"] = sum(len(dates) for dates in db_target["dates"].values())
    return targets


def analyze_targets(targets: dict, period: str, limit: int | None) -> dict:
    items = sorted(targets.items(), key=lambda kv: kv[0])
    if limit:
        items = items[:limit]

    results = []
    total_null = 0
    total_fillable = 0
    total_failed = 0
    for idx, (good_id, target) in enumerate(items, 1):
        series, err = fetch_series(good_id, period)
        entry = {
            "good_id": good_id,
            "name": target["name"],
            "series_days": len(series) if series else 0,
            "series_first": min(series) if series else None,
            "series_last": max(series) if series else None,
            "status": "ok" if series else "error",
            "error": err if not series else "",
            "dbs": {},
        }
        if series is None:
            total_failed += 1
            results.append(entry)
            continue

        for db_path, db_target in target["dbs"].items():
            fillable = 0
            missing_still = 0
            for item_id, dates in db_target["dates"].items():
                for date in dates:
                    if date in series:
                        fillable += 1
                    else:
                        missing_still += 1
            entry["dbs"][db_path] = {
                "null_count": db_target["null_count"],
                "fillable": fillable,
                "missing_still": missing_still,
            }
            total_null += db_target["null_count"]
            total_fillable += fillable
        results.append(entry)
        log(
            f"[{idx}/{len(items)}] good={good_id} {target['name'][:30]:32s} "
            f"series={entry['series_days']} fillable={sum(v['fillable'] for v in entry['dbs'].values())}"
        )

    return {
        "generated": datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "period": period,
        "target_goods": len(items),
        "failed_goods": total_failed,
        "total_null_rows": total_null,
        "total_fillable_rows": total_fillable,
        "results": results,
    }


def apply_backfill(targets: dict, period: str, limit: int | None) -> dict:
    items = sorted(targets.items(), key=lambda kv: kv[0])
    if limit:
        items = items[:limit]

    backups = {}
    for db_path in DB_PATHS:
        if db_path.exists():
            backup = db_path.with_name(db_path.stem + f".bak-insale1095-{datetime.now(TZ_BJ).strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(db_path, backup)
            backups[str(db_path)] = str(backup)
            log(f"backup: {backup}")

    updated_rows = 0
    for idx, (good_id, target) in enumerate(items, 1):
        series, err = fetch_series(good_id, period)
        if series is None:
            log(f"[{idx}/{len(items)}] good={good_id} {target['name'][:30]:32s} ERROR {err}")
            continue
        item_updates = 0
        for db_path, db_target in target["dbs"].items():
            conn = sqlite3.connect(db_path)
            try:
                for item_id, dates in db_target["dates"].items():
                    for date in dates:
                        value = series.get(date)
                        if value is None:
                            continue
                        cur = conn.execute(
                            "UPDATE price_history SET in_sale_count=? "
                            "WHERE item_id=? AND date=? AND in_sale_count IS NULL",
                            (value, item_id, date),
                        )
                        item_updates += cur.rowcount
                conn.commit()
            finally:
                conn.close()
        updated_rows += item_updates
        log(
            f"[{idx}/{len(items)}] good={good_id} {target['name'][:30]:32s} updated={item_updates}"
        )

    return {"updated_rows": updated_rows, "backups": backups}


# ---------------------------------------------------------------------------
# 0-value gap backfill (2026-08-15)
# ---------------------------------------------------------------------------

def _load_zero_gap_targets() -> dict[int, dict]:
    """Return good_id -> item info + per-DB zero-value gap rows.

    Only rows with in_sale_count = 0 AND date IN [GAP_START, GAP_END] are
    targets. Non-zero rows in the gap and everything outside the gap are left
    untouched.
    """
    targets: dict[int, dict] = {}
    for db_path in DB_PATHS:
        if not db_path.exists():
            continue
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT i.id AS item_id, i.good_id, i.name, p.date
                FROM items i
                JOIN price_history p ON p.item_id = i.id
                WHERE i.good_id > 0
                  AND p.in_sale_count = 0
                  AND p.date BETWEEN ? AND ?
                ORDER BY i.good_id, i.id, p.date
                """,
                (GAP_START, GAP_END),
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            good_id = row["good_id"]
            target = targets.setdefault(good_id, {"name": row["name"], "dbs": {}})
            db_target = target["dbs"].setdefault(str(db_path), {"item_ids": set(), "dates": {}})
            db_target["item_ids"].add(row["item_id"])
            db_target["dates"].setdefault(row["item_id"], set()).add(row["date"])

    for target in targets.values():
        for db_target in target["dbs"].values():
            db_target["item_ids"] = sorted(db_target["item_ids"])
            db_target["zero_count"] = sum(len(dates) for dates in db_target["dates"].values())
    return targets


def _classify_dates(series: dict[str, int], dates) -> tuple[int, int, int]:
    """Split target dates into (written, zero_kept, missing_still) counts."""
    written = zero_kept = missing_still = 0
    for date in dates:
        value = series.get(date)
        if value is None:
            missing_still += 1
        elif value == 0:
            zero_kept += 1
        else:
            written += 1
    return written, zero_kept, missing_still


def _analyze_zero_gap(targets: dict, period: str, limit: int | None) -> dict:
    items = sorted(targets.items(), key=lambda kv: kv[0])
    if limit:
        items = items[:limit]

    results = []
    total_zero = 0
    total_written = 0
    total_zero_kept = 0
    total_missing_still = 0
    total_failed = 0
    for idx, (good_id, target) in enumerate(items, 1):
        series, err = fetch_series(good_id, period)
        entry = {
            "good_id": good_id,
            "name": target["name"],
            "series_days": len(series) if series else 0,
            "status": "ok" if series else "error",
            "error": err if not series else "",
            "dbs": {},
        }
        if series is None:
            total_failed += 1
            results.append(entry)
            continue

        for db_path, db_target in target["dbs"].items():
            written = zero_kept = missing_still = 0
            for item_id, dates in db_target["dates"].items():
                w, zk, ms = _classify_dates(series, dates)
                written += w
                zero_kept += zk
                missing_still += ms
            entry["dbs"][db_path] = {
                "zero_count": db_target["zero_count"],
                "written": written,
                "zero_kept": zero_kept,
                "missing_still": missing_still,
            }
            total_zero += db_target["zero_count"]
            total_written += written
            total_zero_kept += zero_kept
            total_missing_still += missing_still
        results.append(entry)
        log(
            f"[{idx}/{len(items)}] good={good_id} {target['name'][:30]:32s} "
            f"series={entry['series_days']} written={sum(v['written'] for v in entry['dbs'].values())}"
        )

    return {
        "generated": datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "period": period,
        "target_goods": len(items),
        "failed_goods": total_failed,
        "total_zero_rows": total_zero,
        "total_written": total_written,
        "total_zero_kept": total_zero_kept,
        "total_missing_still": total_missing_still,
        "results": results,
    }


def _append_zero_gap_write_log(item_id: int, db_name: str, n_upd: int, detail: list):
    """Append a B-1-style record to data/price_history_write_log.jsonl."""
    try:
        with WRITE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(TZ_BJ).isoformat(timespec="seconds"),
                "item_id": item_id,
                "mode": "backfill-insale0gap",
                "db": db_name,
                "n_insert": 0,
                "n_update": n_upd,
                "detail": detail,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _apply_zero_gap(targets: dict, period: str, limit: int | None) -> dict:
    items = sorted(targets.items(), key=lambda kv: kv[0])
    if limit:
        items = items[:limit]

    backups = {}
    for db_path in DB_PATHS:
        if db_path.exists():
            backup = db_path.with_name(
                db_path.stem + f".bak-insale0gap-{datetime.now(TZ_BJ).strftime('%Y%m%d-%H%M%S')}"
            )
            shutil.copy2(db_path, backup)
            backups[str(db_path)] = str(backup)
            log(f"backup: {backup}")

    updated_rows = 0
    zero_kept_total = 0
    missing_still_total = 0
    for idx, (good_id, target) in enumerate(items, 1):
        series, err = fetch_series(good_id, period)
        if series is None:
            log(f"[{idx}/{len(items)}] good={good_id} {target['name'][:30]:32s} ERROR {err}")
            continue
        item_updates = 0
        for db_path, db_target in target["dbs"].items():
            conn = sqlite3.connect(db_path)
            try:
                for item_id, dates in db_target["dates"].items():
                    n_upd = 0
                    detail = []
                    for date in dates:
                        value = series.get(date)
                        if value is None:
                            missing_still_total += 1
                            continue
                        if value == 0:
                            zero_kept_total += 1
                            continue
                        cur = conn.execute(
                            "UPDATE price_history SET in_sale_count=? "
                            "WHERE item_id=? AND date=? AND in_sale_count=0",
                            (value, item_id, date),
                        )
                        if cur.rowcount:
                            n_upd += cur.rowcount
                            detail.append({"op": "update", "date": date, "in_sale_count": value})
                    item_updates += n_upd
                    if n_upd:
                        _append_zero_gap_write_log(item_id, Path(db_path).name, n_upd, detail)
                conn.commit()
            finally:
                conn.close()
        updated_rows += item_updates
        log(
            f"[{idx}/{len(items)}] good={good_id} {target['name'][:30]:32s} updated={item_updates}"
        )

    return {
        "updated_rows": updated_rows,
        "zero_kept": zero_kept_total,
        "missing_still": missing_still_total,
        "backups": backups,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="fetch and report, do not write")
    parser.add_argument("--apply", action="store_true", help="back up DBs and update in_sale_count")
    parser.add_argument("--period", default="1095", choices=("365", "1095"))
    parser.add_argument("--limit", type=int, default=0, help="limit number of good_ids to process")
    parser.add_argument(
        "--zero-gap",
        action="store_true",
        help="backfill 0-value gap rows (2026-02-01~04-30) instead of NULL rows",
    )
    args = parser.parse_args()

    if args.zero_gap:
        targets = _load_zero_gap_targets()
        if not targets:
            log("no in_sale_count = 0 gap rows found")
            return
        log(f"zero-gap targets: {len(targets)} good_ids")

        report = _analyze_zero_gap(targets, args.period, args.limit or None)
        OUT_ZERO_GAP.parent.mkdir(parents=True, exist_ok=True)
        with OUT_ZERO_GAP.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        log(f"report: {OUT_ZERO_GAP}")
        log(
            "summary: zero_rows=%d written=%d zero_kept=%d missing_still=%d failed=%d"
            % (
                report["total_zero_rows"],
                report["total_written"],
                report["total_zero_kept"],
                report["total_missing_still"],
                report["failed_goods"],
            )
        )

        if args.apply:
            result = _apply_zero_gap(targets, args.period, args.limit or None)
            report["apply"] = result
            with OUT_ZERO_GAP.open("w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=1)
            log(
                "applied: %d rows updated (zero_kept=%d missing_still=%d)"
                % (result["updated_rows"], result["zero_kept"], result["missing_still"])
            )
        return

    targets = load_null_rows()
    if not targets:
        log("no NULL in_sale_count rows found")
        return
    log(f"targets: {len(targets)} good_ids")

    report = analyze_targets(targets, args.period, args.limit or None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    log(f"report: {OUT}")
    log(
        "summary: null_rows=%d fillable=%d failed=%d"
        % (report["total_null_rows"], report["total_fillable_rows"], report["failed_goods"])
    )

    if args.apply:
        result = apply_backfill(targets, args.period, args.limit or None)
        report["apply"] = result
        with OUT.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        log(f"applied: {result['updated_rows']} rows updated")


if __name__ == "__main__":
    main()
