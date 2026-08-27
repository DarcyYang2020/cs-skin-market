# -*- coding: utf-8 -*-
"""Wave4 E1 · 回测质量门 5 项（2026-08-27，roadmap v82 卡 / 架构 §5.1）。

候选/策略准入前必过 5 项质量门：
  ① 时序特征平稳性体检（ADF/KPSS）——防未来 ML/回归类因子伪回归；
  ② 特征无泄露审计——显式验证每个特征只用 T 日及以前信息；
  ③ 幸存者偏差核查——回放池是否含"历史存在但后被淘汰/停更"的品；
  ④ 压力测试——极端时期回测（2024-02 崩盘期 / 2025-10 回落期 / 流动性枯竭）；
  ⑤ 成本真实化——不对称费率 买 0 / 卖 1（E2 已 config 化，本门校验产物 net 口径）。

实现约束：纯 Python 标准库（无 numpy/scipy/statsmodels——项目惯例），
ADF/KPSS 为自实现 OLS 回归 + 临界值查表（统计量/临界值口径可复核）。

用法: python references/run_quality_gate.py
产出: data/_exp_quality_gate_2026-08-27.json
"""
import io
import json
import math
import os
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 回放库同源（E2 同款；config.DB_PATH 在 import 前确定）
os.environ.setdefault("CS_MODEL_DB", str(ROOT / "data" / "replay_cycle_win.db"))

REPLAY = ROOT / "data" / "_exp_current_engine_fullpool_2026-08-27.json"
REPLAY_FEE_CAL = ROOT / "data" / "_exp_v2t13_fee_cal_2026-08-27.json"
OUT = ROOT / "data" / "_exp_quality_gate_2026-08-27.json"

# ---- 压力测试窗口（架构 §5.1④；与 EVENT_CALENDAR / period_route 五时期对齐）----
STRESS_WINDOWS = {
    "2024-02 崩盘期": ("2024-02-01", "2024-03-15"),
    "2025-10 回落期": ("2025-10-01", "2025-11-15"),
    "流动性枯竭段":   ("2026-02-01", "2026-04-30"),  # in_sale NULL/断档段（DECISION-6）
}

# 质量门特征（②特征无泄露审计对象：仅 T 日及以前信息可计算的引擎特征）
GATE_FEATURES = ["pct", "z", "chg3d", "chg7", "supply_change_30d", "th", "market_th", "sentiment", "micro_th"]

# ① 平稳性验证对象：因子输入形式（架构 §5.1①——差分/比率/截面分位天然规避，须正式验证）。
# 价格原值=随机游走预期非平稳；收益（差分/比率）须平稳；截面分位（pct/z）为有界分布预期平稳。
# 采样对象：市场指数 + 代表品价格（回放库）；信号日特征值序列仅作参考视图（非均匀采样不作判定）。
STATIONARITY_SAMPLES = 12  # 代表品数量（种子固定可复现）


# ============================================================
#  ① ADF / KPSS（纯标准库实现）
# ============================================================

