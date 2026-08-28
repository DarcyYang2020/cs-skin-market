# -*- coding: utf-8 -*-
"""EXEC-2 自动盯盘链（2026-08-27，decision-log HC，PM 立项交④研发执行；HG 增量 2026-08-28）。

链路缺口：18:00 采集后→21:30 之间（及日间）无自动信号重算 → 新 buy 无法及时推送。
本脚本 = 自动重算活跃池/自选+持仓融合决策，新 buy 走 S3 意向单钉钉推送（已闭环：CS 前缀+加签）。

双轨（方案 A + B，均本脚本，--scope 区分）：
  - 方案 A（兜底，18:00 采集收尾挂接）：--scope active —— 活跃池全量重算；
  - 方案 B（覆盖空窗，独立 2h 定时任务）：--scope watchlist —— 先刷大盘指数（HC 修订段，
    2026-08-28 ②修订版采纳：collect_market_index 复用 run_daily_collect，大盘随 2h 链更新）
    → 再自选+持仓增量刷新+重算+推送。
复用：scan_tasks._scan_item（增量，KLINE_FRESH_BATCH 复用窗口）+ paper_trading.create_intention/push_intention（S3）；
红线：不碰引擎参数、不 bump ENGINE_VERSION；推送幂等对齐 M2（settings key，同品同日不重复推）。

HG 增量（2026-08-28，PM 追卡）：
  - G1 csQAQ 风控护栏：连续失败 ≥10 → 暂停+O4 告警+冷却 45min（settings exec2_cooldown_until）；
    冷却期内跳过运行；失败品入台账（settings exec2_failed_{date}）下轮补扫；连败 3 轮降级每日一次；
  - G2 扫描进度可见性：写 scan_progress（source=auto，复用 scan_tasks._persist_scan_progress）；
    /exec2 独立进度页（webapp 路由，只读最近任务）；完成/卡住走 O4 钉钉通知；
    进度含 阶段/current/total/失败数/ETA。

用法: python exec2_auto_watch.py [--scope active|watchlist] [--dry-run]
stdout 末行 = RESULT ...（④侧取末行记 log）；退出码 0=成功 / 非 0=失败。
"""
import argparse
import asyncio
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from pipeline.config import TZ_BJ  # noqa: E402
from pipeline import db  # noqa: E402

# 幂等 key 前缀（对齐 M2 monitor_push_{date}_{slot}）：exec2_push_{date}_{item_id}
_PUSH_KEY_PREFIX = "exec2_push"

# HG-G1 护栏参数（decision-log HG，2026-08-28）
G1_FAIL_THRESHOLD = 10      # 连续失败 ≥10 触发护栏
G1_COOLDOWN_MIN = 45        # 冷却 45min（规格 30-60min 取中）
G1_MAX_ROUNDS = 3           # 连败 3 轮 → 降级每日一次
G1_COOLDOWN_KEY = "exec2_cooldown_until"
G1_ROUNDS_KEY = "exec2_fail_rounds"
G1_FAIL_LEDGER_KEY = "exec2_failed"  # +_{date} = 失败品名单


def _today():
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d")


def _log(msg):
    print(f"[{datetime.now(TZ_BJ).strftime('%H:%M:%S')}] {msg}", flush=True)


def scope_rows(scope):
    """取扫描范围（验收③：仅自选+持仓+活跃池，不扩全池）。"""
    conn = db.get_conn()
    try:
        if scope == "watchlist":
            # 方案 B：自选 + 持仓（in_watchlist=1 OR holding=1）
            rows = conn.execute(
                "SELECT id, name, holding, avg_cost, quantity, in_watchlist FROM items "
                "WHERE (in_watchlist=1 OR holding=1) AND good_id>0 ORDER BY id").fetchall()
        else:  # active（方案 A，与活跃池口径一致：notes 无剔除标记）
            rows = conn.execute(
                "SELECT id, name, holding, avg_cost, quantity, in_watchlist FROM items "
                "WHERE good_id>0 AND (in_watchlist=1 OR holding=1 OR notes IS NULL "
                "OR (notes NOT LIKE '%存世量过低%' AND notes NOT LIKE '%活跃池淘汰%' "
                "AND notes NOT LIKE '%贴纸模块停采%')) ORDER BY id").fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def already_pushed(item_id, date):
    """幂等检查（对齐 M2）：同品同日已推送 → 跳过。"""
    conn = db.get_conn()
    try:
        v = db.get_setting(conn, f"{_PUSH_KEY_PREFIX}_{date}_{item_id}", None)
    finally:
        conn.close()
    return bool(v)


