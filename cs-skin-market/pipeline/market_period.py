# -*- coding: utf-8 -*-
"""大盘五时期生产持久化（2026-08-16）。

- classify / state_bucket：五时期路由唯一实现 = pipeline.market_context.state_bucket
  （本模块不重复定义路由，仅引用）。
- daily_state(conn)：从生产库 market_index 计算当日 M1 状态行
  （chg7/30/90/180、th、vol20、距 60/180 日高低点、period），字段口径与
  references/probe_market_base.py 的 M1 基座一致（TH 同 backtest_common 的
  compute_market_trend_health 90 窗）。
- append_daily_state()：把当日状态追加进 data/market_state_daily.json
  （M1 研究基座的实盘延伸，同字段幂等覆盖当日）。
纯计算/持久化：不触碰引擎参数；异常由调用方隔离。
"""
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from .market_context import state_bucket
    from .db import TZ_BJ
except ImportError:  # 直接运行兜底
    from pipeline.market_context import state_bucket
    from pipeline.db import TZ_BJ

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = _ROOT / "data" / "market_state_daily.json"


def daily_state(conn, today=None):
    """从生产库 market_index 计算当日状态行；数据不足返回 None。"""
    rows = conn.execute("SELECT date, value FROM market_index WHERE value>0 ORDER BY date").fetchall()
    if len(rows) < 30:
        return None
    dates = [r["date"] for r in rows]
    vals = [float(r["value"]) for r in rows]
    i = len(vals) - 1
    if today and dates[i] != today:
        return None
    v = vals[i]

    def chg(k):
        return round((v / vals[i - k] - 1) * 100, 2) if i >= k and vals[i - k] > 0 else None

    rets = [(vals[j] - vals[j - 1]) / vals[j - 1] for j in range(i - 19, i + 1) if vals[j - 1] > 0]
    vol20 = round((sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets)) ** 0.5, 4) if rets else None
    try:
        from .market_th import compute_market_trend_health
        th = compute_market_trend_health(vals[i - 90:i + 1]).corrected_score
    except Exception:
        th = 50.0
    c30, c180 = chg(30), chg(180)
    row = {
        "th": th,
        "chg7": chg(7),
        "chg30": c30,
        "chg90": chg(90),
        "chg180": c180,
        "vol20": vol20,
        "dist_hi60": round((v / max(vals[i - 59:i + 1]) - 1) * 100, 2),
        "dist_lo60": round((v / min(vals[i - 59:i + 1]) - 1) * 100, 2),
        "dist_hi180": round((v / max(vals[i - 179:i + 1]) - 1) * 100, 2) if i >= 180 else None,
        "dist_lo180": round((v / min(vals[i - 179:i + 1]) - 1) * 100, 2) if i >= 180 else None,
    }
    # 广度（2026-08-17 大盘引擎 A+D 补缺口）：HQ 池 5 日上涨品占比，与 market_signal 同源口径
    try:
        from .market_signal import _breadth5
        row["breadth5"] = _breadth5(conn)
    except Exception:
        logger.warning("breadth5 compute failed in daily_state", exc_info=True)
    if c180 is not None:
        row["period"] = state_bucket(c180, c30 or 0.0)
    return {"date": dates[i], **row}


def append_daily_state(conn=None, today=None):
    """把当日 M1 状态追加进 market_state_daily.json（幂等；异常上抛由调用方隔离）。"""
    from . import db as _db

    _today = today or datetime.now(TZ_BJ).strftime("%Y-%m-%d")
    _conn = conn
    try:
        if _conn is None:
            _conn = _db.get_conn()
        row = daily_state(_conn, today=_today)
    finally:
        if conn is None and _conn is not None:
            _conn.close()
    if row is None:
        return None
    if STATE_FILE.exists():
        st = json.load(open(STATE_FILE, encoding="utf-8"))
    else:
        st = {}
    st[row["date"]] = {k: v for k, v in row.items() if k != "date"}
    json.dump(st, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return row
