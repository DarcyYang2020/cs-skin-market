# -*- coding: utf-8 -*-
"""P1（H4）：S1 失败指纹（2026-08-17，预注册判据，第一批①）。

问题：S1 牛市上行是引擎唯一跑输等权的时期（引擎 14d +3.6 vs 等权 +5.8，−2.2pp）。
假设 H4：S1 的族定义与时期错配，存在可定位的子条件失手。
数据：官方 v2-T13 回放产物 S1 段信号（base/supply_accum）+ 回放库在售量联算 s7/s30/sc30/chg8。
预注册判据（跑数前锁定）：
  1. 指纹=特征对比：S1 信号 vs 其他时期同族信号的特征中位数差异表；
  2. 子条件扫描（9 桶预注册）：pct≥40 / z≥0 / chg7>1 / chg8>1 / sc30≥-10（收缩浅）/
     supply_change_30d≥0 / micro_th<50 / sent≤40 / th≥55——每桶报 n/win14/avg14/win30/avg30；
  3. 判定：存在桶 n≥10 且 win14<40% → S1 专属门候选（进入 H4 落地候选流程）；
     全部桶 win14≥40% → H4 证伪（S1 低增量为结构性，非子条件可修），登记后不再调参重试。
输出 data/_exp_s1_family_fingerprint.json。
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
OUT = ROOT / "data" / "_exp_s1_family_fingerprint.json"

BUCKETS = OrderedDict([
    ("pct>=40", lambda s: (s.get("pct") or 0) >= 40),
    ("z>=0", lambda s: (s.get("z") or -9) >= 0),
    ("chg7>1", lambda s: (s.get("chg7") or 0) > 1),
    ("chg8>1", lambda s: (s.get("_chg8") or -9) > 1),
    ("sc30>=-10(收缩浅)", lambda s: (s.get("_sc30") or -99) >= -10),
    ("supply_change_30d>=0", lambda s: (s.get("supply_change_30d") or -9) >= 0),
    ("micro_th<50", lambda s: (s.get("micro_th") or 99) < 50),
    ("sent<=40(贪婪)", lambda s: (s.get("sentiment") or 99) <= 40),
    ("th>=55", lambda s: (s.get("th") or 0) >= 55),
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
        if iid is None:
            out.append(s)
            continue
        rows = c.execute(
            "SELECT date, price_rmb, in_sale_count FROM price_history "
            "WHERE item_id=? AND date<=? ORDER BY date", (iid, s["date"])).fetchall()
        s = dict(s)
        if len(rows) >= 8 and rows[-1]["price_rmb"] and rows[-8]["price_rmb"] > 0:
            s["_chg8"] = (rows[-1]["price_rmb"] / rows[-8]["price_rmb"] - 1) * 100
        if len(rows) >= 30:
            s7 = sum(r["in_sale_count"] or 0 for r in rows[-7:]) / 7
            s30 = sum(r["in_sale_count"] or 0 for r in rows[-30:]) / 30
            if s30 > 0:
                s["_s7"] = round(s7, 1)
                s["_s30"] = round(s30, 1)
                s["_sc30"] = round((s7 / s30 - 1) * 100, 1)
        out.append(s)
    c.close()
    return out


def main():
    d = json.load(open(REPLAY, encoding="utf-8"))
    m180 = load_chg180()
    sigs = []
    for s in d["signals"]:
        s = dict(s)
        s["_period"] = state_bucket(m180.get(s["date"]), s.get("mkt_chg30"))
        s["_fam"] = family_key_for_label(s.get("action_label") or "")
        sigs.append(s)
    sigs = join_supply(sigs)
    s1 = [s for s in sigs if s["_period"] == "S1牛市上行"]
    others = [s for s in sigs if s["_period"] != "S1牛市上行"]
    print("S1 信号 n=%d（fam: %s）；其他时期 n=%d" % (
        len(s1), dict(__import__("collections").Counter(s["_fam"] for s in s1)), len(others)))

    # 特征中位数对比（S1 vs 其他时期，同族 supply_accum/base 池）
    feats = ("pct", "z", "th", "micro_th", "chg7", "_chg8", "sentiment", "market_th",
             "mkt_chg30", "supply_change_30d", "_sc30")
    med = lambda xs, k: sorted([x[k] for x in xs if x.get(k) is not None])[len([x for x in xs if x.get(k) is not None]) // 2] \
        if [x for x in xs if x.get(k) is not None] else None
    print("== 特征中位数对比 ==")
    for k in feats:
        a, b = med(s1, k), med(others, k)
        print("  %-18s S1=%-8s 其他=%-8s" % (k, a, b))

    # 子条件扫描（预注册 9 桶，S1 全信号 + 分族）
    print("== S1 子条件扫描（win14<40% 且 n>=10 → 候选门）==")
    verdict = None
    scan = {}
    for name, pred in BUCKETS.items():
        sub = [s for s in s1 if pred(s)]
        row = {"n": len(sub),
               "n14": wa([s["net14"] for s in sub if s.get("net14") is not None]),
               "n30": wa([s["net30"] for s in sub if s.get("net30") is not None])}
        scan[name] = row
        flag = ""
        if row["n"] >= 10 and row["n14"]["win"] is not None and row["n14"]["win"] < 40:
            flag = " ← 候选门"
            verdict = verdict or name
        print("  %-22s n=%2d | 14d %s | 30d %s%s" % (
            name, row["n"], _f(row["n14"]), _f(row["n30"]), flag))
    print("判定:", ("候选门=%s（进入 H4 落地流程）" % verdict) if verdict else "H4 证伪：S1 低增量为结构性，非子条件可修")
    json.dump({"probe": "P1 S1 失败指纹", "s1_n": len(s1),
               "s1_fam": {f: sum(1 for s in s1 if s["_fam"] == f) for f in set(s["_fam"] for s in s1)},
               "medians": {k: {"s1": med(s1, k), "others": med(others, k)} for k in feats},
               "buckets": scan, "verdict": verdict},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s" % (x["n"], x["win"], x["avg"])


if __name__ == "__main__":
    main()