def mark_pushed(item_id, date, meta):
    """推送成功留痕（幂等 key，对齐 M2 JSON 值模式）。"""
    conn = db.get_conn()
    try:
        db.set_setting(conn, f"{_PUSH_KEY_PREFIX}_{date}_{item_id}", json.dumps(meta, ensure_ascii=False))
        conn.commit()
    finally:
        conn.close()


# ================= HG-G1 · csQAQ 风控护栏（decision-log HG，2026-08-28）=================

def _get_setting(key, default=""):
    conn = db.get_conn()
    try:
        return db.get_setting(conn, key, default)
    finally:
        conn.close()


def _set_setting(key, value):
    conn = db.get_conn()
    try:
        db.set_setting(conn, key, value)
        conn.commit()
    finally:
        conn.close()


def cooldown_remaining_sec():
    """剩余冷却秒数（0=未冷却）。"""
    v = _get_setting(G1_COOLDOWN_KEY, "")
    if not v:
        return 0
    try:
        until = float(v)
    except (TypeError, ValueError):
        return 0
    return max(0, until - time.time())


def enter_cooldown(reason, dry_run=False):
    """触发冷却：记录 until + 连败轮次 +1 + O4 告警。
    dry_run=True 时告警仅 dry-run 不真实推送（测试/演练用；2026-08-28 修复：冒烟测试曾真实推送钉钉 ~10 次）。"""
    until = time.time() + G1_COOLDOWN_MIN * 60
    _set_setting(G1_COOLDOWN_KEY, str(until))
    rounds = int(_get_setting(G1_ROUNDS_KEY, "0") or 0) + 1
    _set_setting(G1_ROUNDS_KEY, str(rounds))
    _log(f"G1 护栏触发：{reason} → 冷却 {G1_COOLDOWN_MIN}min（连败轮次 {rounds}）")
    try:
        from notify_alert import route_alert
        route_alert("quality", "EXEC-2 风控护栏", 
                    f"连续失败≥{G1_FAIL_THRESHOLD}：{reason}；暂停 {G1_COOLDOWN_MIN}min 冷却（防 csQAQ 封号）；"
                    f"连败轮次 {rounds}/{G1_MAX_ROUNDS}，达上限降级每日一次。", dry_run=dry_run)
    except Exception as exc:
        _log(f"G1 O4 告警异常（不阻断冷却）: {type(exc).__name__}: {str(exc)[:80]}")


def degraded_daily():
    """连败达上限 → 降级每日一次（记录降级标记，后续 run 直接退出）。"""
    rounds = int(_get_setting(G1_ROUNDS_KEY, "0") or 0)
    return rounds >= G1_MAX_ROUNDS


def record_failed(name, reason):
    """失败品入台账（exec2_failed_{date}，下轮补扫用）。"""
    key = G1_FAIL_LEDGER_KEY + "_" + _today()
    ledger = json.loads(_get_setting(key, "[]") or "[]")
    ledger.append({"name": name, "reason": str(reason)[:100], "ts": datetime.now(TZ_BJ).isoformat(timespec="minutes")})
    _set_setting(key, json.dumps(ledger, ensure_ascii=False))


def failed_ledger_today():
    key = G1_FAIL_LEDGER_KEY + "_" + _today()
    try:
        return json.loads(_get_setting(key, "[]") or "[]")
    except Exception:
        return []


def reset_fail_rounds():
    """整轮成功（errors=0）→ 连败轮次清零。"""
    _set_setting(G1_ROUNDS_KEY, "0")


def should_run():
    """G1 门：冷却期内 / 已降级每日一次 → 跳过（不无限重试）。返回 (ok, reason)。"""
    rem = cooldown_remaining_sec()
    if rem > 0:
        return False, f"G1 冷却中（剩余 {int(rem // 60)}min）"
    if degraded_daily():
        return False, "G1 连败已达上限，降级每日一次（明日 18:00 链重试）"
    return True, ""


# ================= HG-G2 · 扫描进度可见性（decision-log HG，2026-08-28）=================

