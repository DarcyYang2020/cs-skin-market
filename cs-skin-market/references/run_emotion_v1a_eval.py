# -*- coding: utf-8 -*-
"""W7-1 v1a 内生情绪（v0+bid+spread）评估脚本（②算法研究窗口 · 预注册判据 references/w7-1-v1a-emotion-prereg-2026-08-27.md，FC 冻结）

硬约束（判据 §1-§5，跑前定死）：
  1. v1a 合成 = clip(emo_v0 + 0.5*bid_norm + 0.5*spread_norm, 0, 100)；emo_v0 = R5 冻结定义；
     权重 w1=w2=w3=w4=0.5 固定禁优化（权重变化=新预注册）；
  2. 归一化 bid_norm/spread_norm = fit 段逐日截面 rank（0-100，R5 同规则）；
  3. 增量 IC 双口径硬判据：
     判据 A = 对核心因子集（pct/z/chg30/sc30/vol30/mchg30）截面回归残差 → 增量 IC≥0.02 且滚动同号月≥80%；
     判据 B = 对核心因子集+emo_v0 联合回归残差 → 增量 IC≥0.02（相对 v0 净增量）；
     verdict：A 且 B 均过 → 候选；任一不过 → 无增量/证伪登记；
  4. oos_zone 守院：探索仅 fit 段（require_fit D6）；val 仅预注册声明验证动作（增量 IC val 复验）触碰；
  5. 仅守卫/加分评估：不进打分主干、不改族触发、不碰引擎；产物仅 data/_exp_emotion_v1a_2026-08-27.json；
  6. 确定性：无随机性。
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
from pipeline.oos_guard import require_fit  # noqa: E402

SPLIT = OOS_ZONE["val_start"]
PREREG = "references/w7-1-v1a-emotion-prereg-2026-08-27.md"
MATRIX = ROOT / "data" / "_exp_fullscan_features_2026-08-20.json"
OUT = ROOT / "data" / "_exp_emotion_v1a_2026-08-27.json"
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"
PROD_DB = DB_PATH

CORE_FACTORS = ["pct", "z", "chg30", "sc30", "vol30", "mchg30"]
INC_IC_MIN = 0.02
ROLL_STABLE = 0.80
W1 = W2 = W3 = W4 = 0.5
EMO_MIN, EMO_MAX = 0.0, 100.0


# ---------------------------------------------------------------- 工具（R1/R5 同款）
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
    n = len(vals)
    if n == 0:
        return []
    ranks = rank_list(vals)
    return [(r - 1) / (n - 1) * 100.0 if n > 1 else 50.0 for r in ranks]


def inc_ic_daily(vals, indices, extra_cols=None):
    """对核心因子集（+可选 extra）截面回归取残差 -> 残差 vs fwd14 逐日 IC（R5 同款，扩展 extra）"""
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
        if extra_cols:
            for ec in extra_cols:
                core_vals.append([ec[i] for i in idxs])
        res = ols_residual(xs, core_vals)
        if res is None:
            continue
        c = spearman(res, y14)
        if c is not None:
            out.append(c)
    return out


# ---------------------------------------------------------------- 数据加载
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
print(f"[data] matrix rows={n} fit={len(FIT)} val={len(VAL)}", flush=True)

# 回放库 price_history（恐慌分 + spread 用价）
conn = sqlite3.connect(str(REPLAY_DB), timeout=15)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT item_id, date, price_rmb FROM price_history ORDER BY item_id, date").fetchall()
ph = defaultdict(list)
for r in rows:
    ph[r["item_id"]].append((r["date"], r["price_rmb"]))
print(f"[data] replay price_history rows={len(rows)} items={len(ph)}", flush=True)

# market_index -> 时期
mrows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
m_dates = [r["date"] for r in mrows]
m_vals = [r["value"] for r in mrows]
conn.close()


def _sub_days(dstr, ndays):
    from datetime import date, timedelta
    return (date.fromisoformat(dstr) - timedelta(days=ndays)).isoformat()


MKT = {}
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
        MKT[dd] = (round(chg180, 2), round(chg30, 2))
period_of = {}
for _d in m_dates:
    if _d in MKT:
        c180, c30 = MKT[_d]
        period_of[_d] = state_bucket(c180, c30)

# name 桥：矩阵 item_id（good_id 体系）-> 生产库 items（name<->good_id<->id）
_mat = json.load(open(MATRIX, encoding="utf-8"))
_mat_id2name = {int(k): v for k, v in _mat["meta"]["item_name"].items()}
_pc = sqlite3.connect(str(PROD_DB), timeout=15)
_pc.row_factory = sqlite3.Row
_name2gid = {r["name"]: r["good_id"] for r in _pc.execute("SELECT name, good_id FROM items")}
_nid_map = {r["name"]: r["id"] for r in _pc.execute("SELECT id, name FROM items")}
# bid_history（全量含 val——val 仅复验触碰）
bid_rows = _pc.execute(
    "SELECT good_id, date, buy_price_max FROM bid_history").fetchall()
bid = {}
for r in bid_rows:
    if r["buy_price_max"] is not None:
        bid[(r["good_id"], r["date"])] = r["buy_price_max"]
_pc.close()
print(f"[data] name->good_id 桥={len(_name2gid)} bid 行={len(bid_rows)}", flush=True)

# 矩阵 item_id(good_id) -> 回放库 price_history.item_id（生产库 id 体系）
GID2PHID = {}
for gid, nm in _mat_id2name.items():
    pid = _nid_map.get(nm)
    if pid is not None:
        GID2PHID[gid] = pid
print(f"[derived] item_id 桥（good_id -> 生产库id）命中 {len(GID2PHID)}/{len(_mat_id2name)}", flush=True)


# ---------------------------------------------------------------- 恐慌分复算（fit 探索 + val 复验触碰）
seq = {}
for it in ph:
    seq[it] = {dd[0]: k for k, dd in enumerate(ph[it])}
SENT = [None] * len(dates)
done = 0
for i in range(len(dates)):
    if dates[i] < SPLIT:
        require_fit(dates[i], prereg=PREREG, label="W7-1v1a 恐慌分复算")
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
print(f"[derived] 恐慌分复算完成 done={done}", flush=True)


# ---------------------------------------------------------------- bid/spread（g9 桥接，全量含 val）
BID = [None] * len(dates)
SPREAD = [None] * len(dates)
for i in range(len(dates)):
    if dates[i] < SPLIT:
        require_fit(dates[i], prereg=PREREG, label="W7-1v1a bid/spread")
    nm = _mat_id2name.get(items[i])
    gid = _name2gid.get(nm) if nm else None
    if gid is None:
        continue
    b = bid.get((gid, dates[i]))
    if b is None:
        continue
    BID[i] = b
    phid = GID2PHID.get(items[i])
    if phid is not None and dates[i] in (seq.get(phid) or {}):
        p = ph[phid][seq[phid][dates[i]]][1]
        if p is not None:
            SPREAD[i] = round(p - b, 4)
cov_bid = sum(1 for i in FIT if BID[i] is not None) / len(FIT)
cov_spread = sum(1 for i in FIT if SPREAD[i] is not None) / len(FIT)
print(f"[derived] bid 覆盖率={cov_bid:.3f} spread 覆盖率={cov_spread:.3f}", flush=True)


# ---------------------------------------------------------------- 归一化（逐日截面 rank，fit/val 同规则）
def daily_rank_0_100(factor_vals):
    norm = [None] * len(dates)
    by_day = defaultdict(list)
    for i in range(len(dates)):
        if factor_vals[i] is not None:
            by_day[dates[i]].append(i)
    for dd, idxs in by_day.items():
        if len(idxs) < 5:
            continue
        rk = pct_rank_0_100([factor_vals[i] for i in idxs])
        for k, i in enumerate(idxs):
            norm[i] = rk[k]
    return norm


SC30_NORM = daily_rank_0_100(X["sc30"])
CHG7_NORM = daily_rank_0_100(X["chg7"])
BID_NORM = daily_rank_0_100(BID)
SPREAD_NORM = daily_rank_0_100(SPREAD)

# emo_v0（R5 冻结定义）+ emo_v1a（本判据）
EMO_V0 = [None] * len(dates)
EMO_V1A = [None] * len(dates)
for i in range(len(dates)):
    s, s30, c7 = SENT[i], SC30_NORM[i], CHG7_NORM[i]
    if s is None or s30 is None or c7 is None:
        continue
    v0 = max(EMO_MIN, min(EMO_MAX, s + W1 * s30 - W2 * c7))
    EMO_V0[i] = v0
    bn, sn = BID_NORM[i], SPREAD_NORM[i]
    if bn is not None and sn is not None:
        EMO_V1A[i] = max(EMO_MIN, min(EMO_MAX, v0 + W3 * bn + W4 * sn))
n_v1a_fit = sum(1 for i in FIT if EMO_V1A[i] is not None)
print(f"[eval] emo_v1a fit 可算 {n_v1a_fit}/{len(FIT)}", flush=True)


# ---------------------------------------------------------------- 组件 IC + v1a 全 IC（fit 段）
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
    return ic_stats(ics)


def rolling_stability(vals, indices):
    dg = defaultdict(list)
    for i in indices:
        dg[dates[i]].append(i)
    monthly = defaultdict(list)
    for dd in sorted(dg):
        idxs = dg[dd]
        c = spearman([vals[i] for i in idxs], [fwd14[i] for i in idxs])
        if c is not None:
            monthly[dd[:7]].append(c)
    m_means = {m: sum(cs) / len(cs) for m, cs in monthly.items() if cs}
    n_pos = sum(1 for m in m_means if m_means[m] > 0)
    return {"months": len(m_means),
            "same_sign_ratio": round(n_pos / len(m_means), 4) if m_means else None}


def period_ic(vals, indices):
    dg = defaultdict(list)
    for i in indices:
        dg[dates[i]].append(i)
    by_period = defaultdict(list)
    for dd in sorted(dg):
        if dd not in period_of:
            continue
        idxs = dg[dd]
        c = spearman([vals[i] for i in idxs], [fwd14[i] for i in idxs])
        if c is not None:
            by_period[period_of[dd]].append(c)
    return {p: ic_stats(by_period[p]) for p in sorted(by_period)}


components = {}
for cid, cname, vals in (("sentiment", "恐慌分(approx_sentiment)", SENT),
                         ("sc30", "供给30日变化", X["sc30"]),
                         ("chg7", "价格7日动量", X["chg7"]),
                         ("bid", "bid(最高买价)", BID),
                         ("spread", "spread(卖价-最高买价)", SPREAD)):
    components[cid] = {
        "name": cname,
        "coverage_fit": round(sum(1 for i in FIT if vals[i] is not None) / len(FIT), 4),
        "IC14": factor_ic(vals, FIT, "fwd14"),
        "IC30": factor_ic(vals, FIT, "fwd30"),
        "rolling_stability": rolling_stability(vals, FIT),
    }
    print(f"[eval] 组件 {cid}: IC14={components[cid]['IC14'].get('mean')} 滚动同号={components[cid]['rolling_stability']['same_sign_ratio']}", flush=True)

# v1a 全 IC / 滚动 / 时期
v1a_ic14 = factor_ic(EMO_V1A, FIT, "fwd14")
v1a_ic30 = factor_ic(EMO_V1A, FIT, "fwd30")
v1a_roll = rolling_stability(EMO_V1A, FIT)
v1a_per = period_ic(EMO_V1A, FIT)

# 增量 IC 双口径（fit 段，硬判据）
inc_A_fit = ic_stats(inc_ic_daily(EMO_V1A, FIT))                 # 对核心因子集
inc_B_fit = ic_stats(inc_ic_daily(EMO_V1A, FIT, extra_cols=[EMO_V0]))  # 对核心因子集+emo_v0
# 判据 A 滚动同号月（增量 IC 逐日 -> 月均值）
dg_inc = defaultdict(list)
for i in FIT:
    if EMO_V1A[i] is not None and dates[i] in period_of:
        dg_inc[dates[i]].append(i)
inc_monthly = defaultdict(list)
for dd in sorted(dg_inc):
    idxs = dg_inc[dd]
    xs = [EMO_V1A[i] for i in idxs]
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
inc_A_roll = {"months": len(inc_m_means),
              "same_sign_ratio": round(inc_n_pos / len(inc_m_means), 4) if inc_m_means else None}

# val 复验（预注册 §5 声明：增量 IC 的 val 复验触碰；双口径）
val_A = val_B = None
if VAL:
    if sum(1 for i in VAL if EMO_V1A[i] is not None) >= 30:
        val_A = ic_stats(inc_ic_daily(EMO_V1A, VAL))
        val_B = ic_stats(inc_ic_daily(EMO_V1A, VAL, extra_cols=[EMO_V0]))
print(f"[eval] val 复验：A={val_A.get('mean') if val_A else None} B={val_B.get('mean') if val_B else None}", flush=True)

# ---------------------------------------------------------------- verdict（判据 §2：A 且 B 均过 -> 候选）
mA, mB = inc_A_fit.get("mean"), inc_B_fit.get("mean")
ssrA = inc_A_roll.get("same_sign_ratio")
if (mA is not None and mA >= INC_IC_MIN and ssrA is not None and ssrA >= ROLL_STABLE
        and mB is not None and mB >= INC_IC_MIN):
    verdict = "候选"
    verdict_note = (f"判据A 增量IC={mA} ≥0.02 且同号月 {ssrA} ≥0.80，判据B(相对v0)增量IC={mB} ≥0.02 -> v1a 候选成立")
else:
    verdict = "无增量"
    verdict_note = (f"判据A 增量IC={mA}（阈值0.02）/同号月 {ssrA}（阈值0.80）或判据B(相对v0)增量IC={mB}（阈值0.02）未过 -> v1a 无增量/证伪登记")

out = {
    "meta": {
        "card": "W7-1 v1a 内生情绪（v0+bid+spread）评估（roadmap v82）",
        "prereg": PREREG,
        "script": "references/run_emotion_v1a_eval.py",
        "split_oos": SPLIT,
        "fit_rows": len(FIT), "val_rows": len(VAL),
        "v1a_formula": "clip(emo_v0 + 0.5*bid_norm + 0.5*spread_norm, 0, 100)",
        "v0_formula": "clip(恐慌分 + 0.5*sc30_norm - 0.5*chg7_norm, 0, 100)（R5 冻结）",
        "weights_fixed": {"w1": W1, "w2": W2, "w3": W3, "w4": W4, "note": "固定值禁优化（判据 §1）"},
        "norm_def": "bid_norm/spread_norm/sc30_norm/chg7_norm = 逐日截面百分位 rank（0-100），fit/val 同规则",
        "core_factors": CORE_FACTORS,
        "thresholds": {"inc_ic_min": INC_IC_MIN, "roll_stable": ROLL_STABLE,
                       "verdict_rule": "判据A且判据B均过 -> 候选"},
        "oos_zone": "探索仅 fit 段（require_fit D6）；val 仅预注册 §5 声明增量 IC 复验触碰",
        "matrix": str(MATRIX.name),
        "matrix_db": "data/replay_cycle_win.db（与 R1/R5 同源）",
        "bid_source": "生产库 bid_history.buy_price_max（good_id 桥，全量含 val 仅复验）",
        "fwd_label_cost": "fwd14/fwd30 已扣 2% 双边成本",
        "engine": "v2-T13（只读，未改动）",
        "runtime_sec": round(time.time() - t0, 1),
    },
    "components_ic": components,
    "emo_v0": {
        "coverage_fit": round(sum(1 for i in FIT if EMO_V0[i] is not None) / len(FIT), 4),
        "IC14": factor_ic(EMO_V0, FIT, "fwd14"),
        "rolling_stability": rolling_stability(EMO_V0, FIT),
    },
    "emo_v1a": {
        "coverage_fit": round(n_v1a_fit / len(FIT), 4),
        "IC14": v1a_ic14, "IC30": v1a_ic30,
        "rolling_stability": v1a_roll,
        "IC14_by_period": v1a_per,
        "inc_ic_A_fit": inc_A_fit,          # 判据 A：对核心因子集
        "inc_ic_A_rolling": inc_A_roll,
        "inc_ic_B_fit": inc_B_fit,          # 判据 B：对核心因子集+emo_v0
        "val_recheck_A": val_A,
        "val_recheck_B": val_B,
        "verdict": verdict,
        "verdict_note": verdict_note,
    },
    "verdict": verdict,
    "note": ("仅筛查层：verdict=候选 交 PM 评估是否立'情绪守卫 v1a'落地卡（§4 四关+③审计+研发落地）；"
             "无增量/证伪 登记 registry 防重复挖。不进打分主干、不改族触发、不碰引擎。"),
}

json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("=" * 60)
print(f"saved -> {OUT}")
print(f"verdict: {verdict}")
print(f"  inc_A_fit: {inc_A_fit}  inc_A_roll: {inc_A_roll}")
print(f"  inc_B_fit: {inc_B_fit}")
print(f"  val_A: {val_A}  val_B: {val_B}")
print(f"runtime: {out['meta']['runtime_sec']}s")
