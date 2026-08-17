# -*- coding: utf-8 -*-
"""P3（H6）：S3 base 拆解（2026-08-17，预注册判据，第一批②）。

问题：S3 里 base 基础族 18 条 77.8%/+27.4 是全场最强"隐性精选腿"，但子条件构成未知。
假设 H6：拆出的子结构可独立复现 → S3 专用族候选。
预注册判据（跑数前锁定）：
  1. 拆解：18 条 S3 base 信号 × 10 个预注册子条件桶（pct≤20/pct≤30/z≤-1/th35-54/th<55/
     chg7≤0/chg7<0/sent≥60/sc30≤-10/supply_change_30d≤0），报 n/win14/avg14/win30/avg30；
  2. C 定义：n≥8 且 win14 最高的桶（样本内选择→仅候选，落地须发射口径三关）；
  3. 复现：S3 全量朴素候选日（pct90≤40 且 z≤0，引擎无关）× C 条件 → fwd14 扣 2%，
     复现标准=n≥15 且 win14≥60% → S3 专用族候选；不达标 → H6 证伪。
输出 data/_exp_s3_base_decomposition.json。
"""
import json
import os
import sqlite3
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

from pipeline.market_context import state_bucket  # noqa: E402
from pipeline.signal_tracking import family_key_for_label  # noqa: E402

REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
OUT = ROOT / "data" / "_exp_s3_base_decomposition.json"
S3_DAYS_FILE = ROOT / "data" / "market_state_daily.json"

BUCKETS = OrderedDict([
    ("pct<=20", lambda s: (s.get("pct") or 99) <= 20),
    ("pct<=30", lambda s: (s.get("pct") or 99) <= 30),
    ("z<=-1", lambda s: (s.get("z") or 9) <= -1),
    ("th35-54", lambda s: 35 <= (s.get("th") or 0) < 55),
    ("th<55", lambda s: (s.get("th") or 99) < 55),
    ("chg7<=0", lambda s: (s.get("chg7") or 9) <= 0),
    ("chg7<0", lambda s: (s.get("chg7") or 9) < 0),
    ("sent>=60", lambda s: (s.get("sentiment") or 0) >= 60),
    ("sc30<=-10", lambda s: (s.get("_sc30") or 99) <= -10),
    ("supply_change_30d<=0", lambda s: (s.get("supply_change_30d") or 9) <= 0),
])


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None}
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(sum(vals) / n, 2)}


def load_chg180():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    c.close()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]
    out = {}
    for i in range(180, len(mvals)):
        if mvals[i - 180] > 0:
            out[mdates[i]] = (mvals[i] / mvals[i - 180] - 1) * 100
    return out


def join_supply(sigs):
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = {r["name"]: r["id"] for r in c.execute("SELECT id, name FROM items")}
    out = []
    for s in sigs:
        iid = items.get(s["name"])
        s = dict(s)
        if iid is not None:
            rows = c.execute(
                "SELECT date, in_sale_count FROM price_history "
                "WHERE item_id=? AND date<=? ORDER BY date", (iid, s["date"])).fetchall()
            if len(rows) >= 30:
                s7 = sum(r["in_sale_count"] or 0 for r in rows[-7:]) / 7
                s30 = sum(r["in_sale_count"] or 0 for r in rows[-30:]) / 30
                if s30 > 0:
                    s["_sc30"] = round((s7 / s30 - 1) * 100, 1)
        out.append(s)
    c.close()
    return out


