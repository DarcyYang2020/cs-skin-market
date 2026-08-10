# -*- coding: utf-8 -*-
"""第一性原理审计只读探针（2026-08-10 首轮执行，配套 references/first-principles-test-plan.md）。

只读：不改引擎、不写业务库。产物：
  data/_exp_cost_ladder.json       T2B 成本阶梯（fwd14 毛利重算 win/avg by cost）
  data/_exp_liq_bucket.json        T3  回放信号 × 信号日在售量分桶
  data/_exp_accum_chg7_bucket.json T4  吸筹族按信号日价格7日变化分桶（含±3天事件聚类）
  data/_exp_whale_cross_avail.json T6  大户集中度快照可用性检查
"""
import json, statistics, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.backtest_methodology import signal_cluster_report

REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
OUT = ROOT / "data"

def load_replay():
    return json.load(open(REPLAY, encoding="utf-8"))

def fam(s):
    l = s.get("action_label", "")
    if "恐慌" in l: return "panic"
    if "深值" in l: return "deep"
    return "accum"

def stat(rows, key="net14"):
    n = len(rows)
    if n == 0:
        return {"n": 0, "win14": None, "avg14": None}
    w = sum(1 for r in rows if r[key] > 0)
    a = statistics.mean([r[key] for r in rows])
    wsum = sum(r.get("position_limit", 0.1) or 0.1 for r in rows)
    wa = sum(r[key] * (r.get("position_limit", 0.1) or 0.1) for r in rows) / wsum if wsum else 0
    return {"n": n, "win14": round(100.0 * w / n, 1), "avg14": round(a, 2), "wavg14": round(wa, 2)}

def cluster_stats(rows):
    dates = [r["date"] for r in rows]
    rep = signal_cluster_report(dates, window=3)
    return {"events": rep["event_count"], "max_share": rep["max_cluster_share"],
            "flagged": rep["flagged"], "warnings": rep["warnings"]}

