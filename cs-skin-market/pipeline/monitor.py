# -*- coding: utf-8 -*-
"""M1 监控模式（2026-08-08）：每日自选品异动事件生成 + 归档。

纯提醒/展示层：只读引擎输出（run_item_analysis 不落库），不产生新信号、不触碰引擎参数。
事件规则（8 类）：买点接近 / 破位止损 / 决策翻转 / 供给突变 / 价格异动 / 大盘状态切换 / 持仓到期 / 新 buy 信号。
消费链：run_daily_collect 收尾自动跑（当日采集后数据已最新）；M2 接入钉钉推送。
"""
import io, json, os, sys, uuid
from datetime import datetime, timedelta, date as _date

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import db
from pipeline.config import TZ_BJ

MD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "monitor_daily.md")

# 事件规则阈值（纯提醒层，人工确认不回测拟合；参数治理纪律内）
NEAR_BUY_MIN = 60      # 买点接近度 >= 60 且非 buy
STOP_LOSS_PCT = 0.75   # 现价 <= 成本 * 0.75
SUPPLY_SHIFT_7D = (-20, 30)  # 在售量 7 日变化超出区间
PRICE_SPIKE_PCT = 8.0  # 单日 |涨跌| >= 8%
PUSH_DETAIL_MAX = 10   # 钉钉正文 danger 明细上限（其余计数）
_TYPE_LABEL = {"near_buy": "买点接近", "stop_loss": "破位止损", "decision_flip": "决策翻转",
               "supply_shift": "供给突变", "price_spike": "价格异动", "market_state": "大盘状态",
               "exec_due": "持仓到期", "new_buy_signal": "新买信号"}

SLOT_LABEL = {"noon": "午间", "night": "晚间"}


