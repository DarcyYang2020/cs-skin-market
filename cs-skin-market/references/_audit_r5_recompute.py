# -*- coding: utf-8 -*-
"""③审计 · R5 独立复算脚本（2026-08-27，只读，不覆盖②产物）。

对 R5 产物 data/_exp_emotion_v0_2026-08-27.json 做独立只读核验：
- 恐慌分复算（pipeline.backtest_common.approx_sentiment 生产函数，同②口径）
- v0 合成 emo_v0 = clip(恐慌分 + 0.5*sc30_norm - 0.5*chg7_norm, 0, 100)（fit/val 同规则）
- 组件 IC / emo_v0 IC / 增量 IC（核心6因子 OLS 残差 vs fwd14，独立实现 OLS/Spearman）
- 滚动同号月 / val 复验增量 IC / 分位数表
- 守院核验：require_fit 仅 fit 段调用（代码审查已核），val 仅增量 IC 复验
输出：data/_audit_r5_recompute_2026-08-27.json（审计产物）。
"""
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.config import DB_PATH, OOS_ZONE  # noqa: E402
from pipeline.backtest_common import approx_sentiment  # noqa: E402

SPLIT = OOS_ZONE["val_start"]
MATRIX = ROOT / "data" / "_exp_fullscan_features_2026-08-20.json"
ISO = ROOT / "data" / "_exp_emotion_v0_2026-08-27.json"
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"
CORE_FACTORS = ["pct", "z", "chg30", "sc30", "vol30", "mchg30"]
W1, W2 = 0.5, 0.5

audit = {"title": "③审计 R5 独立复算", "checks": {}, "pass": True}