def main():
    d = load_replay()
    sigs = d["signals"]
    out = {"source": "item_backtest_full_2025.json", "generated": "2026-08-10", "args": {}}

    # ---------- T2B 成本阶梯 ----------
    costs = [0, 1, 2, 3, 5]  # 百分数口径（fwd14 单位为 %）
    ladder = {}
    fwd = [s["fwd14"] for s in sigs]
    for c in costs:
        n = len(fwd)
        w = sum(1 for x in fwd if x > c)
        avg = statistics.mean([x - c for x in fwd])
        wsum = sum(s.get("position_limit", 0.1) or 0.1 for s in sigs)
        wavg = sum((s["fwd14"] - c) * (s.get("position_limit", 0.1) or 0.1) for s in sigs) / wsum
        ladder[str(c)] = {"n": n, "win14": round(100.0 * w / n, 1), "avg14": round(avg, 2), "wavg14": round(wavg, 2)}
    ladder["break_even_cost_pct"] = round(statistics.mean(fwd), 2)  # 毛利均值 = 盈亏平衡成本(%)
    by_fam = {}
    for k in ("panic", "deep", "accum"):
        rows = [s for s in sigs if fam(s) == k]
        f2 = [s["fwd14"] for s in rows]
        by_fam[k] = {"n": len(rows),
                     "break_even_cost_pct": round(statistics.mean(f2), 2) if f2 else None,
                     "win_at_2": round(100.0 * sum(1 for x in f2 if x > 2) / len(f2), 1) if f2 else None}
    out["T2B_cost_ladder"] = ladder
    out["T2B_by_family"] = by_fam
    out["T2B_verdict"] = ("3% 成本下 avg14>0 => 2% 假设偏保守可维持" if ladder["3"]["avg14"] > 0
                          else "3% 成本下 avg14<=0 => 需 F-4 分层成本")

    # ---------- T3 流动性分桶 ----------
    import sqlite3
    conn = sqlite3.connect(ROOT / "data" / "market.db")
    conn.row_factory = sqlite3.Row
    name2id = {}
    for r in conn.execute("SELECT id, name FROM items"):
        name2id[r["name"]] = r["id"]
    dup = len(sigs) - sum(1 for s in sigs if s["name"] in name2id)
    liq = {}
    for lo, hi, lab in ((15, 50, "15-50"), (50, 200, "50-200"), (200, 500, "200-500"), (500, 10**9, ">500")):
        rows = []
        for s in sigs:
            iid = name2id.get(s["name"])
            if not iid: continue
            r = conn.execute(
                "SELECT in_sale_count FROM price_history WHERE item_id=? AND date=?",
                (iid, s["date"])).fetchone()
            ins = (r["in_sale_count"] if r and r["in_sale_count"] is not None else None)
            if ins is None or ins < lo or ins >= hi: continue
            s2 = dict(s); s2["_in_sale"] = ins
            rows.append(s2)
        st = stat(rows); st.update(cluster_stats(rows)); st["median_in_sale"] = round(statistics.median([r["_in_sale"] for r in rows]), 1) if rows else None
        liq[lab] = st
    # 价格带 × 在售 交叉（仅 15-200 低流动区）
    cross = {}
    for plo, phi, plab in ((0, 100, "<100"), (100, 1000, "100-1000"), (1000, 10**9, ">1000")):
        rows = []
        for s in sigs:
            iid = name2id.get(s["name"])
            if not iid: continue
            r = conn.execute(
                "SELECT in_sale_count FROM price_history WHERE item_id=? AND date=?",
                (iid, s["date"])).fetchone()
            ins = (r["in_sale_count"] if r and r["in_sale_count"] is not None else None)
            if ins is None or ins >= 200: continue
            if not (plo <= s["entry_price"] < phi): continue
            rows.append(s)
        st = stat(rows); st.update(cluster_stats(rows))
        cross[f"{plab} & in_sale<200"] = st
    # 高价低流动构成（entry>=1000 且 in_sale<200）
    hi_comp = []
    for s in sigs:
        iid = name2id.get(s["name"])
        if not iid or s["entry_price"] < 1000: continue
        r = conn.execute("SELECT in_sale_count FROM price_history WHERE item_id=? AND date=?", (iid, s["date"])).fetchone()
        ins = (r["in_sale_count"] if r and r["in_sale_count"] is not None else None)
        if ins is not None and ins < 200: hi_comp.append(s["action_label"])
    conn.close()
    out["T3_liq_bucket"] = liq
    out["T3_comp_hi_liq_low"] = dict(Counter(hi_comp))
    out["T3_price_cross"] = cross
    out["T3_unmatched"] = dup
    out["T3_verdict"] = "低桶(15-50) 相对 >500 桶 win 差>=10pp 且 n>=30 且 events>=3 => 候选分层下限（当前见数据）"

    # ---------- T4 吸筹族 chg7 分桶（含事件聚类） ----------
    acc = [s for s in sigs if fam(s) == "accum"]
    buckets = {"<-3%": lambda c: c < -3, "-3~0%": lambda c: -3 <= c < 0,
               "0~3%": lambda c: 0 <= c < 3, ">3%": lambda c: c >= 3}
    t4 = {}
    for lab, pred in buckets.items():
        rows = [s for s in acc if s.get("chg7") is not None and pred(s["chg7"])]
        st = stat(rows); st.update(cluster_stats(rows)); st["median_chg7"] = round(statistics.median([s["chg7"] for s in rows]), 2) if rows else None
        t4[lab] = st
    base = stat(acc); base.update(cluster_stats(acc))
    t4["_all_accum"] = base
    over3 = [s for s in acc if s.get("chg7") is not None and s["chg7"] >= 3]
    t4["_comp_over3"] = dict(Counter(s["action_label"] for s in over3))
    t4["_comp_over3_date_range"] = [min(s["date"] for s in over3), max(s["date"] for s in over3)]
    t4["_comp_over3_supply30"] = dict(Counter("<-10" if (s.get("supply_change_30d") or 0) < -10 else ("-10~-5" if (s.get("supply_change_30d") or 0) < -5 else ("-5~0" if (s.get("supply_change_30d") or 0) < 0 else ">=0")) for s in over3))
    worst = t4[">3%"]
    t4["_verdict"] = ("候选成立（>3% 桶 win<50% 且 n>=25 且 events>=3）→ 进入三件套 A/B"
                      if worst["n"] >= 25 and worst["events"] >= 3 and (worst["win14"] or 100) < 50
                      else "候选不成立/样本不足")
    out["T4_accum_chg7_bucket"] = t4

    # ---------- T6 大户集中度可用性 ----------
    conn = sqlite3.connect(ROOT / "data" / "market.db")
    dates = [r[0] for r in conn.execute("SELECT DISTINCT date FROM monitor_rank_snapshot ORDER BY date")]
    per_date = dict(conn.execute("SELECT date, COUNT(*) FROM monitor_rank_snapshot GROUP BY date ORDER BY date").fetchall())
    conn.close()
    out["T6_avail"] = {"snapshot_dates": dates, "rows_per_date": per_date,
                       "note": "周度快照 5 期；交叉验证需 >=12 周（约 2026-11），当前仅可用性检查"}

    json.dump(out, open(OUT / "_exp_first_principles_probes.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 分文件归档（按方案命名）
    json.dump({"T2B": out["T2B_cost_ladder"], "by_family": out["T2B_by_family"], "verdict": out["T2B_verdict"]},
              open(OUT / "_exp_cost_ladder.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"T3": out["T3_liq_bucket"], "cross": out["T3_price_cross"], "unmatched": dup, "verdict": out["T3_verdict"]},
              open(OUT / "_exp_liq_bucket.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"T4": out["T4_accum_chg7_bucket"], "verdict": out["T4_accum_chg7_bucket"]["_verdict"]},
              open(OUT / "_exp_accum_chg7_bucket.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(out["T6_avail"], open(OUT / "_exp_whale_cross_avail.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("=== T2B 成本阶梯（全 332 信号，fwd14 毛利口径）===")
    for c, v in ladder.items():
        if isinstance(v, dict): print(f"  cost {c:>4s}: win14={v['win14']}% avg14={v['avg14']:+.2f} wavg14={v['wavg14']:+.2f}")
    print("  break_even:", ladder["break_even_cost_pct"], "| verdict:", out["T2B_verdict"])
    print("  by_family break_even:", {k: v["break_even_cost_pct"] for k, v in by_fam.items()})
    print()
    print("=== T3 在售量分桶（net14）===")
    for k, v in liq.items():
        print(f"  in_sale {k:8s}: {v}")
    print("  price cross:", {k: (v["n"], v["win14"], v["avg14"], v["events"]) for k, v in cross.items()})
    print("  unmatched:", dup)
    print()
    print("=== T4 吸筹族 chg7 分桶（net14）===")
    for k in ("<-3%", "-3~0%", "0~3%", ">3%", "_all_accum"):
        v = t4[k]
        print(f"  {k:10s}: n={v['n']} win={v['win14']} avg={v['avg14']:+.2f} wavg={v['wavg14']:+.2f} events={v['events']} maxShare={v['max_share']:.2f} flagged={v['flagged']}")
    print("  verdict:", t4["_verdict"])
    print()
    print("=== T6 大户快照可用性 ===")
    print("  dates:", dates, "rows:", per_date)

if __name__ == "__main__":
    main()
