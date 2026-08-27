# -*- coding: utf-8 -*-
"""③审计 · W7-1 v1a 独立复算脚本（2026-08-27，只读，不覆盖②产物）。

对 data/_exp_emotion_v1a_2026-08-27.json 独立只读核验：
- 组件 IC（sentiment/sc30/chg7/bid/spread）+ emo_v0/emo_v1a 全 IC + 滚动 + 时期
- 判据 A（核心6因子正交化增量 IC）+ 判据 B（核心6+emo_v0 联合正交化增量 IC）+ val 复验
- 守院核验（require_fit fit 段 / val 仅复验）
输出：data/_audit_v1a_recompute_2026-08-27.json（审计产物）。
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
ISO = ROOT / "data" / "_exp_emotion_v1a_2026-08-27.json"
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"
CORE_FACTORS = ["pct", "z", "chg30", "sc30", "vol30", "mchg30"]
W1 = W2 = W3 = W4 = 0.5

audit = {"title": "③审计 W7-1 v1a 独立复算", "checks": {}, "pass": True}


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


def daily_ic(vals, indices, fwd, core=None, extra=None):
    dg = defaultdict(list)
    for i in indices:
        dg[dates[i]].append(i)
    out = []
    for dd in sorted(dg):
        idxs = dg[dd]
        xs = [vals[i] for i in idxs]
        ys = [fwd[i] for i in idxs]
        cols = [[X[c][i] for i in idxs] for c in core] if core else None
        if extra:
            cols = (cols or []) + [[e[i] for i in idxs] for e in extra]
        if cols:
            res = ols_residual(xs, cols)
            c = spearman(res, ys) if res is not None else None
        else:
            c = spearman(xs, ys)
        if c is not None:
            out.append(c)
    return out


def rolling(rows):
    monthly = defaultdict(list)
    for dk, c in rows:
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
conn.close()

_mat_id2name = {int(k): v for k, v in d["meta"]["item_name"].items()}
_pc = sqlite3.connect(str(DB_PATH), timeout=15)
_pc.row_factory = sqlite3.Row
_name2gid = {r["name"]: r["good_id"] for r in _pc.execute("SELECT name, good_id FROM items")}
_nid_map = {r["name"]: r["id"] for r in _pc.execute("SELECT id, name FROM items")}
bid_rows = _pc.execute("SELECT good_id, date, buy_price_max FROM bid_history").fetchall()
_pc.close()
bid = {}
for r in bid_rows:
    if r["buy_price_max"] is not None:
        bid[(r["good_id"], r["date"])] = r["buy_price_max"]
GID2PHID = {gid: _nid_map.get(nm) for gid, nm in _mat_id2name.items() if nm in _nid_map}

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

BID = [None] * len(dates)
SPREAD = [None] * len(dates)
for i in range(len(dates)):
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


def daily_rank(vals):
    norm = [None] * len(dates)
    by_day = defaultdict(list)
    for i in range(len(dates)):
        if vals[i] is not None:
            by_day[dates[i]].append(i)
    for dd, idxs in by_day.items():
        if len(idxs) < 5:
            continue
        rk = avg_ranks([vals[i] for i in idxs])
        rk100 = [(r - 1) / (len(idxs) - 1) * 100.0 if len(idxs) > 1 else 50.0 for r in rk]
        for k, i in enumerate(idxs):
            norm[i] = rk100[k]
    return norm


SC30_NORM = daily_rank(X["sc30"])
CHG7_NORM = daily_rank(X["chg7"])
BID_NORM = daily_rank(BID)
SPREAD_NORM = daily_rank(SPREAD)

EMO_V0 = [None] * len(dates)
EMO_V1A = [None] * len(dates)
n_v1a_fit = 0
for i in range(len(dates)):
    s, s30, c7 = SENT[i], SC30_NORM[i], CHG7_NORM[i]
    if s is None or s30 is None or c7 is None:
        continue
    v0 = max(0.0, min(100.0, s + W1 * s30 - W2 * c7))
    EMO_V0[i] = v0
    bn, sn = BID_NORM[i], SPREAD_NORM[i]
    if bn is not None and sn is not None:
        EMO_V1A[i] = max(0.0, min(100.0, v0 + W3 * bn + W4 * sn))
        if i in FIT:
            n_v1a_fit += 1

# ---------- 独立复算 ----------
res = {}
for cid, vals in (("sentiment", SENT), ("sc30", X["sc30"]), ("chg7", X["chg7"]),
                  ("bid", BID), ("spread", SPREAD)):
    ic14 = ic_stats(daily_ic(vals, FIT, fwd14))
    ic30 = ic_stats(daily_ic(vals, FIT, fwd30))
    cov = round(sum(1 for i in FIT if vals[i] is not None) / len(FIT), 4)
    dg = defaultdict(list)
    for i in FIT:
        dg[dates[i]].append(i)
    rows = []
    for dd in sorted(dg):
        c = spearman([vals[i] for i in dg[dd]], [fwd14[i] for i in dg[dd]])
        if c is not None:
            rows.append((dd, c))
    res[cid] = {"coverage_fit": cov, "IC14": ic14, "IC30": ic30,
                "rolling_stability": rolling(rows)}

res["emo_v0"] = {"coverage_fit": round(sum(1 for i in FIT if EMO_V0[i] is not None) / len(FIT), 4),
                 "IC14": ic_stats(daily_ic(EMO_V0, FIT, fwd14))}
v1a_ic14 = ic_stats(daily_ic(EMO_V1A, FIT, fwd14))
v1a_ic30 = ic_stats(daily_ic(EMO_V1A, FIT, fwd30))
dg = defaultdict(list)
for i in FIT:
    dg[dates[i]].append(i)
rows = []
for dd in sorted(dg):
    c = spearman([EMO_V1A[i] for i in dg[dd]], [fwd14[i] for i in dg[dd]])
    if c is not None:
        rows.append((dd, c))
v1a_roll = rolling(rows)
inc_A = ic_stats(daily_ic(EMO_V1A, FIT, fwd14, core=CORE_FACTORS))
inc_B = ic_stats(daily_ic(EMO_V1A, FIT, fwd14, core=CORE_FACTORS, extra=[EMO_V0]))
val_A = ic_stats(daily_ic(EMO_V1A, VAL, fwd14, core=CORE_FACTORS)) if VAL else {"n": 0}
val_B = ic_stats(daily_ic(EMO_V1A, VAL, fwd14, core=CORE_FACTORS, extra=[EMO_V0])) if VAL else {"n": 0}
# 判据 A 滚动（period_of 过滤口径，同②）
from pipeline.market_context import state_bucket as _sb
from datetime import date as _date, timedelta as _td
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
_dg2 = defaultdict(list)
for i in FIT:
    if EMO_V1A[i] is not None and dates[i] in _period_of:
        _dg2[dates[i]].append(i)
inc_rows = []
for dd in sorted(_dg2):
    idxs = _dg2[dd]
    resd = ols_residual([EMO_V1A[i] for i in idxs], [[X[c][i] for i in idxs] for c in CORE_FACTORS])
    c = spearman(resd, [fwd14[i] for i in idxs]) if resd is not None else None
    if c is not None:
        inc_rows.append((dd, c))
inc_A_roll = rolling(inc_rows)

res["emo_v1a"] = {"coverage_fit": round(n_v1a_fit / len(FIT), 4),
                  "IC14": v1a_ic14, "IC30": v1a_ic30, "rolling_stability": v1a_roll,
                  "inc_ic_A_fit": inc_A, "inc_ic_A_rolling": inc_A_roll,
                  "inc_ic_B_fit": inc_B, "val_recheck_A": val_A, "val_recheck_B": val_B}

# ---------- 对比产物 ----------
iso = json.load(open(ISO, encoding="utf-8"))
checks = {}
for cid in ("sentiment", "sc30", "chg7", "bid", "spread"):
    exp = iso["components_ic"][cid]
    act = res[cid]
    ok = (act["coverage_fit"] == exp["coverage_fit"]
          and act["IC14"]["mean"] == exp["IC14"]["mean"] and act["IC14"]["n"] == exp["IC14"]["n"]
          and act["IC30"]["mean"] == exp["IC30"]["mean"]
          and act["rolling_stability"] == exp["rolling_stability"])
    checks["component_" + cid] = {"ok": ok, "actual": act, "expected": exp}
    if not ok:
        audit["pass"] = False

ea, ee = res["emo_v1a"], iso["emo_v1a"]
checks["emo_v1a_ic"] = {"ok": (ea["IC14"] == ee["IC14"] and ea["IC30"] == ee["IC30"]
                               and ea["coverage_fit"] == ee["coverage_fit"]
                               and ea["rolling_stability"] == ee["rolling_stability"]),
                        "actual": {k: ea[k] for k in ("coverage_fit", "IC14", "IC30", "rolling_stability")},
                        "expected": {k: ee[k] for k in ("coverage_fit", "IC14", "IC30", "rolling_stability")}}
checks["emo_v0_ic"] = {"ok": (res["emo_v0"]["IC14"] == iso["emo_v0"]["IC14"]
                              and res["emo_v0"]["coverage_fit"] == iso["emo_v0"]["coverage_fit"]),
                       "actual": res["emo_v0"], "expected": iso["emo_v0"]}
checks["inc_ic_AB"] = {"ok": (ea["inc_ic_A_fit"] == ee["inc_ic_A_fit"]
                              and ea["inc_ic_B_fit"] == ee["inc_ic_B_fit"]
                              and ea["val_recheck_A"] == ee["val_recheck_A"]
                              and ea["val_recheck_B"] == ee["val_recheck_B"]
                              and ea["inc_ic_A_rolling"] == ee["inc_ic_A_rolling"]),
                       "actual": {k: ea[k] for k in ("inc_ic_A_fit", "inc_ic_A_rolling", "inc_ic_B_fit", "val_recheck_A", "val_recheck_B")},
                       "expected": {k: ee[k] for k in ("inc_ic_A_fit", "inc_ic_A_rolling", "inc_ic_B_fit", "val_recheck_A", "val_recheck_B")}}
checks["verdict"] = {"ok": iso["verdict"] == "无增量", "actual": iso["verdict"]}
checks["meta_rows"] = {"ok": (iso["meta"]["fit_rows"] == len(FIT) and iso["meta"]["val_rows"] == len(VAL)
                              and iso["meta"]["split_oos"] == SPLIT),
                       "actual": {"fit": len(FIT), "val": len(VAL), "split": SPLIT}}

for name, c in checks.items():
    audit["pass"] &= bool(c.get("ok"))
audit["checks"] = checks
out_path = ROOT / "data" / "_audit_v1a_recompute_2026-08-27.json"
json.dump(audit, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("AUDIT PASS" if audit["pass"] else "AUDIT FAIL")
for name, c in checks.items():
    print("  %-16s %s" % (name, "PASS" if c.get("ok") else "FAIL"))
    if not c.get("ok"):
        print("    actual:  ", json.dumps(c.get("actual"), ensure_ascii=False)[:250])
        print("    expected:", json.dumps(c.get("expected"), ensure_ascii=False)[:250])
print("v1a 复算: IC14=%s A=%s B=%s valA=%s valB=%s" % (
    v1a_ic14["mean"], inc_A["mean"], inc_B["mean"], val_A.get("mean"), val_B.get("mean")))
print("saved:", out_path)