def _progress_file():
    from pathlib import Path as _P
    # 2026-08-28 修复：脚本位于 cs-skin-market 根目录，正确为 parent/"data"（原 parent.parent
    # 多一层，曾写到 cs-model/data/exec2_progress.json——git 仓库根污染 + 位置违反约定）。
    return _P(__file__).resolve().parent / "data" / "exec2_progress.json"


def write_progress(stage, current, total, failed=0, started=None, done=False, note=""):
    """G2：exec2 任务进度落盘（独立文件，source=auto 标注；webapp /exec2 页只读）。"""
    import json as _json
    p = {
        "source": "auto",
        "stage": stage,           # 阶段：大盘刷新/扫描/推送/完成/卡住
        "current": current, "total": total, "failed": failed,
        "started": started or datetime.now(TZ_BJ).isoformat(timespec="seconds"),
        "updated": datetime.now(TZ_BJ).isoformat(timespec="seconds"),
        "done": done, "note": note or "",
    }
    try:
        _progress_file().write_text(_json.dumps(p, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        _log(f"G2 进度落盘失败: {type(exc).__name__}: {str(exc)[:80]}")
    return p


def notify_complete(payload):
    """G2：任务完成/卡住 → O4 钉钉通知。"""
    try:
        from notify_alert import route_alert
        scope = payload.get("scope", "?")
        p = payload.get("progress") or {}
        route_alert("quality", "EXEC-2 盯盘完成",
                    f"scope={scope} items={p.get('total')} pushed={payload.get('pushed')} "
                    f"failed={p.get('failed')} 阶段={p.get('stage')}",
                    dry_run=False)
    except Exception as exc:
        _log(f"G2 完成通知异常（不阻断）: {type(exc).__name__}: {str(exc)[:80]}")


def check_stuck(scan_id, timeout_min=180):
    """G2：卡住检测——进度文件超过 timeout 未更新（由 webapp 轮询调用）。返回 (stuck, note)。"""
    try:
        from pathlib import Path as _P
        fp = _P(__file__).resolve().parent.parent / "data" / ("scan_progress_" + scan_id + ".json")
        if not fp.exists():
            return False, ""
        import json as _json
        d = _json.loads(fp.read_text(encoding="utf-8"))
        ts = d.get("ts") or 0
        if time.time() - float(ts) > timeout_min * 60 and not d.get("done"):
            return True, f"scan_id={scan_id} 卡住（{timeout_min}min 未更新）"
    except Exception:
        pass
    return False, ""


def check_stuck_exec2(timeout_min=180):
    """G2：EXEC-2 自身卡住检测（PM 非阻断登记 2026-08-28 已修）——读 exec2_progress.json，
    以 updated 字段为基准（与 batch_scan 老格式 scan_progress_{id}.json 的 ts 字段区分开；
    check_stuck 保留给 batch_scan 用）。返回 (stuck, note)。webapp /api/exec2/progress 轮询接入。"""
    try:
        fp = _progress_file()
        if not fp.exists():
            return False, ""
        import json as _json
        d = _json.loads(fp.read_text(encoding="utf-8"))
        if d.get("done"):
            return False, ""
        upd = d.get("updated") or ""
        if not upd:
            return False, ""
        from datetime import datetime as _dt
        ts = _dt.fromisoformat(upd).timestamp()
        if time.time() - ts > timeout_min * 60:
            return True, f"exec2 卡住（{timeout_min}min 未更新，updated={upd}）"
    except Exception:
        pass
    return False, ""


async def _scan_one(row, idx, ms, market_th_score, sentiment_score, total_assets, max_stale_hours=0):
    """max_stale_hours（2026-08-28）：watchlist 2h 任务传 1——当日已采超 1h 强制重新采集，
    保证每 2h 轮次拿到真实新数据（此前 3 日缓存窗口导致 2h 任务纯走缓存不刷新）。
    active（18:00 链收尾重算）传 0：当日刚全量采集，复用重算即可。"""
    from pipeline.scan_tasks import _scan_item
    try:
        res = await _scan_item(row, idx, ms, market_th_score, sentiment_score,
                               total_assets=total_assets, force_refresh=False,
                               max_stale_hours=max_stale_hours)
        return res
    except Exception as exc:
        _log(f"  scan FAIL {row['name'][:30]}: {type(exc).__name__}: {str(exc)[:80]}")
        return None


def _family_of(action_label):
    try:
        from pipeline.config import assign_fine_family
        return assign_fine_family(action_label or "")
    except Exception:
        return "base"


def push_buy_signal(res, date, dry_run=False, conn=None):
    """新 buy → S3 意向单推送（create_intention + push_intention，复用闭环链路）。返回推送结果或 None。

    conn 可注入（测试/多环境用临时库）；缺省用生产库。幂等 key 走生产 settings（M2 同款）。
    """
    fd = (res.get("fusion_decision") or {})
    if fd.get("action") not in ("buy", "oversold_buy"):
        return None
    item_id = res.get("id")
    if not item_id or already_pushed(item_id, date):
        return {"skipped": "already_pushed"}
    own = conn is None
    if own:
        conn = db.get_conn()
    try:
        from pipeline import paper_trading as pt
        oid = pt.create_intention(
            conn, item_id=item_id, item_name=res["name"],
            family=_family_of(fd.get("action_label") or ""),
            direction="buy", qty=1,
            ref_price=res.get("price_rmb") or 0,
            reason="EXEC-2 自动盯盘: " + (fd.get("action_label") or "buy"),
            expectancy=None,
            risk_tag=f"limit={fd.get('position_limit') or 0.10}")
        r = pt.push_intention(conn, oid, dry_run=dry_run)
        if not dry_run and r.get("pushed"):
            mark_pushed(item_id, date, {"ts": datetime.now(TZ_BJ).isoformat(timespec="minutes"),
                                        "order_id": oid, "label": fd.get("action_label") or ""})
        return r
    finally:
        if own:
            conn.close()


async def main_async(args):
    from pipeline.scan_tasks import _scan_progress, _persist_scan_progress  # noqa: F401（确保模块加载）
    from pipeline.collector import fetch_market_index
    from webapp.analysis_service import market_snapshot

    # HG-G1 入口门：冷却/降级 → 跳过（不无限重试，防 csQAQ 封号）
    ok, skip_reason = should_run()
    if not ok:
        _log(f"EXEC-2 跳过：{skip_reason}")
        print(f"RESULT mode=SKIP scope={args.scope} reason={skip_reason}")
        return 0

    rows = scope_rows(args.scope)
    date = _today()
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    _log(f"EXEC-2 {mode} scope={args.scope} items={len(rows)} date={date}")
    started = datetime.now(TZ_BJ).isoformat(timespec="seconds")
    write_progress("启动", 0, len(rows), started=started, note=f"scope={args.scope}")

    # HC 修订段（2026-08-28，②修订版采纳）：方案 B 每 2h 先刷大盘指数再跑 watchlist——
    # 大盘指数是融合决策输入（market_th/周期），2h 链期间 18:00 采集已过、指数须保持新鲜。
    # 复用 run_daily_collect.collect_market_index（单请求 upsert，run_daily_collect.py:58 同款）；
    # 失败不阻断（回退旧指数，扫描仍执行），dry-run 亦执行（保持与 APPLY 同链路验证）。
    if args.scope == "watchlist":
        write_progress("大盘刷新", 0, len(rows), failed=0, started=started)
        try:
            import run_daily_collect as _rdc
            _ok = await asyncio.to_thread(_rdc.collect_market_index)
            _log(f"大盘指数刷新: {'OK' if _ok else 'FAIL（回退旧指数，扫描继续）'}")
        except Exception as exc:
            _log(f"大盘指数刷新异常（不阻断扫描）: {type(exc).__name__}: {str(exc)[:80]}")

    idx = await asyncio.to_thread(fetch_market_index)
    if idx is None or idx.value == 0:
        idx = type("obj", (object,), {"value": 0, "change_7d": 0})()
    ms = market_snapshot()
    market_th_score = ms["th"]
    sentiment_score = ms["sentiment"]
    conn_r = db.get_conn()
    try:
        total_assets = float(db.get_setting(conn_r, "total_assets", 0) or 0)
    finally:
        conn_r.close()

    # 失败品台账补扫（G1）：今日失败名单补入本轮 rows（按 name 去重）。
    # 同范围场景失败品本就在 rows（自然在轮）→ 无需操作；跨范围（如 active→watchlist）
    # 时按 name 从 items 补查完整行加入，补扫真实生效（PM 非阻断登记 2026-08-28 已修）。
    today_failed = [f["name"] for f in failed_ledger_today()]
    if today_failed:
        in_rows = {r["name"] for r in rows}
        missing = [n for n in today_failed if n not in in_rows]
        if missing:
            _conn = db.get_conn()
            try:
                _q = ",".join("?" * len(missing))
                _extra = [dict(r) for r in _conn.execute(
                    f"SELECT id, name, holding, avg_cost, quantity FROM items "
                    f"WHERE name IN ({_q})", missing).fetchall()]
            finally:
                _conn.close()
            rows = rows + _extra
            _log(f"G1 失败台账补扫：跨范围补入 {len(_extra)} 品")
        else:
            _log(f"G1 失败台账：今日失败 {len(today_failed)} 品已在本轮（同范围）")

    pushed, skipped, no_signal, errors = 0, 0, 0, 0
    fail_streak = 0
    consec_fail = 0  # 连续失败计数（G1 触发判定）
    t0 = time.time()
    # 2026-08-28：watchlist 2h 任务需真实刷新（当日已采超 1h 强制重新采集）；
    # active（18:00 链收尾）复用当日采集数据重算即可（max_stale_hours=0 保持默认 3 日窗口）。
    max_stale_hours = 1 if args.scope == "watchlist" else 0
    for i, row in enumerate(rows, 1):
        res = await _scan_one(row, idx, ms, market_th_score, sentiment_score, total_assets,
                              max_stale_hours=max_stale_hours)
        if res is None or res.get("error"):
            errors += 1
            consec_fail += 1
            fail_streak += 1
            record_failed(row["name"], (res or {}).get("error") or "scan_fail")
            # G1：连续失败达阈值 → 暂停 + 冷却 + O4 告警（不无限重试）
            if consec_fail >= G1_FAIL_THRESHOLD:
                enter_cooldown(f"连续失败 {consec_fail} 品（{row['name']}）")
                write_progress("G1 冷却", i, len(rows), failed=errors, started=started,
                               note=f"连续失败{consec_fail}触发护栏")
                _log(f"G1 触发：连续失败 {consec_fail} ≥ {G1_FAIL_THRESHOLD}，任务暂停进入冷却")
                print(f"RESULT mode={mode} scope={args.scope} items={len(rows)} pushed={pushed} "
                      f"skipped={skipped} no_signal={no_signal} errors={errors} gate=cooldown")
                return 0
            continue
        consec_fail = 0
        r = push_buy_signal(res, date, dry_run=args.dry_run)
        if r is None:
            no_signal += 1
        elif r.get("skipped"):
            skipped += 1
        else:
            pushed += 1
            _log(f"  push buy {res['name'][:30]} limit={res.get('position_limit')}")
        # G2 进度（每 10 品更新一次，含失败数/ETA）
        if i % 10 == 0 or i == len(rows):
            elapsed = time.time() - t0
            eta = int(elapsed / i * (len(rows) - i)) if i > 0 else 0
            write_progress("扫描", i, len(rows), failed=errors, started=started,
                           note=f"pushed={pushed} ETA={eta}s")

    # 整轮成功（errors=0）→ 连败轮次清零（G1 降级恢复）
    if errors == 0 and fail_streak == 0:
        reset_fail_rounds()

    write_progress("完成", len(rows), len(rows), failed=errors, started=started, done=True,
                   note=f"pushed={pushed} skipped={skipped} no_signal={no_signal}")
    _log(f"EXEC-2 done scope={args.scope} items={len(rows)} pushed={pushed} skipped={skipped} no_signal={no_signal} errors={errors}")
    print(f"RESULT mode={mode} scope={args.scope} items={len(rows)} pushed={pushed} skipped={skipped} no_signal={no_signal} errors={errors}")
    # G2：完成 → O4 通知（非 dry-run）
    if not args.dry_run:
        notify_complete({"scope": args.scope, "pushed": pushed,
                         "progress": {"total": len(rows), "failed": errors, "stage": "完成"}})
    return 0


def main():
    ap = argparse.ArgumentParser(description="EXEC-2 自动盯盘链（活跃池/自选+持仓融合决策重算 + 新 buy S3 推送）")
    ap.add_argument("--scope", default="active", choices=["active", "watchlist"],
                    help="active=活跃池（方案 A，18:00 收尾）/ watchlist=自选+持仓（方案 B，2h 定时）")
    ap.add_argument("--dry-run", action="store_true", help="仅扫描不推送")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR exec2_auto_watch: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
