# -*- coding: utf-8 -*-
"""运维层核心模块（Wave6 O1–O4，2026-08-27 落地；出处 = roadmap v82 卡 / decision-log DC / Wave6 落地条目）。

六层架构 §6.2 运维层四点（roadmap v82 O1–O4 卡）：
  O1 交易级监控   run_ops_monitor()：读 S2 模拟盘台账（paper_* 表 + paper_trading_status.json）
                 → 对账差异 / 回撤破阈 / 连续拒单 / 数据源异常 → FAIL 项走 O4 告警；
                 自动急停条件（回撤破阈/连续拒单/数据源异常/采集闸门触警）→ auto_escalate()
  O2 kill switch  data/ops_kill_switch.json（全局/策略级 × 手动/自动双通道），独立于业务链——
                 状态文件可被 CLI（ops_tool.py）直接读写，webapp 卡死也能触发（上层卡死也能停）
  O3 审计/日志    config_audit() → data/config_audit_log.jsonl（谁/何时/改了什么/依据哪个 decision-log 条目）；
                 log_event() → data/ops_log.jsonl（统一 JSONL，级别/来源/可检索）
  O4 告警分级路由 见 notify_alert.py::route_alert（三档：采集 collect / 质量 quality / 交易 trade）

全部阈值/路由规则在 config.OPS_RULES（已登记 PARAM_REGIME 参数台账，含出处）。
设计约束：
  - 一切写入 append-only JSONL（审计/日志），与 D3 cleaning_ledger / D4 provenance 同构（机器可读、可追溯）；
  - kill switch 只允许「手动/自动 → 开闸」，解除必须人工（自动急停不自动恢复，防震荡）；
  - 所有函数支持 data_dir 覆盖（测试/多环境用），默认 config.DATA_DIR。
"""
import json
import os
from datetime import datetime

from .config import DATA_DIR, OPS_RULES, TZ_BJ

# ---- 路径（默认生产 data/；测试可用 data_dir 覆盖）----
KILL_FILE_NAME = "ops_kill_switch.json"
AUDIT_FILE_NAME = "config_audit_log.jsonl"
OPS_LOG_FILE_NAME = "ops_log.jsonl"
PAPER_PEAK_FILE_NAME = "ops_paper_peak.json"
MONITOR_LATEST_NAME = "ops_monitor_latest.json"

_SCOPES = ("global", "paper", "notify")  # paper=模拟盘出单/建仓；notify=钉钉通知（S3 出单/通知并入 paper/notify）


def _now():
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")


def _p(data_dir, name):
    return os.path.join(data_dir or DATA_DIR, name)


# ======================= O3 结构化日志 + 操作审计 =======================

