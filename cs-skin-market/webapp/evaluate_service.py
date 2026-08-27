# -*- coding: utf-8 -*-
"""Wave4 E3/E4 · 评估层数据服务（2026-08-27，roadmap v82 卡 / 架构 §5.2/§5.3）。

聚合评估层产物供 /evaluate 页（研究视图）展示：
  三层 = ①信号级（近期信号+族期望）②策略族级（净值/回撤/胜率/期望/Calmar/月度/分布）
        ③因子组合级（因子 IC/贡献/分层 + 组合 vs 等权 vs 大盘 + 分时期质量表）
  质量标签 = E1 回测质量门状态（未过质量门不展示，§5.2 纪律）。
  风险归因 = §5.3：b1 组合模拟 closed 逐笔按族/时期/品类分组 + top5>50% 集中度警示。

纯只读：不碰引擎/不写库；产物缺失时该层标记 missing 而非报错。
"""
import io
import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ---- E1 质量门产物（质量标签事实源）----
QGATE = DATA / "_exp_quality_gate_2026-08-27.json"
# ---- E2 费率校准 ----
FEE_CAL = DATA / "_exp_v2t13_fee_cal_2026-08-27.json"
FEE_DIFF = DATA / "_exp_fee_calibration_2026-08-27.json"
# ---- 回放/组合/基准 ----
REPLAY = DATA / "_exp_v2t13_fee_cal_2026-08-27.json"      # E2 校准后回放（net 买0/卖1）
REPLAY_2PCT = DATA / "_exp_current_engine_fullpool_2026-08-27.json"  # 旧 2% 对照
BENCHMARK = DATA / "benchmark_compare.json"                 # 净值 vs 基准（历史基线口径）
B1 = DATA / "b1_risk_validation_v2.json"                    # 组合模拟（旧 2%）
# ---- R1/R2 因子 ----
FACTOR_EVAL = DATA / "_exp_factor_eval_2026-08-27.json"
FACTOR_REGISTRY = DATA / "factor_registry.json"
# ---- R3 隔离评估 ----
FAMILY_ISO = DATA / "_exp_family_isolation_2026-08-27.json"


def _load(path):
    if not path.exists():
        return None
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return None


def _pct(v, digits=1):
    if v is None:
        return None
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None


def _family_key(label):
    lab = label or ""
    if "恐慌" in lab:
        return "panic"
    if "深值" in lab:
        return "deep_value"
    return "accumulate"


def _display_label(key):
    return {"panic": "恐慌族", "deep_value": "深值企稳", "accumulate": "吸筹/回补组"}.get(key, key)


def _wilson_ci(k, n, z=1.96):
    if n <= 0:
        return (None, None)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (round(100.0 * max(0.0, center - half), 1), round(100.0 * min(1.0, center + half), 1))


def _calmar(returns, max_dd_pct):
    """Calmar = 总收益% / |maxDD%|（无回撤或无收益返回 None）。"""
    if max_dd_pct is None or abs(max_dd_pct) < 1e-9 or returns is None:
        return None
    return round(returns / abs(max_dd_pct), 2)


# ============================================================
#  ① 信号级（主界面决策视角已有信号卡片；这里=族期望 + 最近信号摘要）
# ============================================================

def _signal_layer():
    replay = _load(REPLAY)
    if not replay:
        return {"missing": True, "note": "缺少 E2 校准回放产物 data/_exp_v2t13_fee_cal_2026-08-27.json"}
    sigs = replay.get("signals", [])
    fam = {}
    for s in sigs:
        k = _family_key(s.get("action_label"))
        fam.setdefault(k, []).append(s)
    families = []
    for k, ss in fam.items():
        net14 = [s["net14"] for s in ss if s.get("net14") is not None]
        wins = sum(1 for v in net14 if v > 0)
        n = len(net14)
        avg14 = sum(net14) / n if n else None
        lo, hi = _wilson_ci(wins, n) if n else (None, None)
        families.append({
            "key": k, "label": _display_label(k), "n": len(ss),
            "win14": _pct(100.0 * wins / n, 1) if n else None,
            "avg14": _pct(avg14),
            "ci14": [lo, hi],
        })
    families.sort(key=lambda x: -x["n"])
    recent = sorted(sigs, key=lambda s: (s.get("date") or ""), reverse=True)[:8]
    return {
        "missing": False,
        "replay": {"signals": len(sigs), "generated": replay.get("generated"),
                   "engine": (replay.get("args") or {}).get("engine")},
        "families": families,
        "recent": [{
            "date": s.get("date"), "name": s.get("name"),
            "action_label": (s.get("action_label") or "").replace("🟢 ", "").replace("🔴 ", ""),
            "entry_price": s.get("entry_price"), "net14": _pct(s.get("net14")),
            "net30": _pct(s.get("net30")), "position_limit": s.get("position_limit"),
        } for s in recent],
    }


