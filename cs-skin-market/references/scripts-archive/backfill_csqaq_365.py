# -*- coding: utf-8 -*-
"""Backfill price_history pre-2026-02-03 using csQAQ chart API period=365.

Why: price_history starts 2026-02-03 (youpin 180d limit + csqaq 90d chart).
The csQAQ info/chart API accepts period=365 and returns DAILY bars back to
~2025-08-04 (price + in_sale_count, no volume). This unlocks the pre-1/23
non-panic small-bull window (2025-11 ~ 2026-01) for offline replay.

Calibration: k = median(existing.price / csqaq365.price) over overlapping
dates (2026-02-03+). Backfilled price = csqaq365.price * k, so the boundary
stays smooth. Only dates strictly BEFORE 2026-02-03 are inserted; existing
rows are never modified (single-variable experiment).

Usage:
  python backfill_csqaq_365.py --limit 3        # smoke
  python backfill_csqaq_365.py --dry-run        # report only
  python backfill_csqaq_365.py                  # full backfill
  python backfill_csqaq_365.py --force          # refetch items already extended
"""
import sys, os, json, asyncio, argparse, sqlite3, datetime, statistics, time
from collections import defaultdict
sys.path.insert(0, ".")
from pipeline import db
from pipeline.collector_csqaq import _get_browser, _wait_chart, CSQAQ_WEB

TZ_BJ = datetime.timezone(datetime.timedelta(hours=8))
CUTOFF = "2026-02-03"
REPORT = Path = None


def load_targets(limit=None, force=False):
    conn = db.get_conn()
    sql = """SELECT i.id, i.name, i.good_id FROM items i
             WHERE i.good_id > 0 AND EXISTS (SELECT 1 FROM price_history p WHERE p.item_id = i.id)"""
    if not force:
        sql += """ AND (SELECT MIN(p.date) FROM price_history p WHERE p.item_id = i.id) >= '2026-02-03'"""
    sql += " ORDER BY i.id"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return rows[:limit] if limit else rows


