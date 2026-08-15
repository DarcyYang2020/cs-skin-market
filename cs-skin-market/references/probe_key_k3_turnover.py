# -*- coding: utf-8 -*-
"""K3 成交量分离度（C5GAME turnover_number，platform=3，period=1095，只读重开审查）。

种子 = 10 条已知信号（W1 4 + W3 6）。两指标：
  量能跟随 = 5d turnover 涨幅 / 5d 卖价涨幅；
  放量滞涨 = 信号日 turnover / 前 20 日均量。
"""
import json
import sqlite3
import statistics
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.collector import _api_call  # noqa: E402
from pipeline.config import TZ_BJ  # noqa: E402

CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"
SIG = ROOT / "data" / "_exp_trend_tight_1.json"
OUT = ROOT / "data" / "_exp_key_k3.json"


def fetch_turnover(good_id):
    resp = _api_call("POST", "/info/chart", {
        "good_id": str(good_id), "key": "turnover_number", "platform": 3,
        "period": "1095", "style": "all_style"})
    if resp.get("code") != 200 or not isinstance(resp.get("data"), dict):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def daily(data):
    out = {}
    ts = data.get("timestamp") or []
    vals = data.get("main_data") or []
    for i in range(min(len(ts), len(vals))):
        try:
            t = int(ts[i])
            if t < 10 ** 11:
                t *= 1000
            v = float(vals[i])
        except (TypeError, ValueError):
            continue
        if t <= 0 or v < 0:
            continue
        d = datetime.fromtimestamp(t / 1000, tz=TZ_BJ).strftime("%Y-%m-%d")
        out[d] = v
    return out


def val_at(series_dates, series_vals, target):
    """最近 <= target 的值。"""
    best = None
    for d, v in zip(series_dates, series_vals):
        if d <= target:
            best = v
        else:
            break
    return best


def main():
    sigs = json.load(open(SIG, encoding="utf-8"))["signals"]
    cyc = sqlite3.connect(CYCLE_DB)
    cyc.row_factory = sqlite3.Row
    rows = []
    for s in sigs:
        iid = s["item"]
        g = cyc.execute("SELECT good_id FROM items WHERE id=?", (iid,)).fetchone()
        gid = g["good_id"]
        sell_rows = cyc.execute("SELECT date, price_rmb FROM price_history WHERE item_id=? "
                                "AND price_rmb IS NOT NULL ORDER BY date", (iid,)).fetchall()
        sdates = [r["date"] for r in sell_rows]
        sprices = [r["price_rmb"] for r in sell_rows]
        i = sdates.index(s["date"])
        data, err = fetch_turnover(gid)
        if data is None:
            rows.append({"win": "W1" if s["date"] <= "2025-10-24" else "W3", "name": s["name"],
                         "date": s["date"], "err": err, "vol_follow": None, "vol_surge": None})
            print(f"  [{s['date']}] {s['name'][:18]} FAIL {err}")
            continue
        tser = daily(data)
        tdates = sorted(tser)
        tvals = [tser[d] for d in tdates]
        t_now = val_at(tdates, tvals, s["date"])
        t_5d = val_at(tdates, tvals, sdates[i - 5]) if i >= 5 else t_now
        # 量能跟随
        t_ret = (t_now - t_5d) / t_5d * 100 if t_5d else 0
        s_now = sprices[i]
        s_5d = sprices[i - 5] if i >= 5 else s_now
        s_ret = (s_now - s_5d) / s_5d * 100 if s_5d else 0
        vol_follow = round(t_ret / s_ret, 3) if s_ret != 0 else None
        # 放量滞涨：信号日量 / 前20日均量
        idx_now = next((j for j, d in enumerate(tdates) if d >= s["date"]), None)
        if idx_now is not None and idx_now >= 20:
            avg20 = sum(tvals[idx_now - 20:idx_now]) / 20
            vol_surge = round(tvals[idx_now] / avg20, 3) if avg20 > 0 else None
        else:
            vol_surge = None
        rows.append({"win": "W1" if s["date"] <= "2025-10-24" else "W3", "name": s["name"],
                     "date": s["date"], "err": "", "vol_follow": vol_follow, "vol_surge": vol_surge,
                     "t_ret": round(t_ret, 1), "s_ret": round(s_ret, 1)})
        print(f"  [{s['date']}] {s['name'][:18]} t_ret={t_ret:.1f} s_ret={s_ret:.1f} "
              f"follow={vol_follow} surge={vol_surge}")
    cyc.close()

    def med(vals):
        v = [x for x in vals if x is not None]
        return round(statistics.median(v), 3) if v else None

    w1 = [r for r in rows if r["win"] == "W1"]
    w3 = [r for r in rows if r["win"] == "W3"]
    sep = {
        "K3_量能跟随": {"W1_median": med([r["vol_follow"] for r in w1]), "W3_median": med([r["vol_follow"] for r in w3])},
        "K3_放量滞涨": {"W1_median": med([r["vol_surge"] for r in w1]), "W3_median": med([r["vol_surge"] for r in w3])},
    }
    out = {"probe": "K3 成交量分离度", "n_W1": len(w1), "n_W3": len(w3), "separation": sep, "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== K3 分离度 ===")
    for k, v in sep.items():
        opposite = v["W1_median"] is not None and v["W3_median"] is not None and v["W1_median"] != v["W3_median"]
        print(f"  {k}: W1中位={v['W1_median']}  W3中位={v['W3_median']}  分离={opposite}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
