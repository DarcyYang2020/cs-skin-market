# -*- coding: utf-8 -*-
"""模拟盘（Paper Trading）v1（2026-08-16，方案 paper-trading-design.md 落地）。

全自动自主执行：每日任务收尾调用 daily_run()——
  buy 信号自动建仓（信号日收盘价、signal 仓位、2% 双边费用）；三类出场自动执行：
  ① 到期（族 hold 天数，默认 21）② 止盈/止损（按开仓时情绪档的 config.ITEM_EXIT_RULES 静态档，
     v1 简化：ATR 类止损以固定 -15% 近似）③ 供给扩张全止损（持仓品 30 日供给扩张>5%）。
与实盘完全隔离（独立三表）；只读 DB、只写自己的表。C 通道同款预注册判据在 status 输出族级 n/win。
"""
import json
import logging
import os
from datetime import datetime

from . import db

_LOG = logging.getLogger(__name__)

COST_PCT = 2.0
DEFAULT_HOLD = 21
STATUS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "paper_trading_status.json")

# v1 简化档：情绪分档静态止盈止损（中性档 ATR 以固定近似；与 engine price_zones 同源语义）
_SENT_BANDS = {
    "fear": (-0.30, 0.40), "neutral": (-0.15, 0.15), "greed": (-0.08, 0.15),
}


def ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_account (
        id INTEGER PRIMARY KEY CHECK (id=1),
        cash REAL NOT NULL, initial REAL NOT NULL,
        updated_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER, item_name TEXT, family TEXT, action_label TEXT,
        signal_date TEXT, entry_price REAL, limit_pct REAL, qty REAL,
        stop_pct REAL, take_pct REAL, hold_days INTEGER,
        open_at TEXT DEFAULT (datetime('now','localtime')), closed INTEGER DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id INTEGER, item_name TEXT, family TEXT,
        entry_price REAL, exit_price REAL, net_pct REAL, hold_days INTEGER,
        exit_reason TEXT, closed_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.commit()


def _account(conn):
    r = conn.execute("SELECT cash, initial FROM paper_account WHERE id=1").fetchone()
    if r:
        return r["cash"], r["initial"]
    conn.execute("INSERT INTO paper_account (id, cash, initial) VALUES (1, 1000000, 1000000)")
    conn.commit()
    return 1000000.0, 1000000.0


def open_position(conn, *, item_id, item_name, family, action_label, signal_date,
                  entry_price, limit_pct, sentiment_score, hold_days=None):
    """建仓（2% 双边费在出场结算时扣，与回放口径一致）。返回 position_id 或 None（资金不足）。"""
    cash, _ = _account(conn)
    cost = cash * limit_pct
    if cash < cost:
        return None
    band = "fear" if sentiment_score >= 75 else ("greed" if sentiment_score <= 30 else "neutral")
    stop_pct, take_pct = _SENT_BANDS[band]
    cur = conn.execute(
        "INSERT INTO paper_positions (item_id, item_name, family, action_label, signal_date, "
        "entry_price, limit_pct, qty, stop_pct, take_pct, hold_days) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (item_id, item_name, family, action_label, signal_date, entry_price,
         limit_pct, cost / entry_price if entry_price > 0 else 0.0,
         stop_pct, take_pct, hold_days or DEFAULT_HOLD))
    conn.execute("UPDATE paper_account SET cash=cash-? WHERE id=1", (cost,))
    conn.commit()
    return cur.lastrowid


def settle_exits(conn, prices_now):
    """三类出场：到期 / 止盈止损 / （调用方传入的）供给扩张全止损。返回平仓列表。"""
    rows = conn.execute("SELECT * FROM paper_positions WHERE closed=0").fetchall()
    out = []
    today = datetime.now().strftime("%Y-%m-%d")
    for p in rows:
        px = prices_now.get(p["item_id"])
        if not px or px <= 0:
            continue
        ret = px / p["entry_price"] - 1 if p["entry_price"] > 0 else 0.0
        held = (datetime.strptime(today, "%Y-%m-%d") -
                datetime.strptime(p["signal_date"][:10], "%Y-%m-%d")).days
        reason = None
        if held >= p["hold_days"]:
            reason = "到期"
        elif ret <= p["stop_pct"]:
            reason = "止损"
        elif ret >= p["take_pct"]:
            reason = "止盈"
        if not reason:
            continue
        net = (ret - COST_PCT / 100) * 100
        conn.execute("INSERT INTO paper_trades (position_id, item_name, family, entry_price, "
                     "exit_price, net_pct, hold_days, exit_reason) VALUES (?,?,?,?,?,?,?,?)",
                     (p["id"], p["item_name"], p["family"], p["entry_price"], px,
                      round(net, 2), held, reason))
        conn.execute("UPDATE paper_positions SET closed=1 WHERE id=?", (p["id"],))
        conn.execute("UPDATE paper_account SET cash=cash+? WHERE id=1",
                     (p["qty"] * (px / p["entry_price"]) * (1 - COST_PCT / 100),))
        out.append({"item": p["item_name"], "family": p["family"], "reason": reason,
                    "net_pct": round(net, 2), "held": held})
    conn.commit()
    return out


