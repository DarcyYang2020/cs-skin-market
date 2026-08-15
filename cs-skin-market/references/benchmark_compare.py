# -*- coding: utf-8 -*-
"""基准对照（Benchmark Compare，2026-08-07）。

给 engine-unified / 决策日志补充参照系：策略信号组合 vs 池内等权买入持有 vs 大盘指数。

- 策略腿: 去量引擎 v2 信号组合模拟（复用 b1_risk_backtest_v2.simulate，现行政策 cap0.8、
  hold21（2026-08-10 对齐单品 hold_guidance，见 decision-log）、手续费 2%、拒绝优先级 panic>accumulate>deep_value，权益曲线按未部署资金计现金）。
- 基准腿A: 策略池等权买入持有（price_history.price_rmb，前向填充，2025-01-01 起）。
- 基准腿B: 大盘指数（market_index.value）同期。

窗口:
- full:   回放窗口 2025-01-01 ~ 2026-08-05（与回放 args 一致）。
- active: 策略活跃窗口（首个信号日 ~ 末日+hold21，即组合模拟曲线覆盖区间）。

输出: data/benchmark_compare.json
用法: python references/benchmark_compare.py
"""
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util

spec = importlib.util.spec_from_file_location("b1v2", str(Path(__file__).resolve().parent / "b1_risk_backtest_v2.py"))
b1v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1v2)

from pipeline import db
from pipeline.config import display_key_for_label  # noqa: E402

REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
REPLAY_CLEAN = ROOT / "data" / "_exp_v2t9_win_replay.json"
OUT = ROOT / "data" / "benchmark_compare.json"
HOLD = 21
COST = 0.02


def load_signals(replay_path=None):
    path = Path(replay_path) if replay_path else REPLAY
    d = json.load(io.open(path, encoding="utf-8"))
    sigs = []
    for s in d["signals"]:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        st = display_key_for_label(s.get("action_label"))
        sigs.append({
            "date": date.fromisoformat(s["date"]), "item": s["name"],
            "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
            "fwd": fwd, "st": st, "prio": b1v2.PRIORITY.get(st, 1),
            "net14": s.get("net14"),
        })
    return sigs, d.get("args", {})


def id_by_name(names):
    conn = db.get_conn()
    out = {}
    for n in names:
        r = conn.execute("SELECT id FROM items WHERE name=?", (n,)).fetchone()
        if r:
            out[r["id"]] = n
    conn.close()
    return out


def price_series(item_ids):
    conn = db.get_conn()
    out = {}
    if item_ids:
        q = "SELECT item_id, date, price_rmb FROM price_history WHERE item_id IN (%s) ORDER BY date" % (
            ",".join("?" * len(item_ids)))
        for r in conn.execute(q, list(item_ids)):
            out.setdefault(r["item_id"], {})[r["date"]] = r["price_rmb"]
    conn.close()
    return out


def market_series():
    conn = db.get_conn()
    rows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    conn.close()
    return {r["date"]: r["value"] for r in rows}


def ffill_curve(series, start, end):
    """(start,end] 闭区间前向填充曲线: [(date, value), ...]；无数据返回 []。"""
    days = (end - start).days
    if days < 0:
        return []
    cur = None
    out = []
    for i in range(days + 1):
        d = (start + timedelta(days=i)).isoformat()
        if d in series:
            cur = series[d]
        if cur is not None:
            out.append((d, cur))
    return out


def metrics(curve):
    """curve = [(date, value), ...] → total/maxDD/days/年化。"""
    if len(curve) < 2:
        return {"total_return_pct": 0.0, "max_drawdown_pct": 0.0, "days": len(curve),
                "annualized_pct": None, "first": None, "last": None}
    base = curve[0][1]
    peak = base
    max_dd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        dd = (v / peak - 1) * 100 if peak else 0.0
        max_dd = min(max_dd, dd)
    total = (curve[-1][1] / base - 1) * 100 if base else 0.0
    days = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(curve[0][0])).days
    ann = ((curve[-1][1] / base) ** (365.0 / days) - 1) * 100 if base and days > 0 else None
    return {"total_return_pct": round(total, 2), "max_drawdown_pct": round(max_dd, 2),
            "days": days, "annualized_pct": round(ann, 2) if ann is not None else None,
            "first": curve[0][0], "last": curve[-1][0]}