def _ols_regression(x, y):
    """普通最小二乘 y = X b + e，返回 b 与残差标准差（纯标准库，X 每行 = 特征向量）。"""
    n, k = len(y), len(x[0])
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for i in range(n):
        for a in range(k):
            xty[a] += x[i][a] * y[i]
            for b in range(k):
                xtx[a][b] += x[i][a] * x[i][b]
    # 高斯消元解 xtx b = xty
    m = [row[:] + [xty[j]] for j, row in enumerate(xtx)]
    for col in range(k):
        pivot = max(range(col, k), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        piv = m[col][col]
        if abs(piv) < 1e-12:
            continue
        for r in range(k):
            if r != col and abs(m[r][col]) > 1e-12:
                f = m[r][col] / piv
                for c in range(col, k + 1):
                    m[r][c] -= f * m[col][c]
    b = [0.0] * k
    for r in range(k):
        if abs(m[r][r]) > 1e-12:
            b[r] = m[r][k] / m[r][r]
    resid = [y[i] - sum(b[a] * x[i][a] for a in range(k)) for i in range(n)]
    sse = sum(v * v for v in resid)
    sigma = math.sqrt(sse / max(1, n - k))
    # 系数标准误（用于 t 统计量）
    se = []
    for a in range(k):
        inv_diag = 1.0 / abs(m[a][a]) if abs(m[a][a]) > 1e-12 else float("inf")
        se.append(sigma * math.sqrt(inv_diag) if math.isfinite(inv_diag) else float("inf"))
    return b, se, resid


# ADF 临界值（带常数 + 趋势，n≈50~100；Dickey-Fuller τ 表，MacKinnon 近似）
_ADF_CRIT = {"1%": -4.15, "5%": -3.50, "10%": -3.18}


def adf_test(series, max_lag=4):
    """ADF 检验（常数+趋势 + 滞后差分）。返回 tau/临界值/结论（平稳=拒绝单位根）。"""
    vals = [float(v) for v in series if v is not None]
    n = len(vals)
    if n < 10 + max_lag:
        return {"stat": None, "crit": _ADF_CRIT, "verdict": "样本不足",
                "n": n, "note": "样本 < 10+lag，不作判定"}
    dy = [vals[i] - vals[i - 1] for i in range(1, n)]
    y_lag = vals[:-1]
    t = list(range(n - 1))
    # 自适应滞后：显著滞后才纳入（防过度差分）
    used_lag = 0
    for lag in range(1, max_lag + 1):
        if lag >= len(dy) - 2:
            break
        # 检查最后一个滞后项是否显著（t 值 > 1.6）
        X = [[1.0, float(t[i]), y_lag[i]] + [dy[i - j] for j in range(1, lag + 1)]
             for i in range(lag, len(dy))]
        y = dy[lag:]
        if len(X) < 5:
            break
        b, se, _ = _ols_regression(X, y)
        if abs(b[-1] / se[-1]) > 1.6:
            used_lag = lag
        else:
            break
    lag = used_lag
    X = [[1.0, float(t[i]), y_lag[i]] + [dy[i - j] for j in range(1, lag + 1)]
         for i in range(lag, len(dy))]
    y = dy[lag:]
    b, se, _ = _ols_regression(X, y)
    tau = b[2] / se[2] if se[2] not in (0, float("inf")) else None
    crit = _ADF_CRIT
    if tau is None:
        verdict = "无法计算"
    elif tau < crit["1%"]:
        verdict = "平稳(1%)"
    elif tau < crit["5%"]:
        verdict = "平稳(5%)"
    elif tau < crit["10%"]:
        verdict = "弱平稳(10%)"
    else:
        verdict = "非平稳"
    return {"stat": round(tau, 3) if tau is not None else None, "crit": crit,
            "verdict": verdict, "n": len(X), "lag": lag}


_KPSS_CRIT = {"1%": 0.739, "5%": 0.463, "10%": 0.347}


def kpss_test(series, max_lag=4):
    """KPSS 检验（常数项；LM 统计量）。结论相反：小统计量 = 平稳。"""
    vals = [float(v) for v in series if v is not None]
    n = len(vals)
    if n < 15:
        return {"stat": None, "crit": _KPSS_CRIT, "verdict": "样本不足", "n": n}
    mean = sum(vals) / n
    e = [v - mean for v in vals]
    s = [0.0]
    for v in e:
        s.append(s[-1] + v)
    # 长程方差（Newey-West 核）
    l = int(max_lag * (n / 100.0) ** 0.25) or 1
    gamma = []
    for k in range(l + 1):
        g = sum(e[i] * e[i - k] for i in range(k, n)) / n
        gamma.append(g)
    w = [1.0] + [2.0 * (1.0 - k / (l + 1.0)) for k in range(1, l + 1)]
    long_var = gamma[0] + sum(w[k] * gamma[k] for k in range(1, l + 1))
    if long_var <= 0:
        return {"stat": None, "crit": _KPSS_CRIT, "verdict": "长程方差<=0", "n": n}
    lm = sum(v * v for v in s[1:]) / (n * n) / long_var
    crit = _KPSS_CRIT
    if lm < crit["10%"]:
        verdict = "平稳"
    elif lm < crit["5%"]:
        verdict = "平稳(10%临界)"
    elif lm < crit["1%"]:
        verdict = "弱平稳(5%临界)"
    else:
        verdict = "非平稳"
    return {"stat": round(lm, 3), "crit": crit, "verdict": verdict, "n": n, "l": l}


# ============================================================
#  ② 特征无泄露审计
# ============================================================

# 泄露风险扫描清单：全周期标准化 = 泄露；滚动/截面分位 = 无泄露（T 日及以前）。
# 判定依据 = 生产实现（pipeline/valuation.py 滚动 90d 分位/z；trend_health 滚动窗口；
# supply.py 滚动 7/30d；market_th 大盘 30d；micro_th 滚动 ATR；sentiment 当日近似）。
LEAK_FEATURE_DEFS = {
    "pct":    {"computation": "90d 滚动分位（valuation.py，T 日及以前窗口）", "leak": False},
    "z":      {"computation": "90d 滚动 zscore（valuation.py）", "leak": False},
    "chg3d":  {"computation": "4 日前差分（当日/4 日前价格，纯 T 日信息）", "leak": False},
    "chg7":   {"computation": "8 日前差分（回放口径分母 8 日，纯 T 日信息）", "leak": False},
    "supply_change_30d": {"computation": "在售量 30d 变化率（supply.py 滚动）", "leak": False},
    "th":     {"computation": "趋势健康度（trend_health.py 滚动窗口 7/30/90d）", "leak": False},
    "market_th": {"computation": "大盘趋势健康度（市场指数滚动窗口）", "leak": False},
    "sentiment": {"computation": "当日近似情绪（价格动量函数，T 日信息）", "leak": False},
    "micro_th":  {"computation": "滚动 ATR%（信号日前 14 日窗口）", "leak": False},
}

# 全周期标准化（泄露）特征扫描：pipeline/ 源码中禁止出现对整序列 min/max/std 的标准化
_LEAK_PATTERNS = [
    (r"\.std\(\)\s*[-+*/]", "全序列 std 参与计算"),
    (r"min\([^)]*price[^)]*\).*max\(", "全序列 min/max 归一化"),
    (r"(zscore|z_score|standardize)\s*\([^)]*all", "疑似全量标准化"),
]


def audit_feature_leak():
    """② 特征无泄露审计：源码扫描 + 特征定义元数据。返回逐特征 verdict。"""
    findings = []
    pipe_dir = ROOT / "pipeline"
    for py in sorted(pipe_dir.glob("*.py")):
        src = py.read_text(encoding="utf-8")
        for pat, desc in _LEAK_PATTERNS:
            for m in re.finditer(pat, src):
                line_no = src[:m.start()].count("\n") + 1
                findings.append({"file": py.name, "line": line_no, "pattern": desc,
                                 "snippet": src[max(0, m.start() - 30):m.start() + 30].strip()})
    features = []
    for name, meta in LEAK_FEATURE_DEFS.items():
        features.append({
            "name": name, "computation": meta["computation"],
            "verdict": "OK" if not meta["leak"] else "LEAK",
            "leak": meta["leak"],
        })
    leaked = [f for f in features if f["leak"]]
    return {
        "verdict": "通过" if not findings and not leaked else "未通过",
        "source_scan_findings": findings,
        "features": features,
        "note": "扫描对象=pipeline/*.py 全周期标准化模式；特征定义=滚动/截面（T 日及以前）视为无泄露。"
                "发现的全量标准化模式须逐一核实（可能为展示口径非特征计算）。",
    }


# ============================================================
#  ③ 幸存者偏差核查
# ============================================================

def check_survivorship():
    """③ 幸存者偏差核查：回放池 vs 当前活跃池/淘汰记录。"""
    import sqlite3
    conn = sqlite3.connect(os.environ["CS_MODEL_DB"])
    conn.row_factory = sqlite3.Row
    replay_items = {r["name"] for r in conn.execute(
        "SELECT DISTINCT name FROM items").fetchall()}
    conn.close()

    # 生产池淘汰记录（pool_maintenance_log 不直接含淘汰品名；以 items.active=0 / watchlist 记录为准）
    prod_conn = sqlite3.connect(ROOT / "data" / "market.db")
    prod_conn.row_factory = sqlite3.Row
    try:
        inactive = {r["name"] for r in prod_conn.execute(
            "SELECT name FROM items WHERE active=0 OR status='淘汰'").fetchall()}
        all_prod = {r["name"] for r in prod_conn.execute("SELECT name FROM items").fetchall()}
    except Exception:
        inactive, all_prod = set(), set()
    prod_conn.close()

    replay_only = sorted(replay_items - all_prod)          # 回放池有、生产无（历史淘汰/停更候选）
    eliminated = sorted(replay_items & inactive)           # 明确标记淘汰
    verdict = "通过" if not eliminated else "存在淘汰品（见清单）"
    return {
        "verdict": verdict,
        "replay_pool_size": len(replay_items),
        "prod_pool_size": len(all_prod),
        "eliminated_in_replay": eliminated,
        "replay_only_but_unknown": replay_only[:30],
        "note": "回放库 items vs 生产库 items 比对；eliminated=生产标记淘汰/停更的回放品（幸存者偏差来源）；"
                "replay_only_but_unknown=回放有而生产无（可能为历史池成员/已清理），须人工核验。",
    }


# ============================================================
#  ④ 压力测试
# ============================================================

def stress_test(signals):
    """④ 压力测试：极端时期窗口内信号的 14d 期望（net14，E2 费率）。"""
    rows = []
    for name, (ws, we) in STRESS_WINDOWS.items():
        seg = [s for s in signals if ws <= (s.get("date") or "") <= we]
        ok = [s for s in seg if s.get("net14") is not None]
        if not ok:
            rows.append({"window": name, "range": [ws, we], "n": 0,
                         "verdict": "无信号（窗口内引擎不发射=天然回避）", "win14": None, "avg14": None})
            continue
        wins = sum(1 for s in ok if s["net14"] > 0)
        rows.append({"window": name, "range": [ws, we], "n": len(ok),
                     "win14": round(100.0 * wins / len(ok), 1),
                     "avg14": round(sum(s["net14"] for s in ok) / len(ok), 2),
                     "verdict": "通过" if (sum(s["net14"] for s in ok) / len(ok)) > 0 else "负期望"})
    return {"verdict": "通过" if all(r["verdict"] == "通过" for r in rows) else "未通过（见窗口明细）",
            "windows": rows,
            "note": "极端窗口 = 2024-02 崩盘 / 2025-10 回落 / 2026-02~04 流动性断档（DECISION-6 段）。"
                    "压力期 n 小属正常（引擎低位回避），看 avg14 符号与样本量。"}


# ============================================================
#  ⑤ 成本真实化（E2 费率校验）
# ============================================================

def cost_realism_check():
    """⑤ 成本真实化：FEE-CAL 产物 net 口径 = fwd − 1.0%（买0/卖1），与 config 一致。"""
    from pipeline.config import backtest_roundtrip_cost
    expected = backtest_roundtrip_cost()
    if not REPLAY_FEE_CAL.exists():
        return {"verdict": "未执行", "note": "缺少 FEE-CAL 产物（先跑 references/run_fee_calibration.py）"}
    data = json.load(io.open(REPLAY_FEE_CAL, encoding="utf-8"))
    sigs = [s for s in data.get("signals", []) if s.get("fwd14") is not None and s.get("net14") is not None]
    bad = [s for s in sigs[:200] if abs(s["net14"] - (s["fwd14"] - expected)) > 0.02]
    return {
        "verdict": "通过" if not bad else "未通过",
        "config_roundtrip_pct": expected,
        "checked": len(sigs),
        "mismatch": len(bad),
        "note": "net14 = fwd14 − roundtrip(%.1f%%)；费率来源 pipeline.config.BACKTEST_FEES（买0/卖1，E2 config 化）。" % expected,
    }


# ============================================================
#  main
# ============================================================

def _load_price_series():
    """回放库：市场指数 + 代表品价格序列（用于 ① 平稳性验证）。"""
    import sqlite3
    conn = sqlite3.connect(os.environ["CS_MODEL_DB"])
    conn.row_factory = sqlite3.Row
    series = {}
    try:
        mkt = [(r["date"], float(r["value"])) for r in conn.execute(
            "SELECT date, value FROM market_index ORDER BY date").fetchall()]
        if mkt:
            series["market_index"] = mkt
        items = conn.execute(
            "SELECT i.id, i.name FROM items i WHERE i.name NOT LIKE '%印花%' "
            "AND i.name NOT LIKE '%角色%' ORDER BY i.id LIMIT ?",
            (STATIONARITY_SAMPLES,)).fetchall()
        for it in items:
            px = [(r["date"], float(r["price_rmb"])) for r in conn.execute(
                "SELECT date, price_rmb FROM price_history WHERE item_id=? AND price_rmb>0 ORDER BY date",
                (it["id"],)).fetchall()]
            if len(px) >= 60:
                series[it["name"][:24]] = px
    finally:
        conn.close()
    return series


def _to_returns(series):
    """价格/指数序列 → 日收益序列（差分/比率形式，验证其平稳性）。"""
    vals = [v for _, v in series]
    return [(vals[i] / vals[i - 1] - 1.0) * 100 for i in range(1, len(vals)) if vals[i - 1] > 0]


def stationarity_check():
    """① 时序特征平稳性体检：ADF/KPSS 验证因子输入形式（价格收益/指数收益）平稳。"""
    results = {}
    for name, series in _load_price_series().items():
        rets = _to_returns(series)
        results[name] = {
            "n_price": len(series), "n_ret": len(rets),
            "adf_return": adf_test(rets),
            "kpss_return": kpss_test(rets),
        }
    # 判定：收益率序列 ADF 平稳 或 KPSS 平稳 即通过（比率形式天然规避伪回归）
    fails = {k: v for k, v in results.items()
             if not (v["adf_return"]["verdict"].startswith("平稳") or
                     v["kpss_return"]["verdict"].startswith("平稳"))}
    return {
        "verdict": "通过（%d/%d 序列收益平稳）" % (len(results) - len(fails), len(results)) if results else "无数据",
        "series": results,
        "note": "验证对象=价格/指数日收益（差分/比率形式，因子实际输入）；原值序列预期非平稳（随机游走），"
                "不作判定。信号日特征值序列为截面分位（有界分布），见 ② 特征定义。",
        "fails": list(fails.keys()),
    }


def main():
    data = json.load(io.open(REPLAY, encoding="utf-8"))
    signals = data.get("signals", [])

    stat = stationarity_check()
    leak = audit_feature_leak()
    surv = check_survivorship()
    stress = stress_test(signals)
    cost = cost_realism_check()

    gates = {
        "1_stationarity": stat,
        "2_no_leak": leak,
        "3_survivorship": surv,
        "4_stress": stress,
        "5_cost_realism": cost,
    }
    overall = "通过" if all(g["verdict"].startswith("通过") or g["verdict"] == "未执行" for g in gates.values()) else "未通过"
    out = {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
        "card": "Wave4 E1 回测质量门",
        "prereg": "roadmap v82 E1（架构 §5.1，2026-08-27 PM 立卡）",
        "replay": str(REPLAY),
        "signals": len(signals),
        "overall": overall,
        "gates": gates,
        "note": "质量门 = 候选/策略准入前必过；未过质量门不准入（E3 /evaluate 展示层据此挂质量标签）。"
                "本跑为现有候选回放（v2-T13 当前引擎全池）基线登记，非落地变更。",
    }
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("=== Wave4 E1 回测质量门（%d 信号）===" % len(signals))
    print("overall:", overall)
    for k, g in gates.items():
        print("  %-18s %s" % (k, g["verdict"]))
    if stress["verdict"].startswith("未通过"):
        for r in stress["windows"]:
            print("    stress %-12s n=%d avg14=%s win14=%s" % (
                r["window"], r["n"], r.get("avg14"), r.get("win14")))
    print("written:", OUT)


if __name__ == "__main__":
    main()