async def fetch_chart_365(browser, good_id, tries=4):
    """Navigate goods page with period=365 interception; return (series, err)."""
    last_err = None
    for attempt in range(tries):
        page = await browser.new_page()
        captured = {"chart": None}
        async def on_response(response):
            try:
                if "info/chart" in response.url and response.ok:
                    captured["chart"] = await response.text()
            except Exception:
                pass
        async def modify_chart(route, request):
            if "info/chart" in request.url:
                try:
                    body = json.loads(request.post_data)
                    body["period"] = "365"
                    body["key"] = "sell_price"
                    body["platform"] = 2
                    await route.continue_(post_data=json.dumps(body))
                except Exception:
                    await route.continue_()
            else:
                await route.continue_()
        page.on("response", on_response)
        await page.route("**/info/chart**", modify_chart)
        try:
            await page.goto(f"{CSQAQ_WEB}/goods/{good_id}", wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            last_err = f"goto {e}"
        try:
            await _wait_chart(page, captured, timeout=10)
        except Exception:
            pass
        await page.close()
        if captured["chart"]:
            try:
                d = json.loads(captured["chart"])
                if d.get("code") == 200 and d.get("data"):
                    cd = d["data"]
                    series = {}
                    for ts, p, n in zip(cd.get("timestamp", []), cd.get("main_data", []), cd.get("num_data", [])):
                        try:
                            price = float(p)
                        except (TypeError, ValueError):
                            continue
                        if price <= 0 or not ts:
                            continue
                        dt = datetime.datetime.fromtimestamp(int(ts) / 1000, TZ_BJ).strftime("%Y-%m-%d")
                        ins = int(float(n)) if n not in (None, "") else 0
                        series[dt] = (round(price, 2), ins)
                    if series:
                        return series, None
                last_err = f"code={d.get('code')}"
            except Exception as e:
                last_err = f"parse {e}"
        else:
            last_err = "empty chart"
        if attempt < tries - 1:
            await asyncio.sleep(2 + attempt)
    return None, last_err


def backfill_one(item_id, name, good_id, series, dry_run=False):
    conn = db.get_conn()
    try:
        hist = conn.execute(
            "SELECT date, price_rmb FROM price_history WHERE item_id=? ORDER BY date", (item_id,)
        ).fetchall()
        cq = {h["date"]: h["price_rmb"] for h in hist}
        overlap = sorted(set(cq) & set(series))
        if not overlap:
            return {"name": name, "status": "skip", "reason": "no overlap for calibration"}
        ratios = [cq[d] / series[d][0] for d in overlap if series[d][0] > 0]
        k = statistics.median(ratios)
        if k < 0.85 or k > 1.15:
            return {"name": name, "status": "skip", "reason": f"calibration k={k:.4f} out of [0.85,1.15]"}
        pre = sorted(d for d in series if d < CUTOFF)
        written = 0
        boundary_jump = None
        if not dry_run:
            for d in pre:
                price = round(series[d][0] * k, 2)
                conn.execute(
                    "INSERT OR REPLACE INTO price_history (item_id, date, price_rmb, volume_day, volume_total, in_sale_count) "
                    "VALUES (?,?,?,0,0,?)",
                    (item_id, d, price, series[d][1]),
                )
                written += 1
            conn.commit()
        if pre and overlap:
            last_bf = pre[-1]
            p_bf = round(series[last_bf][0] * k, 2)
            p_ex = cq[overlap[0]]
            boundary_jump = round((p_ex / p_bf - 1) * 100, 2) if p_bf else None
        return {"name": name, "good": good_id, "csqaq_days": len(series), "overlap": len(overlap),
                "k": round(k, 4), "backfilled": len(pre),
                "range": f"{pre[0] if pre else '-'}~{pre[-1] if pre else '-'}",
                "boundary_jump_pct": boundary_jump, "status": "ok" if not dry_run else "dry"}
    finally:
        conn.close()


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--skip", type=int, default=0, help="skip first N targets (resume)")
    p.add_argument("--retry-errors", action="store_true", help="only re-fetch items that errored in the last report")
    args = p.parse_args()
    if args.retry_errors:
        rep_path = os.path.join("data", "backfill_csqaq365_report.json")
        rep = json.load(open(rep_path, encoding="utf-8"))
        bad_goods = [it["good"] for it in rep.get("items", []) if it.get("status") == "error"]
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT id, name, good_id FROM items WHERE good_id IN (%s) ORDER BY id"
            % ",".join("?" * len(bad_goods)), bad_goods).fetchall()
        conn.close()
        targets = rows
        print(f"retry-errors: {len(targets)} items", flush=True)
    else:
        targets = load_targets(args.limit or None, force=args.force)
    print(f"targets: {len(targets)}", flush=True)
    pw, browser = await _get_browser()
    results = []
    ok = skip = err = 0
    try:
        for i, (item_id, name, good_id) in enumerate(targets, 1):
            if i <= args.skip:
                continue
            series, serr = await fetch_chart_365(browser, good_id)
            if series is None:
                r = {"name": name, "good": good_id, "status": "error", "reason": serr}
                err += 1
            else:
                r = backfill_one(item_id, name, good_id, series, args.dry_run)
                if r["status"] in ("ok", "dry"):
                    ok += 1
                else:
                    skip += 1
            results.append(r)
            line = f"[{i}/{len(targets)}] {name[:34]:36s} {r['status']:6s} " + (
                f"bf={r.get('backfilled')}d {r.get('range')} k={r.get('k')} jump={r.get('boundary_jump_pct')}%"
                if r["status"] in ("ok", "dry") else f"({r.get('reason')})")
            print(line, flush=True)
            # incremental report
            Path = os.path.join("data", "backfill_csqaq365_report.json")
            tmp = {"dry_run": args.dry_run, "processed": i, "ok": ok, "skip": skip, "error": err, "items": results}
            with open(Path, "w", encoding="utf-8") as f:
                json.dump(tmp, f, ensure_ascii=False, indent=1)
    finally:
        try:
            await browser.close()
        except Exception:
            pass
    print(f"\nok={ok} skip={skip} error={err}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