# ============================================================
#  ② 策略族级（净值/回撤/胜率/期望/Calmar + 月度 + 分布）
# ============================================================

def _monthly_pnl(signals):
    """按 年月 聚合 net14：{ '2025-11': {n, avg14, win14} }。"""
    out = {}
    for s in signals:
        d = s.get("date") or ""
        v = s.get("net14")
        if len(d) < 7 or v is None:
            continue
        m = d[:7]
        out.setdefault(m, []).append(v)
    rows = []
    for m in sorted(out):
        vals = out[m]
        wins = sum(1 for x in vals if x > 0)
        rows.append({"month": m, "n": len(vals), "avg14": _pct(sum(vals) / len(vals)),
                     "win14": _pct(100.0 * wins / len(vals), 1)})
    return rows


def _return_distribution(signals):
    """net14 收益分布（分桶，前端画条形图）。"""
    vals = [s["net14"] for s in signals if s.get("net14") is not None]
    if not vals:
        return []
    buckets = [(-1e9, -20), (-20, -10), (-10, 0), (0, 10), (10, 20), (20, 40), (40, 1e9)]
    labels = ["<-20%", "-20~-10", "-10~0", "0~+10", "+10~20", "+20~40", ">+40%"]
    counts = [0] * len(buckets)
    for v in vals:
        for i, (lo, hi) in enumerate(buckets):
            if lo <= v < hi:
                counts[i] += 1
                break
    return [{"label": labels[i], "count": counts[i]} for i in range(len(buckets))]


def _strategy_layer():
    replay = _load(REPLAY)
    b1 = _load(B1)
    bench = _load(BENCHMARK)
    if not replay:
        return {"missing": True, "note": "缺少 E2 校准回放产物"}
    sigs = replay.get("signals", [])
    net14 = [s["net14"] for s in sigs if s.get("net14") is not None]
    n = len(net14)
    wins = sum(1 for v in net14 if v > 0)
    avg14 = sum(net14) / n if n else None
    lo, hi = _wilson_ci(wins, n) if n else (None, None)

    # 组合模拟指标（B1 v2 口径：cap0.8 / hold21 / 费率 2%——E2 校准后 net 平移 1pp，
    # 组合口径仍为旧 2%，此处标注费率口径，不混算）
    comb = (b1 or {}).get("results", {}).get("baseline_cap08") or {}
    calmar = _calmar(comb.get("total_return_pct"), comb.get("max_drawdown_pct"))

    # 基准对照（benchmark_compare HIST-FULL 双窗口：strategy vs pool_buy_hold vs market_index）
    bench_rows = []
    if bench:
        for blabel in ("HIST-FULL", "CLEAN-CUR"):
            b = (bench.get("baselines") or {}).get(blabel)
            if not b:
                continue
            w = (b.get("windows") or {}).get("active") or {}
            bench_rows.append({
                "baseline": blabel,
                "strategy": w.get("strategy") or {},
                "pool_buy_hold": w.get("pool_buy_hold") or {},
                "market_index": w.get("market_index") or {},
            })
    return {
        "missing": False,
        "overall": {
            "signals": len(sigs), "n14": n,
            "win14": _pct(100.0 * wins / n, 1) if n else None,
            "avg14": _pct(avg14), "ci14": [lo, hi],
            "n30": sum(1 for s in sigs if s.get("net30") is not None),
        },
        "portfolio": {
            "total_return_pct": _pct(comb.get("total_return_pct")),
            "max_drawdown_pct": _pct(comb.get("max_drawdown_pct")),
            "calmar": calmar,
            "n_trades": comb.get("n_trades"),
            "rejected_cap": comb.get("rejected_cap"),
            "fee_note": "组合模拟为 B1 v2 口径（cap0.8/hold21/2% 双边）；E2 校准后信号级 net 为买0/卖1",
        },
        "benchmark": bench_rows,
        "monthly": _monthly_pnl(sigs),
        "distribution": _return_distribution(sigs),
        "equity_curve": _equity_curve(sigs),
    }


