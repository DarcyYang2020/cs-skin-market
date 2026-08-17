# -*- coding: utf-8 -*-
"""大盘自身信号 + 风险仪表（2026-08-17，主路径第(1)步模块 A+D，纯引擎无关）。

职责：大盘级结论（时期→动作区 + 大盘自身前视期望 + 风险档位），不产生单品信号。
证据：时期前视引用冻结表 data/_exp_market_periods.json（数据挖掘定稿，非重算）；
风险档位预注册自时期波动指纹（P vol20 中位 4.59% / S1 0.68%，方案 market-engine-completion-plan.md）。
单一事实源：大盘指数取生产库 market_index（3 年）；breadth5 按 HQ 池实盘 5 日上涨品占比现算。
"""
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from .market_context import state_bucket
except ImportError:  # 直接运行兜底
    from pipeline.market_context import state_bucket

_ROOT = Path(__file__).resolve().parent.parent
_PERIODS_JSON = _ROOT / "data" / "_exp_market_periods.json"
_HQ_EXCLUDE = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")

# 时期 → (动作区, 标题, 证据文案)。证据=大盘自身前视（_exp_market_periods.json）。
_ACTION = {
    "P恐慌深跌": ("buy_zone", "抄底区", "恐慌深跌后 V 型反弹概率历史最高，分批建仓窗口"),
    "S1牛市上行": ("hold_zone", "持多区", "慢牛主升——涨得慢但稳，回调低吸优于追高"),
    "S2牛市回调": ("pullback_buy", "回调买点区", "二波前夜——短平中正，60d 期望转正扩大"),
    "S3弱市阴跌": ("avoid", "空仓区", "规避——大盘全期限负期望，只保留精选腿"),
    "S4弱市反弹": ("trap", "反抽陷阱区", "反弹多为派发——不追反弹，新仓从严"),
}

_CACHE = {"ts": 0.0, "data": None}
_TTL = 300  # 5 分钟进程内缓存（dashboard 每页加载都会调用）


def _periods_evidence():
    """冻结证据表：{时期: {fwd14, fwd30} 字符串}，异常兜底空表（展示层不阻断）。"""
    try:
        d = json.load(open(_PERIODS_JSON, encoding="utf-8"))
        return {k: {"fwd14": v.get("fwd14"), "fwd30": v.get("fwd30")}
                for k, v in d.get("periods", {}).items()}
    except Exception:
        logger.warning("market periods evidence load failed", exc_info=True)
        return {}


def _breadth5(conn):
    """HQ 池 5 日上涨品占比（实盘口径，与 probe_market_base 同源）；异常返回 None。"""
    try:
        ids = [r["id"] for r in conn.execute(
            "SELECT id, name FROM items WHERE good_id>0").fetchall()
               if not any(m in r["name"] for m in _HQ_EXCLUDE)]
        up = tot = 0
        for iid in ids:
            rows = conn.execute(
                "SELECT date, price_rmb FROM price_history WHERE item_id=? AND price_rmb IS NOT NULL "
                "ORDER BY date DESC LIMIT 2", (iid,)).fetchall()
            if len(rows) >= 2 and rows[0]["price_rmb"] > 0 and rows[1]["price_rmb"] > 0:
                tot += 1
                if rows[0]["price_rmb"] >= rows[1]["price_rmb"]:
                    up += 1
        return round(100.0 * up / tot, 1) if tot >= 10 else None
    except Exception:
        logger.warning("breadth5 compute failed", exc_info=True)
        return None


def _risk_level(vol20, dist_hi60, dist_lo60):
    """风险档位（预注册，方案 D）：高=恐慌波动或深跌中；低=慢牛低波贴低点上方；中=其余。"""
    if vol20 is None:
        return "unknown"
    if vol20 >= 0.03 or (dist_hi60 is not None and dist_hi60 <= -15):
        return "high"
    if vol20 <= 0.007 and (dist_lo60 is not None and dist_lo60 >= -5):
        return "low"
    return "medium"


# ---- 模块 B：黑天鹅事件响应（预研探针 probe_crash_window_forward.py 定稿）----
# 指纹：大盘单日 ≤-8% 或 3 日累计 ≤-12%。历史窗口 fwd14/30 全部收涨（3/5 次事件，+2.3~+84.4）
# → V 型反弹规律成立 → 规则=暂停新开 + 不砍恐慌仓（恐慌深跌档按止损矩阵转补仓评估），绝不自动卖出。
_CRASH_1D = -8.0
_CRASH_3D = -12.0
_CRASH_RESPONSE = (
    "黑天鹅急跌窗口：暂停新开仓；恐慌仓按止损矩阵管理（恐慌深跌档=不止损转补仓评估）。"
    "历史急跌窗口（单日≤-8%/3日≤-12%，n=3~5）14/30d 全部收涨——V 型反弹规律，不追砍。"
)


