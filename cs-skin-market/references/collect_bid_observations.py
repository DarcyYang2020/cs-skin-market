import argparse
import asyncio
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from pipeline import collector_csqaq, db

# Chinese strings kept as escapes so this script is pure ASCII on disk.
_EXCL_LOW_SURVIVE = "\u5b58\u4e16\u91cf\u8fc7\u4f4e"
_EXCL_POOL_PRUNE = "\u6d3b\u8dc3\u6c60\u6dd8\u6c70"


SUPPLY_RATIO_MAX = 0.85
PRICE_STABLE_CHG7_CAP = 3.0


def _supply_metrics(conn, item_id):
    rows = conn.execute(
        "SELECT date, price_rmb, in_sale_count FROM price_history WHERE item_id = ? ORDER BY date",
        (item_id,),
    ).fetchall()
    if not rows:
        return None
    vals30 = [(r["in_sale_count"] or 0) for r in rows[-30:]]
    vals7 = [(r["in_sale_count"] or 0) for r in rows[-7:]]
    s30 = sum(vals30) / len(vals30) if vals30 else 0.0
    s7 = sum(vals7) / len(vals7) if vals7 else 0.0
    ratio = (s7 / s30) if s30 > 0 else None
    chg7 = None
    if len(rows) >= 2:
        last_close = rows[-1]["price_rmb"] or 0
        prior_close = rows[max(0, len(rows) - 8)]["price_rmb"] or 0
        if prior_close > 0 and last_close > 0:
            chg7 = (last_close / prior_close - 1) * 100
    supply_contract = s30 > 0 and s7 > 0 and ratio is not None and ratio <= SUPPLY_RATIO_MAX
    price_stable = chg7 is not None and abs(chg7) <= PRICE_STABLE_CHG7_CAP
    return {
        "s30": round(s30, 2),
        "s7": round(s7, 2),
        "ratio": round(ratio, 4) if ratio is not None else None,
        "chg7": round(chg7, 2) if chg7 is not None else None,
        "supply_contract": supply_contract,
        "price_stable": price_stable,
    }


def candidate_rows(limit, mode):
    conn = db.get_conn()
    base_sql = """
        SELECT id, good_id, name FROM items
        WHERE good_id > 0 AND (
            in_watchlist = 1 OR holding = 1 OR notes IS NULL OR (
                notes NOT LIKE ? AND notes NOT LIKE ?
            )
        )
    """
    like_low = f"%{_EXCL_LOW_SURVIVE}%"
    like_prune = f"%{_EXCL_POOL_PRUNE}%"
    if mode == "supply_contract":
        all_rows = conn.execute(base_sql, (like_low, like_prune)).fetchall()
        candidates = []
        for row in all_rows:
            m = _supply_metrics(conn, row["id"])
            if m and m["supply_contract"] and m["price_stable"]:
                candidates.append((m["ratio"], m["chg7"], row))
        candidates.sort(key=lambda x: (x[0] if x[0] is not None else 999.0, x[1] if x[1] is not None else 999.0, x[2]["id"]))
        rows = [r for _, _, r in candidates[:limit]]
    else:
        rows = conn.execute(
            base_sql + " ORDER BY (holding = 1) DESC, in_watchlist DESC, id LIMIT ?",
            (like_low, like_prune, limit),
        ).fetchall()
    conn.close()
    return rows