# ---------- 独立实现：平均秩 / Spearman / OLS ----------
def avg_ranks(vals):
    n = len(vals)
    order = sorted(range(n), key=lambda i: vals[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 5:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    n = len(xs)
    rx, ry = avg_ranks(xs), avg_ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sxx = syy = 0.0
    for i in range(n):
        dx, dy = rx[i] - mx, ry[i] - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def ols_residual(y, Xcols):
    keep = [i for i in range(len(y))
            if y[i] is not None and all(x[i] is not None for x in Xcols)]
    if len(keep) < 10:
        return None
    y = [y[i] for i in keep]
    Xcols = [[x[i] for i in keep] for x in Xcols]
    rows, cols = len(y), len(Xcols) + 1
    A = [[0.0] * cols for _ in range(cols)]
    b = [0.0] * cols
    for i in range(rows):
        xr = [1.0] + [Xcols[k][i] for k in range(len(Xcols))]
        for r in range(cols):
            b[r] += xr[r] * y[i]
            for c in range(cols):
                A[r][c] += xr[r] * xr[c]
    # 高斯-约当消元（独立实现）
    M = [A[i] + [b[i]] for i in range(cols)]
    for col in range(cols):
        piv = max(range(col, cols), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for c in range(cols + 1):
            M[col][c] /= pv
        for r in range(cols):
            if r == col:
                continue
            f = M[r][col]
            for c in range(col, cols + 1):
                M[r][c] -= f * M[col][c]
    beta = [M[i][cols] for i in range(cols)]
    res = [0.0] * rows
    for i in range(rows):
        pred = beta[0] + sum(beta[k + 1] * Xcols[k][i] for k in range(len(Xcols)))
        res[i] = y[i] - pred
    return res


def ic_stats(ics):
    n = len(ics)
    if n == 0:
        return {"n": 0}
    mean = sum(ics) / n
    var = sum((x - mean) ** 2 for x in ics) / n
    std = math.sqrt(var) if var > 0 else 0.0
    t = mean / (std / math.sqrt(n)) if std > 0 else 0.0
    return {"n": n, "mean": round(mean, 4), "std": round(std, 4),
            "t": round(t, 3), "pos_ratio": round(sum(1 for x in ics if x > 0) / n, 4)}


def daily_ic(vals, indices, fwd, core=None):
    dg = defaultdict(list)
    for i in indices:
        dg[dates[i]].append(i)
    out = []
    for dd in sorted(dg):
        idxs = dg[dd]
        xs = [vals[i] for i in idxs]
        ys = [fwd[i] for i in idxs]
        if core is None:
            c = spearman(xs, ys)
        else:
            res = ols_residual(xs, [[X[c][i] for i in idxs] for c in core])
            c = spearman(res, ys) if res is not None else None
        if c is not None:
            out.append(c)
    return out


def rolling(ics_by_day_key, day_keys):
    monthly = defaultdict(list)
    for dk, c in ics_by_day_key:
        monthly[dk[:7]].append(c)
    m_means = {m: sum(cs) / len(cs) for m, cs in monthly.items() if cs}
    n_pos = sum(1 for m in m_means if m_means[m] > 0)
    return {"months": len(m_means),
            "same_sign_ratio": round(n_pos / len(m_means), 4) if m_means else None}


# ---------- 数据加载（同②口径）----------
d = json.load(open(MATRIX, encoding="utf-8"))
dates = d["date"]
items = d["item_id"]
X = d["X"]
fwd14 = d["fwd14"]
fwd30 = d["fwd30"]
n = len(dates)
FIT = [i for i in range(n) if dates[i] < SPLIT]
VAL = [i for i in range(n) if dates[i] >= SPLIT]

conn = sqlite3.connect(str(REPLAY_DB), timeout=15)
conn.row_factory = sqlite3.Row
ph = defaultdict(list)
for r in conn.execute("SELECT item_id, date, price_rmb FROM price_history ORDER BY item_id, date"):
    ph[r["item_id"]].append((r["date"], r["price_rmb"]))
mrows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
conn.close()
m_dates = [r["date"] for r in mrows]
m_vals = [r["value"] for r in mrows]

# item_id 桥（good_id -> 生产库 id -> 回放 price_history.item_id）
_mat_id2name = {int(k): v for k, v in d["meta"]["item_name"].items()}
_pc = sqlite3.connect(str(DB_PATH), timeout=15)
_pc.row_factory = sqlite3.Row
_pn2id = {r["name"]: r["id"] for r in _pc.execute("SELECT id, name FROM items")}
_pc.close()
GID2PHID = {gid: _pn2id.get(nm) for gid, nm in _mat_id2name.items() if nm in _pn2id}

seq = {it: {dd[0]: k for k, dd in enumerate(ph[it])} for it in ph}
SENT = [None] * len(dates)
for i in range(len(dates)):
    phid = GID2PHID.get(items[i])
    if phid is None:
        continue
    s = seq.get(phid)
    if not s or dates[i] not in s:
        continue
    idx = s[dates[i]]
    bars = ph[phid]
    prices_hist = [b[1] for b in bars[:idx + 1] if b[1] is not None]
    if len(prices_hist) >= 15:
        SENT[i] = approx_sentiment(prices_hist, len(prices_hist) - 1)

# 逐日截面 rank（0-100）
def pct_rank(vals):
    n = len(vals)
    if n == 0:
        return []
    ranks = avg_ranks(vals)
    return [(r - 1) / (n - 1) * 100.0 if n > 1 else 50.0 for r in ranks]


SC30_NORM = [None] * len(dates)
CHG7_NORM = [None] * len(dates)
for dd in sorted(set(dates)):
    idxs = [i for i in range(len(dates)) if dates[i] == dd]
    sc_ok = [i for i in idxs if X["sc30"][i] is not None]
    cg_ok = [i for i in idxs if X["chg7"][i] is not None]
    if len(sc_ok) >= 5:
        rk = pct_rank([X["sc30"][i] for i in sc_ok])
        for k, i in enumerate(sc_ok):
            SC30_NORM[i] = rk[k]
    if len(cg_ok) >= 5:
        rk = pct_rank([X["chg7"][i] for i in cg_ok])
        for k, i in enumerate(cg_ok):
            CHG7_NORM[i] = rk[k]

EMO = [None] * len(dates)
n_emo_fit = 0
for i in range(len(dates)):
    s, s30, c7 = SENT[i], SC30_NORM[i], CHG7_NORM[i]
    if s is None or s30 is None or c7 is None:
        continue
    EMO[i] = max(0.0, min(100.0, s + W1 * s30 - W2 * c7))
    if i in FIT:
        n_emo_fit += 1

# ---------- 独立复算各数字 ----------
res = {}

# 组件 IC
for cid, vals in (("sentiment", SENT), ("sc30", X["sc30"]), ("chg7", X["chg7"])):
    ic14 = ic_stats(daily_ic(vals, FIT, fwd14))
    ic30 = ic_stats(daily_ic(vals, FIT, fwd30))
    cov = round(sum(1 for i in FIT if vals[i] is not None) / len(FIT), 4)
    roll = rolling([(dates[dd], c) for dd in []], [])  # placeholder
    res[cid] = {"coverage_fit": cov, "IC14": ic14, "IC30": ic30}
    # 滚动：重算
    dg = defaultdict(list)
    for i in FIT:
        dg[dates[i]].append(i)
    rows = []
    for dd in sorted(dg):
        c = spearman([vals[i] for i in dg[dd]], [fwd14[i] for i in dg[dd]])
        if c is not None:
            rows.append((dd, c))
    res[cid]["rolling_stability"] = rolling(rows, [])

# emo_v0
cov_emo = round(n_emo_fit / len(FIT), 4)
emo_ic14 = ic_stats(daily_ic(EMO, FIT, fwd14))
emo_ic30 = ic_stats(daily_ic(EMO, FIT, fwd30))
dg = defaultdict(list)
for i in FIT:
    dg[dates[i]].append(i)
rows = []
for dd in sorted(dg):
    c = spearman([EMO[i] for i in dg[dd]], [fwd14[i] for i in dg[dd]])
    if c is not None:
        rows.append((dd, c))
emo_roll = rolling(rows, [])

# 分位数
pairs = [(EMO[i], fwd14[i]) for i in FIT if EMO[i] is not None and fwd14[i] is not None]
pairs.sort(key=lambda p: p[0])
nq = len(pairs) // 5
quantile = []
for k in range(5):
    seg = pairs[k * nq:(k + 1) * nq] if k < 4 else pairs[4 * nq:]
    quantile.append({"q": k + 1, "n": len(seg),
                     "avg_fwd14": round(sum(p[1] for p in seg) / len(seg), 3),
                     "win": round(sum(1 for p in seg if p[1] > 0) / len(seg), 4)})

# 增量 IC（fit / val）
inc_fit = ic_stats(daily_ic(EMO, FIT, fwd14, core=CORE_FACTORS))
val_inc = ic_stats(daily_ic(EMO, VAL, fwd14, core=CORE_FACTORS)) if VAL else {"n": 0}

# 增量 IC 滚动同号月
dg = defaultdict(list)
for i in FIT:
    dg[dates[i]].append(i)
inc_rows = []
for dd in sorted(dg):
    idxs = dg[dd]
    resd = ols_residual([EMO[i] for i in idxs], [[X[c][i] for i in idxs] for c in CORE_FACTORS])
    c = spearman(resd, [fwd14[i] for i in idxs]) if resd is not None else None
    if c is not None:
        inc_rows.append((dd, c))
inc_roll = rolling(inc_rows, [])

res["emo_v0"] = {"coverage_fit": cov_emo, "IC14": emo_ic14, "IC30": emo_ic30,
                 "rolling_stability": emo_roll, "quantile_table": quantile,
                 "inc_ic_fit": inc_fit, "inc_ic_rolling_stability": inc_roll,
                 "val_recheck_inc_ic": val_inc}

# ---------- 复现②的 period_of 过滤滚动口径（审计观察：②月度聚合仅统计市场上下文可算日期）----------
from pipeline.market_context import state_bucket as _sb  # noqa: E402
from datetime import date as _date, timedelta as _td  # noqa: E402
conn2 = sqlite3.connect(str(REPLAY_DB), timeout=15)
conn2.row_factory = sqlite3.Row
_mrows = conn2.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
conn2.close()
_md = [r["date"] for r in _mrows]
_mv = [r["value"] for r in _mrows]
_ctx = {}
for _i, _dd in enumerate(_md):
    _v = _mv[_i]
    def _find(db):
        _t = (_date.fromisoformat(_dd) - _td(days=db)).isoformat()
        lo, hi = 0, _i
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _md[mid] <= _t:
                lo = mid
            else:
                hi = mid - 1
        return lo if _md[lo] <= _t else None
    _i30, _i180 = _find(30), _find(180)
    _c30 = (_v / _mv[_i30] - 1) * 100 if _i30 is not None and _mv[_i30] else None
    _c180 = (_v / _mv[_i180] - 1) * 100 if _i180 is not None and _mv[_i180] else None
    if _c30 is not None and _c180 is not None:
        _ctx[_dd] = (_c180, _c30)
_period_of = {_dd: _sb(c180, c30) for _dd, (c180, c30) in _ctx.items()}
_inc_m = defaultdict(list)
_dg2 = defaultdict(list)
for _i in FIT:
    if EMO[_i] is not None and dates[_i] in _period_of:
        _dg2[dates[_i]].append(_i)
for _dd in sorted(_dg2):
    _idxs = _dg2[_dd]
    _res = ols_residual([EMO[_i] for _i in _idxs], [[X[c][_i] for _i in _idxs] for c in CORE_FACTORS])
    _c = spearman(_res, [fwd14[_i] for _i in _idxs]) if _res is not None else None
    if _c is not None:
        _inc_m[_dd[:7]].append(_c)
_m_means = {m: sum(cs) / len(cs) for m, cs in _inc_m.items() if cs}
_n_pos = sum(1 for m in _m_means if _m_means[m] > 0)
repro_period_of_roll = {"months": len(_m_means),
                        "same_sign_ratio": round(_n_pos / len(_m_means), 4) if _m_means else None,
                        "note": "②口径：月度聚合仅统计 period_of（市场上下文可算）日期；审计全量口径见 inc_ic_rolling_stability"}

# ---------- 对比产物 ----------
iso = json.load(open(ISO, encoding="utf-8"))
checks = {}
for cid in ("sentiment", "sc30", "chg7"):
    exp = iso["components_ic"][cid]
    act = res[cid]
    ok = (act["coverage_fit"] == exp["coverage_fit"]
          and act["IC14"]["mean"] == exp["IC14"]["mean"]
          and act["IC14"]["n"] == exp["IC14"]["n"]
          and act["IC30"]["mean"] == exp["IC30"]["mean"]
          and act["rolling_stability"] == exp["rolling_stability"])
    checks["component_" + cid] = {"ok": ok, "actual": act, "expected": exp}
    if not ok:
        audit["pass"] = False

emo_act, emo_exp = res["emo_v0"], iso["emo_v0"]
checks["emo_v0_ic"] = {"ok": (emo_act["IC14"] == emo_exp["IC14"]
                              and emo_act["IC30"] == emo_exp["IC30"]
                              and emo_act["coverage_fit"] == emo_exp["coverage_fit"]
                              and emo_act["rolling_stability"] == emo_exp["rolling_stability"]),
                       "actual": {k: emo_act[k] for k in ("coverage_fit", "IC14", "IC30", "rolling_stability")},
                       "expected": {k: emo_exp[k] for k in ("coverage_fit", "IC14", "IC30", "rolling_stability")}}
checks["emo_v0_inc_ic"] = {"ok": (emo_act["inc_ic_fit"] == emo_exp["inc_ic_fit"]
                                  and emo_act["inc_ic_rolling_stability"] == emo_exp["inc_ic_rolling_stability"]
                                  and emo_act["val_recheck_inc_ic"] == emo_exp["val_recheck_inc_ic"]),
                           "actual": {"inc_ic_fit": emo_act["inc_ic_fit"],
                                      "inc_ic_rolling": emo_act["inc_ic_rolling_stability"],
                                      "val_recheck": emo_act["val_recheck_inc_ic"]},
                           "expected": {"inc_ic_fit": emo_exp["inc_ic_fit"],
                                        "inc_ic_rolling": emo_exp["inc_ic_rolling_stability"],
                                        "val_recheck": emo_exp["val_recheck_inc_ic"]}}
checks["quantile"] = {"ok": emo_act["quantile_table"] == emo_exp["quantile_table"],
                      "actual": emo_act["quantile_table"], "expected": emo_exp["quantile_table"]}
checks["verdict"] = {"ok": iso["verdict"] == "无增量", "actual": iso["verdict"]}
checks["inc_roll_period_of_repro"] = {"ok": (repro_period_of_roll["months"] == emo_exp["inc_ic_rolling_stability"]["months"]
                                            and repro_period_of_roll["same_sign_ratio"] == emo_exp["inc_ic_rolling_stability"]["same_sign_ratio"]),
                                      "actual": repro_period_of_roll,
                                      "expected": emo_exp["inc_ic_rolling_stability"]}
checks["meta_rows"] = {"ok": (iso["meta"]["fit_rows"] == len(FIT) and iso["meta"]["val_rows"] == len(VAL)
                              and iso["meta"]["split_oos"] == SPLIT),
                       "actual": {"fit": len(FIT), "val": len(VAL), "split": SPLIT}}

for name, c in checks.items():
    audit["pass"] &= bool(c.get("ok"))
audit["checks"] = checks
out_path = ROOT / "data" / "_audit_r5_recompute_2026-08-27.json"
json.dump(audit, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("AUDIT PASS" if audit["pass"] else "AUDIT FAIL")
for name, c in checks.items():
    print("  %-18s %s" % (name, "PASS" if c.get("ok") else "FAIL"))
    if not c.get("ok"):
        print("    actual:  ", json.dumps(c.get("actual"), ensure_ascii=False)[:300])
        print("    expected:", json.dumps(c.get("expected"), ensure_ascii=False)[:300])
print("emo_v0 复算: IC14=%s inc_fit=%s val_recheck=%s roll=%s" % (
    emo_ic14["mean"], inc_fit["mean"], val_inc.get("mean"), inc_roll["same_sign_ratio"]))
print("saved:", out_path)