def _crash(chg1d, chg3d):
    if chg1d is None and chg3d is None:
        return None
    active = (chg1d is not None and chg1d <= _CRASH_1D) or (chg3d is not None and chg3d <= _CRASH_3D)
    return {"active": bool(active), "chg1d": chg1d, "chg3d": chg3d,
            "response": _CRASH_RESPONSE if active else ""}


def market_signal(conn=None):
    """大盘信号 + 风险仪表（模块 A+D，TTL 缓存）。返回 dict；异常返回最小兜底（不抛）。"""
    now = time.time()
    if _CACHE["data"] is not None and now - _CACHE["ts"] < _TTL:
        return _CACHE["data"]
    try:
        from . import db as _db
        _conn = conn
        if _conn is None:
            _conn = _db.get_conn()
        try:
            rows = _conn.execute(
                "SELECT date, value FROM market_index WHERE value>0 ORDER BY date").fetchall()
            hist = [(r["date"], float(r["value"])) for r in rows]
            stats = _stats(hist)
            breadth = _breadth5(_conn)
        finally:
            if conn is None:
                _conn.close()
    except Exception:
        logger.warning("market_signal failed", exc_info=True)
        return {"period": "unknown", "market_action": "unknown", "ok": False}

    period = state_bucket(stats["chg180"], stats["chg30"])
    action, title, note = _ACTION.get(period, ("unknown", "未知", ""))
    ev = _periods_evidence().get(period, {})
    vol20 = stats.get("vol20")
    risk = _risk_level(vol20, stats.get("dist_hi60"), stats.get("dist_lo60"))
    out = {
        "ok": True,
        "period": period,
        "market_action": action,
        "action_label": title,
        "action_note": note,
        "period_forward": ev,
        "chg180": stats["chg180"], "chg30": stats["chg30"],
        "crash": _crash(stats.get("chg1d"), stats.get("chg3d")),
        "risk_level": risk,
        "risk_factors": {
            "vol20": vol20,
            "breadth5": breadth,
            "dist_hi60": stats.get("dist_hi60"),
            "dist_lo60": stats.get("dist_lo60"),
            "dist_hi180": stats.get("dist_hi180"),
            "dist_lo180": stats.get("dist_lo180"),
        },
    }
    _CACHE["data"] = out
    _CACHE["ts"] = time.time()
    return out


def _stats(hist):
    """大盘指数统计（chg1d/3d/30/180/vol20/距60-180高低点；与 market_index_stats 同源口径）。"""
    vals = [v for _, v in hist]
    n = len(vals)
    cur = vals[-1]
    out = {"chg1d": None, "chg3d": None, "chg30": 0.0, "chg180": 0.0, "vol20": None,
           "dist_hi60": None, "dist_lo60": None, "dist_hi180": None, "dist_lo180": None}
    if n < 2:
        return out
    if vals[-2] > 0:
        out["chg1d"] = round((cur / vals[-2] - 1) * 100, 1)
    if n >= 4 and vals[-4] > 0:
        out["chg3d"] = round((cur / vals[-4] - 1) * 100, 1)
    if n >= 31 and vals[-31] > 0:
        out["chg30"] = round((cur / vals[-31] - 1) * 100, 1)
    if n >= 181 and vals[-181] > 0:
        out["chg180"] = round((cur / vals[-181] - 1) * 100, 1)
    if n >= 21:
        rets = [(vals[i] - vals[i - 1]) / vals[i - 1] for i in range(n - 20, n) if vals[i - 1] > 0]
        if rets:
            mu = sum(rets) / len(rets)
            out["vol20"] = round((sum((r - mu) ** 2 for r in rets) / len(rets)) ** 0.5, 4)
    if n >= 60:
        out["dist_hi60"] = round((cur / max(vals[-60:]) - 1) * 100, 2)
        out["dist_lo60"] = round((cur / min(vals[-60:]) - 1) * 100, 2)
    if n >= 180:
        out["dist_hi180"] = round((cur / max(vals[-180:]) - 1) * 100, 2)
        out["dist_lo180"] = round((cur / min(vals[-180:]) - 1) * 100, 2)
    return out


def bust_cache():
    _CACHE["data"] = None
    _CACHE["ts"] = 0.0