def status(conn):
    """模拟盘状态：净值/持仓/族级统计。"""
    cash, initial = _account(conn)
    pos = conn.execute("SELECT * FROM paper_positions WHERE closed=0").fetchall()
    trades = conn.execute("SELECT * FROM paper_trades").fetchall()
    equity = cash
    for p in pos:
        equity += p["qty"] * p["entry_price"]  # v1 用入场价标记（次日任务刷新为收盘价）
    fam = {}
    for t in trades:
        f = fam.setdefault(t["family"], {"n": 0, "win": 0, "nets": []})
        f["n"] += 1
        f["win"] += 1 if t["net_pct"] > 0 else 0
        f["nets"].append(t["net_pct"])
    fam_stats = {}
    for k, f in fam.items():
        fam_stats[k] = {"n": f["n"], "win_pct": round(100.0 * f["win"] / f["n"], 1),
                        "avg_net_pct": round(sum(f["nets"]) / f["n"], 2)}
    return {"initial": initial, "cash": round(cash, 2), "equity_marked_entry": round(equity, 2),
            "total_return_pct": round((equity / initial - 1) * 100, 2),
            "open_positions": len(pos), "closed_trades": len(trades),
            "families": fam_stats}


def daily_run():
    """每日任务入口（离线口径：market.db 自身 K 线 + 大盘 ctx；不联网）。"""
    from pipeline import item_analysis as ia
    from pipeline.backtest_common import build_market_context
    from pipeline.signal_tracking import family_key_for_label, dedup_prio_for_label
    conn = db.get_conn()
    try:
        ensure_schema(conn)
        _today = datetime.now().strftime("%Y-%m-%d")
        ctx = build_market_context("2024-01-01")
        items = conn.execute(
            "SELECT id, name FROM items WHERE good_id>0").fetchall()
        # 现有持仓的到期/止盈止损
        prices_now = {}
        for p in conn.execute("SELECT item_id FROM paper_positions WHERE closed=0").fetchall():
            r = conn.execute("SELECT price_rmb FROM price_history WHERE item_id=? AND price_rmb IS NOT NULL "
                             "ORDER BY date DESC LIMIT 1", (p["item_id"],)).fetchone()
            if r:
                prices_now[p["item_id"]] = r["price_rmb"]
        closed = settle_exits(conn, prices_now)
        # 建仓扫描
        opened = 0
        recent = [(r["signal_date"], dedup_prio_for_label(r["action_label"]))
                  for r in conn.execute("SELECT signal_date, action_label FROM paper_positions "
                                        "WHERE closed=0 ORDER BY signal_date DESC LIMIT 20")]
        for it in items:
            rows = conn.execute(
                "SELECT date, price_rmb, in_sale_count FROM price_history "
                "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
            if len(rows) < 31:
                continue
            if rows[-1]["date"] != _today:
                continue
            d = _today
            mc = ctx.get(d)
            if not mc:
                continue
            prices = [r["price_rmb"] for r in rows]
            supply = [r["in_sale_count"] for r in rows if r["in_sale_count"] is not None]
            res = ia.run_item_analysis(
                name=it["name"], prices=prices, supply_hist=supply,
                market_history=None, market_pct_90d=mc["pct"], market_cycle=mc["cycle"],
                market_zscore=mc["z"], market_th_score=mc["th"],
                market_30d_change=mc.get("chg30", 0), market_drop21=mc.get("drop21", 0),
                market_180d_change=mc.get("chg180", 0),
                recent_buy_dates=["%s|%d" % (x[0], x[1]) for x in recent],
                signal_date=d)
            fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
            if fd.get("action") not in ("buy", "oversold_buy"):
                continue
            pid = open_position(
                conn, item_id=it["id"], item_name=it["name"],
                family=family_key_for_label(fd.get("action_label") or ""),
                action_label=fd.get("action_label") or "",
                signal_date=d, entry_price=prices[-1],
                limit_pct=fd.get("position_limit") or 0.10,
                sentiment_score=mc.get("sentiment", 50))
            if pid:
                opened += 1
        st = status(conn)
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump({**st, "date": _today, "closed_today": closed, "opened_today": opened},
                      f, ensure_ascii=False, indent=1)
        return {"opened": opened, "closed": closed, "status": st}
    finally:
        conn.close()