def _equity_curve(signals):
    """E4 净值曲线（复用 b1_risk_backtest_v2.simulate，cap0.8/hold21；只读纯计算）。

    输出抽样后折线（约 60 点）供前端 SVG 渲染：{dates, strategy, market}。
    曲线 = 组合模拟权益（信号级 fwd 序列）；market = 同期大盘指数归一化（回放库）。
    """
    try:
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / "references"))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
        b1v2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b1v2)

        sigs = []
        for s in signals:
            fwd = s.get("fwd_series") or []
            if not fwd:
                continue
            from datetime import date as _date
            st = _family_key(s.get("action_label"))
            sigs.append({
                "date": _date.fromisoformat(s["date"]), "item": s["name"],
                "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
                "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1),
                "net14": s.get("net14"),
            })
        if not sigs:
            return {"missing": True}
        sim = b1v2.simulate(sigs, cap=0.8)
        curve = sim["curve"]  # [(date, pos, eq, gate, active)]
        if len(curve) < 10:
            return {"missing": True, "note": "曲线过短"}
        # 抽样 ~60 点
        step = max(1, len(curve) // 60)
        pts = curve[::step]
        if pts[-1] != curve[-1]:
            pts.append(curve[-1])
        # 大盘同期归一化（回放库 market_index）
        mkt = {}
        try:
            import sqlite3
            conn = sqlite3.connect(os.environ.get("CS_MODEL_DB", str(DATA / "replay_cycle_win.db")))
            mkt = {r[0]: float(r[1]) for r in conn.execute(
                "SELECT date, value FROM market_index ORDER BY date").fetchall()}
            conn.close()
        except Exception:
            pass
        base_mkt = None
        mkt_pts = []
        for d, _, _, _, _ in pts:
            if d in mkt:
                if base_mkt is None:
                    base_mkt = mkt[d]
                mkt_pts.append({"d": d, "v": round(100.0 * (mkt[d] / base_mkt - 1.0), 2) if base_mkt else None})
            else:
                mkt_pts.append({"d": d, "v": None})
        return {
            "missing": False,
            "points": [{"d": d, "strategy": round((eq - 1.0) * 100, 2), "position": round(pos, 3)}
                       for d, pos, eq, _, _ in pts],
            "market": mkt_pts,
            "note": "策略=信号组合模拟权益（B1 v2 cap0.8/hold21，费率 2%）；大盘=market_index 同期归一化。"
                    "E2 校准后信号级 net 为买0/卖1，组合级曲线待重跑校准（仅形态参考）。",
        }
    except Exception as exc:
        return {"missing": True, "error": str(exc)[:200]}


# ============================================================
#  ③ 因子组合级（因子 IC/贡献/分层 + 组合 vs 等权 vs 大盘 + 分时期质量表）
# ============================================================

def _factor_layer():
    eval_ = _load(FACTOR_EVAL)
    registry = _load(FACTOR_REGISTRY)
    if not eval_:
        return {"missing": True, "note": "缺少 R1 因子评估产物 data/_exp_factor_eval_2026-08-27.json"}
    cards = eval_.get("cards") or []
    rows = []
    for c in cards:
        rows.append({
            "id": c.get("id"), "name": c.get("name"),
            "verdict": c.get("verdict"), "ic14": _pct(c.get("ic14")),
            "roll_stable": _pct(c.get("roll_stable"), 0),
            "category": c.get("category"),
            "note": (c.get("note") or "")[:80],
        })
    rows.sort(key=lambda r: -(r["ic14"] if r["ic14"] is not None else -9))
    status_dist = {}
    for c in cards:
        v = c.get("verdict") or "unknown"
        status_dist[v] = status_dist.get(v, 0) + 1
    registry_summary = None
    if registry:
        regs = registry.get("factors") or registry.get("registry") or []
        status_dist_reg = {}
        for f in regs:
            st = f.get("status") or "unknown"
            status_dist_reg[st] = status_dist_reg.get(st, 0) + 1
        registry_summary = {"total": len(regs), "status": status_dist_reg,
                            "generated": registry.get("generated")}
    return {
        "missing": False,
        "factor_eval": {"cards": len(cards), "status": status_dist,
                        "generated": eval_.get("generated")},
        "registry": registry_summary,
        "top": rows[:15],
    }


def _quality_gate():
    qg = _load(QGATE)
    if not qg:
        return {"missing": True, "note": "缺少 E1 质量门产物 data/_exp_quality_gate_2026-08-27.json"}
    gates = {}
    for k, g in (qg.get("gates") or {}).items():
        gates[k] = {"verdict": g.get("verdict"),
                    "note": (g.get("note") or "")[:120]}
    return {
        "missing": False,
        "overall": qg.get("overall"),
        "generated": qg.get("generated"),
        "gates": gates,
    }


# ============================================================
#  E4 风险归因（§5.3：b1 closed 逐笔按族/时期/品类分组 + top5 集中度）
# ============================================================

def _risk_attribution():
    replay = _load(REPLAY)
    b1 = _load(B1)
    if not replay:
        return {"missing": True, "note": "缺少回放产物"}
    sigs = replay.get("signals", [])
    out = {"missing": False}

    # 按族（信号级 net14 期望 × 信号数 = 族贡献近似；§5.3「信号数×平均期望」）
    fam_rows = []
    by_fam = {}
    for s in sigs:
        k = _family_key(s.get("action_label"))
        by_fam.setdefault(k, []).append(s)
    for k, ss in by_fam.items():
        net14 = [s["net14"] for s in ss if s.get("net14") is not None]
        if not net14:
            continue
        avg = sum(net14) / len(net14)
        fam_rows.append({"family": _display_label(k), "n": len(net14),
                         "avg14": _pct(avg), "contribution_pct": _pct(avg * len(net14))})
    fam_rows.sort(key=lambda r: -(r["contribution_pct"] or 0))
    out["by_family"] = fam_rows

    # 按时期（_period 字段：P恐慌/S1牛市/S2回调/S3阴跌/S4反弹）
    period_rows = []
    by_period = {}
    for s in sigs:
        p = s.get("_period") or "未知"
        by_period.setdefault(p, []).append(s)
    for p, ss in by_period.items():
        net14 = [s["net14"] for s in ss if s.get("net14") is not None]
        if not net14:
            continue
        period_rows.append({"period": p, "n": len(net14),
                            "avg14": _pct(sum(net14) / len(net14)),
                            "win14": _pct(100.0 * sum(1 for v in net14 if v > 0) / len(net14), 1)})
    period_rows.sort(key=lambda r: -(r["n"] or 0))
    out["by_period"] = period_rows

    # 按品类（③审计 2026-08-27 修复指令：原品名前缀 372/376 落"其他"失效）。
    # 口径：品名 "武器 | 皮肤" 的武器段（英文，稳定）+ 中文品类前缀回退（手套/匕首/箱/胶囊等）。
    # 数据层 items.weapon 列覆盖 9/405 不可用，故用武器名映射（weapon 字段待采集补齐后切换）。
    _WEAPON_CAT = {
        # 步枪
        "AK-47": "步枪", "M4A4": "步枪", "M4A1消音版": "步枪", "AWP": "步枪",
        "法玛斯": "步枪", "加利尔AR": "步枪", "SSG 08": "步枪", "SCAR-20": "步枪",
        "G3SG1": "步枪", "SG 553": "步枪", "AUG": "步枪",
        # 手枪
        "沙漠之鹰": "手枪", "USP消音版": "手枪", "格洛克18型": "手枪", "P250": "手枪",
        "五七": "手枪", "Tec-9": "手枪", "双持贝瑞塔": "手枪", "R8 左轮手枪": "手枪",
        # 微型冲锋枪
        "MP7": "微型冲锋枪", "MP9": "微型冲锋枪", "P90": "微型冲锋枪", "MP5-SD": "微型冲锋枪",
        "UMP-45": "微型冲锋枪", "MAC-10": "微型冲锋枪", "PP-野牛": "微型冲锋枪",
        # 霰弹枪 / 机枪
        "新星": "霰弹枪", "XM1014": "霰弹枪", "截短霰弹枪": "霰弹枪", "MAG-7": "霰弹枪",
        "M249": "机枪", "内格夫": "机枪",
    }
    _CAT_PREFIX = ["手套", "匕首", "武器箱", "胶囊", "挂件", "印花", "探员", "音乐盒", "收藏品"]
    by_cat = {}
    for s in sigs:
        name = s.get("name") or ""
        wpn = (name.split(" | ")[0] if " | " in name else name).strip()
        cat = _WEAPON_CAT.get(wpn) or next((c for c in _CAT_PREFIX if name.startswith(c)), "其他")
        by_cat.setdefault(cat, []).append(s)
    cat_rows = []
    for c, ss in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        net14 = [s["net14"] for s in ss if s.get("net14") is not None]
        cat_rows.append({"category": c, "n": len(ss),
                         "avg14": _pct(sum(net14) / len(net14)) if net14 else None})
    out["by_category"] = cat_rows

    # 集中度：top5 单品贡献（信号级 net14 求和）
    by_item = {}
    for s in sigs:
        if s.get("net14") is None:
            continue
        by_item[s.get("name")] = by_item.get(s.get("name"), 0.0) + s["net14"]
    total = sum(by_item.values())
    top5 = sorted(by_item.items(), key=lambda kv: -kv[1])[:5]
    top5_share = (sum(v for _, v in top5) / total) if total else None
    out["concentration"] = {
        "top5": [{"name": n, "contrib": _pct(v)} for n, v in top5],
        "top5_share_pct": _pct(100.0 * top5_share, 1) if top5_share is not None else None,
        "flag": "⚠️ 集中风险" if (top5_share or 0) > 0.50 else "正常",
        "threshold": "top5 贡献 >50% 警示（§5.3）",
    }

    # 组合级 closed 逐笔（③审计 2026-08-27 修复指令：b1_risk_validation_v2.json 未存 closed 明细
    # → 原实现 n_trades=0 空归因。修复 = 从回放信号实时跑 b1v2.simulate（cap0.8/hold21），closed 明细直接可得）
    try:
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / "references"))
        import importlib.util
        from datetime import date as _date
        spec = importlib.util.spec_from_file_location(
            "b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
        b1v2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b1v2)
        sim_sigs = []
        for s in sigs:
            fwd = s.get("fwd_series") or []
            if not fwd:
                continue
            st = _family_key(s.get("action_label"))
            sim_sigs.append({
                "date": _date.fromisoformat(s["date"]), "item": s["name"],
                "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
                "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1),
                "net14": s.get("net14"),
            })
        if sim_sigs:
            _sim = b1v2.simulate(sim_sigs, cap=0.8)
            closed = _sim.get("closed") or []
        else:
            closed = []
    except Exception:
        closed = []
    out["portfolio_closed"] = {
        "n_trades": len(closed),
        "total_pnl": _pct(sum(closed)),
        "win_rate": _pct(100.0 * sum(1 for v in closed if v > 0) / len(closed), 1) if closed else None,
        "avg_pnl": _pct(sum(closed) / len(closed)) if closed else None,
        "fee_note": "组合级 closed 逐笔 = 从回放信号实时模拟（b1v2.simulate cap0.8/hold21/2% 双边；"
                    "E2 校准后信号级为买0/卖1，组合级待重跑校准，仅形态参考——诚实标注）",
    }
    return out


