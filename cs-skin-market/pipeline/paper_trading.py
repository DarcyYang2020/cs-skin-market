# -*- coding: utf-8 -*-
"""模拟盘 v2（2026-08-16，用户裁定：好好设计、用户不参与、模拟真实环境）。

设计原则 = **生产镜像**：模拟盘不重算引擎，而是完全跟随生产信号流——
  买入：signal_tracking 当日新增 buy 信号自动建仓（生产同款入场价/仓位/族）；
  卖出：三类真实出场自动执行——
    ① 到期（族 hold 天数，默认 21，族卡可配）
    ② 止盈/止损（config.ITEM_EXIT_RULES 情绪档；中性档 2.5×ATR 在开仓时按近14日行情计算定死）
    ③ 供给扩张全止损（开仓时记 sc30，逐日查 sc30>5 全止损）
  净值逐日按真实收盘价标记；基准腿 = 同起点 HQ 等权买入持有。
与实盘 executions 完全隔离；只读 DB、只写自己三表；任何异常不中断每日任务。
"""
import json
import logging
import os
from datetime import datetime

from . import db

_LOG = logging.getLogger(__name__)

COST_PCT = 2.0
DEFAULT_HOLD = 21
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_PATH = os.path.join(_ROOT, "data", "paper_trading_status.json")

# 情绪档静态止盈止损（与 engine price_zones 同源语义；中性档的 ATR 在开仓时计算定死）
_SENT_BANDS = {
    "fear": (-0.30, 0.40), "neutral": (None, 0.15), "greed": (-0.08, None),
}
_NEUTRAL_ATR_MULT = 2.5
_GREED_ATR_MULT = 1.5


def ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_account (
        id INTEGER PRIMARY KEY CHECK (id=1),
        cash REAL NOT NULL, initial REAL NOT NULL,
        updated_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER, item_name TEXT, family TEXT, action_label TEXT,
        signal_date TEXT, entry_price REAL, limit_pct REAL, qty REAL,
        stop_pct REAL, take_pct REAL, hold_days INTEGER, sc30_open REAL,
        open_at TEXT DEFAULT (datetime('now','localtime')), closed INTEGER DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id INTEGER, item_name TEXT, family TEXT,
        entry_price REAL, exit_price REAL, net_pct REAL, hold_days INTEGER,
        exit_reason TEXT, closed_at TEXT DEFAULT (datetime('now','localtime')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS paper_baseline (
        date TEXT PRIMARY KEY, equity REAL)""")
    try:
        conn.execute("ALTER TABLE paper_positions ADD COLUMN sc30_open REAL")
    except Exception:
        pass
    conn.commit()


def _account(conn):
    r = conn.execute("SELECT cash, initial FROM paper_account WHERE id=1").fetchone()
    if r:
        return r["cash"], r["initial"]
    conn.execute("INSERT INTO paper_account (id, cash, initial) VALUES (1, 1000000, 1000000)")
    conn.commit()
    return 1000000.0, 1000000.0


def _atr_pct(conn, item_id, days=14):
    """近 N 日平均真实波幅%（生产 price_zones 同款近似）；无数据/异常回退 3%。"""
    try:
        rows = conn.execute("SELECT price_rmb FROM price_history WHERE item_id=? AND price_rmb IS NOT NULL "
                            "ORDER BY date DESC LIMIT ?", (item_id, days + 1)).fetchall()
    except Exception:
        return 0.03
    ps = [r["price_rmb"] for r in rows][::-1]
    if len(ps) < 3:
        return 0.03
    rets = [(ps[j] - ps[j - 1]) / ps[j - 1] for j in range(1, len(ps)) if ps[j - 1] > 0]
    atr = sum(abs(r) for r in rets) / len(rets) if rets else 0.03
    return max(0.01, min(0.10, atr))


def _bands_for(sentiment_score, conn, item_id):
    band = "fear" if sentiment_score >= 75 else ("greed" if sentiment_score <= 30 else "neutral")
    stop, take = _SENT_BANDS[band]
    atr = _atr_pct(conn, item_id)
    if band == "neutral" and stop is None:
        stop = -max(0.05, _NEUTRAL_ATR_MULT * atr)
    if band == "greed" and take is None:
        take = max(0.05, _GREED_ATR_MULT * atr)
    return stop, take


def open_position(conn, *, item_id, item_name, family, action_label, signal_date,
                  entry_price, limit_pct, sentiment_score, sc30=None, hold_days=None):
    cash, _ = _account(conn)
    cost = cash * limit_pct
    if cash < cost or entry_price <= 0:
        return None
    stop_pct, take_pct = _bands_for(sentiment_score, conn, item_id)
    cur = conn.execute(
        "INSERT INTO paper_positions (item_id, item_name, family, action_label, signal_date, "
        "entry_price, limit_pct, qty, stop_pct, take_pct, hold_days, sc30_open) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (item_id, item_name, family, action_label, signal_date, entry_price,
         limit_pct, cost / entry_price, stop_pct, take_pct, hold_days or DEFAULT_HOLD, sc30))
    conn.execute("UPDATE paper_account SET cash=cash-? WHERE id=1", (cost,))
    conn.commit()
    return cur.lastrowid


def settle_exits(conn, prices_now, sc30_now):
    """三类出场：到期 / 止盈止损 / 供给扩张全止损。返回平仓列表。"""
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
        # 供给扩张全止损优先级最高（实盘矩阵同语义：扩张=硬止损）
        if sc30_now.get(p["item_id"]) is not None and sc30_now[p["item_id"]] > 5:
            reason = "供给扩张全止损"
        elif ret <= p["stop_pct"]:
            reason = "止损"
        elif ret >= p["take_pct"]:
            reason = "止盈"
        elif held >= p["hold_days"]:
            reason = "到期"
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


def _sc30_now(conn):
    out = {}
    rows = conn.execute(
        "SELECT item_id, in_sale_count, date FROM price_history WHERE in_sale_count IS NOT NULL "
        "ORDER BY date").fetchall()
    buf = {}
    for r in rows:
        buf.setdefault(r["item_id"], []).append((r["date"], r["in_sale_count"]))
    for iid, seq in buf.items():
        if len(seq) < 60:
            continue
        s30 = sum(x[1] for x in seq[-30:]) / 30
        s30a = sum(x[1] for x in seq[-60:-30]) / 30
        if s30a > 0:
            out[iid] = (s30 / s30a - 1) * 100
    return out


def _latest_prices(conn):
    out = {}
    for p in conn.execute("SELECT item_id FROM paper_positions WHERE closed=0").fetchall():
        r = conn.execute("SELECT price_rmb FROM price_history WHERE item_id=? AND price_rmb IS NOT NULL "
                         "ORDER BY date DESC LIMIT 1", (p["item_id"],)).fetchone()
        if r:
            out[p["item_id"]] = r["price_rmb"]
    return out


def _baseline_update(conn):
    """基准腿：HQ 等权（生产池全部 good_id>0 品）自模拟盘创建日起的净值。"""
    created = conn.execute("SELECT MIN(open_at) FROM paper_positions").fetchone()[0] or \
        conn.execute("SELECT MIN(closed_at) FROM paper_trades").fetchone()[0]
    start = (created or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))[:10]
    if not conn.execute("SELECT 1 FROM paper_baseline LIMIT 1").fetchone():
        ids = [r["id"] for r in conn.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
        mp = {}
        for iid in ids:
            rows = conn.execute("SELECT date, price_rmb FROM price_history WHERE item_id=? "
                                "AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
            mp[iid] = {r["date"]: r["price_rmb"] for r in rows}
        days = conn.execute("SELECT DISTINCT date FROM price_history WHERE date>=? ORDER BY date",
                            (start,)).fetchall()
        for d in days:
            vals = []
            for iid, m in mp.items():
                keys = [k for k in m if k <= d["date"]]
                if keys and m[min(keys)] and m[min(keys)] > 0:
                    vals.append(m[max(keys)] / m[min(keys)])
            if vals:
                conn.execute("INSERT OR REPLACE INTO paper_baseline (date, equity) VALUES (?,?)",
                             (d["date"], sum(vals) / len(vals)))
    conn.commit()


def status(conn):
    cash, initial = _account(conn)
    pos = conn.execute("SELECT * FROM paper_positions WHERE closed=0").fetchall()
    trades = conn.execute("SELECT * FROM paper_trades").fetchall()
    px = _latest_prices(conn)
    equity = cash
    for p in pos:
        equity += p["qty"] * px.get(p["item_id"], p["entry_price"])
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
    base_row = conn.execute("SELECT equity FROM paper_baseline ORDER BY date DESC LIMIT 1").fetchone()
    strat_total = (equity / initial - 1) * 100
    base_total = (base_row["equity"] - 1) * 100 if base_row else None
    return {"initial": initial, "equity": round(equity, 2),
            "total_return_pct": round(strat_total, 2),
            "baseline_equal_weight_pct": round(base_total, 2) if base_total is not None else None,
            "excess_vs_ew_pct": round(strat_total - base_total, 2) if base_total is not None else None,
            "open_positions": len(pos), "closed_trades": len(trades),
            "families": fam_stats,
            "criteria": _criteria(fam_stats, len(trades),
                                  round(strat_total - base_total, 2)
                                  if base_total is not None else None)}


def _criteria(fam_stats, n_closed, excess_vs_ew):
    """落地前预注册判据（paper-trading-design.md 第四节，2026-08-17 补漏落地）：
    20 笔结算后按族评估——胜率 >= 族特征卡 win14 −15pp 且期望 >= −5pp → 保留，否则停腿告警；
    策略腿 vs 等权：超额为负 → 重审提示（连续 3 个月统计暂以"当前超额<0"代理，月度序列待积累）。"""
    out = {"threshold_n": 20, "n_closed": n_closed,
           "state": "accumulating" if n_closed < 20 else "evaluating"}
    if n_closed < 20:
        out["note"] = "结算 %d/20 笔，达到 20 笔后按族判据自动评估（胜率≥族卡−15pp 且 期望≥−5pp）" % n_closed
        return out
    try:
        import json as _json
        from pathlib import Path as _P
        _cards = _json.load(open(_P(__file__).resolve().parent.parent / "data" /
                                 "family_feature_cards.json", encoding="utf-8"))["families"]
        fam_verdicts = {}
        for k, f in fam_stats.items():
            card = _cards.get(k) or {}
            h14 = card.get("horizons", {}).get("14") or {}
            ref_win = h14.get("win")
            win_ok = (ref_win is None or f["win_pct"] >= ref_win - 15)
            exp_ok = f["avg_net_pct"] >= -5.0
            fam_verdicts[k] = {"keep": bool(win_ok and exp_ok),
                               "win_pct": f["win_pct"], "ref_win14": ref_win,
                               "avg_net_pct": f["avg_net_pct"],
                               "note": "" if win_ok and exp_ok else "停腿告警：胜率或期望低于预注册判据"}
    except Exception:
        fam_verdicts = {}
    out["families"] = fam_verdicts
    out["vs_ew"] = {"excess_pct": excess_vs_ew,
                    "note": "超额为负——策略腿重审（连续 3 个月统计待积累，当前以瞬时超额代理）"
                    if excess_vs_ew is not None and excess_vs_ew < 0 else "超额为正"}
    return out


def daily_run():
    """每日任务入口（生产镜像：跟随 signal_tracking 当日 buy 信号，不重算引擎）。"""
    from pipeline.signal_tracking import family_key_for_label
    conn = db.get_conn()
    try:
        ensure_schema(conn)
        _today = datetime.now().strftime("%Y-%m-%d")
        # 出场
        closed = settle_exits(conn, _latest_prices(conn), _sc30_now(conn))
        # 跟随生产信号建仓（当日 signal_tracking 新增、未镜像过的 buy）
        rows = conn.execute(
            "SELECT * FROM signal_tracking WHERE signal_date=? AND action IN ('buy','oversold_buy') "
            "ORDER BY id", (_today,)).fetchall()
        mirrored = {r["item_name"] + r["signal_date"] + r["action_label"]
                    for r in conn.execute("SELECT item_name, signal_date, action_label FROM paper_positions")}
        opened = 0
        # O2（2026-08-27）kill switch 联动：paper 闸停 → 暂停出单/建仓（出场与估值照常，不中断采集）
        from . import ops as _ops
        if _ops.is_blocked("paper"):
            _LOG.warning("kill switch 已拦停模拟盘建仓（paper scope），仅执行出场/估值")
        else:
            for s in rows:
                key = s["item_name"] + s["signal_date"] + (s["action_label"] or "")
                if key in mirrored:
                    continue
                pid = open_position(
                    conn, item_id=s["item_id"], item_name=s["item_name"],
                    family=family_key_for_label(s["action_label"] or ""),
                    action_label=s["action_label"] or "",
                    signal_date=s["signal_date"], entry_price=s["entry_price"],
                    limit_pct=s["position_limit"] or 0.10,
                    sentiment_score=s["sentiment"] if s["sentiment"] is not None else 50,
                    sc30=s["sc30"])
                if pid:
                    opened += 1
        _baseline_update(conn)
        st = status(conn)
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump({**st, "date": _today, "closed_today": closed, "opened_today": opened},
                      f, ensure_ascii=False, indent=1)
        return {"opened": opened, "closed": closed, "status": st}
    finally:
        conn.close()
