# -*- coding: utf-8 -*-
"""M1 监控模式（2026-08-08）：每日自选品异动事件生成 + 归档。

纯提醒/展示层：只读引擎输出（run_item_analysis 不落库），不产生新信号、不触碰冻结参数。
事件规则（8 类）：买点接近 / 破位止损 / 决策翻转 / 供给突变 / 价格异动 / 大盘状态切换 / 持仓到期 / 新 buy 信号。
消费链：run_daily_collect 收尾自动跑（当日采集后数据已最新）；Web /monitor 展示；M2 接入钉钉推送。
"""
import io, os, sys
from datetime import datetime, timezone, timedelta, date as _date

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import db

TZ_BJ = timezone(timedelta(hours=8))
MD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "monitor_daily.md")

# 事件规则阈值（纯提醒层，人工确认不回测拟合；冻结纪律内）
NEAR_BUY_MIN = 60      # 买点接近度 >= 60 且非 buy
STOP_LOSS_PCT = 0.75   # 现价 <= 成本 * 0.75
SUPPLY_SHIFT_7D = (-20, 30)  # 在售量 7 日变化超出区间
PRICE_SPIKE_PCT = 8.0  # 单日 |涨跌| >= 8%


def _today() -> str:
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")


def _market_ctx_from_db(conn):
    """大盘上下文（纯 DB，不拉网络；每日采集后 market_index/macro_history 已最新）。

    与 webapp.analysis_service.market_snapshot 同源口径：分位/Z/周期/TH/涨跌幅 + 情绪。
    情绪用 macro_history 最新非空 greedy_index 映射（避免 live fetch 网络依赖）。
    """
    rows = conn.execute("SELECT date, value FROM market_index WHERE value>0 ORDER BY date").fetchall()
    market_history = [(r["date"], float(r["value"])) for r in rows]
    values = [v for _, v in market_history]
    pct, z = 50.0, 0.0
    cycle, th = "unknown", 50.0
    chg7 = chg30 = drop21 = 0.0
    if len(values) >= 30:
        from pipeline.index_analysis import analyze_index
        _ires = analyze_index(market_history[-90:])
        _ipos = _ires.get("position", {}) if isinstance(_ires, dict) else {}
        pct = _ipos.get("percentile_90d", 50)
        z = _ipos.get("zscore_90d", 0)
        cur = values[-1]
        m7 = values[-7] if len(values) >= 7 else values[0]
        m30 = values[-30]
        m21 = values[-21] if len(values) >= 21 else values[0]
        chg7 = round((cur - m7) / m7 * 100, 1) if m7 > 0 else 0
        chg30 = round((cur - m30) / m30 * 100, 1) if m30 > 0 else 0
        drop21 = round((cur - m21) / m21 * 100, 1) if m21 > 0 else 0
        from pipeline.market_th import derive_market_cycle, compute_market_trend_health
        cycle = derive_market_cycle(values, len(values) - 1)
        try:
            _mth = compute_market_trend_health(values[-90:])
            th = _mth.corrected_score if hasattr(_mth, "corrected_score") else _mth.score
        except Exception:
            th = max(0, min(100, 50 + chg30 * 3))
    sent = 50.0
    _g = conn.execute(
        "SELECT greedy_index FROM macro_history WHERE greedy_index IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if _g and _g["greedy_index"]:
        from pipeline.market_macro import greedy_to_sentiment
        sent = float(greedy_to_sentiment(float(_g["greedy_index"])))
    from pipeline.market_context import state_bucket
    bucket = state_bucket(sent, th, chg30)
    return {"pct": pct, "z": z, "cycle": cycle, "th": th,
            "chg7": chg7, "chg30": chg30, "drop21": drop21,
            "sentiment": sent, "bucket": bucket}


def _analyze_item(conn, item, ms, signal_date):
    """单品味监控分析（只读 DB 最新 90 日 K 线 + run_item_analysis，不落库）。"""
    rows = conn.execute(
        "SELECT date, price_rmb, in_sale_count FROM price_history WHERE item_id=? ORDER BY date ASC",
        (item["id"],),
    ).fetchall()[-90:]
    valid = [(float(r["price_rmb"]), int(r["in_sale_count"] or 0))
             for r in rows if r["price_rmb"] and r["price_rmb"] > 0]
    if len(valid) < 30:
        return None
    prices = [p for p, _ in valid]
    supply_hist = [s for _, s in valid]
    cutoff = (datetime.now(TZ_BJ) - timedelta(days=7)).strftime("%Y-%m-%d")
    rb = [r["date"][:10] for r in conn.execute(
        "SELECT date FROM snapshots WHERE item_id=? AND action IN ('buy','oversold_buy') AND date>=? ORDER BY date DESC",
        (item["id"], cutoff),
    ).fetchall()]
    from pipeline import item_analysis
    analysis = item_analysis.run_item_analysis(
        name=item["name"], prices=prices, supply_hist=supply_hist or None,
        index_change_7d=ms["chg7"], market_cycle=ms["cycle"], market_th_score=int(ms["th"]),
        market_30d_change=ms["chg30"], market_drop21=ms["drop21"],
        recent_buy_dates=rb, signal_date=signal_date,
    )  # survive_count 不在 DB items 表（来自 info/good），监控只读分析不判存世量闸门
    return {"analysis": analysis, "prices": prices, "latest": prices[-1]}


def _prev_snapshot_action(conn, item_id, date):
    r = conn.execute(
        "SELECT action FROM snapshots WHERE item_id=? AND date < ? ORDER BY date DESC LIMIT 1",
        (item_id, date),
    ).fetchone()
    return (r["action"] or "") if r else ""


def _gen_item_events(date, item, res, prev_action):
    """单品 5 类事件：买点接近 / 破位止损 / 决策翻转 / 供给突变 / 价格异动。"""
    analysis = res["analysis"]
    fd = dict(analysis.fusion_decision or {})
    action = fd.get("action")
    action_label = fd.get("action_label") or action or ""
    latest = res["latest"]
    events = []

    def _add(etype, level, detail):
        events.append({
            "item_id": item["id"], "item_name": item["name"],
            "event_type": etype, "level": level, "detail": detail,
            "dedup_key": f"{date}|{item['id']}|{etype}",
        })

    prox = fd.get("proximity")
    if prox and isinstance(prox, dict) and action != "buy" and (prox.get("score") or 0) >= NEAR_BUY_MIN:
        _add("near_buy", "warn", f"买点接近度 {prox['score']}% · {prox.get('nearest') or ''}")

    if item.get("holding") and (item.get("avg_cost") or 0) > 0 and latest:
        _sl = item["avg_cost"] * STOP_LOSS_PCT
        if latest <= _sl:
            _add("stop_loss", "danger", f"现价 ¥{latest:.2f} ≤ 成本-25% ¥{_sl:.2f}，建议止损")

    if prev_action and action and prev_action != action:
        flips = {("watch", "buy"), ("avoid", "buy"), ("buy", "watch"), ("buy", "avoid"), ("buy", "sell")}
        if (prev_action, action) in flips:
            _add("decision_flip", "danger" if action == "buy" else "warn",
                 f"决策翻转：{prev_action} → {action_label}")

    sup = analysis.supply_analysis or {}
    s7 = sup.get("supply_change_7d")
    if s7 is not None:
        if s7 <= SUPPLY_SHIFT_7D[0]:
            _add("supply_shift", "warn", f"在售量 7 日 {s7:+.0f}%（供给收缩）")
        elif s7 >= SUPPLY_SHIFT_7D[1]:
            _add("supply_shift", "warn", f"在售量 7 日 {s7:+.0f}%（供给扩张）")

    if len(res["prices"]) >= 2:
        _chg = (res["prices"][-1] / res["prices"][-2] - 1) * 100
        if abs(_chg) >= PRICE_SPIKE_PCT:
            _add("price_spike", "danger" if _chg < 0 else "warn", f"单日 {_chg:+.1f}%")

    return events


def _gen_market_events(conn, date, bucket):
    """大盘状态事件：当日状态记录（幂等）+ 跨日切换提醒。"""
    label = f"大盘状态：{bucket}"
    events = [{
        "item_id": None, "item_name": None, "event_type": "market_state",
        "level": "info", "detail": label, "dedup_key": f"{date}||market_state",
    }]
    prev = conn.execute(
        "SELECT detail FROM monitor_events WHERE event_type='market_state' AND date < ? "
        "ORDER BY date DESC, id DESC LIMIT 1", (date,),
    ).fetchone()
    if prev and prev["detail"] != label:
        events.append({
            "item_id": None, "item_name": None, "event_type": "market_state",
            "level": "warn", "detail": f"大盘状态切换：{prev['detail']} → {bucket}",
            "dedup_key": f"{date}||market_state_flip",
        })
    return events


def _gen_exec_events(conn, date):
    """持仓到期事件：executions 14/30 日复盘到期且未结算。"""
    events = []
    today = _date.fromisoformat(date)
    rows = conn.execute(
        "SELECT id, item_id, name, advice_date, advice_signal, exec_price, settle_14, settle_30 "
        "FROM executions").fetchall()
    for r in rows:
        try:
            adv = _date.fromisoformat(r["advice_date"])
        except (TypeError, ValueError):
            continue
        for _days, col in ((14, "settle_14"), (30, "settle_30")):
            if r[col] is not None:
                continue
            if adv + timedelta(days=_days) > today:
                continue
            events.append({
                "item_id": r["item_id"], "item_name": r["name"], "event_type": "exec_due",
                "level": "info",
                "detail": f"{_days} 日复盘到期（建议 {r['advice_date']} · 执行价 ¥{r['exec_price']:.2f}）",
                "dedup_key": f"{date}|{r['item_id']}|exec_due_{_days}",
            })
    return events


def _gen_new_buy_events(conn, date):
    """新 buy 信号事件：signal_tracking 当日新增（analyze_fresh/批量扫描落库）。"""
    events = []
    rows = conn.execute(
        "SELECT item_id, item_name, action_label, entry_price FROM signal_tracking "
        "WHERE signal_date=? ORDER BY id", (date,),
    ).fetchall()
    for r in rows:
        events.append({
            "item_id": r["item_id"], "item_name": r["item_name"], "event_type": "new_buy_signal",
            "level": "danger",
            "detail": f"新 buy 信号：{r['action_label'] or 'buy'}（入场 ¥{r['entry_price']:.2f}）",
            "dedup_key": f"{date}|{r['item_id']}|new_buy_signal",
        })
    return events


def _write_md(date, summary, events):
    """监控日报 data/monitor_daily.md（纯展示）。"""
    try:
        lines = [f"# 监控日报 {date}", "",
                 f"大盘状态：**{summary['bucket']}** · 分析 {summary['analyzed']} 品 / 数据不足跳过 {summary['skipped']} 品", ""]
        if not events:
            lines.append("今日无异动事件。")
        else:
            order = {"danger": 0, "warn": 1, "info": 2}
            tag = {"danger": "🔴", "warn": "🟡", "info": "🔵"}
            for e in sorted(events, key=lambda x: (order.get(x["level"], 9), x["item_name"] or "大盘")):
                lines.append(f"- {tag.get(e['level'], '•')} [{e['event_type']}] "
                             f"{(e['item_name'] or '大盘')}：{e['detail']}")
        with open(MD_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def run_daily_monitor(date=None):
    """M1 监控主入口：大盘上下文 + 自选品只读分析 + 8 类事件生成 + 落库 + 日报。

    返回 summary dict（供 run_daily_collect 日志 / M2 推送）。
    """
    date = date or _today()
    conn = db.get_conn()
    try:
        ms = _market_ctx_from_db(conn)
        items = conn.execute(
            "SELECT id, name, in_watchlist, holding, avg_cost, quantity, good_id FROM items "
            "WHERE in_watchlist=1 OR holding=1 ORDER BY id").fetchall()
        events, analyzed, skipped = [], 0, 0
        for it in items:
            res = _analyze_item(conn, it, ms, date)
            if res is None:
                skipped += 1
                continue
            analyzed += 1
            prev_action = _prev_snapshot_action(conn, it["id"], date)
            events.extend(_gen_item_events(date, dict(it), res, prev_action))
        events.extend(_gen_market_events(conn, date, ms["bucket"]))
        events.extend(_gen_exec_events(conn, date))
        events.extend(_gen_new_buy_events(conn, date))
        saved = db.save_monitor_events(conn, date, events)
        conn.commit()
    finally:
        conn.close()
    summary = {"date": date, "bucket": ms["bucket"], "analyzed": analyzed,
               "skipped": skipped, "generated": len(events), "saved": saved}
    _write_md(date, summary, events)
    return summary


def list_events(days=7):
    """Web API 用：近 N 天监控事件（日期倒序）。"""
    conn = db.get_conn()
    try:
        rows = [dict(r) for r in db.list_monitor_events(conn, days=days)]
    finally:
        conn.close()
    return rows


if __name__ == "__main__":
    import json
    _s = run_daily_monitor()
    print(json.dumps(_s, ensure_ascii=False))
