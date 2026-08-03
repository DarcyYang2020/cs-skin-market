# -*- coding: utf-8 -*-
"""深值建仓变体回测（方向1，纯数据验证，不改引擎代码）。

基线 = 现引擎 buy 信号（应与 data/item_backtest_latest.json 一致：88 信号 / 14d 79.5% / 30d 61.4%）。
变体 = 引擎未买入的日子，额外检查「深值建仓」规则：
    pct<=P and z<=Z and TH_LO<=单品TH<55 and 大盘TH>=MTH and 21日跌幅<=DROP
去重：距最近一次买入（引擎或变体）>=7 天。
输出：基线核对 + 主规则补充信号 + 敏感度网格，分窗口（全窗口 / pre-1/23 / 1/23~2/12 / 之后）。
"""
import sys, json, statistics, traceback
from datetime import datetime
from collections import defaultdict
sys.path.insert(0, ".")
from pipeline import db
import pipeline.item_analysis as ia
from pipeline.backtest_common import patch_sentiment, build_market_context
from run_item_backtest import load_item_series, load_items

START = "2025-11-02"
WARMUP = 60
COST = 0.02


def replay(limit_items=None, verbose=False):
    market_ctx = build_market_context(START)
    patch_sentiment(50.0)
    items = load_items()
    if limit_items:
        items = {k: v for k, v in items.items() if v in limit_items}
    records = []
    for idx, (iid, iname) in enumerate(sorted(items.items())):
        dates, prices, in_sale = load_item_series(iid)
        if len(prices) < WARMUP + 1:
            continue
        n = len(prices)
        recent_buys = []
        cnt = 0
        for i in range(WARMUP, n):
            d = dates[i]
            if d not in market_ctx:
                continue
            mc = market_ctx[d]
            patch_sentiment(mc["sentiment"])
            prefix = prices[:i + 1]
            try:
                res = ia.run_item_analysis(
                    name=iname, prices=prefix, volumes=[0] * len(prefix),
                    supply_hist=in_sale[:i + 1], market_history=None,
                    market_pct_90d=mc["pct"], market_cycle=mc["cycle"],
                    market_zscore=mc["z"], market_th_score=mc["th"],
                    market_30d_change=mc.get("chg30", 0),
                    market_drop21=mc.get("drop21", 0),
                    recent_buy_dates=recent_buys, signal_date=d,
                )
            except Exception:
                continue
            fd = res.fusion_decision if isinstance(res.fusion_decision, dict) else {}
            action = fd.get("action", "")
            is_buy = action in ("buy", "oversold_buy")
            if is_buy:
                recent_buys.append(d)
            pos = res.position
            th_obj = res.trend_health or {}
            th = th_obj.get("score", 50) if isinstance(th_obj, dict) else getattr(th_obj, "score", 50)
            fwd14 = (prices[i + 14] / prices[i] - 1) * 100 if i + 14 < n else None
            fwd30 = (prices[i + 30] / prices[i] - 1) * 100 if i + 30 < n else None
            net14 = fwd14 - COST * 100 if fwd14 is not None else None
            net30 = fwd30 - COST * 100 if fwd30 is not None else None
            dd = 0.0
            for j in range(i + 1, min(i + 15, n)):
                dd = min(dd, (prices[j] / prices[i] - 1) * 100)
            records.append({
                "date": d, "item": iname, "engine_buy": is_buy,
                "action": action, "label": fd.get("action_label", action),
                "pct": pos.percentile_90d, "z": pos.zscore_90d,
                "th": th, "mth": mc["th"], "drop21": mc.get("drop21", 0),
                "sent": mc["sentiment"], "cycle": mc["cycle"],
                "fwd14": fwd14, "fwd30": fwd30, "net14": net14, "net30": net30, "dd": dd,
            })
            cnt += 1
        if verbose:
            print(f"  replayed {iname} ({cnt} days)", flush=True)
    return records


def stats(recs):
    if not recs:
        return None
    v14 = [r["net14"] for r in recs if r["net14"] is not None]
    v30 = [r["net30"] for r in recs if r["net30"] is not None]
    w14 = sum(1 for v in v14 if v > 0)
    w30 = sum(1 for v in v30 if v > 0)
    def pf(vals):
        wins = [v for v in vals if v > 0]
        loss = [v for v in vals if v <= 0]
        aw = statistics.mean(wins) if wins else 0.0
        al = statistics.mean(loss) if loss else 0.0
        return round(aw, 1), round(al, 1), (round(aw / -al, 2) if al < 0 else None)
    return {
        "n": len(recs),
        "win14%": round(w14 / len(v14) * 100, 1) if v14 else None,
        "avg14": round(statistics.mean(v14), 2) if v14 else None,
        "sum14": round(sum(v14), 1) if v14 else None,
        "win30%": round(w30 / len(v30) * 100, 1) if v30 else None,
        "avg30": round(statistics.mean(v30), 2) if v30 else None,
        "sum30": round(sum(v30), 1) if v30 else None,
        "pf14": pf(v14), "pf30": pf(v30),
        "maxdd": round(min((r["dd"] for r in recs), default=0.0), 1),
    }


def in_window(date, w):
    if w == "full":
        return True
    if w == "pre123":
        return date <= "2026-01-22"
    if w == "feb":
        return "2026-01-23" <= date <= "2026-02-12"
    if w == "post_feb":
        return date > "2026-02-12"
    return False


