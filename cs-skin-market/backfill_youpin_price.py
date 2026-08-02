"""Backfill price_history with youpin898 180-day real trade prices (P0 sample expansion).

Why: csQAQ chart only exposes ~90 days (item history starts 2026-04-21). Youpin
trend API day=180 returns 181 days of real trade samples (2026-02-03+) at ~2-4
rows/day (price samples, NOT full volume). We backfill ONLY missing dates so the
existing 2026-04-21+ csqaq series stays untouched (single-variable experiment):
new signals come from the wider window, existing signals are re-evaluated under a
true 90-day valuation window.

Calibration: csqaq close vs youpin close differ by ~3-5% on average (different
platforms/close definition). We compute k = median(csqaq/youpin) over overlapping
dates and backfill price = youpin_close * k, so the 04-21 boundary stays smooth
and the extended history is on the same level as csqaq.

Usage:
  python backfill_youpin_price.py --limit 5     # smoke test
  python backfill_youpin_price.py                # all items with history
  python backfill_youpin_price.py --dry-run      # report only, no writes
"""
import sys, json, asyncio, argparse, statistics
from pathlib import Path
sys.path.insert(0, ".")
import httpx
from pipeline import db
from pipeline.collector_csqaq import fetch_item_detail
from pipeline.collector_youpin import _api_headers

YUPIN_URL = "https://pc-api.youpin898.com/api/youpin/price/trend/data"


def load_targets(limit=None, new_only=False):
    conn = db.get_conn()
    sql = """SELECT i.id, i.name, i.good_id, i.yyyp_id FROM items i
             WHERE i.good_id > 0 AND EXISTS (SELECT 1 FROM price_history p WHERE p.item_id = i.id)"""
    if new_only:
        sql += """ AND (SELECT MIN(p.date) FROM price_history p WHERE p.item_id = i.id) >= '2026-05-01'"""
    sql += " ORDER BY i.id"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return rows[:limit] if limit else rows


async def pull_youpin(template_id):
    headers = _api_headers()
    if not headers:
        return None, "no auth headers"
    body = {"filterTemplateTypeNames": [], "templateId": str(template_id), "orderType": "1",
            "day": "180", "templateTypeName": "", "customizeDay": False}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(YUPIN_URL, json=body, headers=headers)
            payload = resp.json()
    except Exception as e:
        return None, f"http err {e}"
    if payload.get("code") != 0:
        return None, f"code={payload.get('code')} {payload.get('msg')}"
    rows = (payload.get("data") or {}).get("tradeDataList") or []
    per_day = {}
    for r in rows:
        d = str(r.get("localDate") or "")
        t = int(r.get("time") or 0)
        p = float(r.get("price") or 0)
        if d and p > 0 and (d not in per_day or t > per_day[d][0]):
            per_day[d] = (t, p)
    return per_day, None


async def backfill_one(item_id, name, good_id, dry_run=False, yyyp_id=""):
    yyyp = yyyp_id
    if not yyyp:
        det = await fetch_item_detail(good_id)
        yyyp = getattr(det, "yyyp_id", "") if det else ""
    if not yyyp:
        return {"name": name, "status": "skip", "reason": "no yyyp_id"}
    yp, err = pull_err = await pull_youpin(yyyp)
    if yp is None:
        return {"name": name, "status": "skip", "reason": err}
    conn = db.get_conn()
    try:
        hist = conn.execute(
            "SELECT date, price_rmb FROM price_history WHERE item_id=? ORDER BY date", (item_id,)
        ).fetchall()
        cq = {h["date"]: h["price_rmb"] for h in hist}
        overlap = sorted(set(cq) & set(yp))
        if not overlap:
            return {"name": name, "status": "skip", "reason": "no overlap for calibration"}
        ratios = [cq[d] / yp[d][1] for d in overlap if yp[d][1] > 0]
        k = statistics.median(ratios)
        # Quality gate: youpin template must be the same item (calibration factor near 1).
        if k < 0.85 or k > 1.15:
            return {"name": name, "status": "skip",
                    "reason": f"calibration k={k:.4f} out of [0.85,1.15] (template mismatch)"}
        backfill_dates = sorted(set(yp) - set(cq))
        written = 0
        boundary_jump = None
        if not dry_run:
            for d in backfill_dates:
                price = round(yp[d][1] * k, 2)
                conn.execute(
                    "INSERT OR REPLACE INTO price_history (item_id, date, price_rmb, volume_day, volume_total, in_sale_count) "
                    "VALUES (?,?,?,0,0,0)",
                    (item_id, d, price),
                )
                written += 1
            conn.commit()
        # boundary jump check: last backfilled date vs first existing date
        if backfill_dates:
            last_bf = backfill_dates[-1]
            first_ex = overlap[0]
            p_bf = round(yp[last_bf][1] * k, 2)
            p_ex = cq[first_ex]
            boundary_jump = round((p_ex / p_bf - 1) * 100, 2) if p_bf else None
        return {"name": name, "good": good_id, "yyyp": yyyp, "csqaq_days": len(cq),
                "youpin_days": len(yp), "overlap": len(overlap), "k": round(k, 4),
                "backfilled": len(backfill_dates), "range": f"{backfill_dates[0] if backfill_dates else '-'}~{backfill_dates[-1] if backfill_dates else '-'}",
                "boundary_jump_pct": boundary_jump, "status": "ok" if not dry_run else "dry"}
    finally:
        conn.close()


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--new-only", action="store_true", help="only items whose history starts on/after 2026-05-01")
    args = p.parse_args()
    targets = load_targets(args.limit or None, new_only=args.new_only)
    print(f"targets: {len(targets)}")
    results = []
    ok = skip = 0
    for i, (item_id, name, good_id, yyyp_id) in enumerate(targets, 1):
        r = await backfill_one(item_id, name, good_id, args.dry_run, yyyp_id)
        results.append(r)
        if r["status"] in ("ok", "dry"):
            ok += 1
        else:
            skip += 1
        print(f"[{i}/{len(targets)}] {name[:34]:36s} {r['status']:6s} " +
              (f"bf={r.get('backfilled')}d {r.get('range')} k={r.get('k')} jump={r.get('boundary_jump_pct')}%" if r["status"] in ("ok", "dry") else f"({r.get('reason')})"))
    summary = {"dry_run": args.dry_run, "ok": ok, "skip": skip, "items": results}
    out = Path("data/backfill_youpin_report.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nok={ok} skip={skip} report: {out}")


if __name__ == "__main__":
    asyncio.run(main())