async def collect_bids(rows, today, source):
    conn = db.get_conn()
    ok = 0
    try:
        for row in rows:
            good_id = row["good_id"]
            name = row["name"] or ""
            try:
                item = await collector_csqaq.fetch_item_detail(good_id)
            except Exception as exc:
                print(f"[skip] {name} (gid={good_id}): {type(exc).__name__}: {exc}")
                continue
            if item is None or not getattr(item, "order_book", None):
                print(f"[skip] {name} (gid={good_id}): no order_book captured")
                continue
            ob = item.order_book
            # Engine-consistent context: chart close/in_sale_count are the same caliber
            # as price_history. Keep site anchor (item.price_rmb) only in the log line.
            kline = getattr(item, "kline_90d", []) or []
            chart_price = float(kline[-1].close or 0) if kline else 0.0
            last_bar = next((_b for _b in reversed(kline) if getattr(_b, "in_sale_count", 0) or 0), None)
            engine_price = chart_price or float(item.price_rmb or 0)
            engine_ins = int(getattr(last_bar, "in_sale_count", 0) or item.in_sale_count or 0)

            highest_buy = ob.get("highest_buy")
            bid7 = ob.get("bid_7d_chg")
            bid30 = ob.get("bid_30d_chg")
            spread = ob.get("spread_pct")
            spread_avg = ob.get("spread_avg")
            # Critical quality guard: unusable bid/spread samples are never written.
            if highest_buy is None or highest_buy <= 0:
                print(f"[guard] {name} (gid={good_id}): highest_buy missing/zero, skip")
                continue
            if bid7 is None:
                print(f"[guard] {name} (gid={good_id}): bid_7d_chg missing, skip")
                continue
            if spread is None or spread <= 0:
                print(f"[guard] {name} (gid={good_id}): spread_pct missing/zero, skip")
                continue

            notes = []
            if bid30 is not None and abs(bid30) >= 40:
                notes.append("bid30_extreme")
            if spread_avg == 0:
                notes.append("spread_avg_zero")
            db_ctx = conn.execute(
                "SELECT price_rmb, in_sale_count FROM price_history WHERE item_id = ? ORDER BY date DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if db_ctx is not None:
                db_price, db_ins = db_ctx["price_rmb"], db_ctx["in_sale_count"]
                price_mismatch = db_price and engine_price and abs(engine_price / db_price - 1) > 0.20
                ins_mismatch = db_ins and engine_ins and abs(engine_ins / db_ins - 1) > 0.30
                if price_mismatch or ins_mismatch:
                    notes.append("chart_db_mismatch")
            quality_note = ",".join(notes) if notes else "ok"

            vals = (
                today,
                row["id"],
                good_id,
                name,
                engine_price,
                engine_ins,
                highest_buy,
                bid7,
                bid30,
                spread,
                spread_avg,
                quality_note,
                source,
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO bid_observations (
                    date, item_id, good_id, item_name, price_rmb, in_sale_count,
                    bid_highest, bid_7d_chg, bid_30d_chg, spread_pct, spread_avg,
                    quality_note, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                vals,
            )
            conn.commit()
            ok += 1
            print(f"[ok] {name} (gid={good_id}) anchor={item.price_rmb} engine_price={engine_price} engine_ins={engine_ins} spread={spread} bid7={bid7} quality={quality_note}")
    finally:
        conn.close()
        try:
            if collector_csqaq._browser_inst is not None:
                await collector_csqaq._browser_inst.close()
        except Exception:
            pass
        try:
            if collector_csqaq._browser_pw is not None:
                await collector_csqaq._browser_pw.stop()
        except Exception:
            pass
        collector_csqaq._browser_inst = None
        collector_csqaq._browser_pw = None
    return ok


def main():
    parser = argparse.ArgumentParser(description="Manual bid observation accumulator (read-only engine impact)")
    parser.add_argument("--limit", type=int, default=8, help="max items to probe (default 8)")
    parser.add_argument("--today", default=db._today(), help="observation date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="only list candidates, no network")
    parser.add_argument("--source", default="manual", help="observation source label (default manual)")
    parser.add_argument("--mode", choices=("priority", "supply_contract"), default="priority",
                        help="candidate selection: priority = holding/watchlist first; supply_contract = supply shrink + price stable")
    args = parser.parse_args()

    rows = candidate_rows(args.limit, args.mode)
    print(f"candidates={len(rows)} mode={args.mode}")
    for row in rows:
        print(f"  id={row['id']} gid={row['good_id']} name={row['name']}")
    if args.dry_run:
        print("dry-run: no network calls")
        return
    ok = asyncio.run(collect_bids(rows, args.today, args.source))
    print(f"stored={ok}/{len(rows)} date={args.today} source={args.source}")


if __name__ == "__main__":
    main()
