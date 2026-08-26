# -*- coding: utf-8 -*-
"""P1 data-reserve collector: survive history + series snapshot + holder rank (v58, 2026-08-13).

Research-layer only; never writes items/price_history or engine decisions.
Default is dry-run. `--apply` writes DB. `--monitor` enables holder-rank collection
(weekly privacy-minimal Top N, same target table as browser collector).

Usage:
  python collect_data_reserve_p1.py --scope watchlist --limit 5
  python collect_data_reserve_p1.py --apply --scope watchlist
  python collect_data_reserve_p1.py --apply --scope all --monitor --top 20
"""

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import db
from pipeline.collector import _api_call
from pipeline.config import TZ_BJ

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "data_reserve_p1.log")

SCOPE_SQL = {
    "watchlist": """
        SELECT id, good_id, name
        FROM items
        WHERE good_id > 0
          AND (in_watchlist=1 OR holding=1)
        ORDER BY id
    """,
    "active": """
        SELECT id, good_id, name
        FROM items
        WHERE good_id > 0
          AND (notes IS NULL
               OR (notes NOT LIKE '%\u5B58\u4E16\u91CF\u8FC7\u4F4E%'
                   AND notes NOT LIKE '%\u6D3B\u8DC3\u6C60\u6DD8\u6C70%'
                   AND notes NOT LIKE '%\u8D34\u7EB8\u6A21\u5757\u505C\u91C7%'))
        ORDER BY id
    """,
    "all": """
        SELECT id, good_id, name
        FROM items
        WHERE good_id > 0
          AND (in_watchlist=1 OR holding=1 OR notes IS NULL
               OR (notes NOT LIKE '%\u5B58\u4E16\u91CF\u8FC7\u4F4E%'
                   AND notes NOT LIKE '%\u6D3B\u8DC3\u6C60\u6DD8\u6C70%'
                   AND notes NOT LIKE '%\u8D34\u7EB8\u6A21\u5757\u505C\u91C7%'))
        ORDER BY id
    """,
}


def log(msg: str):
    line = f"[{datetime.now(TZ_BJ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _direct(method, path, body=None):
    """csQAQ direct API with 1.5s effective pacing."""
    time.sleep(0.4)
    return _api_call(method, path, body)


def fetch_statistic(good_id: int):
    resp = _direct("GET", f"/info/good/statistic?id={good_id}")
    if resp.get("code") != 200 or not isinstance(resp.get("data"), list):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def fetch_series_list():
    resp = _direct("POST", "/info/get_series_list")
    if resp.get("code") != 200 or not isinstance(resp.get("data"), list):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def fetch_monitor_rank(good_id: int):
    resp = _direct("POST", "/monitor/rank", {"good_id": str(good_id)})
    if resp.get("code") != 200 or not isinstance(resp.get("data"), list):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def parse_statistic_rows(item_id: int, good_id: int, item_name: str, data: list) -> list:
    rows = []
    for r in data or []:
        raw_created = r.get("created_at")
        day = str(raw_created)[:10] if raw_created else ""
        statistic = _int(r.get("statistic"))
        if len(day) != 10 or statistic is None:
            continue
        rows.append({
            "date": day,
            "item_id": item_id,
            "good_id": good_id,
            "item_name": item_name,
            "source": "csqaq_direct",
            "platform": 2,
            "statistic": statistic,
            "source_created_at": raw_created,
        })
    return rows


def parse_series_rows(data: list, date: str) -> list:
    modeled = {
        "id", "key", "name", "amount", "total_value",
        "sell_price_1", "sell_price_7", "sell_price_15", "sell_price_30",
        "sell_price_90", "sell_price_180", "recently_data",
    }
    rows = []
    for item in data or []:
        series_id = _int(item.get("id"))
        series_key = _int(item.get("key"))
        if series_id is None:
            series_id = series_key
        if series_id is None:
            continue
        recently = item.get("recently_data")
        extra = {k: v for k, v in item.items() if k not in modeled}
        rows.append({
            "date": date,
            "series_id": series_id,
            "series_key": series_key,
            "series_name": item.get("name"),
            "source": "csqaq_direct",
            "amount": _num(item.get("amount")),
            "total_value": _num(item.get("total_value")),
            "sell_price_1": _num(item.get("sell_price_1")),
            "sell_price_7": _num(item.get("sell_price_7")),
            "sell_price_15": _num(item.get("sell_price_15")),
            "sell_price_30": _num(item.get("sell_price_30")),
            "sell_price_90": _num(item.get("sell_price_90")),
            "sell_price_180": _num(item.get("sell_price_180")),
            "recently_data_json": json.dumps(recently, ensure_ascii=False) if recently is not None else None,
            "extra_json": json.dumps(extra, ensure_ascii=False) if extra else None,
        })
    return rows


def parse_monitor_rows(data: list, top_n: int) -> list:
    rows = []
    for r in data or []:
        num = _int(r.get("num"))
        if not num or num <= 0:
            continue
        rows.append({
            "steam_name": r.get("steam_name"),
            "steam_id": str(r.get("steam_id") or ""),
            "num": num,
        })
    rows.sort(key=lambda x: x["num"], reverse=True)
    return rows[:top_n]


