# -*- coding: utf-8 -*-
"""TREND-GRID-1 正式 A2 探针（只读，真 TH，组合版 5~20% / 分位≤75%）。

验证段 2025-08-10~2026-08-05 扫 TREND-GRID-1 信号，事件级去簇，四小牛市分窗，
逐条打钩 A2 五条门槛（第③条 2026-02~03 陷阱 ≤2% 且净期望非负）。
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.trend_health import compute_trend_health  # noqa: E402

DB = ROOT / "data" / "replay_cycle_win.db"
OLD_REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
OUT = ROOT / "data" / "_exp_trend_grid_1_a2.json"
START, END = "2025-08-10", "2026-08-05"

WINDOWS = [
    ("W1_真趋势", "2025-08-10", "2025-10-24"),
    ("W2_V反弹", "2025-11-01", "2025-12-31"),
    ("W3_陷阱", "2026-02-01", "2026-03-31"),
    ("W4_恐慌反弹", "2026-05-27", "2026-06-10"),
]


def ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def decluster(signals, day_gap=3):
    """按日期去簇：相邻信号日期差 <= day_gap 归为同一事件簇。返回簇列表。"""
    ss = sorted(signals, key=lambda x: x["date"])
    clusters = []
    for s in ss:
        if clusters and (s["date"] <= clusters[-1][-1]["date"] or
                         _days_between(clusters[-1][-1]["date"], s["date"]) <= day_gap):
            clusters[-1].append(s)
        else:
            clusters.append([s])
    return clusters


def _days_between(a, b):
    from datetime import datetime
    da = datetime.fromisoformat(a)
    db = datetime.fromisoformat(b)
    return (db - da).days


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    mrows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    mdates = [r["date"] for r in mrows]
    mvals = [r["value"] for r in mrows]
    regime = {}
    for i in range(90, len(mvals)):
        ma30 = sum(mvals[i - 29:i + 1]) / 30
        ma90 = sum(mvals[i - 89:i + 1]) / 90
        new_high60 = mvals[i] >= max(mvals[max(0, i - 59):i + 1])
        # 预注册 regime 门：现价>MA30 且 MA30>MA90（多头排列），或指数创 60 日新高
        regime[mdates[i]] = (mvals[i] > ma30 and ma30 > ma90) or new_high60

    items = conn.execute("SELECT id, name, good_id FROM items WHERE good_id > 0 ORDER BY id").fetchall()
    series = {}
    for it in items:
        rows = conn.execute(
            "SELECT date, price_rmb, in_sale_count FROM price_history WHERE item_id=? "
            "AND price_rmb IS NOT NULL ORDER BY date", (it["id"],)).fetchall()
        series[it["id"]] = {"name": it["name"], "dates": [r["date"] for r in rows],
                            "price": [r["price_rmb"] for r in rows],
                            "insale": [r["in_sale_count"] for r in rows]}
    conn.close()

    sigs = []
    for iid, s in series.items():
        dates, price, insale = s["dates"], s["price"], s["insale"]
        n = len(price)
        for i in range(90, n):
            d = dates[i]
            if not (START <= d <= END):
                continue
            if i + 14 >= n:
                continue
            if not regime.get(d):
                continue
            p30 = ma(price[:i + 1], 30)
            if p30 is None or not (price[i] > p30):
                continue
            th_obj = compute_trend_health(price[:i + 1], supply=insale[:i + 1])
            if getattr(th_obj, "score", 0) < 55:
                continue
            hi30 = max(price[max(0, i - 29):i + 1])
            dd30 = (price[i] - hi30) / hi30 * 100 if hi30 > 0 else 0
            if not (-20.0 <= dd30 <= -5.0):
                continue
            if i >= 3 and price[i] < min(price[i - 3:i]):
                continue
            if i >= 7 and insale[i] is not None and insale[i - 7] and insale[i - 7] > 0:
                if (insale[i] - insale[i - 7]) / insale[i - 7] * 100 > 5.0:
                    continue
            win90 = price[max(0, i - 89):i + 1]
            pct90 = sum(1 for p in win90 if p <= price[i]) / len(win90) * 100
            if pct90 > 75.0:
                continue
            mi = mdates.index(d) if d in mdates else -1
            if mi < 0:
                continue
            chg7 = (mvals[mi] / mvals[mi - 7] - 1) * 100
            chg14 = (mvals[mi] / mvals[mi - 14] - 1) * 100
            sent = max(10.0, min(90.0, 50 - chg7 * 2 - chg14))
            if sent <= 30:
                continue
            fwd14 = (price[i + 14] / price[i] - 1) * 100 - 2.0
            fwd30 = (price[i + 30] / price[i] - 1) * 100 - 2.0 if i + 30 < n else None
            sigs.append({"item": iid, "name": s["name"], "date": d, "sent": round(sent, 1),
                         "dd30": round(dd30, 1), "pct90": round(pct90, 1),
                         "fwd14": round(fwd14, 2), "fwd30": round(fwd30, 2) if fwd30 is not None else None})

    clusters = decluster(sigs)
    n_sig = len(sigs)
    n_cluster = len(clusters)

    def st(rs):
        n = len(rs)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "win30": None, "avg30": None}
        w14 = [r for r in rs if r["fwd14"] is not None]
        w30 = [r for r in rs if r["fwd30"] is not None]
        win14 = sum(1 for r in w14 if r["fwd14"] > 0) / len(w14) * 100 if w14 else None
        avg14 = sum(r["fwd14"] for r in w14) / len(w14) if w14 else None
        win30 = sum(1 for r in w30 if r["fwd30"] > 0) / len(w30) * 100 if w30 else None
        avg30 = sum(r["fwd30"] for r in w30) / len(w30) if w30 else None
        return {"n": n, "win14": round(win14, 1) if win14 is not None else None,
                "avg14": round(avg14, 2) if avg14 is not None else None,
                "win30": round(win30, 1) if win30 is not None else None,
                "avg30": round(avg30, 2) if avg30 is not None else None}

    by_win = {}
    for wn, ws, we in WINDOWS:
        by_win[wn] = st([s for s in sigs if ws <= s["date"] <= we])

    # 旧引擎验证段 14d net
    old = json.load(open(OLD_REPLAY, encoding="utf-8"))
    old_val = [s for s in old["signals"] if s["date"] >= "2025-08-10" and s.get("fwd14") is not None]
    old_avg14 = sum(s["fwd14"] for s in old_val) / len(old_val) if old_val else None

    # 五条门槛
    w3_n = by_win["W3_陷阱"]["n"]
    w3_rate = round(100.0 * w3_n / n_sig, 1) if n_sig else None
    w3_avg14 = by_win["W3_陷阱"]["avg14"]
    gates = {
        "① 验证段14d net vs 旧引擎+3pp": {
            "trg_grid_avg14": st(sigs)["avg14"],
            "old_engine_avg14": round(old_avg14, 2) if old_avg14 is not None else None,
            "pass": (st(sigs)["avg14"] is not None and old_avg14 is not None
                     and st(sigs)["avg14"] >= old_avg14 + 3.0),
        },
        "② 2025-08~10 分窗 14d 胜率>=60%": {
            "win14": by_win["W1_真趋势"]["win14"],
            "pass": by_win["W1_真趋势"]["win14"] is not None and by_win["W1_真趋势"]["win14"] >= 60.0,
        },
        "③ 2026-02~03 陷阱 信号<=2% 且净期望非负": {
            "n": w3_n, "rate_pct": w3_rate, "avg14": w3_avg14,
            "pass": (w3_rate is not None and w3_rate <= 2.0
                     and w3_avg14 is not None and w3_avg14 >= 0),
        },
        "④ 组合 maxDD 不破 -20%": {"pass": None, "note": "待 portfolio 组合模拟（本轮未算）"},
        "⑤ 去簇后 n>=15": {"n_cluster": n_cluster, "pass": n_cluster >= 15},
    }

    out = {
        "probe": "TREND-GRID-1 正式 A2", "window": f"{START}~{END}",
        "params": "回调5~20% / 分位<=75% / TH>=55真 / sent>30",
        "n_signals": n_sig, "n_clusters": n_cluster,
        "overall": st(sigs), "by_window": by_win,
        "old_engine_validate_avg14": round(old_avg14, 2) if old_avg14 is not None else None,
        "gates": gates,
        "signals": sigs,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== TREND-GRID-1 A2（验证段）===")
    print("总信号:", n_sig, "| 去簇后:", n_cluster, "| 总体:", json.dumps(st(sigs), ensure_ascii=False))
    print("旧引擎验证段 avg14:", round(old_avg14, 2) if old_avg14 is not None else None)
    for wn, ws, we in WINDOWS:
        print(f"  {wn} ({ws}~{we}):", json.dumps(by_win[wn], ensure_ascii=False))
    print("=== 五条门槛 ===")
    for k, v in gates.items():
        print(f"  {k}: {'PASS' if v['pass'] is True else 'FAIL' if v['pass'] is False else 'N/A'} {json.dumps(v, ensure_ascii=False)}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
