# -*- coding: utf-8 -*-
"""组合层绩效归因（A1-3，2026-08-10，纯分析不动引擎）。

目标：拆解「策略 +83.65%/-13.05% 低于池内等权 +252.31%/-55.59%」的可解释分量——
族级贡献 / 月度贡献 / 单品集中度 / 入场择时 vs 持有退出。

口径：与 portfolio_backtest.py 完全同源（hold14 / 双边成本2% / cap0.8 /
拒绝优先级 panic>accumulate>deep_value / 未部署资金按现金），复用 b1v2.simulate。

输出: data/portfolio_attribution.json（族级 leave-one-out + 月度 PnL 归因 + 单品集中度）。
"""
import io
import json
import statistics
from collections import defaultdict
from datetime import date
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

import sys

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
REPLAY = BASE / "data" / "item_backtest_full_2025.json"
REPLAY_CLEAN = BASE / "data" / "_exp_v2t7_win_replay.json"
OUT = BASE / "data" / "portfolio_attribution.json"

_spec = spec_from_file_location("pb", str(BASE / "references" / "portfolio_backtest.py"))
pb = module_from_spec(_spec)
_spec.loader.exec_module(pb)
_spec2 = spec_from_file_location("b1v2", str(BASE / "references" / "b1_risk_backtest_v2.py"))
b1v2 = module_from_spec(_spec2)
_spec2.loader.exec_module(b1v2)

from pipeline.config import SIGNAL_FAMILY_TAXONOMY, display_key_for_label  # noqa: E402

FAMILY_LABEL = dict(SIGNAL_FAMILY_TAXONOMY["display_labels"])
FAMILY_LABEL.update({"base": "基础族", "oversold": "超跌例外"})


def load_signals(replay_path):
    d = json.load(io.open(replay_path, encoding="utf-8"))
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
    return sigs


def total_return(sigs, cap=0.8):
    sim = b1v2.simulate(sigs, cap=cap)
    return sim["curve"][-1][2] / sim["curve"][0][2] - 1, sim


def build_attribution(replay_path, baseline_label):
    sigs = load_signals(replay_path)
    base_ret, _base_sim = total_return(sigs)
    print(f"[{baseline_label}] cap0.8: total={base_ret*100:.2f}% n_sig={len(sigs)}")

    fam = defaultdict(list)
    for s in sigs:
        fam[s["st"]].append(s)
    fam_contrib = {}
    for st, ss in fam.items():
        ret_ex, _ = total_return([x for x in sigs if x["st"] != st])
        contrib = base_ret - ret_ex
        n = len(ss)
        wins = sum(1 for x in ss if (x.get("net14") or 0) > 0)
        avg14 = statistics.mean([x["net14"] for x in ss]) if ss else 0
        fam_contrib[st] = {
            "label": FAMILY_LABEL.get(st, st),
            "n_signals": n,
            "win14_pct": round(100.0 * wins / n, 1) if n else None,
            "avg14_net_pct": round(avg14, 2),
            "leave_out_contrib_pp": round(contrib * 100, 2),
            "share_of_signals_pct": round(100.0 * n / len(sigs), 1),
        }

    month = defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0})
    for s in sigs:
        m = s["date"].strftime("%Y-%m")
        month[m]["n"] += 1
        net = s.get("net14")
        if net is None:
            continue
        month[m]["pnl"] += net * (s.get("limit") or 0)
        if net > 0:
            month[m]["wins"] += 1
    monthly = {}
    for m in sorted(month):
        d = month[m]
        monthly[m] = {"n": d["n"], "pnl_weighted": round(d["pnl"], 2),
                      "win14_pct": round(100.0 * d["wins"] / d["n"], 1)}

    item = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    for s in sigs:
        item[s["item"]]["n"] += 1
        if s.get("net14") is not None:
            item[s["item"]]["pnl"] += s["net14"] * (s.get("limit") or 0)
    ranked = sorted(item.items(), key=lambda kv: -kv[1]["pnl"])
    total_pnl = sum(v["pnl"] for v in item.values())
    top10 = [{"name": k[:40], "n": v["n"], "pnl": round(v["pnl"], 2)} for k, v in ranked[:10]]
    top10_share = sum(v["pnl"] for _, v in ranked[:10]) / total_pnl * 100 if total_pnl else 0

    bh = _pool_buy_hold()
    out = {
        "baseline": baseline_label,
        "caveat": ("HIST-FULL: accumulate leave-out +111.69pp is hold21 portfolio attribution; "
                   "contains ~50% missing-depth signals" if baseline_label == "HIST-FULL"
                   else "CLEAN-CUR: clean current-engine window; panic single-event share 55.3%"),
        "meta": "组合绩效归因双基线（A1-3）：与 portfolio_backtest 同源口径；leave-one-out=剔除该族后组合总收益差值(pp)。",
        "generated": date.today().isoformat(),
        "base": {"total_return_pct": round(base_ret * 100, 2), "n_signals": len(sigs)},
        "family_contribution": fam_contrib,
        "monthly_pnl": monthly,
        "item_concentration": {"top10": top10, "top10_share_pct": round(top10_share, 1),
                               "total_pnl": round(total_pnl, 2)},
        "pool_buy_hold_concentration": bh,
    }
    return out


def main():
    hist = build_attribution(REPLAY, "HIST-FULL")
    clean = build_attribution(REPLAY_CLEAN, "CLEAN-CUR")
    out = {k: v for k, v in hist.items()}
    out["baselines"] = {"HIST-FULL": hist, "CLEAN-CUR": clean}
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written:", OUT)


def _pool_buy_hold():
    """等权池 buy&hold 集中度：读 price_history（2025-08-10~2026-08-05 窗口），按品首末价。"""
    from pipeline import db
    conn = db.get_conn()
    rows = conn.execute("""
        SELECT i.name, MIN(p.price_rmb) first_p, MAX(p.price_rmb) last_p,
               MIN(p.date) d0, MAX(p.date) d1
        FROM price_history p JOIN items i ON i.id = p.item_id
        WHERE p.date >= '2025-08-10' AND p.date <= '2026-08-05' AND p.price_rmb > 0
        GROUP BY p.item_id HAVING d0 <= '2025-08-10'""").fetchall()
    conn.close()
    rets = []
    for r in rows:
        first, last = r["first_p"], r["last_p"]
        if first and last and first > 0:
            rets.append({"name": r["name"][:40], "ret_pct": round((last / first - 1) * 100, 1)})
    rets.sort(key=lambda x: -x["ret_pct"])
    n = len(rets)
    total = sum(r["ret_pct"] for r in rets)
    top10 = rets[:10]
    share = sum(r["ret_pct"] for r in top10) / total * 100 if total else 0
    return {
        "n_items": n,
        "equal_weight_avg_ret_pct": round(total / n, 1) if n else None,
        "top10": top10,
        "top10_share_of_total_ret_pct": round(share, 1),
        "note": "池内等权=95 品等权买入持有；若头部品贡献 >50% 则验证「2025 低价品暴涨主导」假设",
    }


if __name__ == "__main__":
    main()
