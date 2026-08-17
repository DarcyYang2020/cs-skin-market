# -*- coding: utf-8 -*-
"""P11（H11）：逆市走强指纹（2026-08-17，预注册判据，第二批②）。

问题：大盘走弱期（S3/S4）单品持续走强的特征是什么？能否成为"逆市持有腿"候选？
fixture（用户点名）：2026-06-20~07-11 霸意大名/异星世界 + 2025 抽象派 1337/合纵。
预注册判据（跑数前锁定）：
  1. 指纹候选（逐层加严）：
     Fa = 大盘 chg30<0 且 单品 chg30>+5（逆市走强）
     Fb = Fa + 单品 20 日波动 <=0.02（低波慢涨）
     Fc = Fb + 单品 sc30<=0（供给收缩或平稳）
  2. 每层报 n / fwd14/30/60/180（扣 2%）；
  3. 升格标准：fwd14 与 fwd60 同时显著为正（|avg|>=2SE 且 n>=30）→ 该层为候选指纹；
  4. fixture 校验（发现标准）：fixture 品×窗口 ≥3/4 落在候选指纹内；
  5. 前后半段一致性：候选指纹的 fwd60 在 2026-03-02 前后两段同号。
  全部通过 → "逆市持有腿"候选（进入发射口径三关）；否则 H11 证伪。
输出 data/_exp_countertrend_strength.json。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_countertrend_strength.json"
EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")
CUT = "2026-03-02"
HORIZONS = (14, 30, 60, 180)
FIXTURE = ("M4A4 | 合纵 (崭新出厂)", "AK-47 | 抽象派 1337 (崭新出厂)",
           "FN57 | 霸意大名 (崭新出厂)", "格洛克 18 型 | 异星世界 (崭新出厂)")


def wa(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "win": None, "avg": None, "se": None}
    mu = sum(vals) / n
    sd = (sum((v - mu) ** 2 for v in vals) / n) ** 0.5
    return {"n": n, "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1),
            "avg": round(mu, 2), "se": round(sd / (n ** 0.5), 2)}


def main():
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [float(r["value"]) for r in mrows]
    mkt30 = {}
    for i in range(30, len(mvals)):
        if mvals[i - 30] > 0:
            mkt30[mdates[i]] = (mvals[i] / mvals[i - 30] - 1) * 100
    items = c.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    hq = [r for r in items if not any(m in r["name"] for m in EXCL)]

    layers = {"Fa_逆市走强": [], "Fb_+低波": [], "Fc_+供稳": []}
    fixture_hits = {k: 0 for k in layers}
    for r in hq:
        rows = c.execute(
            "SELECT date, price_rmb, in_sale_count FROM price_history "
            "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (r["id"],)).fetchall()
        dts = [x["date"] for x in rows]
        px = [float(x["price_rmb"]) for x in rows]
        sup = [x["in_sale_count"] for x in rows]
        n = len(px)
        for i in range(90, n):
            d = dts[i]
            m30 = mkt30.get(d)
            if m30 is None or m30 >= 0 or i + 180 >= n or i < 30 or px[i - 30] <= 0:
                continue
            cur = px[i]
            c30 = (cur / px[i - 30] - 1) * 100
            if c30 <= 5:
                continue
            fwd = {}
            ok180 = all(h <= 180 for h in ())
            for h in HORIZONS:
                fwd[h] = (px[i + h] / cur - 1) * 100 - 2.0
            rec = {"d": d, "fwd": fwd}
            hit_a = True
            layers["Fa_逆市走强"].append(rec)
            vol20 = None
            rets = [(px[j] - px[j - 1]) / px[j - 1] for j in range(i - 19, i + 1) if px[j - 1] > 0]
            if rets:
                mu = sum(rets) / len(rets)
                vol20 = (sum((x - mu) ** 2 for x in rets) / len(rets)) ** 0.5
            if vol20 is not None and vol20 <= 0.02:
                layers["Fb_+低波"].append(rec)
                sc30 = None
                if i >= 29 and sup[i] is not None:
                    s7 = sum(x for x in sup[i - 6:i + 1] if x is not None) / 7
                    s30 = sum(x for x in sup[i - 29:i + 1] if x is not None) / 30
                    sc30 = (s7 / s30 - 1) * 100 if s30 > 0 else None
                if sc30 is not None and sc30 <= 0:
                    layers["Fc_+供稳"].append(rec)
                    if r["name"] in FIXTURE and "2026-06-20" <= d <= "2026-07-11":
                        fixture_hits["Fc_+供稳"] += 1

    out = {"probe": "P11 逆市走强指纹", "layers": {}}
    print("== 逆市走强指纹（大盘chg30<0 且 单品chg30>+5 基底）==")
    verdict = None
    for k in layers:
        recs = layers[k]
        row = {str(h): wa([x["fwd"][h] for x in recs]) for h in HORIZONS}
        sig = (row["14"]["n"] >= 30 and row["14"]["avg"] is not None and row["14"]["se"] and
               abs(row["14"]["avg"]) >= 2 * row["14"]["se"] and
               row["60"]["n"] >= 30 and row["60"]["avg"] is not None and row["60"]["se"] and
               abs(row["60"]["avg"]) >= 2 * row["60"]["se"])
        out["layers"][k] = {"horizons": row, "sig14_60": bool(sig)}
        print("%-14s n=%4d | 14d %s | 30d %s | 60d %s | 180d %s | 显著=%s" % (
            k, row["14"]["n"], _f(row["14"]), _f(row["30"]), _f(row["60"]), _f(row["180"]), sig))
        if sig:
            verdict = k
    # fixture 校验
    if verdict:
        hits = fixture_hits.get(verdict, 0)
        out["fixture"] = {"candidate_layer": verdict, "fixture_hits_in_window": hits, "need": 3}
        print("fixture 校验：%s 层命中 %d/4（窗口 2026-06-20~07-11）" % (verdict, hits))
        if hits < 3:
            verdict = None
    # 前后半段一致性（fwd60 两段同号）
    if verdict:
        recs = layers[verdict]
        f60 = wa([x["fwd"][60] for x in recs if x["d"] < CUT])
        b60 = wa([x["fwd"][60] for x in recs if x["d"] >= CUT])
        consistent = (f60["avg"] is not None and b60["avg"] is not None and
                      f60["avg"] * b60["avg"] > 0)
        out["front_back"] = {"front60": f60, "back60": b60, "consistent": bool(consistent)}
        print("前后半段 fwd60: front %s | back %s | 同号=%s" % (_f(f60), _f(b60), consistent))
        if not consistent:
            verdict = None
    out["verdict"] = ("逆市持有腿候选: %s" % verdict) if verdict else "H11 证伪"
    print("判定:", out["verdict"])
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _f(x):
    if x["n"] == 0:
        return "n=0"
    return "n=%d win=%s avg=%s se=%s" % (x["n"], x["win"], x["avg"], x["se"])


if __name__ == "__main__":
    main()
