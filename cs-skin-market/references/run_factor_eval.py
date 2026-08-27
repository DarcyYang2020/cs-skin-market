# -*- coding: utf-8 -*-
"""R1 因子评估脚本（②算法研究窗口 · 预注册判据 references/r1-factor-eval-prereg-2026-08-27.md）

硬约束（判据 §5）：
  1. 仅跑 fit 段（date < '2025-08-10'）；val 段（oos_zone）不参与任何计算，触碰即作废；
  2. 只读生产库（SELECT），不写任何生产数据；
  3. 不改引擎、不立落地卡；产物仅 data/_exp_factor_eval_2026-08-27.json；
  4. 确定性：无随机性，同一输入同一输出。
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
from pipeline.trend_health import compute_trend_health  # noqa: E402
from pipeline.backtest_common import approx_sentiment  # noqa: E402
from pipeline.oos_guard import require_fit, in_oos_zone  # noqa: E402（D6 正式守卫，DJ②）

SPLIT = OOS_ZONE["val_start"]  # 与 D6 oos_zone 单一事实源对齐（=2025-08-10）
PREREG = "references/r1-factor-eval-prereg-2026-08-27.md"  # 预注册判据（DE 修订组9）
MATRIX = ROOT / "data" / "_exp_fullscan_features_2026-08-20.json"
OUT = ROOT / "data" / "_exp_factor_eval_2026-08-27.json"
# 矩阵生成于 replay_cycle_win.db（items.id = 回放库 id 体系）；price_history/market_index 必须同源
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"
# 生产库（bid_history 覆盖率用；bid_history 在回放库为 0 行）
PROD_DB = DB_PATH

# 核心因子集（增量 IC 正交化基准；判据 §3：R2 落定前先以引擎六维）
CORE_FACTORS = ["pct", "z", "chg30", "sc30", "vol30", "mchg30"]

# 判据 §5 硬阈值
IC_MIN = 0.05          # |IC14 均值| < 0.05 -> 弱/无效
ROLL_STABLE = 0.80     # 滚动同号月份占比 >= 80% -> 稳定
INC_IC_MIN = 0.02      # 增量 IC >= 0.02 才算新信息
CORR_REDUNDANT = 0.80  # 因子间 IC 相关 > 0.8 -> 冗余
COV_MAIN = 0.80        # 覆盖率 >= 80% 主评资格
COV_LOW = 0.30         # 覆盖率 < 30% -> 待数据


# ---------------------------------------------------------------- 工具
def rank_list(vals):
    """vals: list[float]（无 None）-> 平均秩列表（1..n）"""
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
    """daily_ics: list[float]（每日截面 IC）-> dict(mean/std/t/pos_ratio/n)"""
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
    """截面多元回归 y ~ Xcols(+常数)，返回残差 list。矩阵求逆用高斯-约当。"""
    # 过滤任何含 None 的行（y 或任一 X 为 None 均剔除）
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
    """高斯-约当消元解 A x = b（原地复制）"""
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


# ---------------------------------------------------------------- 数据加载
t0 = time.time()


def load_matrix():
    d = json.load(open(MATRIX, encoding="utf-8"))
    dates = d["date"]
    items = d["item_id"]
    X = d["X"]
    fwd14 = d["fwd14"]
    fwd30 = d["fwd30"]
    n = len(dates)
    fit = [i for i in range(n) if dates[i] < SPLIT]
    val = [i for i in range(n) if dates[i] >= SPLIT]
    if not fit:
        sys.exit("FATAL: fit 段为空（SPLIT=%s）" % SPLIT)
    print(f"[data] matrix rows={n} fit={len(fit)} val={len(val)}（val=oos_zone 不参与计算）", flush=True)
    return dates, items, X, fwd14, fwd30, fit, val


dates, items, X, fwd14, fwd30, FIT, VAL = load_matrix()
assert len(VAL) == 0 or True  # val 仅计数，绝不进入计算

# DB 读取（只读；price_history/market_index 用回放库与矩阵同源，bid_history 用生产库）
conn = sqlite3.connect(str(REPLAY_DB), timeout=15)
conn.row_factory = sqlite3.Row

# price_history: 每品价格/在售量序列（供复算因子；item_id = 回放库 id，与矩阵对齐）
rows = conn.execute(
    "SELECT item_id, date, price_rmb, in_sale_count FROM price_history "
    "WHERE date < ? ORDER BY item_id, date", (SPLIT,)).fetchall()
ph = defaultdict(list)  # item_id -> [(date, price, in_sale)]
for r in rows:
    ph[r["item_id"]].append((r["date"], r["price_rmb"], r["in_sale_count"]))
print(f"[data] replay price_history fit rows={len(rows)} items={len(ph)}", flush=True)

# market_index: 大盘 value（算 chg30/chg180 -> 时期；与矩阵 mchg 同源）
mrows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
m_dates = [r["date"] for r in mrows]
m_vals = [r["value"] for r in mrows]
print(f"[data] replay market_index rows={len(mrows)}", flush=True)
conn.close()

# bid_history（生产库）：组9 覆盖率（回放库 bid_history 为 0 行）
pconn = sqlite3.connect(str(PROD_DB), timeout=15)
pconn.row_factory = sqlite3.Row
bid_rows = pconn.execute(
    "SELECT COUNT(*) AS n, COUNT(DISTINCT date) AS days "
    "FROM bid_history WHERE date < ?", (SPLIT,)).fetchone()
bid_n = bid_rows["n"] or 0
bid_days = bid_rows["days"] or 0
pconn.close()
print(f"[data] prod bid_history fit rows={bid_n} distinct_days={bid_days}", flush=True)


# ---------------------------------------------------------------- 大盘时期映射
def mkt_ctx():
    """date -> (chg180, chg30)（日期偏移 30/180 天取最近 value）"""
    ctx = {}
    for i, d in enumerate(m_dates):
        v = m_vals[i]
        # 找 <= (d-30)/(d-180) 的最大日期索引（二分）
        def _find(days_back):
            target = _sub_days(d, days_back)
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
            ctx[d] = (round(chg180, 2), round(chg30, 2))
    return ctx


def _sub_days(dstr, ndays):
    from datetime import date, timedelta
    d = date.fromisoformat(dstr) - timedelta(days=ndays)
    return d.isoformat()


MKT = mkt_ctx()
period_of = {}
for _d in m_dates:
    if _d in MKT:
        c180, c30 = MKT[_d]
        period_of[_d] = state_bucket(c180, c30)
n_period = defaultdict(int)
for _d, _p in period_of.items():
    n_period[_p] += 1
print(f"[data] 时期映射 days={len(period_of)} 分布={dict(n_period)}", flush=True)


# ---------------------------------------------------------------- 复算因子（按品序列）
# item_id 桥：矩阵 item_id（回放库 items.id=good_id 体系）-> name -> 生产库 items.id
# （= 回放库 price_history.item_id 体系 1-222；回放库内部两套 id，必须经 name 桥）
import json as _json
_mat = _json.load(open(MATRIX, encoding="utf-8"))
_mat_id2name = {int(k): v for k, v in _mat["meta"]["item_name"].items()}
_pc = sqlite3.connect(str(PROD_DB), timeout=15)
_pc.row_factory = sqlite3.Row
_pn2id = {r["name"]: r["id"] for r in _pc.execute("SELECT id, name FROM items")}
_pc.close()
GID2PHID = {gid: _pn2id.get(nm) for gid, nm in _mat_id2name.items() if nm in _pn2id}
print(f"[derived] item_id 桥（good_id -> 生产库id）命中 {len(GID2PHID)}/{len(_mat_id2name)}", flush=True)


# 对矩阵每行 (item_id, date) 计算：s7_ratio / sentiment / th5 维
def build_derived():
    """返回 lists（与矩阵行对齐）：s7_ratio, sentiment, th_*（None=缺）"""
    # 每品：date -> index 映射（key = 回放库 price_history.item_id = 生产库 items.id 体系）
    seq = {}   # ph_item_id -> {date: idx}
    for it in ph:
        seq[it] = {d[0]: k for k, d in enumerate(ph[it])}
    s7r = [None] * len(dates)
    sent = [None] * len(dates)
    th5 = {k: [None] * len(dates) for k in
           ("persistence", "steepness", "structure", "supply", "anomaly")}
    done = 0
    for i in range(len(dates)):
        it = items[i]
        dt = dates[i]
        if i in VAL:  # val 行跳过（不计算；守院由下方 require_fit 兜底）
            continue
        require_fit(dt, prereg=PREREG, label="R1因子评估 build_derived")  # D6 守卫：val 触碰即 raise
        phid = GID2PHID.get(it)
        if phid is None:
            continue
        s = seq.get(phid)
        if not s or dt not in s:
            continue
        idx = s[dt]
        bars = ph[phid]
        price = bars[idx][1]
        ins = bars[idx][2]
        if idx >= 0:
            # s7_ratio：s7/s30（signal_tracking.py:68 口径，用 in_sale_count）
            window = [b[2] for b in bars[max(0, idx - 29):idx + 1] if b[2] is not None]
            if len(window) >= 30:
                s30 = sum(window[-30:]) / 30.0
                s7 = sum(window[-7:]) / 7.0
                if s30 > 0:
                    s7r[i] = round(s7 / s30, 4)
            # sentiment：approx_sentiment(prices, idx)
            prices_hist = [b[1] for b in bars[:idx + 1] if b[1] is not None]
            if len(prices_hist) >= 15:
                sent[i] = approx_sentiment(prices_hist, len(prices_hist) - 1)
            # 趋势健康度 5 维
            if len(prices_hist) >= 30:
                th = compute_trend_health(prices_hist,
                                          supply=[b[2] for b in bars[:idx + 1] if b[2] is not None])
                th5["persistence"][i] = getattr(th, "persistence_score", None)
                th5["steepness"][i] = getattr(th, "steepness_score", None)
                th5["structure"][i] = getattr(th, "structure_score", None)
                th5["supply"][i] = getattr(th, "supply_score", None)
                th5["anomaly"][i] = getattr(th, "anomaly_score", None)
        done += 1
        if done % 20000 == 0:
            print(f"[derived] {done}/{len(FIT)}", flush=True)
    return s7r, sent, th5


print("[derived] 开始复算 s7_ratio/sentiment/趋势健康度5维（仅 fit 段）...", flush=True)
S7R, SENT, TH5 = build_derived()
print("[derived] 完成", flush=True)


# ---------------------------------------------------------------- 因子表
def cols(name):
    return X[name] if name in X else None


FACTORS = [
    # (id, name, category, role, values-fn)
    ("pct", "pct(90日分位)", "价值", "打分", lambda: X["pct"]),
    ("z", "z(90日zscore)", "价值", "打分", lambda: X["z"]),
    ("chg7", "chg7", "动量", "打分+触发", lambda: X["chg7"]),
    ("chg30", "chg30", "动量", "打分+触发", lambda: X["chg30"]),
    ("chg90", "chg90", "动量", "打分+触发", lambda: X["chg90"]),
    ("vol7", "vol7", "波动", "风险调节", lambda: X["vol7"]),
    ("vol30", "vol30", "波动", "风险调节", lambda: X["vol30"]),
    ("sc7", "sc7", "供给", "打分", lambda: X["sc7"]),
    ("sc30", "sc30", "供给", "打分", lambda: X["sc30"]),
    ("s7_ratio", "s7_ratio", "供给", "打分", lambda: S7R),
    ("th_persistence", "趋势健康度·持续性", "趋势", "决策触发", lambda: TH5["persistence"]),
    ("th_steepness", "趋势健康度·陡峭度", "趋势", "决策触发", lambda: TH5["steepness"]),
    ("th_structure", "趋势健康度·结构", "趋势", "决策触发", lambda: TH5["structure"]),
    ("th_supply", "趋势健康度·供给", "趋势", "决策触发", lambda: TH5["supply"]),
    ("th_anomaly", "趋势健康度·异常", "趋势", "决策触发", lambda: TH5["anomaly"]),
    ("sentiment", "sentiment(approx)", "情绪", "加分/过滤", lambda: SENT),
    ("mchg7", "mchg7", "市场环境", "条件因子", lambda: X["mchg7"]),
    ("mchg21", "mchg21", "市场环境", "条件因子", lambda: X["mchg21"]),
    ("mchg30", "mchg30", "市场环境", "条件因子", lambda: X["mchg30"]),
]

GROUPS = {
    1: ["pct", "z"],
    2: ["chg7", "chg30", "chg90"],
    3: ["vol7", "vol30"],
    4: ["sc7", "sc30", "s7_ratio"],
    5: ["th_persistence", "th_steepness", "th_structure", "th_supply", "th_anomaly"],
    6: ["sentiment"],
    7: ["mchg7", "mchg21", "mchg30"],
    8: ["spread", "bid"],  # 组9（判据编号）：仅覆盖率
}

# 判据 10 组编号映射（保持与预注册文档一致）
GROUP_LABEL = {
    1: "组1 pct/z（价值）", 2: "组3 chg（动量）", 3: "组4 vol（波动）",
    4: "组5/6 sc/s7_ratio（供给，条件IC）", 5: "组7 趋势健康度5维",
    6: "组8 sentiment（情绪，预期证伪）", 7: "组10 mchg（市场环境，regime）",
    8: "组9 spread/bid（盘口，仅覆盖率）",
}


def date_of(i):
    return dates[i]


def daily_groups(ids):
    """按日分组 fit 行索引"""
    dg = defaultdict(list)
    for i in FIT:
        if date_of(i) in period_of:
            dg[date_of(i)].append(i)
    return dg


print("[eval] 开始截面 IC / 分层 / 滚动 / 时期评估...", flush=True)
DAILY = daily_groups(list(range(len(FIT))))
DAYS = sorted(DAILY)
print(f"[eval] fit 段交易日数（有时期映射）= {len(DAYS)}", flush=True)


def eval_factor(fid, fname, vals, cond_ic=False):
    """单因子评估卡"""
    v = vals()
    # 覆盖率
    cov = sum(1 for i in FIT if v[i] is not None) / len(FIT) if FIT else 0
    # 逐日截面 IC14 / IC30
    ic14, ic30 = [], []
    for d in DAYS:
        idxs = DAILY[d]
        xs = [v[i] for i in idxs]
        y14 = [fwd14[i] for i in idxs]
        y30 = [fwd30[i] for i in idxs]
        c14 = spearman(xs, y14)
        c30 = spearman(xs, y30)
        if c14 is not None:
            ic14.append(c14)
        if c30 is not None:
            ic30.append(c30)
    s14 = ic_stats(ic14)
    s30 = ic_stats(ic30)
    # 时期分段 IC14
    by_period = defaultdict(list)
    for k, d in enumerate(DAYS):
        idxs = DAILY[d]
        xs = [v[i] for i in idxs]
        c = spearman(xs, [fwd14[i] for i in idxs])
        if c is not None:
            by_period[period_of[d]].append(c)
    per14 = {p: ic_stats(by_period[p]) for p in sorted(by_period)}
    # 滚动稳定性（按月）
    monthly = defaultdict(list)
    for k, d in enumerate(DAYS):
        idxs = DAILY[d]
        c = spearman([v[i] for i in idxs], [fwd14[i] for i in idxs])
        if c is not None:
            monthly[d[:7]].append(c)
    m_means = {m: sum(cs) / len(cs) for m, cs in monthly.items() if cs}
    n_pos = sum(1 for m in m_means if m_means[m] > 0)
    roll = {"months": len(m_means), "same_sign_ratio": round(n_pos / len(m_means), 4) if m_means else None}
    # 分层 5 档（fwd14）
    pairs = [(v[i], fwd14[i]) for i in FIT if v[i] is not None and fwd14[i] is not None]
    quantile = None
    if len(pairs) >= 50:
        pairs.sort(key=lambda p: p[0])
        q = []
        nq = len(pairs) // 5
        for k in range(5):
            seg = pairs[k * nq:(k + 1) * nq] if k < 4 else pairs[4 * nq:]
            if seg:
                avg = sum(p[1] for p in seg) / len(seg)
                win = sum(1 for p in seg if p[1] > 0) / len(seg)
                q.append({"q": k + 1, "n": len(seg), "avg_fwd14": round(avg, 3), "win": round(win, 4)})
        quantile = q
    # 增量 IC（对核心因子截面回归取残差）
    inc = None
    if fid not in CORE_FACTORS:
        inc_daily = []
        for d in DAYS:
            idxs = DAILY[d]
            xs = [v[i] for i in idxs]
            y14 = [fwd14[i] for i in idxs]
            core_cols = [X[c] for c in CORE_FACTORS]
            # 该日核心因子值
            core_vals = [[X[c][i] for i in idxs] for c in CORE_FACTORS]
            res = ols_residual(xs, core_vals)
            if res is None:
                continue
            c = spearman(res, y14)
            if c is not None:
                inc_daily.append(c)
        inc = ic_stats(inc_daily)
    # 条件 IC（供给类：sc30 收缩/扩张 条件下本因子 IC14）
    cond = None
    if cond_ic:
        c_shrink, c_expand = [], []
        for d in DAYS:
            idxs = DAILY[d]
            sc = [X["sc30"][i] for i in idxs]
            xs = [v[i] for i in idxs]
            y14 = [fwd14[i] for i in idxs]
            sh = spearman([xs[k] for k in range(len(idxs)) if sc[k] is not None and sc[k] < 0],
                          [y14[k] for k in range(len(idxs)) if sc[k] is not None and sc[k] < 0])
            ex = spearman([xs[k] for k in range(len(idxs)) if sc[k] is not None and sc[k] > 0],
                          [y14[k] for k in range(len(idxs)) if sc[k] is not None and sc[k] > 0])
            if sh is not None:
                c_shrink.append(sh)
            if ex is not None:
                c_expand.append(ex)
        cond = {"shrink_sc30": ic_stats(c_shrink), "expand_sc30": ic_stats(c_expand)}
    return {
        "id": fid, "name": fname,
        "coverage": round(cov, 4),
        "IC14": s14, "IC30": s30,
        "IC14_by_period": per14,
        "rolling_stability": roll,
        "quantile_table": quantile,
        "cond_ic": cond,
        "inc_ic": inc,
        "redundant_with": None,
    }


cards = []
for fid, fname, cat, role, fn in FACTORS:
    cond = fid in ("sc7", "sc30", "s7_ratio")
    print(f"[eval] {fid} ...", flush=True)
    c = eval_factor(fid, fname, fn, cond_ic=cond)
    c["category"] = cat
    c["role"] = role
    cards.append(c)

# 组 9：spread/bid 覆盖率卡（判据原按"数据短"标待数据；实际 bid_history 3 年全量，待 PM 裁定升主评）
for sid, sname in (("spread", "spread(日点差派生)"), ("bid", "bid(最高买价)")):
    cards.append({
        "id": sid, "name": sname, "category": "盘口/流动性", "role": "流动性",
        "coverage": round(bid_days / len(DAYS), 4) if DAYS else 0,
        "IC14": None, "IC30": None, "IC14_by_period": None,
        "rolling_stability": None, "quantile_table": None, "cond_ic": None,
        "inc_ic": None, "redundant_with": None,
        "note": "bid_history(fit 段) rows=%d, days=%d —— 3 年全量非数据短；判据原按'数据短→仅覆盖率→待数据'，待 PM 裁定升主评后补 IC" % (bid_n, bid_days),
    })

# ---------------------------------------------------------------- 相关性去重
print("[eval] 因子间 IC 相关矩阵（逐日均值）...", flush=True)
factor_vals = {c["id"]: c for c in cards if c["id"] not in ("spread", "bid")}
ids = [c["id"] for c in cards if c["id"] not in ("spread", "bid")]
valmap = {}
for fid in ids:
    for row in FACTORS:
        if row[0] == fid:
            valmap[fid] = row[4]()
            break
for a in range(len(ids)):
    for b in range(a + 1, len(ids)):
        fa, fb = ids[a], ids[b]
        cors = []
        for d in DAYS:
            idxs = DAILY[d]
            c = spearman([valmap[fa][i] for i in idxs], [valmap[fb][i] for i in idxs])
            if c is not None:
                cors.append(c)
        if cors and sum(cors) / len(cors) > CORR_REDUNDANT:
            for c in cards:
                if c["id"] == fb and c["redundant_with"] is None:
                    c["redundant_with"] = fa
            print(f"  [corr] {fb} ~ {fa}: mean={sum(cors)/len(cors):.3f} -> 冗余标记", flush=True)


# ---------------------------------------------------------------- verdict
def verdict_of(c):
    if c["id"] in ("spread", "bid"):
        return "待数据"
    cov = c["coverage"]
    if cov < COV_LOW:
        return "待数据"
    if c["category"] == "市场环境":
        return "条件因子（regime 分段评估，不做单因子主判）"
    if c["category"] == "供给" and c["id"] in ("sc7", "sc30", "s7_ratio"):
        # 供给类：条件 IC 为主判
        cond = c.get("cond_ic") or {}
        sh = (cond.get("shrink_sc30") or {}).get("mean")
        return "候选（条件IC）" if (sh is not None and abs(sh) >= IC_MIN) else "弱/无效（条件IC）"
    s14 = c.get("IC14") or {}
    mean14 = s14.get("mean")
    roll = c.get("rolling_stability") or {}
    ssr = roll.get("same_sign_ratio")
    if mean14 is None:
        return "无效（无IC）"
    stable = (ssr is not None and ssr >= ROLL_STABLE)
    if abs(mean14) >= IC_MIN and stable:
        return "候选"
    if abs(mean14) >= IC_MIN and not stable:
        return "不稳定"
    return "弱/无效"


# 单时期依赖检查
for c in cards:
    per = c.get("IC14_by_period") or {}
    sig = [p for p, s in per.items() if (s or {}).get("n", 0) >= 10 and abs((s or {}).get("t") or 0) > 2]
    if len(per) >= 2 and len(sig) == 1:
        c["single_period_dep"] = sig[0]
    else:
        c["single_period_dep"] = None

for c in cards:
    c["verdict"] = verdict_of(c)
    c["tested_at"] = "2026-08-27"

# 汇总
summary = {}
for g, fids in GROUPS.items():
    gv = [c["verdict"] for c in cards if c["id"] in fids]
    summary[GROUP_LABEL[g]] = gv

out = {
    "meta": {
        "card": "R1 因子评估（roadmap v82）",
        "prereg": "references/r1-factor-eval-prereg-2026-08-27.md",
        "script": "references/run_factor_eval.py",
        "split_oos": SPLIT,
        "fit_rows": len(FIT), "val_rows": len(VAL),
        "note_val": "val=oos_zone，未参与任何计算（触碰即作废）",
        "matrix": str(MATRIX.name),
        "matrix_db": "data/replay_cycle_win.db（items.id 回放库体系，price_history/market_index 同源）",
        "fwd_label_cost": "fwd14/fwd30 已扣 2% 双边成本（矩阵 COST=2.0，2026-08-20 生成）；E2 费率校准(买0/卖1)后需重评",
        "engine": "v2-T13（只读，未改动）",
        "ic_def": "截面 Spearman(因子, fwd14/fwd30)，逐日 IC 均值/滚动/时期分段",
        "period_def": "state_bucket(chg180, chg30) 五时期（market_context 同款）",
        "core_factors": CORE_FACTORS,
        "thresholds": {"ic_min": IC_MIN, "roll_stable": ROLL_STABLE,
                       "inc_ic_min": INC_IC_MIN, "corr_redundant": CORR_REDUNDANT,
                       "cov_main": COV_MAIN, "cov_low": COV_LOW},
        "runtime_sec": round(time.time() - t0, 1),
    },
    "groups": {GROUP_LABEL[g]: fids for g, fids in GROUPS.items()},
    "summary": summary,
    "cards": cards,
}

json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("=" * 60)
print(f"saved -> {OUT}")
print("summary:")
for k, v in summary.items():
    print(f"  {k}: {v}")
print(f"runtime: {out['meta']['runtime_sec']}s")
