# -*- coding: utf-8 -*-
"""R5 内生情绪 v0 评估脚本（②算法研究窗口 · 预注册判据 references/r5-emotion-v0-prereg-2026-08-27.md，DR 冻结）

硬约束（判据 §0-§4，跑前定死）：
  1. v0 合成 = clip(恐慌分 + w1*sc30_norm - w2*chg7_norm, 0, 100)，w1=w2=0.5 固定，禁权重优化；
  2. 归一化 sc30_norm/chg7_norm 用 fit 段截面 rank（0-100）；
  3. 硬判据：对核心因子集（pct/z/chg30/sc30/vol30/mchg30）截面回归取残差 → 增量 IC；
     增量 IC >= 0.02 且滚动稳定（同号月 >= 80%）→ v0 候选成立；否则登记"无增量/证伪"；
  4. oos_zone 守院：探索（组件/合成/rank）只许 fit 段（date < 2025-08-10）；
     val 段（>= 2025-08-10）仅预注册声明的验证动作（增量 IC 的 val 复验）触碰；
  5. 仅加分/过滤评估：不进打分主干、不改族触发；不碰引擎；产物仅 data/_exp_emotion_v0_2026-08-27.json；
  6. 确定性：无随机性，同一输入同一输出。
"""
import json
import math
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.config import DB_PATH, OOS_ZONE  # noqa: E402
from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.backtest_common import approx_sentiment  # noqa: E402
from pipeline.oos_guard import require_fit, in_oos_zone  # noqa: E402（D6 正式守卫）

SPLIT = OOS_ZONE["val_start"]  # =2025-08-10（D6 单一事实源）
PREREG = "references/r5-emotion-v0-prereg-2026-08-27.md"
MATRIX = ROOT / "data" / "_exp_fullscan_features_2026-08-20.json"
OUT = ROOT / "data" / "_exp_emotion_v0_2026-08-27.json"
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"  # 与矩阵同源（R1 同款）
PROD_DB = DB_PATH

# 核心因子集（增量 IC 正交化基准；判据 §2 = R1 同款）
CORE_FACTORS = ["pct", "z", "chg30", "sc30", "vol30", "mchg30"]

# 判据硬阈值
INC_IC_MIN = 0.02    # 增量 IC >= 0.02 才算新信息（候选门槛）
ROLL_STABLE = 0.80   # 滚动同号月占比 >= 80% -> 稳定
W1 = 0.5             # 供给调节权重（固定，禁优化）
W2 = 0.5             # 动量调节权重（固定，禁优化）
EMO_MIN, EMO_MAX = 0.0, 100.0


# ---------------------------------------------------------------- 工具（R1 同款）
def rank_list(vals):
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


def pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sxx = syy = 0.0
    for i in range(n):
        dx = xs[i] - mx
        dy = ys[i] - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 5:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    return pearson(rank_list(xs), rank_list(ys))


def ic_stats(daily_ics):
    n = len(daily_ics)
    if n == 0:
        return {"n": 0}
    mean = sum(daily_ics) / n
    var = sum((x - mean) ** 2 for x in daily_ics) / n
    std = math.sqrt(var) if var > 0 else 0.0
    t = mean / (std / math.sqrt(n)) if std > 0 else 0.0
    return {"n": n, "mean": round(mean, 4), "std": round(std, 4),
            "t": round(t, 3), "pos_ratio": round(sum(1 for x in daily_ics if x > 0) / n, 4)}


def ols_residual(y, Xcols):
    """截面多元回归 y ~ Xcols(+常数)，返回残差 list。高斯-约当求解（R1 同款）。"""
    keep = [i for i in range(len(y))
            if y[i] is not None and all(x[i] is not None for x in Xcols)]
    if len(keep) < 10:
        return None
    y = [y[i] for i in keep]
    Xcols = [[x[i] for i in keep] for x in Xcols]
    rows = len(y)
    cols = len(Xcols) + 1
    A = [[0.0] * cols for _ in range(cols)]
    b = [0.0] * cols
    for i in range(rows):
        xr = [1.0] + [Xcols[k][i] for k in range(len(Xcols))]
        for r in range(cols):
            b[r] += xr[r] * y[i]
            for c in range(cols):
                A[r][c] += xr[r] * xr[c]
    try:
        beta = _solve(A, b)
    except Exception:
        return None
    res = [0.0] * rows
    for i in range(rows):
        pred = beta[0]
        for k in range(len(Xcols)):
            pred += beta[k + 1] * Xcols[k][i]
        res[i] = y[i] - pred
    return res


