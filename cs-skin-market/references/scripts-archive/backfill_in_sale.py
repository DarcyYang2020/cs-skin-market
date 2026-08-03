"""Backfill price_history.in_sale_count from csQAQ 90-day chart (in-sale history).

csQAQ goods chart returns ~90d of num_data (???). The engine collects it at
analysis time but never persisted it; this one-off script backfills history so
the supply/crowding factor can be backtested offline.

Usage:
  python backfill_in_sale.py            # backfill all items with good_id
  python backfill_in_sale.py --limit 5  # first N items (smoke test)
"""
import sys, time, asyncio, argparse
sys.path.insert(0, ".")
from pipeline import db
from pipeline.collector_csqaq import fetch_kline_90d


def load_targets(limit=None):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT i.id, i.name, i.good_id FROM items i
           WHERE i.good_id IS NOT NULL AND i.good_id > 0
           ORDER BY i.id"""
    ).fetchall()
    conn.close()
    return rows[:limit] if limit else rows


async def backfill_one(item_id, name, good_id):
    ohlc, _ = await fetch_kline_90d(good_id)
    if not ohlc:
        return 0, "empty chart"
    conn = db.get_conn()
    try:
        updated = 0
        for bar in ohlc:
            if not bar.date or not bar.in_sale_count:
                continue
            cur = conn.execute(
                "UPDATE price_history SET in_sale_count=? WHERE item_id=? AND date=?",
                (int(bar.in_sale_count), item_id, bar.date),
            )
            updated += cur.rowcount
        conn.commit()
        return updated, f"{len(ohlc)}d"
    finally:
        conn.close()


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()
    targets = load_targets(args.limit or None)
    print(f"targets: {len(targets)}")
    ok = fail = 0
    for i, (item_id, name, good_id) in enumerate(targets, 1):
        try:
            n, note = await backfill_one(item_id, name, good_id)
            ok += 1
            print(f"[{i}/{len(targets)}] {name[:36]:38s} good={good_id:6d} updated={n:4d} ({note})")
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(targets)}] {name[:36]:38s} FAIL: {e}")
        time.sleep(1.5)
    print(f"done: ok={ok} fail={fail}")


if __name__ == "__main__":
    asyncio.run(main())
