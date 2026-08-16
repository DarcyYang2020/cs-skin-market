# -*- coding: utf-8 -*-
"""第二批 探针2：F 反抽 vs 真反转判别（2026-08-16，只读，描述性分桶）。

样本定义（预注册）：阴跌/派发（前 20 日价跌≤-5% 且 sc30>0）后 3 日急拉（chg3d≥+8%）。
区分特征候选：承接（拉阳期 bid 抗跌=bid3d跌幅≥价格3d跌幅）、大盘（指180d>0）、坑深（dd60 中位分）、
拉阳量级（chg3d 中位分）、价差水平（(价-求购)/价）。
预注册判据：某特征两分组 14d/30d 胜率差≥15pp 且 n≥50 才算可区分；否则换特征视图（不等待积累）。
另报当前市场窗口（2026-06-01~08-14）事件数（用户关注场景）。
"""
import bisect
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "_exp_f_family_discrim.json"


def main():
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    mrows = c.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [r["value"] for r in mrows]
    m180 = {}
    for i in range(180, len(mvals)):
        m180[mdates[i]] = (mvals[i] / mvals[i - 180] - 1) * 100
    items = c.execute("SELECT id, name FROM items WHERE good_id>0").fetchall()
    c.close()

    cb = sqlite3.connect(ROOT / "data" / "market.db")
    cb.row_factory = sqlite3.Row
    bids = {}
    for r in cb.execute("SELECT item_name, date, buy_price_last FROM bid_history "
                        "WHERE buy_price_last IS NOT NULL ORDER BY date"):
        bids.setdefault(r["item_name"], []).append((r["date"], r["buy_price_last"]))
    cb.close()

    def bid_at(name, d, span=4):
        seq = bids.get(name)
        if not seq:
            return None
        ds = [x[0] for x in seq]
        i = bisect.bisect_right(ds, d)
        lo = max(0, i - span)
        cand = [x[1] for x in seq[lo:i]]
        return cand[-1] if cand else None

    events = []
    c = sqlite3.connect(ROOT / "data" / "replay_cycle_win.db")
    c.row_factory = sqlite3.Row
    for it in items:
        rows = c.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                         "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        ins = [r["in_sale_count"] for r in rows]
        n = len(prices)
        sc = [None] * n
        for i in range(59, n):
            ok30 = all(x is not None for x in ins[i - 29:i + 1])
            ok30a = all(x is not None for x in ins[i - 59:i - 29])
            if ok30 and ok30a:
                s30 = sum(ins[i - 29:i + 1]) / 30
                s30a = sum(ins[i - 59:i - 29]) / 30
                if s30a > 0:
                    sc[i] = (s30 / s30a - 1) * 100
        for i in range(90, n):
            if i + 30 >= n:
                continue
            d = dates[i]
            cyc = m180.get(d)
            if cyc is None:
                continue
            if sc[i] is None or sc[i] <= 0:
                continue  # 派发期：sc30>0
            pre = prices[i - 3] / prices[i - 23] - 1 if i >= 23 else None
            if pre is None or pre > -0.05:
                continue  # 阴跌前置
            chg3 = prices[i] / prices[i - 3] - 1
            if chg3 < 0.08:
                continue  # 急拉
            dd60 = prices[i] / max(prices[i - 60:i + 1]) - 1
            bpk = bid_at(it["name"], dates[i - 3])
            bnow = bid_at(it["name"], d)
            sup = None
            spread = None
            if bpk and bnow:
                sup = (bnow / bpk - 1) * 100 - (chg3 * 100)
            if bnow and prices[i] > 0:
                spread = (prices[i] - bnow) / prices[i] * 100
            fwd = {}
            for h in (14, 30, 60):
                fwd[h] = (prices[i + h] / prices[i] - 1) * 100 - 2.0 if i + h < n else None
            # 2b 特征视图：30 日内第几次急拉（首波 vs 二波反抽）+ 急拉前是否已从 60 日低点反弹 >20%
            prior_cnt = 0
            for j in range(max(90, i - 30), i):
                if prices[j] / prices[j - 3] - 1 >= 0.08:
                    prior_cnt += 1
            low60 = min(prices[i - 60:i + 1])
            rebounded = (prices[i] / low60 - 1) > 0.20
            events.append({"d": d, "name": it["name"], "chg3": chg3 * 100, "dd60": dd60 * 100,
                           "sup": sup, "spread": spread, "cyc": cyc, "fwd": fwd,
                           "prior_cnt": prior_cnt, "rebounded": rebounded})
    c.close()
    print("急拉事件总数:", len(events))
    cur = [e for e in events if "2026-06-01" <= e["d"] <= "2026-08-14"]
    print("当前市场窗口(2026-06-01~08-14)事件数:", len(cur))
    for e in cur:
        print("  ", e["d"], e["name"][:20], "chg3=%+.0f dd60=%.0f sup=%s fwd14=%+.0f fwd30=%+.0f" % (
            e["chg3"], e["dd60"], ("%.1f" % e["sup"]) if e["sup"] is not None else "-",
            e["fwd"][14] or 0, e["fwd"][30] or 0))

    def split(recs, key, a, b):
        ga = [r for r in recs if r[key] is not None and r[key] >= a and r[key] < b]
        return ga

    def st(recs, h):
        xs = [r["fwd"][h] for r in recs if r["fwd"][h] is not None]
        if len(xs) < 10:
            return "n=%d(少)" % len(xs)
        return "n=%d win=%.0f%% avg=%+.1f" % (len(xs), 100 * sum(1 for x in xs if x > 0) / len(xs), sum(xs) / len(xs))

    out = {"probe": "F 反抽 vs 真反转判别", "n_events": len(events),
           "current_window": [{"d": e["d"], "name": e["name"], "chg3": e["chg3"], "dd60": e["dd60"],
                               "sup": e["sup"], "spread": e["spread"], "fwd14": e["fwd"][14], "fwd30": e["fwd"][30]}
                              for e in cur]}
    print("\n== 区分特征分桶（14d/30d）==")
    for key, bands in (("sup", [(-999, 0, "承接<0"), (0, 999, "承接≥0")]),
                       ("cyc", [(-999, 0, "非牛"), (0, 999, "牛")]),
                       ("chg3", [(8, 15, "急拉8-15%"), (15, 999, "急拉≥15%")]),
                       ("dd60", [(-999, -25, "坑深≤-25"), (-25, 0, "坑深>-25")]),
                       ("spread", [(-999, 10, "价差<10%"), (10, 999, "价差≥10%")]),
                       ("prior_cnt", [(-1, 0, "30日内首次急拉"), (1, 999, "30日内≥2次急拉")]),
                       ("rebounded", [(False, False, "未先行反弹"), (True, True, "已先行反弹>20%")])):
        print("-- %s --" % key)
        for a, b, lab in bands:
            if isinstance(a, bool):
                rs = [r for r in events if r[key] == a]
            else:
                rs = [r for r in events if r[key] is not None and a <= r[key] < b]
            print("  %-10s 14d %s | 30d %s" % (lab, st(rs, 14), st(rs, 30)))
        out.setdefault(key, {})[lab] = {"14d": st(rs, 14), "30d": st(rs, 30)}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)

    # ---- 2c 交互视图：承接×大盘×拉阳量级；路径形态（V型首反 vs 平台二波）----
    print("\n== 2c 三因子交互（承接≥0 × 牛 × 急拉≥15%）==")
    out2c = {}
    for sup_ok in (True, False):
        for bull in (True, False):
            for big in (True, False):
                rs = [r for r in events
                      if r["sup"] is not None and (r["sup"] >= 0) == sup_ok
                      and (r["cyc"] > 0) == bull and (r["chg3"] >= 15) == big]
                if len(rs) < 10:
                    continue
                lab = "承接%s×%s×拉%s" % ("+" if sup_ok else "-", "牛" if bull else "非牛",
                                          "大" if big else "小")
                print("  %-16s 14d %s | 30d %s" % (lab, st(rs, 14), st(rs, 30)))
                out2c[lab] = {"14d": st(rs, 14), "30d": st(rs, 30)}
    print("\n== 2c 路径形态 ==")
    vx = [r for r in events if r["dd60"] <= -25 and not r["rebounded"]]
    pf = [r for r in events if r["dd60"] > -25 and r["rebounded"]]
    other = [r for r in events if r not in vx and r not in pf]
    for lab, rs in (("V型首反(深坑未反弹)", vx), ("平台二波(已反弹20%+)", pf), ("其他", other)):
        print("  %-18s 14d %s | 30d %s" % (lab, st(rs, 14), st(rs, 30)))
        out2c[lab] = {"14d": st(rs, 14), "30d": st(rs, 30)}
    # 当前窗口分布
    cur = [e for e in events if "2026-06-01" <= e["d"] <= "2026-08-14"]
    print("\n== 当前窗口（2026-06~08）在各形态的分布（n=%d）==" % len(cur))
    for lab, rs in (("V型首反", vx), ("平台二波", pf), ("其他", other)):
        cc = [e for e in cur if e in rs]
        print("  %-10s n=%d | 14d %s | 30d %s" % (lab, len(cc), st(cc, 14), st(cc, 30)))
        out2c.setdefault("current_window", {})[lab] = {"14d": st(cc, 14), "30d": st(cc, 30)}
    out["2c"] = out2c
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote 2c ->", OUT)


if __name__ == "__main__":
    main()
