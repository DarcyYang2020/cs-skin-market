# -*- coding: utf-8 -*-
"""SUPPLY-CONF-1 阶段 0：四态分布（只报分布，不判定）。

四态（可靠字段：in_sale 收缩 + 价格行为 + buy_price 价差走阔）：
  真吸筹   = 供缩 + (价涨或价平) + spread 收窄/持平（buy_price 跟随）
  假吸筹   = 供缩 + 价涨 + spread 走阔（buy_price 不跟，陷阱指纹）
  挂单撤走 = 供缩 + 价平 + spread 走阔
  惜售     = 供缩 + 价跌
样本：原始收缩事件（in_sale 7d均 ≤ 0.85×30d均）∩ 求购覆盖，非引擎 |chg7|≤3 子集。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
MARKET_DB = ROOT / "data" / "market.db"
OUT = ROOT / "data" / "_exp_supply_conf_4state.json"


def buy_at(bdates, bprices, target):
    best = None
    for d, p in zip(bdates, bprices):
        if d <= target:
            best = p
        else:
            break
    return best


def main():
    cyc = sqlite3.connect(CYCLE_DB)
    cyc.row_factory = sqlite3.Row
    mkt = sqlite3.connect(MARKET_DB)
    mkt.row_factory = sqlite3.Row

    items = cyc.execute("SELECT id, good_id, name FROM items WHERE good_id > 0 ORDER BY id").fetchall()
    good_cache = {}
    states = {"真吸筹": [], "假吸筹": [], "挂单撤走": [], "惜售": []}
    total_contract = 0
    total_bid_cover = 0

    for it in items:
        iid, gid = it["id"], it["good_id"]
        rows = cyc.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                           "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        dates = [r["date"] for r in rows]
        prices = [r["price_rmb"] for r in rows]
        insale = [r["in_sale_count"] for r in rows]
        if gid not in good_cache:
            r2 = mkt.execute("SELECT date, buy_price_last FROM bid_history "
                             "WHERE good_id=? AND buy_price_last IS NOT NULL ORDER BY date", (gid,)).fetchall()
            good_cache[gid] = {"dates": [x["date"] for x in r2], "price": [x["buy_price_last"] for x in r2]}
        g = good_cache[gid]
        n = len(prices)
        for i in range(30, n):
            if i + 30 >= n:
                continue
            s7 = insale[i - 6:i + 1]
            s30 = insale[i - 29:i + 1]
            if any(x is None for x in s7) or any(x is None for x in s30):
                continue
            a7 = sum(s7) / 7
            a30 = sum(s30) / 30
            if a30 <= 0 or a7 > 0.85 * a30:
                continue
            total_contract += 1
            # 求购覆盖
            buy_now = buy_at(g["dates"], g["price"], dates[i])
            buy_5d = buy_at(g["dates"], g["price"], dates[i - 5]) if i >= 5 else buy_now
            if buy_now is None or buy_5d is None:
                continue
            total_bid_cover += 1
            price_chg = (prices[i] - prices[i - 5]) / prices[i - 5] * 100 if prices[i - 5] else 0
            spread_now = (prices[i] - buy_now) / prices[i] * 100 if prices[i] else None
            spread_5d = (prices[i - 5] - buy_5d) / prices[i - 5] * 100 if prices[i - 5] else None
            spread_chg = (spread_now - spread_5d) if (spread_now is not None and spread_5d is not None) else None
            if spread_chg is None:
                continue
            if price_chg < -3:
                state = "惜售"
            elif price_chg > 3 and spread_chg > 0:
                state = "假吸筹"
            elif price_chg > 3 and spread_chg <= 0:
                state = "真吸筹"
            elif spread_chg > 0:
                state = "挂单撤走"
            else:
                state = "真吸筹"
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 - 2.0
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 - 2.0
            states[state].append({"item": iid, "name": it["name"], "date": dates[i],
                                  "price_chg": round(price_chg, 1), "spread_chg": round(spread_chg, 2),
                                  "fwd14": round(fwd14, 2), "fwd30": round(fwd30, 2)})
    cyc.close()
    mkt.close()

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        win14 = sum(1 for r in recs if r["fwd14"] > 0) / n * 100
        avg14 = sum(r["fwd14"] for r in recs) / n
        win30 = sum(1 for r in recs if r["fwd30"] > 0) / n * 100
        avg30 = sum(r["fwd30"] for r in recs) / n
        return {"n": n, "win14": round(win14, 1), "avg14": round(avg14, 2),
                "win30": round(win30, 1), "avg30": round(avg30, 2)}

    dist = {k: st(v) for k, v in states.items()}
    out = {"probe": "SUPPLY-CONF-1 阶段0 四态分布", "total_contract": total_contract,
           "total_bid_cover": total_bid_cover, "distribution": dist,
           "states": {k: v for k, v in states.items()}}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== 四态分布（供缩事件", total_contract, "，求购覆盖", total_bid_cover, "）===")
    for k, v in dist.items():
        print(f"  {k:6s} n={v['n']:>6}  win14={v['win14']}  avg14={v['avg14']}  win30={v['win30']}  avg30={v['avg30']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