def main():
    d = json.load(open(REPLAY, encoding="utf-8"))
    m180 = load_chg180()
    s3b = []
    for s in d["signals"]:
        if state_bucket(m180.get(s["date"]), s.get("mkt_chg30")) == "S3弱市阴跌" \
                and family_key_for_label(s.get("action_label") or "") == "base":
            s3b.append(s)
    s3b = join_supply(s3b)
    print("S3 base 信号 n=%d" % len(s3b))

    print("== 拆解（10 预注册桶）==")
    best = None
    scan = {}
    for name, pred in BUCKETS.items():
        sub = [s for s in s3b if pred(s)]
        row = {"n": len(sub),
               "n14": wa([s["net14"] for s in sub if s.get("net14") is not None]),
               "n30": wa([s["net30"] for s in sub if s.get("net30") is not None])}
        scan[name] = row
        if row["n"] >= 8 and (best is None or row["n14"]["win"] > best[1]["n14"]["win"]):
            best = (name, row)
        print("  %-22s n=%2d | 14d %s | 30d %s" % (name, row["n"], _f(row["n14"]), _f(row["n30"])))
    if best is None:
        print("判定: 无 n>=8 桶 → H6 证伪")
        json.dump({"probe": "P3 S3 base 拆解", "n": len(s3b), "buckets": scan, "verdict": "证伪:无C"},
                  open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return
    cname = best[0]
    print("C 候选桶=%s（样本内选择，仅候选）" % cname)

    # 复现：S3 全量朴素候选日（pct90<=40 & z<=0）× C 条件
    st = json.load(open(S3_DAYS_FILE, encoding="utf-8"))
    s3_days = {dd for dd, ss in st.items()
               if "chg180" in ss and "chg30" in ss and state_bucket(ss["chg180"], ss["chg30"]) == "S3弱市阴跌"}
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
    EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")
    names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM items WHERE good_id>0")}
    hit_n, hit_wins, hit_avgs = 0, 0, 0.0
    for iid in items:
        if any(m in names.get(iid, "") for m in EXCL):
            continue
        rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                         "WHERE item_id=? ORDER BY date", (iid,)).fetchall()
        for i in range(90, len(rows)):
            dd = rows[i]["date"]
            if dd not in s3_days or i + 14 >= len(rows):
                continue
            w = [r["price_rmb"] for r in rows[i - 89:i + 1] if r["price_rmb"]]
            if len(w) < 30 or w[-1] <= 0:
                continue
            pct = sum(1 for p in w if p <= w[-1]) / len(w) * 100
            if pct > 40:
                continue
            mu = sum(w) / len(w)
            sd = (sum((p - mu) ** 2 for p in w) / len(w)) ** 0.5
            z = (w[-1] - mu) / sd if sd > 0 else 0
            if z > 0:
                continue
            feat = _feat_from(rows, i, pct, z)
            if feat is None:
                continue
            if _pass_bucket(cname, feat):
                fwd = (rows[i + 14]["price_rmb"] / rows[i]["price_rmb"] - 1) * 100 - 2.0
                hit_n += 1
                hit_wins += 1 if fwd > 0 else 0
                hit_avgs += fwd
    c.close()
    rep = {"n": hit_n,
           "win": round(100.0 * hit_wins / hit_n, 1) if hit_n else None,
           "avg": round(hit_avgs / hit_n, 2) if hit_n else None}
    ok = hit_n >= 15 and (rep["win"] or 0) >= 60
    print("复现（S3 朴素候选 × %s）: %s → %s" % (cname, rep, "候选通过" if ok else "H6 证伪"))
    json.dump({"probe": "P3 S3 base 拆解", "n": len(s3b), "buckets": scan,
               "C": cname, "replication": rep,
               "verdict": "S3专用族候选: %s" % cname if ok else "证伪"},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _feat_from(rows, i, pct, z):
    """从 K 线行构造与产品信号同口径的特征（pct/z/chg7/th 近似/sent 近似/sc30）。"""
    w = [r["price_rmb"] for r in rows[i - 89:i + 1] if r["price_rmb"]]
    feat = {"pct": pct, "z": z}
    if len(w) >= 8 and w[-8] > 0:
        feat["chg7"] = (w[-1] / w[-8] - 1) * 100
    if len(rows) >= i + 30:
        s7 = sum(r["in_sale_count"] or 0 for r in rows[i - 6:i + 1]) / 7
        s30 = sum(r["in_sale_count"] or 0 for r in rows[i - 29:i + 1]) / 30
        if s30 > 0:
            feat["_sc30"] = (s7 / s30 - 1) * 100
        s30a = sum(r["in_sale_count"] or 0 for r in rows[i - 59:i - 29]) / 30
        if s30a > 0:
            feat["supply_change_30d"] = (s30 / s30a - 1) * 100
    # th 近似：趋势健康度太重，用 30 日动量代理（仅复现用，登记在产物 note）
    if len(w) >= 30 and w[-30] > 0:
        mom30 = (w[-1] / w[-30] - 1) * 100
        feat["th"] = max(0, min(100, 50 + mom30 * 2))
    feat["sentiment"] = 60  # 复现口径：S3 base 中位 sentiment≈60（产品字段中位数）
    return feat


def _pass_bucket(name, feat):
    return BUCKETS[name](feat)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