def buy_hold(prices_by_item, start, end):
    """池内等权买入持有: 每日 = 各品(价/首价)均值，前向填充，缺数据品当日跳过。"""
    items = [(pid, m) for pid, m in prices_by_item.items() if m]
    if not items:
        return []
    days = (end - start).days
    if days < 0:
        return []
    out = []
    for i in range(days + 1):
        d = (start + timedelta(days=i)).isoformat()
        vals = []
        for _, m in items:
            keys = [k for k in m if k <= d]
            if not keys:
                continue
            base = m[min(keys)]
            if not base or base <= 0:
                continue
            vals.append(m[max(keys)] / base)
        if vals:
            out.append((d, sum(vals) / len(vals)))
    return out


def build_benchmark(replay_path, baseline_label):
    sigs, args = load_signals(replay_path)
    print("[%s] signals: %d | pool: %s | replay window: %s ~ %s" % (
        baseline_label, len(sigs), args.get("pool"), args.get("start"), args.get("end")))
    if not sigs:
        raise SystemExit("no signals for " + baseline_label)

    sim = b1v2.simulate(sigs, cap=0.8)
    sim_nocap = b1v2.simulate(sigs, cap=None)
    strat_curve = [(c[0], c[2]) for c in sim["curve"]]
    strat_nocap_curve = [(c[0], c[2]) for c in sim_nocap["curve"]]
    full_start = date.fromisoformat(args.get("start", "2025-01-01"))
    full_end = date.fromisoformat(args.get("end")) if args.get("end") else date.fromisoformat(strat_curve[-1][0])
    active_start = min(s["date"] for s in sigs)
    active_end = max(s["date"] for s in sigs) + timedelta(days=HOLD)

    names = sorted({s["item"] for s in sigs})
    idmap = id_by_name(names)
    prices = price_series(list(idmap.keys()))
    mkt = market_series()

    windows = {}
    for wname, (ws, we) in (("full", (full_start, full_end)), ("active", (active_start, active_end))):
        def _window(curve):
            return sorted((d, v) for d, v in curve if ws <= date.fromisoformat(d) <= we)
        windows[wname] = {
            "range": [ws.isoformat(), we.isoformat()],
            "strategy": metrics(_window(strat_curve)),
            "strategy_nocap_ref": metrics(_window(strat_nocap_curve)),
            "pool_buy_hold": metrics(buy_hold(prices, ws, we)),
            "market_index": metrics(ffill_curve(mkt, ws, we)),
        }

    n14 = [s for s in sigs if s.get("net14") is not None]
    wins = sum(1 for s in n14 if s["net14"] > 0)
    out = {
        "baseline": baseline_label,
        "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
        "note": "策略腿=信号组合模拟（cap0.8/hold21/手续费2%/拒绝优先级 panic>accumulate>deep_value，"
                "权益曲线未部署资金按现金计，首信号日前无仓位故 full/active 同区间）；strategy_nocap_ref=同模拟去掉 cap 上限"
                "（仅信息参考，实盘不采用）；pool_buy_hold=策略池等权买入持有"
                "（price_history.price_rmb 前向填充，2025 低价品暴涨主导，未计一次性 2% 成本）；"
                "market_index=大盘指数同期。本基线输出必须挂 baseline 标签，禁止裸数字。",
        "caveat": "HIST-FULL: contains ~50% missing-depth signals" if baseline_label == "HIST-FULL"
                  else "CLEAN-CUR: clean after csQAQ period=1095 backfill; panic 26.9% family share, 97.5% of panic in 2026-05 single-event cluster",
        "replay": {"signals": len(sigs), "pool": args.get("pool"), "start": args.get("start"), "end": args.get("end")},
        "windows": windows,
        "signal_stats": {"n14": len(n14), "win14_pct": round(100.0 * wins / len(n14), 1),
                         "avg14": round(sum(s["net14"] for s in n14) / len(n14), 2)},
    }
    return out


def main():
    hist = build_benchmark(REPLAY, "HIST-FULL")
    clean = build_benchmark(REPLAY_CLEAN, "CLEAN-CUR")
    out = {k: v for k, v in hist.items()}
    out["baselines"] = {"HIST-FULL": hist, "CLEAN-CUR": clean}
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written:", OUT)

    for label, b in (("HIST-FULL", hist), ("CLEAN-CUR", clean)):
        print("== baseline %s ==" % label)
        for wname, w in b["windows"].items():
            print("  window %s (%s ~ %s)" % (wname, w["range"][0], w["range"][1]))
            for leg in ("strategy", "strategy_nocap_ref", "pool_buy_hold", "market_index"):
                m = w[leg]
                print("    %-14s total=%8.2f%%  maxDD=%7.2f%%  days=%d  ann=%s" % (
                    leg, m["total_return_pct"], m["max_drawdown_pct"], m["days"], m["annualized_pct"]))


if __name__ == "__main__":
    main()
