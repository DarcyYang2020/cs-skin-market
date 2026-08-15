# -*- coding: utf-8 -*-
"""J-2 三通道监测（2026-08-10 解除冻结期：监测数据照常收集，不再作为禁止调参闸门）。

读 HIST-FULL 基线 item_backtest_full_2025.json（317 信号 v2-T4/T5）+ signal_event_counts.json（事件计数）；CLEAN-CUR 仅展示参考，不参与 C 通道告警。
计算三通道状态（样本完整性/胜率健康度提示项）：
  A. 独立恐慌市场事件 >=3（自然积累，不阻塞）；计数源=signal_event_counts.json display_keys.panic.events
     （信号派生事件簇口径：365d 回放窗口内 action_label 含「恐慌」信号 ±3 天去簇；2025-10 五合一已滑出窗口不计，
       市场独立事件实为 2 个，2026-08-12 核对，见 decision-log 同条目）
  B. v2 引擎样本积累 >=260 天（自 2026-08-07 v2 引擎起点，约 2027-04-25 覆盖完整牛熊循环）
  C. 胜率监测：buy 连续 2 月 14d<70% 或月度 14d<80%/30d<55%
输出 data/j2_channel_status.json，dashboard 数据积累进度卡渲染。
口径注意：C 通道当前为「HIST-FULL 去量 v2 317 信号回放」近似（生产实盘信号跟踪尚未建立）；CLEAN-CUR 仅展示参考。
2026-08-10 事件簇纪律复核（probe_c_channel_cluster_review.py）：6 月劣化为独立簇（06-12~21）而非恐慌簇退出——
恐慌簇(05-22~31) win30 76.3%(net 口径)/79.6%(fwd 口径) 优秀，avg 仍正；6 月簇 win30 42.4% 但 avg30 +9.65 期望仍正、单事件簇，按事件级样本不足处理。
"""
import io
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "data" / "item_backtest_full_2025.json"
SIGNAL_EVENTS = BASE / "data" / "signal_event_counts.json"
OUT = BASE / "data" / "j2_channel_status.json"

CLUSTER_GAP = 4  # 同簇定义：距上一保留信号 <4 天则跳过（±3 天簇，与 j1_event_counts 一致）

# ---- 阈值单一事实源 (Phase 0 单源化): 全部从 pipeline.config 读取，禁止本地硬编码 ----
# 改阈值须同步 PARAM_REGIME["monitors"] 文案，并重跑本脚本刷新 data/j2_channel_status.json
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "references"))
from pipeline.config import PARAM_REGIME, J2_THRESHOLDS, ENGINE_VERSION, SIGNAL_FAMILY_TAXONOMY
import j1_event_counts as j1  # 族级划分单一事实源（action_label 关键词，与 signal_event_counts.json 同口径）

MONITOR_START = PARAM_REGIME["monitor_start"]
SAMPLE_TARGET_DAYS = PARAM_REGIME["sample_target_days"]
A_THRESHOLD = J2_THRESHOLDS["a_events"]
B_THRESHOLD_DAYS = J2_THRESHOLDS["b_days"]
C14_MONTH = J2_THRESHOLDS["c14_month"]
C30_MONTH = J2_THRESHOLDS["c30_month"]
C14_2M = J2_THRESHOLDS["c14_2m"]
PROD_MIN_FILLED14 = 20  # 实盘判定门槛: 回填满 20 条后实盘胜率纳入判定（Phase 2b）
# C 通道族级失效监测（第四批 ②，2026-08-12）：族级样本稀疏，min_n 由全局 10 降至 5；阈值见 config.J2_THRESHOLDS
FAMILY_MIN_N = J2_THRESHOLDS["family_min_n"]
FAMILY_C14_MONTH = J2_THRESHOLDS["family_c14_month"]
FAMILY_C30_MONTH = J2_THRESHOLDS["family_c30_month"]
FAMILY_C14_2M = J2_THRESHOLDS["family_c14_2m"]

FAMILY_LABELS = SIGNAL_FAMILY_TAXONOMY["fine_labels"]


