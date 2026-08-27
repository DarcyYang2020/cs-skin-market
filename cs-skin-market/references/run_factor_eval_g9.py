# -*- coding: utf-8 -*-
"""R1 组9 升主评补充脚本（②算法研究窗口 · 判据修订 DE）

背景：decision-log DE（2026-08-27）裁定——bid_history 实为 3 年全量，组9 spread/bid 升主评 IC，
阈值不变（沿用 R1 预注册判据 references/r1-factor-eval-prereg-2026-08-27.md §5），
bid_history 必须 date<2025-08-10 过滤守 oos_zone。

实现：
  - bid 因子 = bid_history.buy_price_max（生产库，good_id 桥接到矩阵 item_id）
  - spread 因子 = price_history.price_rmb（回放库，与矩阵同源）− bid_history.buy_price_max
  - 完整主评：截面 IC14/30、时期分段、滚动稳定、分层 5 档、增量 IC（对核心因子正交化）、相关性
  - 产物 data/_exp_factor_eval_g9_2026-08-27.json，由合并脚本并入主评估 JSON
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
from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.oos_guard import require_fit, in_oos_zone  # noqa: E402（D6 正式守卫，DJ②）

SPLIT = OOS_ZONE["val_start"]  # 与 D6 单一事实源对齐（=2025-08-10）
PREREG = "references/r1-factor-eval-prereg-2026-08-27.md"
MATRIX = ROOT / "data" / "_exp_fullscan_features_2026-08-20.json"
OUT = ROOT / "data" / "_exp_factor_eval_g9_2026-08-27.json"
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"
PROD_DB = DB_PATH

CORE_FACTORS = ["pct", "z", "chg30", "sc30", "vol30", "mchg30"]
IC_MIN = 0.05
ROLL_STABLE = 0.80
INC_IC_MIN = 0.02
CORR_REDUNDANT = 0.80
COV_MAIN = 0.80
COV_LOW = 0.30


# ---------------- 工具（与 run_factor_eval.py 同款，保持口径一致）
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


# ---------------- 数据
t0 = __import__("time").time()
m = json.load(open(MATRIX, encoding="utf-8"))
dates = m["date"]
items = m["item_id"]
X = m["X"]
fwd14 = m["fwd14"]
fwd30 = m["fwd30"]
item_name = {int(k): v for k, v in m["meta"]["item_name"].items()}
n = len(dates)
FIT = [i for i in range(n) if dates[i] < SPLIT]
VAL = [i for i in range(n) if dates[i] >= SPLIT]
print(f"[g9] matrix fit={len(FIT)} val={len(VAL)}（不触碰）", flush=True)

# 生产库：items name->good_id 桥 + bid_history（date<SPLIT）
conn = sqlite3.connect(str(PROD_DB), timeout=15)
conn.row_factory = sqlite3.Row
name2gid = {r["name"]: r["good_id"] for r in conn.execute("SELECT name, good_id FROM items")}
bid_rows = conn.execute(
    "SELECT good_id, date, buy_price_max FROM bid_history WHERE date < ?",
    (SPLIT,)).fetchall()
bid = {}  # (good_id, date) -> buy_price_max
for r in bid_rows:
    if r["buy_price_max"] is not None:
        bid[(r["good_id"], r["date"])] = r["buy_price_max"]
conn.close()
print(f"[g9] name->good_id 桥={len(name2gid)} bid 行={len(bid_rows)}", flush=True)

# 回放库：price_rmb（回放库 price_history.item_id = 生产库 items.id 体系，需 name 桥转换）
rconn = sqlite3.connect(str(REPLAY_DB), timeout=15)
rconn.row_factory = sqlite3.Row
pr_rows = rconn.execute(
    "SELECT item_id, date, price_rmb FROM price_history WHERE date < ?",
    (SPLIT,)).fetchall()
price = {}  # (ph_item_id=prod id, date) -> price_rmb
for r in pr_rows:
    if r["price_rmb"] is not None:
        price[(r["item_id"], r["date"])] = r["price_rmb"]
mrows = rconn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
rconn.close()
# name 桥：矩阵 item_id（good_id）-> 生产库 items.name -> 生产库 items.id（=回放 price_history.item_id）
# （生产库 name->good_id 已有 name2gid；再补 name->id）
conn2 = sqlite3.connect(str(PROD_DB), timeout=15)
conn2.row_factory = sqlite3.Row
nid_map = {r["name"]: r["id"] for r in conn2.execute("SELECT id, name FROM items")}
conn2.close()
GID2PHID = {}
for gid, nm in item_name.items():
    pid = nid_map.get(nm)
    if pid is not None:
        GID2PHID[gid] = pid
print(f"[g9] price 行={len(pr_rows)} market_index={len(mrows)} item_id桥={len(GID2PHID)}", flush=True)

# 时期映射（与主脚本同款）
from datetime import date, timedelta  # noqa: E402
m_dates = [r["date"] for r in mrows]
m_vals = [r["value"] for r in mrows]


def _sub(dstr, k):
    return (date.fromisoformat(dstr) - timedelta(days=k)).isoformat()


period_of = {}
for i, d in enumerate(m_dates):
    v = m_vals[i]
    def _find(k):
        t = _sub(d, k)
        lo, hi = 0, i
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if m_dates[mid] <= t:
                lo = mid
            else:
                hi = mid - 1
        return lo if m_dates[lo] <= t else None
    i30, i180 = _find(30), _find(180)
    c30 = (v / m_vals[i30] - 1) * 100 if i30 is not None and m_vals[i30] else None
    c180 = (v / m_vals[i180] - 1) * 100 if i180 is not None and m_vals[i180] else None
    if c30 is not None and c180 is not None:
        period_of[d] = state_bucket(round(c180, 2), round(c30, 2))

DAILY = defaultdict(list)
for i in FIT:
    if dates[i] in period_of:
        DAILY[dates[i]].append(i)
DAYS = sorted(DAILY)
print(f"[g9] fit 交易日（有时期）= {len(DAYS)}", flush=True)

# ---------------- 组9 因子构建（与矩阵行对齐）
BID = [None] * n
SPREAD = [None] * n
gid_of = {}
for i in FIT:
    it = items[i]
    dt = dates[i]
    require_fit(dt, prereg=PREREG, label="R1组9 spread/bid")  # D6 守卫：val 触碰即 raise
    if it not in gid_of:
        nm = item_name.get(it)
        gid_of[it] = name2gid.get(nm) if nm else None
    g = gid_of.get(it)
    b = bid.get((g, dt)) if g is not None else None
    if b is not None:
        BID[i] = b
        phid = GID2PHID.get(it)
        p = price.get((phid, dt)) if phid is not None else None
        if p is not None:
            SPREAD[i] = round(p - b, 4)

cov_bid = sum(1 for i in FIT if BID[i] is not None) / len(FIT)
cov_spread = sum(1 for i in FIT if SPREAD[i] is not None) / len(FIT)
print(f"[g9] bid 覆盖率={cov_bid:.3f} spread 覆盖率={cov_spread:.3f}", flush=True)


# ---------------- 评估（复用主脚本口径）
def eval_g9(fid, fname, cat, vals):
    v = vals
    cov = sum(1 for i in FIT if v[i] is not None) / len(FIT)
    ic14, ic30 = [], []
    for d in DAYS:
        idxs = DAILY[d]
        xs = [v[i] for i in idxs]
        c14 = spearman(xs, [fwd14[i] for i in idxs])
        c30 = spearman(xs, [fwd30[i] for i in idxs])
        if c14 is not None:
            ic14.append(c14)
        if c30 is not None:
            ic30.append(c30)
    s14, s30 = ic_stats(ic14), ic_stats(ic30)
    by_period = defaultdict(list)
    for d in DAYS:
        idxs = DAILY[d]
        c = spearman([v[i] for i in idxs], [fwd14[i] for i in idxs])
        if c is not None:
            by_period[period_of[d]].append(c)
    per14 = {p: ic_stats(by_period[p]) for p in sorted(by_period)}
    monthly = defaultdict(list)
    for d in DAYS:
        idxs = DAILY[d]
        c = spearman([v[i] for i in idxs], [fwd14[i] for i in idxs])
        if c is not None:
            monthly[d[:7]].append(c)
    m_means = {m: sum(cs) / len(cs) for m, cs in monthly.items() if cs}
    n_pos = sum(1 for m in m_means if m_means[m] > 0)
    roll = {"months": len(m_means),
            "same_sign_ratio": round(n_pos / len(m_means), 4) if m_means else None}
    pairs = [(v[i], fwd14[i]) for i in FIT if v[i] is not None and fwd14[i] is not None]
    quantile = None
    if len(pairs) >= 50:
        pairs.sort(key=lambda p: p[0])
        nq = len(pairs) // 5
        q = []
        for k in range(5):
            seg = pairs[k * nq:(k + 1) * nq] if k < 4 else pairs[4 * nq:]
            if seg:
                avg = sum(p[1] for p in seg) / len(seg)
                win = sum(1 for p in seg if p[1] > 0) / len(seg)
                q.append({"q": k + 1, "n": len(seg), "avg_fwd14": round(avg, 3), "win": round(win, 4)})
        quantile = q
    inc_daily = []
    for d in DAYS:
        idxs = DAILY[d]
        xs = [v[i] for i in idxs]
        core_vals = [[X[c][i] for i in idxs] for c in CORE_FACTORS]
        res = ols_residual(xs, core_vals)
        if res is None:
            continue
        c = spearman(res, [fwd14[i] for i in idxs])
        if c is not None:
            inc_daily.append(c)
    inc = ic_stats(inc_daily)
    # 与已有主评因子的相关性（用矩阵因子 pct/z/chg30/vol30/sc30 代表）
    redun = None
    for cf in ("pct", "z", "chg30", "sc30", "vol30"):
        cors = []
        for d in DAYS:
            idxs = DAILY[d]
            c = spearman([v[i] for i in idxs], [X[cf][i] for i in idxs])
            if c is not None:
                cors.append(c)
        if cors and sum(cors) / len(cors) > CORR_REDUNDANT:
            redun = cf
            break
    mean14 = s14.get("mean")
    ssr = roll.get("same_sign_ratio")
    stable = ssr is not None and ssr >= ROLL_STABLE
    if cov < COV_LOW:
        verdict = "待数据"
    elif abs(mean14) >= IC_MIN and stable:
        verdict = "候选"
    elif abs(mean14) >= IC_MIN and not stable:
        verdict = "不稳定"
    else:
        verdict = "弱/无效"
    return {
        "id": fid, "name": fname, "category": cat, "role": "流动性",
        "coverage": round(cov, 4), "IC14": s14, "IC30": s30,
        "IC14_by_period": per14, "rolling_stability": roll,
        "quantile_table": quantile, "cond_ic": None, "inc_ic": inc,
        "redundant_with": redun, "verdict": verdict,
        "tested_at": "2026-08-27",
    }


cards = [
    eval_g9("bid", "bid(最高买价)", "盘口/流动性", BID),
    eval_g9("spread", "spread(卖价-最高买价)", "盘口/流动性", SPREAD),
]
for c in cards:
    per = c.get("IC14_by_period") or {}
    sig = [p for p, s in per.items() if (s or {}).get("n", 0) >= 10 and abs((s or {}).get("t") or 0) > 2]
    c["single_period_dep"] = sig[0] if len(per) >= 2 and len(sig) == 1 else None

out = {
    "meta": {
        "card": "R1 组9 升主评（判据修订 DE，2026-08-27）",
        "prereg": "references/r1-factor-eval-prereg-2026-08-27.md（DE 修订组9）",
        "split_oos": SPLIT, "fit_rows": len(FIT), "val_rows": len(VAL),
        "note": "bid=bid_history.buy_price_max（生产库）；spread=price_history.price_rmb(回放库)−buy_price_max；bid_history date<SPLIT 过滤守 oos_zone；lowest_sell 全 NULL（D2 未采历史），spread 用卖价-买价派生；阈值沿用主判据",
        "runtime_sec": round(__import__("time").time() - t0, 1),
    },
    "cards": cards,
}
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("=" * 60)
print(f"saved -> {OUT}")
for c in cards:
    print(f"  {c['id']}: coverage={c['coverage']} IC14={c['IC14'].get('mean') if c['IC14'] else None} "
          f"verdict={c['verdict']} redundant={c['redundant_with']}")
