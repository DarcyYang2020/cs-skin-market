# -*- coding: utf-8 -*-
"""W7-2 steamdt 蓄水池采集（2026-08-27，决策 EY+EZ，契约 references/w7-2-collect-contract-2026-08-27.md）。

steamdt.com 市场级数据（独立第三方站，GET 零鉴权，urllib 即可）每日 1 次落 raw.db：
  - raw_steamdt_market   每日 1 行（大盘指数/成交/新增/在线，summary+players 端点）
  - raw_steamdt_blocks   每日多行（hot/level1/level2/level3 板块指数，item-block 端点）

契约要点：
  - 默认 APPLY 落库；`--dry-run` 仅解析打印不写库（与 collect_data_reserve_p0 默认 dry-run 相反，本契约默认 APPLY）。
  - 幂等：raw.db 表 UNIQUE(date) / UNIQUE(date,level,block_name)（见 pipeline/raw_db.py _SCHEMA，INSERT 冲突自然忽略）。
  - append-only：仅经 pipeline.raw_db.append_raw 写入（白名单表 + 无 UPDATE/DELETE 路径，D7 同构）。
  - stdout 末行 = `RESULT mode=... market=1 blocks=N`（④侧取末行记 log）。
  - 退出码：0=成功 / 非 0=失败（④侧 subprocess 记录 returncode，失败不中断主采集）。
  - 红线：不进引擎、不 bump ENGINE_VERSION、不碰 market.db；数据仅公开市场级（指数/成交/在线/板块）。

用法: python collect_steamdt_reserve.py [--dry-run]
"""
import argparse
import io
import json
import os
import sys
import urllib.request
from datetime import datetime

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from pipeline.config import TZ_BJ  # noqa: E402
from pipeline import raw_db  # noqa: E402

SUMMARY_URL = "https://www.steamdt.com/api/index/statistics/v1/summary"
PLAYERS_URL = "https://www.steamdt.com/api/index/players/v1/statistics"
BLOCKS_URL = "https://www.steamdt.com/api/index/item-block/v1/summary"
TIMEOUT = 10  # 契约：单端点 GET <10s


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def _now_ts():
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")


def fetch_summary():
    """summary 端点 → raw_steamdt_market 行字段（大盘/成交/新增/在线之外，online 来自 players）。"""
    d = _get_json(SUMMARY_URL)
    if not d.get("success") or not isinstance(d.get("data"), dict):
        raise RuntimeError(f"summary 端点失败: success={d.get('success')} code={d.get('errorCode')} msg={d.get('errorMsg')}")
    data = d["data"]
    ts = data.get("todayStatistics") or {}
    ut = data.get("updateTime")
    return {
        "broad_market_index": _num(data.get("broadMarketIndex")),
        "diff_yesterday": _num(data.get("diffYesterday")),
        "diff_yesterday_ratio": _num(data.get("diffYesterdayRatio")),
        "add_num": _int(ts.get("addNum")),
        "add_valuation": _num(ts.get("addValuation")),
        "trade_num": _int(ts.get("tradeNum")),
        "turnover": _num(ts.get("turnover")),
        "add_num_ratio": _num(ts.get("addNumRatio")),
        "add_amount_ratio": _num(ts.get("addAmountRatio")),
        "trade_volume_ratio": _num(ts.get("tradeVolumeRatio")),
        "trade_amount_ratio": _num(ts.get("tradeAmountRatio")),
        "survive_num": _int(data.get("surviveNum")),
        "holders_num": _int(data.get("holdersNum")),
        "update_time": datetime.fromtimestamp(int(ut), tz=TZ_BJ).strftime("%Y-%m-%d %H:%M:%S") if ut else None,
    }


def fetch_players():
    """players 端点 → online_count / month_avg_online（并入 market 行）。"""
    d = _get_json(PLAYERS_URL)
    if not d.get("success") or not isinstance(d.get("data"), dict):
        raise RuntimeError(f"players 端点失败: success={d.get('success')} code={d.get('errorCode')} msg={d.get('errorMsg')}")
    data = d["data"]
    return {
        "online_count": _int(data.get("count")),
        "month_avg_online": _int(data.get("monthAvg")),
    }


def fetch_blocks():
    """item-block 端点 → raw_steamdt_blocks 行列表（hot/level1/level2/level3 × defaultList，每日 20 行）。"""
    d = _get_json(BLOCKS_URL)
    if not d.get("success") or not isinstance(d.get("data"), dict):
        raise RuntimeError(f"item-block 端点失败: success={d.get('success')} code={d.get('errorCode')} msg={d.get('errorMsg')}")
    data = d["data"]
    level_map = {"hot": "hot", "itemTypeLevel1": "level1", "itemTypeLevel2": "level2", "itemTypeLevel3": "level3"}
    rows = []
    for key, level in level_map.items():
        grp = data.get(key) or {}
        for blk in grp.get("defaultList") or []:
            rows.append({
                "level": level,
                "block_name": blk.get("name"),
                "index_value": _num(blk.get("index")),
                "rise_fall_rate": _num(blk.get("riseFallRate")),
                "rise_fall_diff": _num(blk.get("riseFallDiff")),
            })
    if not rows:
        raise RuntimeError("item-block 端点返回空板块列表")
    return rows


def main():
    ap = argparse.ArgumentParser(description="W7-2 steamdt 蓄水池采集（默认 APPLY 落 raw.db）")
    ap.add_argument("--dry-run", action="store_true", help="仅解析打印，不写库")
    args = ap.parse_args()

    ts = _now_ts()
    date = _today()
    mode = "DRY-RUN" if args.dry_run else "APPLY"

    summary = fetch_summary()
    players = fetch_players()
    blocks = fetch_blocks()
    market = {**summary, **players}
    print(f"[{ts}] steamdt {mode} date={date} market_fields={len(market)} blocks={len(blocks)}", flush=True)

    if not args.dry_run:
        conn = raw_db.get_raw_conn()
        try:
            # 幂等守卫：当日 market 已存在 → 跳过写入（重复运行不重复插，契约 §一）
            exists = conn.execute(
                "SELECT COUNT(*) FROM raw_steamdt_market WHERE date=?", (date,)).fetchone()[0]
            if exists:
                print(f"[{_now_ts()}] steamdt 幂等跳过：date={date} 已存在（market={exists}）", flush=True)
            else:
                market_row = {"ts": ts, "date": date, **market, "source": "steamdt"}
                raw_db.append_raw(conn, "raw_steamdt_market", market_row)
                for b in blocks:
                    raw_db.append_raw(conn, "raw_steamdt_blocks", {
                        "ts": ts, "date": date, "source": "steamdt", **b})
                conn.commit()
            # 幂等核对：本日期实际落库行数（UNIQUE 冲突自动忽略）
            m_n = conn.execute("SELECT COUNT(*) FROM raw_steamdt_market WHERE date=?", (date,)).fetchone()[0]
            b_n = conn.execute("SELECT COUNT(*) FROM raw_steamdt_blocks WHERE date=?", (date,)).fetchone()[0]
        finally:
            conn.close()
    else:
        m_n, b_n = 1, len(blocks)

    # stdout 末行 = RESULT（④侧取末行记 log）
    print(f"RESULT mode={mode} date={date} market={m_n} blocks={b_n}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 失败退出非 0，④侧记录不中断主采集
        print(f"ERROR collect_steamdt_reserve: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