def _load(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def _load_benchmark():
    p = BASE / "data" / "benchmark_compare.json"
    if not p.exists():
        return None
    try:
        return _load(p)
    except Exception:
        return None


def _cluster_dedup(recs):
    kept = []
    last = None
    for s in sorted(recs, key=lambda x: x["date"]):
        if last is None:
            kept.append(s)
            last = s["date"]
        else:
            d0 = date.fromisoformat(last)
            d1 = date.fromisoformat(s["date"])
            if (d1 - d0).days >= CLUSTER_GAP:
                kept.append(s)
                last = s["date"]
    return kept


def _wr(recs, field):
    v = [s[field] for s in recs if isinstance(s.get(field), (int, float))]
    if not v:
        return None, 0
    return round(100.0 * sum(1 for x in v if x > 0) / len(v), 1), len(v)


def _avg(recs, field):
    v = [s[field] for s in recs if isinstance(s.get(field), (int, float))]
    if not v:
        return None
    return round(sum(v) / len(v), 2)


def _monthly(sigs):
    by_month = defaultdict(list)
    for s in sigs:
        by_month[s.get("date", "")[:7]].append(s)
    out = {}
    for m in sorted(by_month):
        grp = by_month[m]
        dg = _cluster_dedup(grp)
        w14, n14 = _wr(grp, "fwd14")
        w30, n30 = _wr(grp, "fwd30")
        d14, dn14 = _wr(dg, "fwd14")
        d30, dn30 = _wr(dg, "fwd30")
        a14 = _avg(grp, "net14")
        a30 = _avg(grp, "net30")
        da14 = _avg(dg, "net14")
        da30 = _avg(dg, "net30")
        out[m] = {
            "n": len(grp), "win14": w14, "win30": w30,
            "avg14_net": a14, "avg30_net": a30,
            "dedup_n": len(dg), "dedup_win14": d14, "dedup_win30": d30,
            "dedup_avg14_net": da14, "dedup_avg30_net": da30,
        }
    return out


def _channel_c(sigs):
    monthly = _monthly(sigs)
    rows = []
    months = sorted(monthly)
    for m in months:
        r = monthly[m]
        flags = []
        if r["n"] >= 10:
            if r["win14"] is not None and r["win14"] < C14_MONTH:
                flags.append("14d " + str(r["win14"]) + "% < " + str(int(C14_MONTH)) + "%")
            if r["win30"] is not None and r["win30"] < C30_MONTH:
                flags.append("30d " + str(r["win30"]) + "% < " + str(int(C30_MONTH)) + "%")
            if r["avg14_net"] is not None and r["avg14_net"] < 0:
                flags.append("14d 期望负 " + str(r["avg14_net"]) + "%")
            if r["avg30_net"] is not None and r["avg30_net"] < 0:
                flags.append("30d 期望负 " + str(r["avg30_net"]) + "%")
        if r["dedup_n"] >= 10:
            if r["dedup_win14"] is not None and r["dedup_win14"] < C14_MONTH:
                flags.append("去簇14d " + str(r["dedup_win14"]) + "% < " + str(int(C14_MONTH)) + "%")
            if r["dedup_win30"] is not None and r["dedup_win30"] < C30_MONTH:
                flags.append("去簇30d " + str(r["dedup_win30"]) + "% < " + str(int(C30_MONTH)) + "%")
        rows.append({"month": m, "n": r["n"], "win14": r["win14"], "win30": r["win30"],
                     "avg14_net": r["avg14_net"], "avg30_net": r["avg30_net"],
                     "dedup_n": r["dedup_n"], "dedup_win14": r["dedup_win14"],
                     "dedup_win30": r["dedup_win30"], "dedup_avg14_net": r["dedup_avg14_net"],
                     "dedup_avg30_net": r["dedup_avg30_net"], "flags": flags})
    two_month = []
    for i in range(1, len(months)):
        m1, m2 = months[i - 1], months[i]
        w1, w2 = monthly[m1]["win14"], monthly[m2]["win14"]
        if w1 is not None and w2 is not None and w1 < C14_2M and w2 < C14_2M:
            two_month.append(m1 + "+" + m2 + " 连续2月14d " + str(w1) + "%/" + str(w2) + "% < " + str(int(C14_2M)) + "%")
    return {"monthly": rows, "two_month_flags": two_month}


def _channel_c_family(sigs):
    """C 通道族级失效监测（第四批 ②，2026-08-12）：J-2 C 通道阈值下钻到族级。
    族划分复用 j1_event_counts.assign_family（action_label 关键词，单一事实源）；
    各族月度胜率复用 _monthly（含 ±3 天去簇口径）；n>=FAMILY_MIN_N 生效，
    flag 规则：14d<FAMILY_C14_MONTH / 30d<FAMILY_C30_MONTH / 连续 2 月 14d<FAMILY_C14_2M。
    纯监测提示项（非决策参数），供 signal-family-registry 的 failure_signal 早期预警对照。"""
    by_fam = defaultdict(list)
    for s in sigs:
        by_fam[j1.assign_family(s.get("action_label") or "")].append(s)
    families = {}
    for key in sorted(by_fam):
        grp = by_fam[key]
        monthly = _monthly(grp)
        months = sorted(monthly)
        rows = []
        two_month = []
        for m in months:
            r = monthly[m]
            flags = []
            if r["n"] >= FAMILY_MIN_N:
                if r["win14"] is not None and r["win14"] < FAMILY_C14_MONTH:
                    flags.append("14d " + str(r["win14"]) + "% < " + str(int(FAMILY_C14_MONTH)) + "%")
                if r["win30"] is not None and r["win30"] < FAMILY_C30_MONTH:
                    flags.append("30d " + str(r["win30"]) + "% < " + str(int(FAMILY_C30_MONTH)) + "%")
                if r["avg14_net"] is not None and r["avg14_net"] < 0:
                    flags.append("14d 期望负 " + str(r["avg14_net"]) + "%")
                if r["avg30_net"] is not None and r["avg30_net"] < 0:
                    flags.append("30d 期望负 " + str(r["avg30_net"]) + "%")
            if r["dedup_n"] >= FAMILY_MIN_N:
                if r["dedup_win14"] is not None and r["dedup_win14"] < FAMILY_C14_MONTH:
                    flags.append("去簇14d " + str(r["dedup_win14"]) + "% < " + str(int(FAMILY_C14_MONTH)) + "%")
                if r["dedup_win30"] is not None and r["dedup_win30"] < FAMILY_C30_MONTH:
                    flags.append("去簇30d " + str(r["dedup_win30"]) + "% < " + str(int(FAMILY_C30_MONTH)) + "%")
            rows.append({"month": m, "n": r["n"], "win14": r["win14"], "win30": r["win30"],
                         "avg14_net": r["avg14_net"], "avg30_net": r["avg30_net"],
                         "dedup_n": r["dedup_n"], "dedup_win14": r["dedup_win14"],
                         "dedup_win30": r["dedup_win30"], "dedup_avg14_net": r["dedup_avg14_net"],
                         "dedup_avg30_net": r["dedup_avg30_net"], "flags": flags})
        for i in range(1, len(months)):
            m1, m2 = months[i - 1], months[i]
            w1, w2 = monthly[m1]["win14"], monthly[m2]["win14"]
            n1, n2 = monthly[m1]["n"], monthly[m2]["n"]
            if (w1 is not None and w2 is not None and n1 >= FAMILY_MIN_N and n2 >= FAMILY_MIN_N
                    and w1 < FAMILY_C14_2M and w2 < FAMILY_C14_2M):
                two_month.append(m1 + "+" + m2 + " 连续2月族级14d " + str(w1) + "%/" + str(w2) + "% < " + str(int(FAMILY_C14_2M)) + "%")
        w14, _ = _wr(grp, "fwd14")
        families[key] = {
            "label": FAMILY_LABELS.get(key, key),
            "monthly": rows,
            "flags": [f for r in rows for f in r["flags"]],
            "two_month_flags": two_month,
            "n_total": len(grp),
            "win14_total": w14,
        }
    return {
        "families": families,
        "thresholds": {"min_n": FAMILY_MIN_N, "14d_month": FAMILY_C14_MONTH,
                       "30d_month": FAMILY_C30_MONTH, "14d_2m": FAMILY_C14_2M},
    }


def _production_tracking():
    """生产实盘信号跟踪（2026-08-07）：读 signal_tracking 表（pipeline/signal_tracking.py 记录/回填）。
    返回 {n_total, n_filled14, n_filled30, net14, net30, earliest_open, latest}；无表/异常返回 None。
    """
    import sqlite3
    dbp = BASE / "data" / "market.db"
    if not dbp.exists():
        return None
    try:
        conn = sqlite3.connect(str(dbp))
        conn.row_factory = sqlite3.Row
        try:
            total = conn.execute("SELECT COUNT(*) n FROM signal_tracking").fetchone()["n"] or 0
            n14 = conn.execute("SELECT COUNT(*) n FROM signal_tracking WHERE fwd14 IS NOT NULL").fetchone()["n"] or 0
            n30 = conn.execute("SELECT COUNT(*) n FROM signal_tracking WHERE fwd30 IS NOT NULL").fetchone()["n"] or 0

            def _st(field):
                r = conn.execute("SELECT COUNT(*) n, AVG({0}) a FROM signal_tracking WHERE {0} IS NOT NULL".format(field)).fetchone()
                n = r["n"] or 0
                if n == 0:
                    return {"n": 0, "win": None, "avg": None}
                w = conn.execute("SELECT COUNT(*) n FROM signal_tracking WHERE {0} > 0".format(field)).fetchone()["n"] or 0
                return {"n": n, "win": round(100.0 * w / n, 1), "avg": round(r["a"], 2) if r["a"] is not None else None}

            earliest = conn.execute("SELECT MIN(signal_date) d FROM signal_tracking WHERE fwd14 IS NULL").fetchone()["d"]
            latest = conn.execute("SELECT MAX(signal_date) d FROM signal_tracking").fetchone()["d"]
            return {"n_total": total, "n_filled14": n14, "n_filled30": n30,
                    "net14": _st("net14"), "net30": _st("net30"),
                    "earliest_open": earliest, "latest": latest}
        finally:
            conn.close()
    except Exception:
        return None


def compute():
    replay = _load(REPLAY)
    events = _load(SIGNAL_EVENTS)
    sigs = replay["signals"]

    panic_events = (events.get("display_keys") or {}).get("panic", {}).get("events", 0)
    a_pct = round(100.0 * panic_events / A_THRESHOLD, 1)

    today = date.today()
    monitor_start = date.fromisoformat(MONITOR_START)
    days = max(0, (today - monitor_start).days)
    target_date = (monitor_start + timedelta(days=SAMPLE_TARGET_DAYS)).isoformat()
    b_pct = round(100.0 * days / B_THRESHOLD_DAYS, 1)

    c = _channel_c(sigs)
    c_family = _channel_c_family(sigs)
    production = _production_tracking()
    bench = _load_benchmark()
    n30vals = [s["net30"] for s in sigs if isinstance(s.get("net30"), (int, float))]
    win30net = round(100.0 * sum(1 for v in n30vals if v > 0) / len(n30vals), 1) if n30vals else None
    avg30net = round(sum(n30vals) / len(n30vals), 2) if n30vals else None
    _ow = None
    if bench:
        def _calmar(x):
            ann = x.get("annualized_pct")
            dd = x.get("max_drawdown_pct")
            if ann is None or dd in (None, 0):
                return None
            return round(ann / abs(dd), 2)
        _full = ((bench.get("windows") or {}).get("full") or {}).get("strategy") or {}
        _active = ((bench.get("windows") or {}).get("active") or {}).get("strategy") or {}
        _stats = bench.get("signal_stats") or {}
        _ow = {
            "north_star": PARAM_REGIME.get("north_star"),
            "win14_pct": _stats.get("win14_pct"),
            "avg14_net": _stats.get("avg14"),
            "win30_net": win30net,
            "avg30_net": avg30net,
            "strategy_full": {
                "total_return_pct": _full.get("total_return_pct"),
                "max_drawdown_pct": _full.get("max_drawdown_pct"),
                "annualized_pct": _full.get("annualized_pct"),
                "calmar": _calmar(_full),
            },
            "strategy_active": {
                "total_return_pct": _active.get("total_return_pct"),
                "max_drawdown_pct": _active.get("max_drawdown_pct"),
                "annualized_pct": _active.get("annualized_pct"),
                "calmar": _calmar(_active),
            },
            "note": "2026-08-14 #1: main optimization target = expectancy + Calmar; win rate is a floor constraint, not the sole trigger",
        }

    channels = {
        "A": {
            "label": "独立恐慌市场事件",
            "value": panic_events, "threshold": A_THRESHOLD,
            "progress_pct": a_pct,
            "status": "已达标" if panic_events >= A_THRESHOLD else "积累中",
            "note": "事件不可控，自然积累不阻塞；本值=信号派生事件簇口径（365d 回放窗口，仅 2026-05 恐慌深跌 1 簇；2025-10 五合一已滑出窗口未计）；市场独立事件 2 个（2025-10 五合一 / 2026-05 恐慌深跌），口径见 decision-log 2026-08-12",
        },
        "B": {
            "label": "v2 引擎样本积累",
            "value_days": days, "threshold_days": B_THRESHOLD_DAYS,
            "progress_pct": b_pct, "target_date": target_date,
            "status": "已达标" if days >= B_THRESHOLD_DAYS else "积累中",
            "note": "自 v2 引擎起点 " + MONITOR_START + " 起累计新数据；满 " + str(B_THRESHOLD_DAYS) +
                    " 天（约 " + target_date + "）即样本完整性观察点",
        },
        "C": {
            "label": "胜率+期望监测（回放告警 + 实盘判定分离，Phase 2b）",
            "monthly": c["monthly"],
            "two_month_flags": c["two_month_flags"],
            "family_monitor": c_family,
            "thresholds": {"14d_month": C14_MONTH, "30d_month": C30_MONTH, "14d_2m": C14_2M},
            "replay_alert": {
                "triggered": bool(c["two_month_flags"] or any(r["flags"] for r in c["monthly"])),
                "since": (c["two_month_flags"][0].split(" ")[0] if c["two_month_flags"] else
                          next((r["month"] for r in c["monthly"] if r["flags"]), None)),
                "note": "回放口径告警（信息级提示，非正式重拟合触发）",
            },
            "production": production,
            "production_gate": {
                "min_filled14": PROD_MIN_FILLED14,
                "filled14": (production or {}).get("n_filled14", 0) if production else 0,
                "ready": bool(production) and (production.get("n_filled14") or 0) >= PROD_MIN_FILLED14,
            },
            "production_triggered": bool(production) and (production.get("n_filled14") or 0) >= PROD_MIN_FILLED14
                                     and production.get("net14") and production["net14"].get("win") is not None
                                     and production["net14"]["win"] < C14_2M,
            "status": "已触发" if (c["two_month_flags"] or any(r["flags"] for r in c["monthly"])
                                   or (production and (production.get("n_filled14") or 0) >= PROD_MIN_FILLED14
                                       and production.get("net14") and production["net14"].get("win") is not None
                                       and production["net14"]["win"] < C14_2M)) else "未触发",
            "trigger_state": "待启动重拟合流水线" if (c["two_month_flags"] or any(r["flags"] for r in c["monthly"])) else "监测中",
            "note": "回放口径：官方回放产物 365d 窗口 317 信号为 HIST-FULL（v2-T4/T5，C 通道主口径），当前引擎 ENGINE_VERSION=v2-T9；CLEAN-CUR 仅展示参考，不参与 C 通道告警；月度 n>=10 判定，去簇(±3天) n>=10 判定；2026-08-10 事件簇复核：6 月劣化为独立簇(06-12~21)非恐慌簇退出，恐慌簇 win30 76.3~79.6% 优秀、6 月 avg30 +9.65 期望仍正，按事件级样本不足处理；"
                    "生产实盘口径：signal_tracking 表（buy 信号 14/30 交易日后按真实价格回填，net 扣 2%），回填满 20 条后实盘胜率纳入判定；"
                    "回放告警仅提示复核，正式重拟合评估以 C 通道监测为准，触发后动作见 overall.trigger_action",
        },
    }

    triggered = [k for k, v in channels.items() if v["status"] in ("已达标", "已触发")]
    return {
        "generated": today.isoformat(),
        "engine_version": ENGINE_VERSION,
        "monitor_start": MONITOR_START,
        "sample_target_days": SAMPLE_TARGET_DAYS,
        "channels": channels,
        "optimization_view": _ow,
        "overall": {
            "triggered": bool(triggered),
            "triggered_channels": triggered,
            "note": "J-2 三通道监测（提示项，非禁止调参闸门）：A 事件>=3 / B v2 样本>=260 天 / C 胜率+期望告警",
            "trigger_action": "触发后动作（重拟合评估）：1) 记录当前参数版本(ENGINE_VERSION)基线；"
                              "2) 以新增数据重跑新旧引擎对比；3) A2 三件套(walk-forward+聚类+置换检验)验证；"
                              "4) 人工确认后发布新参数版本并 bump ENGINE_VERSION；"
                              "重拟合流水线已挂载：python references/refit_pipeline.py，"
                              "输出 data/refit_pipeline_report.json（--simulate 演练 / 默认自 v2 起点后新增信号）",
        },
    }


def main():
    d = compute()
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("written:", OUT)


if __name__ == "__main__":
    main()
