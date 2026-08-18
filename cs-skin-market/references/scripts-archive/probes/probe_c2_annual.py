# -*- coding: utf-8 -*-
"""验证用户认知（2026-08-15）：回撤大是因为黑天鹅——按年拆 C2（核心70%+卫星30%不择时等权）。"""
import io, json, sys
from datetime import date
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

ROOT = Path(r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "references"))

REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
CYCLE_DB = ROOT / "data" / "replay_cycle_win.db"

_spec = spec_from_file_location("b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
b1v2 = module_from_spec(_spec); _spec.loader.exec_module(b1v2)
import sqlite3


def annual_metrics(pts, year):
    seg = [(d, v) for d, v in pts if d[:4] == year]
    if len(seg) < 2:
        return None
    vals = [v for _, v in seg]
    peak = vals[0]; mdd = 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100)
    total = (vals[-1] / vals[0] - 1) * 100
    return {"total": round(total, 2), "mdd": round(mdd, 2)}


# 1) 引擎核心曲线
d = json.load(io.open(REPLAY, encoding="utf-8"))
sigs = []
for s in d["signals"]:
    fwd = s.get("fwd_series") or []
    if not fwd:
        continue
    lab = s.get("action_label") or ""
    st = "panic" if "恐慌" in lab else ("deep_value" if "深值" in lab else "accumulate")
    sigs.append({"date": date.fromisoformat(s["date"]), "item": s["name"],
                 "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
                 "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1)})
sim = b1v2.simulate(sigs, cap=0.8)
core = [(c[0], c[2]) for c in sim["curve"]]

# 2) 卫星：不择时等权（与 probe_core_sat_2 同口径）
c = sqlite3.connect(CYCLE_DB); c.row_factory = sqlite3.Row
items = [r["id"] for r in c.execute("SELECT id FROM items WHERE good_id>0").fetchall()]
ph = {}
for r in c.execute("SELECT item_id, date, price_rmb FROM price_history WHERE price_rmb IS NOT NULL ORDER BY date"):
    ph.setdefault(r["item_id"], {})[r["date"]] = r["price_rmb"]
c.close()
all_days = sorted({dd for m in ph.values() for dd in m})
first = {i: list(m)[0] for i, m in ph.items() if m}
sat = []
eq = 1.0
for dd in all_days:
    rets = []
    for i, m in ph.items():
        keys = [k for k in m if k <= dd]
        if len(keys) < 2:
            continue
        p0, p1 = m[keys[-2]], m[keys[-1]]
        if p0 and p1 and p0 > 0:
            rets.append(p1 / p0 - 1.0)
    if rets:
        eq *= (1 + sum(rets) / len(rets))
    sat.append((dd, eq))

sat_map = dict(sat)
c2 = []
for dd, cv in core:
    sv = sat_map.get(dd, sat[-1][1])
    c2.append((dd, 0.7 * cv + 0.3 * sv))

print("=== 按年拆解：核心 / 卫星(等权) / C2(70/30) ===")
for y in ("2023", "2024", "2025", "2026"):
    mc = annual_metrics(core, y)
    ms = annual_metrics(sat, y)
    m2 = annual_metrics(c2, y)
    def f(x):
        return f"total={x['total']:>8}% mdd={x['mdd']:>7}%" if x else "—"
    print(f"  {y}: 核心 {f(mc)} | 卫星 {f(ms)} | C2 {f(m2)}")

def full(pts):
    vals = [v for _, v in pts]
    peak = vals[0]; mdd = 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100)
    return (vals[-1] / vals[0] - 1) * 100, mdd
for name, pts in (("核心", core), ("卫星", sat), ("C2", c2)):
    t, m = full(pts)
    print(f"全周期 {name}: total={t:+.2f}% maxDD={m:.2f}%")
