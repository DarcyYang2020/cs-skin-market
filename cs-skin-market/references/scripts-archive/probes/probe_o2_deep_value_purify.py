# -*- coding: utf-8 -*-
"""O2 深值提纯研究阶段 0（2026-08-15，做厚收益端第 2 步）。

背景：P2 发现 deep_value 全样本 win14 57.1% → 干净 38.5%（漂移 −18.6pp，事件窗口抬高），
avg14 +14.95 右尾仍在。本探针：对 cycle 186 的 21 条 deep_value 信号逐条列出
干净/事件标记 + 信号日 spread 变化（5 日）+ 供给 30 日变化，看赢家/输家能否被
「spread 收窄 / 供给不扩」单变量分开（pilot，n=21 只作线索不作判定）。
"""
import io
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.market_macro import historical_event_impact

CYCLE = ROOT / "data" / "_exp_cycle_replay_2026.json"
CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
MARKET_DB = ROOT / "data" / "market.db"
OUT = ROOT / "data" / "_exp_o2_deep_value_purify.json"


def buy_at(bdates, bprices, target):
    best = None
    for d, p in zip(bdates, bprices):
        if d <= target:
            best = p
        else:
            break
    return best


def main():
    rep = json.load(io.open(CYCLE, encoding="utf-8"))
    dv = [s for s in rep["signals"] if '深值' in (s.get('action_label') or '')]
    print("cycle deep_value 信号数:", len(dv))

    cyc = sqlite3.connect(CYCLE_DB)
    cyc.row_factory = sqlite3.Row
    mkt = sqlite3.connect(MARKET_DB)
    mkt.row_factory = sqlite3.Row

    id_by_name = {r["name"]: r["id"] for r in cyc.execute("SELECT id, name FROM items")}
    good_by_name = {r["name"]: r["good_id"] for r in cyc.execute("SELECT name, good_id FROM items WHERE good_id > 0")}
    bid_cache = {}

    rows_out = []
    for s in dv:
        name = s["name"]
        d = s["date"]
        iid = id_by_name.get(name)
        gid = good_by_name.get(name)
        impacted = bool(historical_event_impact(d, horizon_days=30))
        spread_chg = None
        supply_chg30 = s.get("supply_change_30d")
        if iid and gid:
            ph = cyc.execute("SELECT date, price_rmb, in_sale_count FROM price_history "
                             "WHERE item_id=? AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
            dates = [r["date"] for r in ph]
            prices = [r["price_rmb"] for r in ph]
            if gid not in bid_cache:
                r2 = mkt.execute("SELECT date, buy_price_last FROM bid_history "
                                 "WHERE good_id=? AND buy_price_last IS NOT NULL ORDER BY date", (gid,)).fetchall()
                bid_cache[gid] = {"dates": [x["date"] for x in r2], "price": [x["buy_price_last"] for x in r2]}
            g = bid_cache[gid]
            # 找信号日 index
            for i, dd in enumerate(dates):
                if dd >= d:
                    break
            else:
                i = len(dates) - 1
            if i >= 5:
                p_now = prices[i]
                p_5 = prices[i - 5]
                b_now = buy_at(g["dates"], g["price"], dates[i])
                b_5 = buy_at(g["dates"], g["price"], dates[i - 5])
                if all(x is not None for x in (p_now, p_5, b_now, b_5)) and p_now and p_5:
                    sp_now = (p_now - b_now) / p_now * 100
                    sp_5 = (p_5 - b_5) / p_5 * 100
                    spread_chg = round(sp_now - sp_5, 2)
        rows_out.append({
            "name": name, "date": d, "impacted": impacted,
            "fwd14": s.get("fwd14"), "net14": s.get("net14"),
            "spread_chg5d_pp": spread_chg, "supply_change_30d": supply_chg30,
        })

    clean = [r for r in rows_out if not r["impacted"]]
    imp = [r for r in rows_out if r["impacted"]]

    def st(recs):
        n = len(recs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None}
        f = [r["fwd14"] for r in recs if isinstance(r["fwd14"], (int, float))]
        if not f:
            return {"n": n, "win14": None, "avg14": None}
        return {"n": n, "win14": round(sum(1 for x in f if x > 0) / len(f) * 100, 1),
                "avg14": round(sum(f) / len(f), 2)}

    out = {"probe": "O2 深值提纯阶段0", "clean": clean, "impacted": imp,
           "clean_stats": st(clean), "impacted_stats": st(imp)}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== deep_value 逐条（cycle 186）===")
    for r in sorted(rows_out, key=lambda x: x["date"]):
        print(f"  {r['date']}  {'事件' if r['impacted'] else '干净'}  {r['name'][:20]:20s}  "
              f"fwd14={r['fwd14']:>7}  spread5d={r['spread_chg5d_pp']}  supply30d={r['supply_change_30d']}")
    print("干净:", st(clean), " 事件:", st(imp))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