def collect_survive(conn, r, apply: bool, date: str):
    data, err = fetch_statistic(r["good_id"])
    if data is None:
        return 0, err
    rows = parse_statistic_rows(r["id"], r["good_id"], r["name"], data)
    if apply:
        for row in rows:
            db.save_survive_history(conn, row["date"], row)
        # D7（2026-08-27）：存世量原始值 append-only 落 raw.db（market.db 仍权威；失败不阻断）
        try:
            from pipeline import raw_db
            _rconn = raw_db.get_raw_conn()
            try:
                for row in rows:
                    raw_db.append_raw(_rconn, "raw_survive", {
                        "ts": datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S"),
                        "date": row["date"], "good_id": r["good_id"], "item_name": r["name"],
                        "statistic": row.get("statistic"),
                    })
                _rconn.commit()
            finally:
                _rconn.close()
        except Exception:
            pass  # raw 落库失败不阻断加工层
    return len(rows), None


def collect_monitor(conn, r, apply: bool, date: str, top_n: int):
    data, err = fetch_monitor_rank(r["good_id"])
    if data is None:
        return 0, err
    rows = parse_monitor_rows(data, top_n)
    if apply and rows:
        db.save_monitor_rank_snapshot(conn, date, r["id"], r["good_id"], rows)
    return len(rows), None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write to DB; default is dry-run")
    parser.add_argument("--limit", type=int, default=0, help="limit first N scoped items, 0 = all")
    parser.add_argument("--scope", choices=("watchlist", "active", "all"), default="watchlist")
    parser.add_argument("--no-survive", action="store_true", help="skip survive_history collection")
    parser.add_argument("--no-series", action="store_true", help="skip series_snapshot collection")
    parser.add_argument("--monitor", action="store_true", help="also collect monitor/rank Top N")
    parser.add_argument("--top", type=int, default=20, help="monitor/rank Top N, default 20")
    args = parser.parse_args()

    conn = db.get_conn()
    rows = conn.execute(SCOPE_SQL[args.scope]).fetchall()
    if args.limit > 0:
        rows = rows[: args.limit]
    date = datetime.now(TZ_BJ).strftime("%Y-%m-%d")
    mode = "APPLY" if args.apply else "DRY-RUN"
    log(f"P1 start mode={mode} scope={args.scope} items={len(rows)} date={date} "
        f"survive={not args.no_survive} series={not args.no_series} monitor={args.monitor}")

    stats = {"survive": {"ok": 0, "empty": 0, "fail": 0, "rows": 0},
             "series": {"ok": 0, "fail": 0, "rows": 0},
             "monitor": {"ok": 0, "fail": 0, "rows": 0}}

    if not args.no_series:
        try:
            data, err = fetch_series_list()
            if data is None:
                stats["series"]["fail"] += 1
                log(f"  [series] FAIL {err}")
            else:
                series_rows = parse_series_rows(data, date)
                if args.apply:
                    for row in series_rows:
                        db.save_series_snapshot(conn, row["date"], row)
                stats["series"]["ok"] += 1
                stats["series"]["rows"] += len(series_rows)
                log(f"  [series] OK rows={len(series_rows)}")
        except Exception as e:
            stats["series"]["fail"] += 1
            log(f"  [series] EXC {type(e).__name__}: {str(e)[:80]}")

    for idx, r in enumerate(rows, 1):
        if not args.no_survive:
            try:
                n, err = collect_survive(conn, r, args.apply, date)
            except Exception as e:
                stats["survive"]["fail"] += 1
                log(f"  [{r['id']}] survive EXC {type(e).__name__}: {str(e)[:80]}")
            else:
                if err:
                    stats["survive"]["fail"] += 1
                    log(f"  [{r['id']}] survive FAIL {r['name'][:30]} {err}")
                elif n == 0:
                    stats["survive"]["empty"] += 1
                    log(f"  [{r['id']}] survive EMPTY {r['name'][:30]}")
                else:
                    stats["survive"]["ok"] += 1
                    stats["survive"]["rows"] += n
                    if stats["survive"]["ok"] <= 3 or stats["survive"]["ok"] % 50 == 0:
                        log(f"  [{r['id']}] survive OK days={n} {r['name'][:30]}")

        if args.monitor:
            try:
                n, err = collect_monitor(conn, r, args.apply, date, args.top)
            except Exception as e:
                stats["monitor"]["fail"] += 1
                log(f"  [{r['id']}] monitor EXC {type(e).__name__}: {str(e)[:80]}")
            else:
                if err:
                    stats["monitor"]["fail"] += 1
                    log(f"  [{r['id']}] monitor FAIL {r['name'][:30]} {err}")
                else:
                    stats["monitor"]["ok"] += 1
                    stats["monitor"]["rows"] += n
                    if stats["monitor"]["ok"] <= 3 or stats["monitor"]["ok"] % 50 == 0:
                        log(f"  [{r['id']}] monitor OK rows={n} {r['name'][:30]}")

        if idx % 25 == 0:
            log(f"  progress {idx}/{len(rows)}")

    if args.apply:
        conn.commit()
    conn.close()

    summary = (f"P1 done mode={mode} scope={args.scope} items={len(rows)} "
               f"survive={stats['survive']['ok']}/{len(rows)} empty={stats['survive']['empty']} rows={stats['survive']['rows']} "
               f"series_rows={stats['series']['rows']} "
               f"monitor={stats['monitor']['ok']}/{len(rows)} rows={stats['monitor']['rows']}")
    log(summary)
    print(f"RESULT {summary}")


if __name__ == "__main__":
    main()