def _solve(A, b):
    n = len(A)
    M = [A[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            raise ValueError("singular")
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for c in range(n + 1):
            M[col][c] /= pv
        for r in range(n):
            if r == col:
                continue
            f = M[r][col]
            for c in range(col, n + 1):
                M[r][c] -= f * M[col][c]
    return [M[i][n] for i in range(n)]


def pct_rank_0_100(vals):
    """截面 rank -> 0-100（percentile）"""
    n = len(vals)
    if n == 0:
        return []
    ranks = rank_list(vals)  # 1..n
    return [(r - 1) / (n - 1) * 100.0 if n > 1 else 50.0 for r in ranks]


# ---------------------------------------------------------------- 数据加载（R1 同款）
t0 = time.time()
d = json.load(open(MATRIX, encoding="utf-8"))
dates = d["date"]
items = d["item_id"]
X = d["X"]
fwd14 = d["fwd14"]
fwd30 = d["fwd30"]
n = len(dates)
FIT = [i for i in range(n) if dates[i] < SPLIT]
VAL = [i for i in range(n) if dates[i] >= SPLIT]
if not FIT:
    sys.exit("FATAL: fit 段为空（SPLIT=%s）" % SPLIT)
print(f"[data] matrix rows={n} fit={len(FIT)} val={len(VAL)}（val=oos_zone 仅预注册复验触碰）", flush=True)

# 回放库 price_history（复算恐慌分；与矩阵同源；全量含 val——val 仅预注册 §4 复验触碰）
conn = sqlite3.connect(str(REPLAY_DB), timeout=15)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT item_id, date, price_rmb FROM price_history "
    "ORDER BY item_id, date").fetchall()
ph = defaultdict(list)
for r in rows:
    ph[r["item_id"]].append((r["date"], r["price_rmb"]))
print(f"[data] replay price_history rows={len(rows)} items={len(ph)}", flush=True)

# market_index -> 时期映射
mrows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
m_dates = [r["date"] for r in mrows]
m_vals = [r["value"] for r in mrows]
conn.close()


def _sub_days(dstr, ndays):
    from datetime import date, timedelta
    return (date.fromisoformat(dstr) - timedelta(days=ndays)).isoformat()


def mkt_ctx():
    ctx = {}
    for i, dd in enumerate(m_dates):
        v = m_vals[i]

        def _find(days_back):
            target = _sub_days(dd, days_back)
            lo, hi = 0, i
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if m_dates[mid] <= target:
                    lo = mid
                else:
                    hi = mid - 1
            return lo if m_dates[lo] <= target else None
        i30 = _find(30)
        i180 = _find(180)
        chg30 = (v / m_vals[i30] - 1) * 100 if i30 is not None and m_vals[i30] else None
        chg180 = (v / m_vals[i180] - 1) * 100 if i180 is not None and m_vals[i180] else None
        if chg30 is not None and chg180 is not None:
            ctx[dd] = (round(chg180, 2), round(chg30, 2))
    return ctx


MKT = mkt_ctx()
period_of = {}
for _d in m_dates:
    if _d in MKT:
        c180, c30 = MKT[_d]
        period_of[_d] = state_bucket(c180, c30)

# item_id 桥（good_id -> 生产库 id -> 回放库 price_history.item_id 体系，R1 同款）
_mat = json.load(open(MATRIX, encoding="utf-8"))
_mat_id2name = {int(k): v for k, v in _mat["meta"]["item_name"].items()}
_pc = sqlite3.connect(str(PROD_DB), timeout=15)
_pc.row_factory = sqlite3.Row
_pn2id = {r["name"]: r["id"] for r in _pc.execute("SELECT id, name FROM items")}
_pc.close()
GID2PHID = {gid: _pn2id.get(nm) for gid, nm in _mat_id2name.items() if nm in _pn2id}
print(f"[derived] item_id 桥（good_id -> 生产库id）命中 {len(GID2PHID)}/{len(_mat_id2name)}", flush=True)

# ---------------------------------------------------------------- 恐慌分复算（fit 段探索 + val 段仅预注册复验触碰）
seq = {}
for it in ph:
    seq[it] = {dd[0]: k for k, dd in enumerate(ph[it])}
SENT = [None] * len(dates)
done = 0
for i in range(len(dates)):
    if dates[i] < SPLIT:
        require_fit(dates[i], prereg=PREREG, label="R5情绪v0 恐慌分复算")  # D6 守卫（探索仅 fit 段）
    # else: val 行 = 预注册 §4 声明的"增量 IC val 复验"触碰（非探索；产物 meta 明示）
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
    done += 1
    if done % 30000 == 0:
        print(f"[derived] sentiment {done}", flush=True)
print(f"[derived] 恐慌分复算完成 done={done}", flush=True)

# ---------------------------------------------------------------- v0 合成
# 归一化：逐日截面 rank（0-100）——规则预注册固定（判据 §1），fit/val 同规则；
# val 段仅用于预注册 §4 声明的增量 IC 复验（未用 val 选择组件/权重/阈值，非探索）。
def daily_slice(indices):
    dg = defaultdict(list)
    for i in indices:
        dg[dates[i]].append(i)
    return dg


DAILY_FIT = daily_slice(FIT)
DAYS_FIT = sorted(DAILY_FIT)
print(f"[eval] fit 段交易日数 = {len(DAYS_FIT)}", flush=True)

# 逐日截面 rank：sc30 / chg7（fit 段探索 + val 段复验，同规则）
SC30_NORM = [None] * len(dates)
CHG7_NORM = [None] * len(dates)
for dd in sorted(set(dates)):
    idxs = [i for i in range(len(dates)) if dates[i] == dd]
    sc_ok = [i for i in idxs if X["sc30"][i] is not None]
    cg_ok = [i for i in idxs if X["chg7"][i] is not None]
    if len(sc_ok) >= 5:
        rk = pct_rank_0_100([X["sc30"][i] for i in sc_ok])
        for k, i in enumerate(sc_ok):
            SC30_NORM[i] = rk[k]
    if len(cg_ok) >= 5:
        rk = pct_rank_0_100([X["chg7"][i] for i in cg_ok])
        for k, i in enumerate(cg_ok):
            CHG7_NORM[i] = rk[k]

# emo_v0 = clip(sent + w1*sc30_norm - w2*chg7_norm, 0, 100)（fit 段探索 + val 段复验）
EMO = [None] * len(dates)
n_emo = 0
n_emo_fit = 0
for i in range(len(dates)):
    s, s30, c7 = SENT[i], SC30_NORM[i], CHG7_NORM[i]
    if s is None or s30 is None or c7 is None:
        continue
    EMO[i] = max(EMO_MIN, min(EMO_MAX, s + W1 * s30 - W2 * c7))
    n_emo += 1
    if i in FIT:
        n_emo_fit += 1
print(f"[eval] emo_v0 全量可算 {n_emo}（fit {n_emo_fit}/{len(FIT)}）", flush=True)

# ---------------------------------------------------------------- 评估：组件 IC + v0 全 IC
def factor_ic(vals, indices, ylabel="fwd14"):
    dg = defaultdict(list)
    for i in indices:
        dg[dates[i]].append(i)
    days = sorted(dg)
    ics = []
    for dd in days:
        idxs = dg[dd]
        xs = [vals[i] for i in idxs]
        ys = [fwd14[i] for i in idxs] if ylabel == "fwd14" else [fwd30[i] for i in idxs]
        c = spearman(xs, ys)
        if c is not None:
            ics.append(c)
    return ic_stats(ics), days, dg


def rolling_stability(vals, days, dg):
    monthly = defaultdict(list)
    for dd in days:
        idxs = dg[dd]
        c = spearman([vals[i] for i in idxs], [fwd14[i] for i in idxs])
        if c is not None:
            monthly[dd[:7]].append(c)
    m_means = {m: sum(cs) / len(cs) for m, cs in monthly.items() if cs}
    n_pos = sum(1 for m in m_means if m_means[m] > 0)
    return {"months": len(m_means),
            "same_sign_ratio": round(n_pos / len(m_means), 4) if m_means else None}


def period_ic(vals, days, dg):
    by_period = defaultdict(list)
    for dd in days:
        if dd not in period_of:
            continue
        idxs = dg[dd]
        c = spearman([vals[i] for i in idxs], [fwd14[i] for i in idxs])
        if c is not None:
            by_period[period_of[dd]].append(c)
    return {p: ic_stats(by_period[p]) for p in sorted(by_period)}


def inc_ic_daily(vals, indices):
    """对核心因子集截面回归取残差 -> 残差 vs fwd14 逐日 IC（R1 同款）"""
    dg = defaultdict(list)
    for i in indices:
        dg[dates[i]].append(i)
    days = sorted(dg)
    out = []
    for dd in days:
        idxs = dg[dd]
        xs = [vals[i] for i in idxs]
        y14 = [fwd14[i] for i in idxs]
        core_vals = [[X[c][i] for i in idxs] for c in CORE_FACTORS]
        res = ols_residual(xs, core_vals)
        if res is None:
            continue
        c = spearman(res, y14)
        if c is not None:
            out.append(c)
    return out


# 组件 IC（fit 段；sentiment 复算 / sc30 / chg7 直接取矩阵）
components = {}
for cid, cname, vals in (("sentiment", "恐慌分(approx_sentiment)", SENT),
                         ("sc30", "供给30日变化", lambda: X["sc30"]),
                         ("chg7", "价格7日动量", lambda: X["chg7"])):
    v = vals() if callable(vals) else vals
    ic14, days, dg = factor_ic(v, FIT, "fwd14")
    ic30, _, _ = factor_ic(v, FIT, "fwd30")
    components[cid] = {
        "name": cname,
        "coverage_fit": round(sum(1 for i in FIT if v[i] is not None) / len(FIT), 4),
        "IC14": ic14, "IC30": ic30,
        "rolling_stability": rolling_stability(v, days, dg),
    }
    print(f"[eval] 组件 {cid}: IC14={ic14.get('mean')} 滚动同号={components[cid]['rolling_stability']['same_sign_ratio']}", flush=True)

# v0 全 IC / 滚动 / 时期 / 分层
emo_ic14, emo_days, emo_dg = factor_ic(EMO, FIT, "fwd14")
emo_ic30, _, _ = factor_ic(EMO, FIT, "fwd30")
emo_roll = rolling_stability(EMO, emo_days, emo_dg)
emo_per = period_ic(EMO, emo_days, emo_dg)
pairs = [(EMO[i], fwd14[i]) for i in FIT if EMO[i] is not None and fwd14[i] is not None]
quantile = None
if len(pairs) >= 50:
    pairs.sort(key=lambda p: p[0])
    nq = len(pairs) // 5
    quantile = []
    for k in range(5):
        seg = pairs[k * nq:(k + 1) * nq] if k < 4 else pairs[4 * nq:]
        if seg:
            quantile.append({"q": k + 1, "n": len(seg),
                             "avg_fwd14": round(sum(p[1] for p in seg) / len(seg), 3),
                             "win": round(sum(1 for p in seg if p[1] > 0) / len(seg), 4)})

# 增量 IC（fit 段，硬判据）
inc_fit = inc_ic_daily(EMO, FIT)
inc_fit_stats = ic_stats(inc_fit)
# 增量 IC 滚动同号月（按增量 IC 逐日 -> 月均值）
inc_monthly = defaultdict(list)
dg_inc = defaultdict(list)
for i in FIT:
    if EMO[i] is not None and dates[i] in period_of:
        dg_inc[dates[i]].append(i)
for dd in sorted(dg_inc):
    if dd not in period_of:
        continue
    idxs = dg_inc[dd]
    xs = [EMO[i] for i in idxs]
    y14 = [fwd14[i] for i in idxs]
    core_vals = [[X[c][i] for i in idxs] for c in CORE_FACTORS]
    res = ols_residual(xs, core_vals)
    if res is None:
        continue
    c = spearman(res, y14)
    if c is not None:
        inc_monthly[dd[:7]].append(c)
inc_m_means = {m: sum(cs) / len(cs) for m, cs in inc_monthly.items() if cs}
inc_n_pos = sum(1 for m in inc_m_means if inc_m_means[m] > 0)
inc_roll = {"months": len(inc_m_means),
            "same_sign_ratio": round(inc_n_pos / len(inc_m_means), 4) if inc_m_means else None}

# val 复验（预注册 §4 声明：仅增量 IC 复验触碰）
val_inc = None
if VAL:
    vc = [i for i in VAL if EMO[i] is not None]
    if len(vc) >= 30:
        val_inc_daily = inc_ic_daily(EMO, VAL)
        val_inc = ic_stats(val_inc_daily)
    print(f"[eval] val 复验：增量IC={val_inc.get('mean') if val_inc else None} (n={val_inc.get('n') if val_inc else 0})", flush=True)
else:
    print("[eval] 无 val 行，跳过复验", flush=True)

# ---------------------------------------------------------------- verdict（判据 §2）
mean_inc = inc_fit_stats.get("mean")
ssr = inc_roll.get("same_sign_ratio")
if mean_inc is not None and mean_inc >= INC_IC_MIN and ssr is not None and ssr >= ROLL_STABLE:
    verdict = "候选"
    verdict_note = f"增量IC={mean_inc} >= {INC_IC_MIN} 且滚动同号月 {ssr} >= {ROLL_STABLE} -> v0 候选成立（仅加分/过滤可行性）"
else:
    verdict = "无增量"
    verdict_note = f"增量IC={mean_inc}（阈值{INC_IC_MIN}）或滚动同号月 {ssr}（阈值{ROLL_STABLE}）未过 -> v0 无增量/证伪登记（R5 判据 §2）"

out = {
    "meta": {
        "card": "R5 内生情绪 v0 评估（roadmap v82）",
        "prereg": PREREG,
        "script": "references/run_emotion_v0_eval.py",
        "split_oos": SPLIT,
        "fit_rows": len(FIT), "val_rows": len(VAL),
        "emo_formula": f"clip(恐慌分 + {W1}*sc30_norm - {W2}*chg7_norm, {EMO_MIN}, {EMO_MAX})",
        "norm_def": "sc30_norm/chg7_norm = 逐日截面百分位 rank（0-100），规则预注册固定（判据 §1），fit/val 同规则；"
                    "val 段计算仅服务于 §4 声明的增量 IC 复验，未用 val 数据做组件/权重/阈值选择（非探索）",
        "weights_fixed": {"w1": W1, "w2": W2, "note": "固定值禁优化（判据 §1，权重变化=新预注册）"},
        "core_factors": CORE_FACTORS,
        "thresholds": {"inc_ic_min": INC_IC_MIN, "roll_stable": ROLL_STABLE},
        "oos_zone": "探索(组件/合成/权重/阈值)仅 fit 段（require_fit 守卫，D6）；val 仅预注册 §4 声明的增量 IC 复验触碰",
        "matrix": str(MATRIX.name),
        "matrix_db": "data/replay_cycle_win.db（与 R1 同源）",
        "fwd_label_cost": "fwd14/fwd30 已扣 2% 双边成本（矩阵 COST=2.0）",
        "engine": "v2-T13（只读，未改动）",
        "runtime_sec": round(time.time() - t0, 1),
    },
    "components_ic": components,
    "emo_v0": {
        "coverage_fit": round(n_emo_fit / len(FIT), 4),
        "IC14": emo_ic14, "IC30": emo_ic30,
        "rolling_stability": emo_roll,
        "IC14_by_period": emo_per,
        "quantile_table": quantile,
        "inc_ic_fit": inc_fit_stats,
        "inc_ic_rolling_stability": inc_roll,
        "val_recheck_inc_ic": val_inc,
        "verdict": verdict,
        "verdict_note": verdict_note,
    },
    "verdict": verdict,
    "note": "仅筛查层结论：verdict=候选 交 PM 评估是否立'情绪守卫'落地卡；无增量/证伪 登记 registry 防重复挖。不进打分主干、不改族触发、不碰引擎。",
}

json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("=" * 60)
print(f"saved -> {OUT}")
print(f"emo_v0 verdict: {verdict}")
print(f"  inc_ic_fit: {inc_fit_stats}")
print(f"  inc_ic_rolling: {inc_roll}")
print(f"  val_recheck: {val_inc}")
print(f"runtime: {out['meta']['runtime_sec']}s")