def _market_ctx_from_db(conn):
    """大盘上下文（纯 DB，不拉网络；每日采集后 market_index/macro_history 已最新）。

    与 webapp.analysis_service.market_snapshot 同源口径：分位/Z/周期/TH/涨跌幅 + 情绪。
    情绪用 macro_history 最新非空 greedy_index 映射（避免 live fetch 网络依赖）。
    """
    from pipeline.market_context import market_index_stats, state_bucket
    rows = conn.execute("SELECT date, value FROM market_index WHERE value>0 ORDER BY date").fetchall()
    market_history = [(r["date"], float(r["value"])) for r in rows]
    stats = market_index_stats(market_history)
    pct, z, cycle, th = stats["pct"], stats["z"], stats["cycle"], stats["th"]
    chg7, chg30, drop21 = stats["chg7"], stats["chg30"], stats["drop21"]
    sent = 50.0
    _g = conn.execute(
        "SELECT greedy_index FROM macro_history WHERE greedy_index IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if _g and _g["greedy_index"]:
        from pipeline.market_macro import greedy_to_sentiment
        sent = float(greedy_to_sentiment(float(_g["greedy_index"])))
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
    _last_sale_row = next((r for r in reversed(rows) if r["price_rmb"] and r["price_rmb"] > 0), None)
    supply_depth_missing = db.supply_depth_missing(_last_sale_row["in_sale_count"], _last_sale_row["date"]) if _last_sale_row is not None else True
    cutoff = (datetime.now(TZ_BJ) - timedelta(days=7)).strftime("%Y-%m-%d")
    rb = [r["date"][:10] for r in conn.execute(
        "SELECT date FROM snapshots WHERE item_id=? AND action IN ('buy','oversold_buy') AND date>=? ORDER BY date DESC",
        (item["id"], cutoff),
    ).fetchall()]
    from pipeline import item_analysis
    analysis = item_analysis.run_item_analysis(
        name=item["name"], prices=prices, supply_hist=supply_hist or None, supply_depth_missing=supply_depth_missing,
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
            "holding": bool(item.get("holding")),  # A-8: 推送 danger 置顶排序用（展示层）
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


def _write_md(date, summary, events, slot="night"):
    """监控日报 data/monitor_daily.md（纯展示；午间/晚间覆盖写入，标题标注时段）。"""
    try:
        _tag = SLOT_LABEL.get(slot, slot)
        lines = [f"# 监控日报 {date}（{_tag}）", "",
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


def _build_push_text(summary, events, slot="night"):
    """组装钉钉正文（纯函数，纯文字自包含、无内网链接）：danger/warn 列明细（截断），info 按类型计数。"""
    from collections import Counter
    danger = [e for e in events if e["level"] == "danger"]
    warn = [e for e in events if e["level"] == "warn"]
    info = [e for e in events if e["level"] == "info"]
    lines = [f"大盘：{summary['bucket']} · 分析 {summary['analyzed']} 品 / 跳过 {summary['skipped']}"]

    def _dump(tag, evs, limit, near_buy_compact=False):
        if not evs:
            return
        lines.append("")
        lines.append(f"{tag} {len(evs)} 条")
        if near_buy_compact:
            _nb = [e for e in evs if e.get("event_type") == "near_buy"]
            _other = [e for e in evs if e.get("event_type") != "near_buy"]
            if _nb:
                _names = "、".join((e.get("item_name") or "")[:20] for e in _nb[:3])
                lines.append(f"- [买点接近] 共 {len(_nb)} 条（Top3：{_names}…，明细见 Web「今日关注」）")
            for e in _other[:limit]:
                lines.append(f"- [{_TYPE_LABEL.get(e['event_type'], e['event_type'])}] "
                             f"{(e.get('item_name') or '大盘')}：{e['detail']}")
            if len(_other) > limit:
                lines.append(f"… 另有 {len(_other) - limit} 条")
            return
        for e in evs[:limit]:
            lines.append(f"- [{_TYPE_LABEL.get(e['event_type'], e['event_type'])}] "
                         f"{(e.get('item_name') or '大盘')}：{e['detail']}")
        if len(evs) > limit:
            lines.append(f"… 另有 {len(evs) - limit} 条")

    # A-8（2026-08-12）：持仓 danger 置顶（仅消费端排序，不改事件生成）
    danger.sort(key=lambda e: (0 if e.get("holding") else 1, _TYPE_LABEL.get(e.get("event_type"), "")))
    _dump("🔴 危险", danger, PUSH_DETAIL_MAX)
    _dump("🟡 提醒", warn, PUSH_DETAIL_MAX, near_buy_compact=True)
    if info:
        _kinds = Counter(_TYPE_LABEL.get(e["event_type"], e["event_type"]) for e in info)
        _parts = "、".join(f"{k} {n} 条" for k, n in sorted(_kinds.items()))
        lines.append("")
        lines.append(f"🔵 信息 {len(info)} 条：" + _parts)
    title = f"CS 监控 {summary['date']} · {SLOT_LABEL.get(slot, slot)} · {summary['bucket']}"
    if danger:
        title += f" · 🚨{len(danger)}危险"
    elif warn:
        title += f" · 🟡{len(warn)}提醒"
    return title, "\n".join(lines)


def push_daily(summary, events, slot="night"):
    """M2 钉钉推送（2026-08-08）：午间/晚间各一次摘要 + danger 明细；按 日期+slot 幂等（settings 记已推送）。

    复用 notify_alert.py（.env NOTIFY_WEBHOOK_URL）；未配置 / 推送失败均不中断，返回原因。
    """
    key = f"monitor_push_{summary['date']}_{slot}"
    conn = db.get_conn()
    try:
        if db.get_setting(conn, key, ""):
            return {"pushed": False, "reason": "already_pushed"}
    finally:
        conn.close()
    try:
        from notify_alert import load_webhook_url, send
    except Exception as e:
        return {"pushed": False, "reason": f"import_error: {e}"}
    url = load_webhook_url()
    if not url:
        return {"pushed": False, "reason": "no_webhook"}
    title, text = _build_push_text(summary, events, slot)
    try:
        send(title, text, url)
    except Exception as e:
        return {"pushed": False, "reason": f"push_failed: {e}"}
    # D-3（2026-08-10）推送归因：生成 push_id 并持久化（日期+slot 幂等键不变，旧值 "1" 兼容）
    push_id = uuid.uuid4().hex[:12]
    conn = db.get_conn()
    try:
        db.set_setting(conn, key, json.dumps({
            "push_id": push_id, "slot": slot,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "n_events": len(events),
            "event_types": sorted({e.get("event_type") or "" for e in events}),
            "items": sorted({e.get("item_name") or e.get("name") or "" for e in events if e.get("item_name") or e.get("name")}),
        }, ensure_ascii=False))
        conn.commit()
    finally:
        conn.close()
    return {"pushed": True, "push_id": push_id}


def run_daily_monitor(date=None, slot="night", push=True):
    """M1 监控主入口：大盘上下文 + 自选品只读分析 + 8 类事件生成 + 落库 + 日报。

    返回 summary dict（供 run_daily_collect 日志 / M2 推送）。
    push=False 时只生成事件+日报不推送（采集收尾用；推送由独立 21:30 任务 run_night_push.py 执行）。
    事件按 slot 前缀幂等去重，21:30 重跑同 slot 不产生重复事件。
    """
    date = date or db._today()
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
        for _e in events:
            _e["dedup_key"] = f"{slot}::{_e['dedup_key']}"
        saved = db.save_monitor_events(conn, date, events)
        conn.commit()
    finally:
        conn.close()
    summary = {"date": date, "slot": slot, "bucket": ms["bucket"], "analyzed": analyzed,
               "skipped": skipped, "generated": len(events), "saved": saved}
    _write_md(date, summary, events, slot)
    try:
        if push:
            summary["pushed"] = push_daily(summary, events, slot)
        else:
            summary["pushed"] = {"pushed": False, "reason": "push_deferred_to_night_task"}
    except Exception as _e:
        summary["pushed"] = {"pushed": False, "reason": f"error: {_e}"}
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
    _s = run_daily_monitor()
    print(json.dumps(_s, ensure_ascii=False))
