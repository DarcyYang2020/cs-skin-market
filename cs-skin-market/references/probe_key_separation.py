# -*- coding: utf-8 -*-
"""陷阱识别钥匙分离度实验：K1 修正版（供缩持续性）+ K2（求购背离）。

种子 = 已知 10 条信号（W1 真趋势 4 + W3 陷阱 6，来自 _exp_trend_tight_1.json）。
每把钥匙报 W1/W3 中位数 + 是否分离，产出 _exp_key_separation.json。
"""
import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
MARKET_DB = ROOT / "data" / "market.db"
SIG = ROOT / "data" / "_exp_trend_tight_1.json"
OUT = ROOT / "data" / "_exp_key_separation.json"


def buy_at(bdates, bprices, target):
    """最近 <= target 的 buy_price_last；无则 None。"""
    best = None
    for d, p in zip(bdates, bprices):
        if d <= target:
            best = p
        else:
            break
    return best


def main():
    sigs = json.load(open(SIG, encoding="utf-8"))["signals"]

    cyc = sqlite3.connect(CYCLE_DB)
    cyc.row_factory = sqlite3.Row
    mkt = sqlite3.connect(MARKET_DB)
    mkt.row_factory = sqlite3.Row

    # 缓存：item -> (dates, price, insale, good_id)；good -> (buy_dates, buy_prices)
    item_cache = {}
    good_cache = {}

    rows = []
    for s in sigs:
        iid = s["item"]
        if iid not in item_cache:
            r = cyc.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                            "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
            g = cyc.execute("SELECT good_id FROM items WHERE id=?", (iid,)).fetchone()
            item_cache[iid] = {
                "dates": [x["date"] for x in r], "price": [x["price_rmb"] for x in r],
                "insale": [x["in_sale_count"] for x in r], "good_id": g["good_id"] if g else None}
        c = item_cache[iid]
        i = c["dates"].index(s["date"])
        gid = c["good_id"]
        if gid not in good_cache:
            r2 = mkt.execute("SELECT date, buy_price_last FROM bid_history "
                             "WHERE good_id=? AND buy_price_last IS NOT NULL ORDER BY date", (gid,)).fetchall()
            good_cache[gid] = {"dates": [x["date"] for x in r2], "price": [x["buy_price_last"] for x in r2]}
        g = good_cache.get(gid) or {"dates": [], "price": []}

        # K2 指标1：求购跟随率 = buy 5d return / sell 5d return
        sell_now = c["price"][i]
        sell_5d = c["price"][i - 5] if i >= 5 else sell_now
        sell_ret = (sell_now - sell_5d) / sell_5d * 100 if sell_5d else 0
        buy_now = buy_at(g["dates"], g["price"], c["dates"][i])
        buy_5d = buy_at(g["dates"], g["price"], c["dates"][i - 5]) if i >= 5 else buy_now
        buy_ret = (buy_now - buy_5d) / buy_5d * 100 if buy_5d else 0
        follow = round(buy_ret / sell_ret, 3) if sell_ret != 0 else None

        # K2 指标2：价差走阔 = spread 5d 变化
        spread_now = (sell_now - buy_now) / sell_now if (sell_now and buy_now) else None
        spread_5d = (sell_5d - buy_5d) / sell_5d if (sell_5d and buy_5d) else None
        widen = round(spread_now - spread_5d, 4) if (spread_now is not None and spread_5d is not None) else None

        # K1 修正：供缩持续性（7 日下降天数 + 单日最大降幅占比）
        ins = c["insale"][max(0, i - 6):i + 1]
        down_days = 0
        drops = []
        for j in range(1, len(ins)):
            a, b = ins[j - 1], ins[j]
            if a is not None and b is not None and b < a:
                down_days += 1
                drops.append(a - b)
        conc_ratio = round(max(drops) / sum(drops), 3) if drops else None  # 单日最大降幅占比

        win = "W1" if s["date"] <= "2025-10-24" else "W3"
        rows.append({"win": win, "item": iid, "name": s["name"], "date": s["date"],
                     "follow": follow, "widen": widen, "down_days": down_days, "conc_ratio": conc_ratio,
                     "sell_ret": round(sell_ret, 1), "buy_ret": round(buy_ret, 1)})
    cyc.close()
    mkt.close()

    def med(vals):
        v = [x for x in vals if x is not None]
        return round(statistics.median(v), 3) if v else None

    w1 = [r for r in rows if r["win"] == "W1"]
    w3 = [r for r in rows if r["win"] == "W3"]
    keys = [
        ("K2_求购跟随率", "follow", "真趋势≈1/陷阱<<1"),
        ("K2_价差走阔", "widen", "陷阱走阔>0/真趋势≤0"),
        ("K1_供缩持续(下降天数)", "down_days", "真吸筹多/假吸筹少"),
        ("K1_单日骤降占比", "conc_ratio", "真吸筹低/假吸筹高"),
    ]
    sep = {}
    for label, key, _ in keys:
        m1 = med([r[key] for r in w1])
        m3 = med([r[key] for r in w3])
        direction_opposite = (m1 is not None and m3 is not None and m1 != m3)
        sep[label] = {"W1_median": m1, "W3_median": m3, "opposite": direction_opposite}

    out = {"probe": "陷阱识别钥匙分离度（K1修正+K2）", "n_W1": len(w1), "n_W3": len(w3),
           "separation": sep, "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== 分离度（W1 4条 vs W3 6条）===")
    for label, _, note in keys:
        s = sep[label]
        print(f"  {label:24s} W1中位={s['W1_median']}  W3中位={s['W3_median']}  分离={s['opposite']}  ({note})")
    print("\n逐条明细:")
    print(f"{'窗':<3}{'date':<11}{'name':<20}{'follow':>8}{'widen':>9}{'down':>6}{'conc':>7}{'sell':>7}{'buy':>7}")
    for r in rows:
        print(f"{r['win']:<3}{r['date']:<11}{r['name'][:18]:<20}{str(r['follow']):>8}{str(r['widen']):>9}"
              f"{r['down_days']:>6}{str(r['conc_ratio']):>7}{r['sell_ret']:>7}{r['buy_ret']:>7}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