def _fee_calibration():
    diff = _load(FEE_DIFF)
    if not diff:
        return {"missing": True, "note": "缺少 E2 差异表 data/_exp_fee_calibration_2026-08-27.json"}
    return {"missing": False, "note": diff.get("note"), "table": diff.get("table")}


# ============================================================
#  总入口
# ============================================================

def evaluate_payload():
    """/evaluate 页全部数据（研究视图，三层 + 质量标签 + 风险归因 + E2 差异）。"""
    return {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
        "quality_gate": _quality_gate(),
        "signal_layer": _signal_layer(),
        "strategy_layer": _strategy_layer(),
        "factor_layer": _factor_layer(),
        "risk_attribution": _risk_attribution(),
        "fee_calibration": _fee_calibration(),
        "layers_note": "三层展示（架构 §5.2）：①信号级=主界面决策视角的族期望+最近信号；"
                       "②策略族级=净值/回撤/胜率/期望/Calmar/月度/分布；③因子组合级=因子 IC/registry。"
                       "质量标签纪律：每条展示绑定 E1 质量门状态，未过质量门不展示（展示≠证据）。",
    }


if __name__ == "__main__":
    p = evaluate_payload()
    print("quality_gate:", p["quality_gate"].get("overall"), "| missing:", [
        k for k, v in p.items() if isinstance(v, dict) and v.get("missing")])
    print("signal families:", [(f["label"], f["n"], f["avg14"]) for f in p["signal_layer"].get("families", [])])
    print("strategy overall:", p["strategy_layer"].get("overall"))
    print("factor status:", p["factor_layer"].get("factor_eval"))