def log_event(level, source, msg, data_dir=None, **fields):
    """统一结构化日志：append-only JSONL（data/ops_log.jsonl），级别/来源/消息/字段。

    level 取值约定：info / warn / error / kill / audit / monitor（自由扩展，便于检索）。
    写失败静默（日志不阻断业务）。
    """
    rec = {"ts": _now(), "level": level, "source": source, "msg": msg, **fields}
    try:
        with open(_p(data_dir, OPS_LOG_FILE_NAME), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


def config_audit(who, key, old, new, decision_log_ref, note="", data_dir=None):
    """O3 配置/参数变更审计：谁、何时、改了什么、依据哪个 decision-log 条目。

    参数调整走预注册（§3.5/§5.4）的留痕机制；与 D4 provenance 同构（JSONL append-only）。
    """
    rec = {"ts": _now(), "who": who, "key": key, "old": old,
           "new": new, "decision_log_ref": decision_log_ref or "", "note": note or ""}
    try:
        with open(_p(data_dir, AUDIT_FILE_NAME), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


def list_audit(limit=50, key=None, data_dir=None):
    """查询审计台账（新→旧），可选按 key 过滤。"""
    out = []
    try:
        with open(_p(data_dir, AUDIT_FILE_NAME), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        return []
    out.reverse()
    if key:
        out = [r for r in out if r.get("key") == key]
    return out[:limit]


# ======================= O2 kill switch（全局/策略级 × 手动/自动）=======================

def _default_kill_state():
    return {"global": False,
            "strategies": {"paper": False, "notify": False},
            "auto": {},                      # {"rule": ts} 自动急停记录（仅手动解除）
            "updated_at": None, "by": None, "reason": None, "decision_log_ref": None}


def kill_switch_state(data_dir=None):
    """读 kill switch 状态；文件缺失/损坏 → 默认全开（不拦截）。"""
    try:
        with open(_p(data_dir, KILL_FILE_NAME), encoding="utf-8") as f:
            st = json.load(f)
        st.setdefault("strategies", {})
        for s in _SCOPES[1:]:
            st["strategies"].setdefault(s, False)
        st.setdefault("global", False)
        st.setdefault("auto", {})
        return st
    except FileNotFoundError:
        return _default_kill_state()
    except Exception:
        return _default_kill_state()


def is_blocked(scope, data_dir=None):
    """业务链闸门：scope ∈ paper/notify/global。全局闸停或该策略级闸停 → True。"""
    if scope not in _SCOPES:
        return False
    st = kill_switch_state(data_dir)
    if st.get("global"):
        return True
    if scope == "global":
        return bool(st.get("global"))
    return bool(st.get("strategies", {}).get(scope))


def set_kill_switch(scope, blocked, by, reason, decision_log_ref=None, data_dir=None):
    """O2 kill switch 写入：全局（global）/ 策略级（paper/notify）。

    - 变更自动落 O3 审计台账（含 decision-log 引用）；
    - 原子写（tmp + replace），webapp 卡死时 CLI 仍可直接读写（独立于业务链）。
    """
    if scope not in _SCOPES:
        raise ValueError(f"scope 必须为 {_SCOPES}，收到 {scope!r}")
    st = kill_switch_state(data_dir)
    old = st.get("global") if scope == "global" else st["strategies"].get(scope)
    if scope == "global":
        st["global"] = bool(blocked)
    else:
        st["strategies"][scope] = bool(blocked)
    # ③审计建议（DF，2026-08-27）：手动解除时清空 auto 急停记录（防残留误导状态）
    if not blocked and scope != "global" and not str(by).startswith("auto:"):
        st["auto"] = {}
    st["updated_at"] = _now()
    st["by"] = by
    st["reason"] = reason
    if decision_log_ref:
        st["decision_log_ref"] = decision_log_ref
    _atomic_write(_p(data_dir, KILL_FILE_NAME), st)
    config_audit(who=by, key=f"kill_switch.{scope}", old=old, new=bool(blocked),
                 decision_log_ref=decision_log_ref or "", note=reason or "", data_dir=data_dir)
    log_event("kill", "kill_switch", f"{scope}={bool(blocked)} by {by}: {reason or ''}",
              data_dir=data_dir, scope=scope, blocked=bool(blocked))
    return st


def auto_escalate(rule, reason, scope="paper", data_dir=None):
    """O2 自动急停（连续拒单/回撤破阈/数据源异常/采集闸门触警）。

    - 总开关 config.OPS_RULES.kill_switch.auto=False 时仅记录不闸停（运维可整体关闭自动急停）；
    - 只允许「自动 → 开闸」，不自动恢复；已闸停时刷新 auto 记录，不重复审计。
    """
    if not OPS_RULES.get("kill_switch", {}).get("auto", True):
        log_event("info", "auto_kill", f"自动急停已关闭（规则 {rule}），仅记录", data_dir=data_dir, rule=rule)
        return None
    if is_blocked(scope, data_dir):
        st = kill_switch_state(data_dir)
        st.setdefault("auto", {})[rule] = _now()
        _atomic_write(_p(data_dir, KILL_FILE_NAME), st)
        log_event("info", "auto_kill", f"{scope} 已闸停，规则 {rule} 记录刷新", data_dir=data_dir, rule=rule)
        return st
    st = set_kill_switch(scope, True, by=f"auto:{rule}", reason=reason, data_dir=data_dir)
    st.setdefault("auto", {})[rule] = _now()
    _atomic_write(_p(data_dir, KILL_FILE_NAME), st)
    log_event("warn", "auto_kill", f"自动急停触发 {scope}={rule}: {reason}", data_dir=data_dir, rule=rule)
    return st


def _atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ======================= O1 交易级监控 =======================

def _read_status_json(status_path):
    try:
        with open(status_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _paper_equity_from_db(conn):
    """S2 台账实库重算权益：cash + Σ(open qty × 最新价)。"""
    cash, _ = 1000000.0, 1000000.0
    try:
        r = conn.execute("SELECT cash, initial FROM paper_account WHERE id=1").fetchone()
        if r:
            cash = r["cash"]
    except Exception:
        pass
    eq = cash
    try:
        rows = conn.execute("SELECT item_id, qty FROM paper_positions WHERE closed=0").fetchall()
        for p in rows:
            r = conn.execute("SELECT price_rmb FROM price_history WHERE item_id=? AND price_rmb IS NOT NULL "
                             "ORDER BY date DESC LIMIT 1", (p["item_id"],)).fetchone()
            if r:
                eq += p["qty"] * r["price_rmb"]
    except Exception:
        pass
    return eq


def run_ops_monitor(db_path=None, status_path=None, data_dir=None, health_fail=0):
    """O1 交易级监控：读 S2/S3 台账 → 检查清单（PASS/FAIL/WARN）+ 自动急停 + 告警请求。

    返回: {"status": "pass|fail", "date", "checks": [{name, level, detail}],
           "auto_killed": [rule...], "alerts": [{level, title, text}], "peak": float|None}
    """
    import sqlite3
    from . import db as _db
    data_dir = data_dir or DATA_DIR
    rules = OPS_RULES.get("trade_monitor", {})
    checks = []
    alerts = []
    auto_killed = []

    conn = sqlite3.connect(db_path or str(_db.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        today = datetime.now(TZ_BJ).strftime("%Y-%m-%d")

        # ---- ① 台账对账差异（status.json 权益 vs 实库重算）----
        sp = status_path or _p(DATA_DIR, "paper_trading_status.json")
        st = _read_status_json(sp)
        if not st:
            checks.append({"name": "模拟盘台账对账", "level": "WARN",
                           "detail": "无 paper_trading_status.json（模拟盘尚无每日产物/未建仓），对账跳过"})
        else:
            eq_st = st.get("equity")
            eq_db = _paper_equity_from_db(conn)
            if eq_st:
                diff = abs(eq_db - eq_st) / max(abs(eq_st), 1.0) * 100
                thr = rules.get("reconcile_diff_pct", 1.0)
                if diff >= thr:
                    checks.append({"name": "模拟盘台账对账", "level": "FAIL",
                                   "detail": f"status.equity={eq_st:.2f} vs 实库重算={eq_db:.2f}，差异 {diff:.2f}% ≥ 阈值 {thr}%"})
                    alerts.append({"level": "trade", "title": "【交易】模拟盘台账对账差异",
                                   "text": f"status.equity={eq_st:.2f} vs 实库重算={eq_db:.2f}，差异 {diff:.2f}% ≥ {thr}%。检查 paper_* 表与 status.json 是否被外部改动。"})
                else:
                    checks.append({"name": "模拟盘台账对账", "level": "PASS",
                                   "detail": f"status.equity={eq_st:.2f} vs 实库重算={eq_db:.2f}，差异 {diff:.2f}%"})
            else:
                checks.append({"name": "模拟盘台账对账", "level": "WARN", "detail": "status.json 无 equity 字段"})

        # ---- ② 回撤破阈（自峰值，峰值台账 ops_paper_peak.json）----
        eq = _paper_equity_from_db(conn)
        peak_rec = {}
        try:
            with open(_p(data_dir, PAPER_PEAK_FILE_NAME), encoding="utf-8") as f:
                peak_rec = json.load(f)
        except Exception:
            peak_rec = {}
        peak = peak_rec.get("peak") if isinstance(peak_rec.get("peak"), (int, float)) else None
        if peak is None or eq > peak:
            peak = eq
            peak_rec = {"peak": round(peak, 2), "ts": _now()}
            _atomic_write(_p(data_dir, PAPER_PEAK_FILE_NAME), peak_rec)
        dd = (peak - eq) / peak * 100 if peak and peak > 0 else 0.0
        thr_dd = rules.get("max_drawdown_pct", 15.0)
        if dd >= thr_dd:
            checks.append({"name": "模拟盘回撤", "level": "FAIL",
                           "detail": f"自峰值回撤 {dd:.2f}% ≥ 阈值 {thr_dd}%（peak={peak:.2f}, equity={eq:.2f}）"})
            alerts.append({"level": "trade", "title": "【交易】模拟盘回撤破阈",
                           "text": f"自峰值回撤 {dd:.2f}% ≥ {thr_dd}%。触发自动急停（paper）。"})
            auto_escalate("drawdown", f"模拟盘自峰值回撤 {dd:.2f}% ≥ {thr_dd}%", scope="paper", data_dir=data_dir)
            auto_killed.append("drawdown")
        else:
            checks.append({"name": "模拟盘回撤", "level": "PASS",
                           "detail": f"自峰值回撤 {dd:.2f}%（阈值 {thr_dd}%）"})

        # ---- ③ 连续拒单（当日 buy 信号数 − 当日已建仓数）----
        try:
            n_sig = conn.execute(
                "SELECT COUNT(*) FROM signal_tracking WHERE signal_date=? AND action IN ('buy','oversold_buy')",
                (today,)).fetchone()[0]
            n_open = conn.execute(
                "SELECT COUNT(*) FROM paper_positions WHERE signal_date=?", (today,)).fetchone()[0]
            rejects = max(0, n_sig - n_open)
            thr_r = rules.get("max_rejects", 3)
            if rejects >= thr_r:
                checks.append({"name": "模拟盘连续拒单", "level": "FAIL",
                               "detail": f"当日 buy 信号 {n_sig} - 已建仓 {n_open} = 拒单/未建仓 {rejects} ≥ 阈值 {thr_r}"})
                alerts.append({"level": "trade", "title": "【交易】模拟盘连续拒单",
                               "text": f"当日拒单/未建仓 {rejects} 笔 ≥ {thr_r}。触发自动急停（paper）。"})
                auto_escalate("rejects", f"当日拒单/未建仓 {rejects} ≥ {thr_r}", scope="paper", data_dir=data_dir)
                auto_killed.append("rejects")
            else:
                checks.append({"name": "模拟盘连续拒单", "level": "PASS",
                               "detail": f"当日 buy 信号 {n_sig} / 已建仓 {n_open} / 拒单 {rejects}"})
        except Exception as e:
            checks.append({"name": "模拟盘连续拒单", "level": "WARN", "detail": f"signal_tracking 读取异常: {e}"})

        # ---- ④ 数据源新鲜度（最新 K 线日距今）+ 采集闸门（健康检查 FAIL 数）----
        from datetime import date as _date
        stale = 999
        try:
            r = conn.execute("SELECT MAX(date) FROM price_history").fetchone()
            if r and r[0]:
                stale = (_date.today() - _date.fromisoformat(r[0])).days
        except Exception:
            pass
        thr_s = rules.get("stale_data_days", 2)
        if stale >= thr_s:
            checks.append({"name": "数据源新鲜度", "level": "FAIL",
                           "detail": f"最新 K 线 {stale} 天前 ≥ 阈值 {thr_s} 天"})
            alerts.append({"level": "quality", "title": "【质量】数据源新鲜度异常",
                           "text": f"最新 K 线距今 {stale} 天 ≥ {thr_s} 天。触发自动急停（paper）。"})
            auto_escalate("stale_data", f"数据源最新 K 线距今 {stale} 天", scope="paper", data_dir=data_dir)
            auto_killed.append("stale_data")
        else:
            checks.append({"name": "数据源新鲜度", "level": "PASS", "detail": f"最新 K 线距今 {stale} 天"})
        if health_fail:
            checks.append({"name": "采集闸门", "level": "FAIL",
                           "detail": f"当日数据健康检查 FAIL {health_fail} 项"})
            alerts.append({"level": "quality", "title": "【质量】采集闸门触警",
                           "text": f"当日数据健康检查 FAIL {health_fail} 项。触发自动急停（paper）。"})
            auto_escalate("collect_gate", f"当日数据健康检查 FAIL {health_fail} 项", scope="paper", data_dir=data_dir)
            auto_killed.append("collect_gate")
        else:
            checks.append({"name": "采集闸门", "level": "PASS", "detail": "当日健康检查无 FAIL"})

        # ---- ⑤ O4 quality 联动（2026-08-27 Wave1 并入，补齐 O4 验收②）----
        # ⑤a 清洗台账消费（D3 联动）：当日 cleaning_ledger 触警计数 → 轻提醒 quality 告警（纯统计，不判 FAIL/不急停）
        try:
            from pipeline.cleaning_ledger import read_since as _cl_read
            _cl_rows = _cl_read(today)
            if _cl_rows:
                _cl_rules = sorted({r.get("rule") or "?" for r in _cl_rows})
                checks.append({"name": "清洗台账消费", "level": "WARN",
                               "detail": f"cleaning_ledger 当日 {len(_cl_rows)} 条触警（规则: {', '.join(_cl_rules[:5])}）"})
                alerts.append({"level": "quality", "title": "【质量】清洗闸门触警",
                               "text": f"cleaning_ledger 当日 {len(_cl_rows)} 条触警（{', '.join(_cl_rules[:5])}）。查看 data/cleaning_ledger.jsonl。"})
            else:
                checks.append({"name": "清洗台账消费", "level": "PASS", "detail": "cleaning_ledger 当日 0 触警"})
        except Exception as e:
            checks.append({"name": "清洗台账消费", "level": "WARN", "detail": f"cleaning_ledger 读取异常: {e}"})
        # ⑤b 备份新鲜度（备份联动）：data/backup/ 最新 market_*.db 年龄超阈 → FAIL + quality 告警（非自动急停条件）
        _bdir = os.path.join(data_dir or DATA_DIR, "backup")
        try:
            _bfiles = [f for f in os.listdir(_bdir) if f.startswith("market_") and f.endswith(".db")]
        except OSError:
            _bfiles = []
        thr_b = rules.get("backup_stale_days", 2)
        if not _bfiles:
            checks.append({"name": "备份新鲜度", "level": "WARN",
                           "detail": "无备份文件（环境未配置每日备份计划任务/未跑 backup_db.py），跳过"})
        else:
            _newest = max(os.path.getmtime(os.path.join(_bdir, f)) for f in _bfiles)
            _age = (_date.today() - _date.fromtimestamp(_newest)).days
            if _age >= thr_b:
                checks.append({"name": "备份新鲜度", "level": "FAIL",
                               "detail": f"最新备份距今 {_age} 天 ≥ 阈值 {thr_b} 天（每日 23:30 备份，对齐 backup_db 保留 14 份）"})
                alerts.append({"level": "quality", "title": "【质量】备份新鲜度异常",
                               "text": f"最新备份距今 {_age} 天 ≥ {thr_b} 天。检查备份计划任务/backup_db.py。"})
            else:
                checks.append({"name": "备份新鲜度", "level": "PASS", "detail": f"最新备份距今 {_age} 天"})

        # ---- ⑥ S3 闭环监控（意向单/回报，2026-08-27 S3 落地后读 paper_orders）----
        try:
            from pipeline.paper_trading import unreported_orders as _uo
            _unrep = _uo(conn, timeout_hours=rules.get("report_timeout_hours", 24))
            if _unrep:
                checks.append({"name": "S3 回报超时", "level": "WARN",
                               "detail": f"{len(_unrep)} 笔意向单未回报超时（> {rules.get('report_timeout_hours', 24)}h，首笔: {_unrep[0]['item_name']}）"})
            else:
                checks.append({"name": "S3 回报超时", "level": "PASS",
                               "detail": "无未回报超时意向单"})
        except Exception as e:
            checks.append({"name": "S3 回报超时", "level": "WARN",
                           "detail": f"paper_orders 未回报检查异常（S3 表未就绪则忽略）: {e}"})

    finally:
        conn.close()

    n_fail = sum(1 for c in checks if c["level"] == "FAIL")
    status = "fail" if n_fail else "pass"
    out = {"status": status, "date": datetime.now(TZ_BJ).strftime("%Y-%m-%d"),
           "checks": checks, "fail_count": n_fail,
           "auto_killed": auto_killed, "alerts": alerts, "peak": peak_rec.get("peak")}
    try:
        _atomic_write(_p(data_dir, MONITOR_LATEST_NAME), out)
    except Exception:
        pass
    log_event("monitor", "ops_monitor", f"status={status} FAIL={n_fail} auto_killed={auto_killed or '无'}",
              data_dir=data_dir, status=status, fail_count=n_fail, auto_killed=auto_killed)
    return out
