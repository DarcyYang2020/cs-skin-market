# -*- coding: utf-8 -*-
"""P0 数据储备采集：活跃池基本面 + 悠悠求购历史（v58，2026-08-13）。

只写研究层新表：
  - item_fundamental_snapshot   info/good 直连字段子集
  - bid_history                 info/chart buy_price/buy_num 按日聚合

默认 dry-run，不写库；`--apply` 才落库。可后续接入 run_daily_collect.py 低峰任务。
用法:
  python collect_data_reserve_p0.py                # dry-run 全量
  python collect_data_reserve_p0.py --limit 5      # dry-run 前 5 品
  python collect_data_reserve_p0.py --apply        # 正式落库全量
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

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "data_reserve_p0.log")
ACTIVE_SQL = """
    SELECT id, good_id, name
    FROM items
    WHERE good_id > 0
      AND (in_watchlist=1 OR holding=1 OR notes IS NULL
           OR (notes NOT LIKE '%存世量过低%'
               AND notes NOT LIKE '%活跃池淘汰%'
               AND notes NOT LIKE '%贴纸模块停采%'))
    ORDER BY id
"""


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


def _chart_body(good_id: int, key: str):
    return {"good_id": str(good_id), "key": key, "platform": 2,
            "period": "90", "style": "all_style"}


def fetch_info_good(good_id: int):
    resp = _direct("GET", f"/info/good?id={good_id}")
    if resp.get("code") != 200 or not isinstance(resp.get("data"), dict):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def fetch_chart(good_id: int, key: str):
    resp = _direct("POST", "/info/chart", _chart_body(good_id, key))
    if resp.get("code") != 200 or not isinstance(resp.get("data"), dict):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def parse_fundamental(item_id: int, good_id: int, item_name: str, data: dict) -> dict:
    gi = data.get("goods_info") or {}
    modeled = {
        "id", "name", "buff_sell_price", "buff_sell_num", "buff_buy_price", "buff_buy_num",
        "yyyp_sell_price", "yyyp_sell_num", "yyyp_buy_price", "yyyp_buy_num",
        "c5_sell_price", "c5_sell_num", "steam_sell_price", "steam_buy_price",
        "turnover_number", "turnover_avg_price",
        "sell_price_rate_1", "sell_price_rate_7", "sell_price_rate_15", "sell_price_rate_30",
        "sell_price_rate_90", "sell_price_rate_180", "sell_price_rate_365",
        "rank_num", "statistic", "rarity_localized_name", "type_localized_name",
        "exterior_localized_name", "quality_localized_name", "min_float", "max_float",
    }
    extra = {k: v for k, v in gi.items() if k not in modeled}
    return {
        "item_id": item_id,
        "good_id": good_id,
        "item_name": item_name,
        "source": "csqaq_direct",
        "platform": 2,
        "yyyp_sell_price": _num(gi.get("yyyp_sell_price")),
        "yyyp_sell_num": _int(gi.get("yyyp_sell_num")),
        "yyyp_buy_price": _num(gi.get("yyyp_buy_price")),
        "yyyp_buy_num": _int(gi.get("yyyp_buy_num")),
        "buff_sell_price": _num(gi.get("buff_sell_price")),
        "buff_sell_num": _int(gi.get("buff_sell_num")),
        "buff_buy_price": _num(gi.get("buff_buy_price")),
        "buff_buy_num": _int(gi.get("buff_buy_num")),
        "c5_sell_price": _num(gi.get("c5_sell_price")),
        "c5_sell_num": _int(gi.get("c5_sell_num")),
        "steam_sell_price": _num(gi.get("steam_sell_price")),
        "steam_buy_price": _num(gi.get("steam_buy_price")),
        "turnover_number": _int(gi.get("turnover_number")),
        "turnover_avg_price": _num(gi.get("turnover_avg_price")),
        "sell_price_rate_1": _num(gi.get("sell_price_rate_1")),
        "sell_price_rate_7": _num(gi.get("sell_price_rate_7")),
        "sell_price_rate_15": _num(gi.get("sell_price_rate_15")),
        "sell_price_rate_30": _num(gi.get("sell_price_rate_30")),
        "sell_price_rate_90": _num(gi.get("sell_price_rate_90")),
        "sell_price_rate_180": _num(gi.get("sell_price_rate_180")),
        "sell_price_rate_365": _num(gi.get("sell_price_rate_365")),
        "rank_num": _int(gi.get("rank_num")),
        "statistic": _int(gi.get("statistic")),
        "rarity_localized_name": gi.get("rarity_localized_name"),
        "type_localized_name": gi.get("type_localized_name"),
        "exterior_localized_name": gi.get("exterior_localized_name"),
        "quality_localized_name": gi.get("quality_localized_name"),
        "min_float": _num(gi.get("min_float")),
        "max_float": _num(gi.get("max_float")),
        "extra_json": json.dumps(extra, ensure_ascii=False) if extra else None,
    }


def _series_by_date(data: dict):
    ts_arr = data.get("timestamp") or []
    val_arr = data.get("main_data") or []
    out = {}
    for i in range(min(len(ts_arr), len(val_arr))):
        try:
            ts = int(ts_arr[i]) // 1000 if ts_arr[i] else 0
            val = float(val_arr[i])
        except (TypeError, ValueError):
            continue
        if ts <= 0 or val <= 0:
            continue
        day = datetime.fromtimestamp(ts, tz=TZ_BJ).strftime("%Y-%m-%d")
        out.setdefault(day, []).append(val)
    return out


def _stats(vals):
    if not vals:
        return (None, None, None, None)
    vals = [float(v) for v in vals]
    return (vals[-1], min(vals), max(vals), round(sum(vals) / len(vals), 4))


def aggregate_bid(item_id: int, good_id: int, item_name: str, buy_price_data: dict, buy_num_data: dict):
    price_by_day = _series_by_date(buy_price_data)
    num_by_day = _series_by_date(buy_num_data)
    days = sorted(set(price_by_day) | set(num_by_day))
    rows = []
    for day in days:
        pv = price_by_day.get(day) or []
        nv = num_by_day.get(day) or []
        p_last, p_min, p_max, p_mean = _stats(pv)
        n_last, n_min, n_max, n_mean = _stats(nv)
        rows.append({
            "date": day,
            "item_id": item_id,
            "good_id": good_id,
            "item_name": item_name,
            "source": "csqaq_direct",
            "platform": 2,
            "buy_price_last": p_last,
            "buy_price_min": p_min,
            "buy_price_max": p_max,
            "buy_price_mean": p_mean,
            "buy_num_last": n_last,
            "buy_num_min": n_min,
            "buy_num_max": n_max,
            "buy_num_mean": n_mean,
            "point_count": max(len(pv), len(nv)),
        })
    return rows


def collect_one(conn, item_row, apply: bool, date: str):
    item_id, good_id, name = item_row["id"], item_row["good_id"], item_row["name"]
    info, err = fetch_info_good(good_id)
    if info is None:
        return 0, f"info_good:{err}"
    buy_price, err = fetch_chart(good_id, "buy_price")
    if buy_price is None:
        return 0, f"buy_price:{err}"
    buy_num, err = fetch_chart(good_id, "buy_num")
    if buy_num is None:
        return 0, f"buy_num:{err}"
    fund = parse_fundamental(item_id, good_id, name, info)
    bid_rows = aggregate_bid(item_id, good_id, name, buy_price, buy_num)
    # D2（2026-08-27）：卖侧盘口 lowest_sell=buff_sell_price / sell_count=buff_sell_num 为当前快照，
    # 仅落当日行（历史卖侧只能从现在积累，宜早）；来源 = csQAQ /info/good 已解析 OrderBook sell 侧。
    for _row in bid_rows:
        if _row["date"] == date:
            _row["lowest_sell"] = fund.get("buff_sell_price")
            _row["sell_count"] = fund.get("buff_sell_num")
    if apply:
        db.save_item_fundamental_snapshot(conn, date, fund)
        for row in bid_rows:
            db.save_bid_history(conn, row["date"], row)
        conn.commit()
        # D7（2026-08-27）：订单簿/成交原始值 append-only 落 raw.db（market.db 仍权威；失败不阻断）
        try:
            from pipeline import raw_db
            _rconn = raw_db.get_raw_conn()
            try:
                _ts = datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")
                raw_db.append_raw(_rconn, "raw_order_book", {
                    "ts": _ts, "date": date, "good_id": good_id, "item_name": name,
                    "lowest_sell": fund.get("buff_sell_price"),
                    "highest_buy": fund.get("buff_buy_price"),
                    "sell_count": fund.get("buff_sell_num"),
                    "buy_count": fund.get("buff_buy_num"),
                })
                raw_db.append_raw(_rconn, "raw_trade", {
                    "ts": _ts, "date": date, "good_id": good_id, "item_name": name,
                    "turnover_number": fund.get("turnover_number"),
                    "turnover_avg_price": fund.get("turnover_avg_price"),
                })
                _rconn.commit()
            finally:
                _rconn.close()
        except Exception:
            pass  # raw 落库失败不阻断加工层
    return len(bid_rows), None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write to DB; default is dry-run")
    parser.add_argument("--limit", type=int, default=0, help="limit first N active items, 0 = all")
    parser.add_argument("--retry-date", type=str, default="", help="only retry active items missing a fundamental snapshot on this date")
    args = parser.parse_args()

    conn = db.get_conn()
    if args.retry_date:
        rows = conn.execute(
            ACTIVE_SQL.replace("ORDER BY id", "AND NOT EXISTS (SELECT 1 FROM item_fundamental_snapshot f WHERE f.date=? AND f.good_id=items.good_id) ORDER BY id"),
            (args.retry_date,)
        ).fetchall()
    else:
        rows = conn.execute(ACTIVE_SQL).fetchall()
    if args.limit > 0:
        rows = rows[: args.limit]
    date = datetime.now(TZ_BJ).strftime("%Y-%m-%d")
    mode = "APPLY" if args.apply else "DRY-RUN"
    log(f"P0 start mode={mode} items={len(rows)} date={date}")

    ok = 0
    fail = 0
    bid_rows = 0
    for r in rows:
        try:
            n, err = collect_one(conn, r, args.apply, date)
        except Exception as e:
            fail += 1
            log(f"  [{r['id']}] EXC {type(e).__name__}: {str(e)[:80]}")
            continue
        if err:
            fail += 1
            log(f"  [{r['id']}] FAIL {r['name'][:30]} {err}")
            continue
        ok += 1
        bid_rows += n
        if ok <= 3 or ok % 50 == 0:
            log(f"  [{r['id']}] OK bid_days={n} {r['name'][:30]}")

    conn.close()
    log(f"P0 done mode={mode} ok={ok}/{len(rows)} fail={fail} bid_rows={bid_rows}")
    print(f"RESULT mode={mode} ok={ok}/{len(rows)} fail={fail} bid_rows={bid_rows}")


if __name__ == "__main__":
    main()