def variant_adds(records, rule, dedup_days=7):
    last_buy = {}
    out = []
    for r in sorted(records, key=lambda x: (x["item"], x["date"])):
        key = r["item"]
        if r["engine_buy"]:
            last_buy[key] = r["date"]
            continue
        if not rule(r):
            continue
        lb = last_buy.get(key)
        if lb:
            gap = (datetime.strptime(r["date"], "%Y-%m-%d") - datetime.strptime(lb, "%Y-%m-%d")).days
            if gap < dedup_days:
                continue
        out.append(r)
        last_buy[key] = r["date"]
    return out


def make_rule(P, Z, TH_LO, MTH, DROP):
    def r(rec):
        if rec["pct"] is None or rec["z"] is None or rec["th"] is None:
            return False
        if rec["pct"] > P or rec["z"] > Z:
            return False
        if rec["th"] < TH_LO or rec["th"] >= 55:
            return False
        if rec["mth"] < MTH:
            return False
        if DROP is not None and rec["drop21"] > DROP:
            return False
        return True
    return r


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", default="", help="semicolon-separated item names for quick run")
    ap.add_argument("--save", default="data/deepvalue_variant.json")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()
    limit = [x.strip() for x in args.limit.split(";") if x.strip()] or None
    print("replaying...", flush=True)
    try:
        recs = replay(limit_items=limit, verbose=bool(limit))
        print(f"replayed records: {len(recs)}", flush=True)
        with open("data/deepvalue_records.json", "w", encoding="utf-8") as f:
            json.dump({"records": recs}, f, ensure_ascii=False)
    except Exception:
        traceback.print_exc()
        raise

    try:
        base = [r for r in recs if r["engine_buy"]]
        print("\n===== 基线核对（应与 88 信号一致） =====")
        print("全部:", stats(base))
        for w in ["pre123", "feb", "post_feb"]:
            wr = [r for r in base if in_window(r["date"], w)]
            print(f"{w:10s}:", stats(wr))

        windows = ["full", "pre123", "feb", "post_feb"]
        print("\n===== 主规则：pct<=15 z<=-1 TH 35-55 大盘TH>=40 21d跌幅<=-10 =====")
        main_rule = make_rule(15, -1.0, 35, 40, -10)
        adds = variant_adds(recs, main_rule)
        for w in windows:
            wa = [r for r in adds if in_window(r["date"], w)]
            print(f"补充[{w:9s}]:", stats(wa))
        by_day = defaultdict(list)
        for r in adds:
            by_day[r["date"]].append(r)
        for d in sorted(by_day):
            vals = [r["net14"] for r in by_day[d] if r["net14"] is not None]
            avg = round(statistics.mean(vals), 1) if vals else None
            print(f"  {d}  n={len(by_day[d])}  avg_net14={avg}")

        print("\n===== 敏感度网格（补充信号，全窗口） =====")
        grid = []
        for P, Z, TH_LO, MTH, DROP in [
            (15, -1.0, 35, 40, -10), (15, -1.0, 35, 40, None),
            (15, -1.0, 30, 40, -10), (15, -0.8, 35, 40, -10),
            (12, -1.0, 35, 40, -10), (20, -1.0, 35, 40, -10),
            (15, -1.2, 35, 40, -10), (15, -1.0, 35, 45, -10),
            (15, -1.0, 35, 40, -15), (15, -1.0, 45, 40, -10),
        ]:
            rule = make_rule(P, Z, TH_LO, MTH, DROP)
            ga = variant_adds(recs, rule)
            s = stats(ga) or {}
            pre = [r for r in ga if in_window(r["date"], "pre123")]
            sp = stats(pre) or {}
            grid.append({
                "rule": f"P{P} Z{Z} TH{TH_LO}-55 MTH{MTH} DROP{DROP}",
                "n": s.get("n", 0), "win14%": s.get("win14%"), "avg14": s.get("avg14"),
                "win30%": s.get("win30%"), "avg30": s.get("avg30"), "pf14": s.get("pf14"),
                "pre123_n": sp.get("n", 0), "pre123_avg14": sp.get("avg14"), "pre123_win14%": sp.get("win14%"),
            })
        for g in grid:
            print(f"  {g['rule']:42s} n={g['n']:3d} 14d:{g['win14%']}%/{g['avg14']:+6.2f} 30d:{g['win30%']}%/{g['avg30']:+6.2f} pf14={g['pf14']} | pre123 n={g['pre123_n']} 14d:{g['pre123_win14%']}%/{g['pre123_avg14']:+6.2f}")

        if not args.no_save:
            out = {
                "args": vars(args), "baseline": stats(base),
                "windows": {w: stats([r for r in base if in_window(r["date"], w)]) for w in windows},
                "main_rule": "pct<=15 z<=-1 TH35-55 MTH>=40 drop21<=-10",
                "main_adds": stats(adds),
                "main_adds_windows": {w: stats([r for r in adds if in_window(r["date"], w)]) for w in windows},
                "main_adds_days": {
                    d: {"n": len(rs), "avg14": round(statistics.mean([r["net14"] for r in rs if r["net14"] is not None]), 1)}
                    for d, rs in sorted(by_day.items()) if any(r["net14"] is not None for r in rs)
                },
                "grid": grid,
            }
            with open(args.save, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1, allow_nan=False)
            print("\nsaved:", args.save)
    except Exception:
        traceback.print_exc()
        raise