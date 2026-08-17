# -*- coding: utf-8 -*-
"""等权池逐时期前视（2026-08-17，只读，引擎无关检验）：
HQ 180 品等权买入持有在各时期进场后的 14/30 日前视——完全不经单品引擎，
检验「五时期区分度」是否独立成立，并给引擎信号提供逐时期对照基线。
输出 data/_exp_period_ew_forward.json。
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

OUT = ROOT / "data" / "_exp_period_ew_forward.json"
EXCL = ("印花 |", "手套", "武器箱", "游击队", "军刀勇士", "特警")
PERIODS = ["P恐慌深跌", "S1牛市上行", "S2牛市回调", "S3弱市阴跌", "S4弱市反弹"]


def main():
    st = json.load(open(ROOT / "data" / "market_state_daily.json", encoding="utf-8"))
    c = sqlite3.connect(os.environ["CS_MODEL_DB"])
    c.row_factory = sqlite3.Row
    items = c.execute(
        "SELECT i.id, i.name FROM items i WHERE i.good_id>0").fetchall()
    hq = [r for r in items if not any(m in r["name"] for m in EXCL)]
    price = {}
    for r in hq:
        rows = c.execute(
            "SELECT date, price_rmb FROM price_history WHERE item_id=? AND price_rmb IS NOT NULL "
            "ORDER BY date", (r["id"],)).fetchall()
        price[r["id"]] = {x["date"]: float(x["price_rmb"]) for x in rows}
    c.close()
    print("HQ 品:", len(hq))

    cells = OrderedDict((p, {"fwd14": [], "fwd30": []}) for p in PERIODS)
    for d, s in sorted(st.items()):
        if "chg180" not in s or "chg30" not in s:
            continue
        p = state_bucket(s["chg180"], s["chg30"])
        if p not in cells:
            continue
        d14 = _add_days(d, 14)
        d30 = _add_days(d, 30)
        r14, r30 = [], []
        for iid, mp in price.items():
            keys = [k for k in mp if k <= d]
            if not keys or mp[min(keys)] <= 0:
                continue
            base = mp[max(keys)]
            k14 = [k for k in mp if d < k <= d14]
            k30 = [k for k in mp if d < k <= d30]
            if k14:
                r14.append(mp[max(k14)] / base - 1)
            if k30:
                r30.append(mp[max(k30)] / base - 1)
        if r14:
            cells[p]["fwd14"].append(sum(r14) / len(r14) * 100)
        if r30:
            cells[p]["fwd30"].append(sum(r30) / len(r30) * 100)

    out = {"probe": "等权池逐时期前视（引擎无关）", "periods": {}}
    print("== 等权池逐时期前视（不经引擎，%扣成本前口径）==")
    for p in PERIODS:
        r14, r30 = cells[p]["fwd14"], cells[p]["fwd30"]

        def wa(vs):
            if not vs:
                return None
            return (len(vs), round(sum(1 for v in vs if v > 0) * 100.0 / len(vs), 1),
                    round(sum(vs) / len(vs), 2))
        w14, w30 = wa(r14), wa(r30)
        out["periods"][p] = {"fwd14": w14, "fwd30": w30}
        print("%-8s 14d n=%s win=%s avg=%s | 30d n=%s win=%s avg=%s" % (
            p, *w14, *w30) if w14 and w30 else print("%-8s %s / %s" % (p, w14, w30)))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


def _add_days(d, n):
    from datetime import date as _d, timedelta as _td
    return (_d.fromisoformat(d) + _td(days=n)).isoformat()


if __name__ == "__main__":
    main()
