# -*- coding: utf-8 -*-
"""P-2 预评估：价格带 × 在售量联合闸门（v2-T4 标准产物 317 信号上重跑 T3 交叉 + 消融）。

只读。对比首轮 T3（旧 332 信号）：chg8 门落地后高价×低在售桶是否仍差；
并做「剔除高价×低在售信号」的只读全引擎模拟（第一阶近似，去重链动态以正式 A/B 为准）。
产物：data/_exp_p2_hi_price_liq.json
"""
import json, sqlite3, statistics, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.backtest_methodology import signal_cluster_report

REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
OUT = ROOT / "data" / "_exp_p2_hi_price_liq.json"

def fam(s):
    l = s.get("action_label", "")
    if "\u6050\u614c" in l: return "panic"
    if "\u6df1\u503c" in l: return "deep"
    return "accum"

def stat(rows):
    n = len(rows)
    if n == 0:
        return {"n": 0, "win14": None, "avg14": None, "wavg14": None}
    w = sum(1 for r in rows if r["net14"] > 0)
    a = statistics.mean([r["net14"] for r in rows])
    wsum = sum(r.get("position_limit", 0.1) or 0.1 for r in rows)
    wa = sum(r["net14"] * (r.get("position_limit", 0.1) or 0.1) for r in rows) / wsum if wsum else 0
    return {"n": n, "win14": round(100.0 * w / n, 1), "avg14": round(a, 2), "wavg14": round(wa, 2)}

def cluster(rows):
    dates = [r["date"] for r in rows]
    rep = signal_cluster_report(dates, window=3)
    return {"events": rep["event_count"], "max_share": round(rep["max_cluster_share"], 3),
            "flagged": rep["flagged"]}

def main():
    d = json.load(open(REPLAY, encoding="utf-8"))
    sigs = d["signals"]
    conn = sqlite3.connect(ROOT / "data" / "market.db")
    conn.row_factory = sqlite3.Row
    name2id = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM items")}

    def in_sale(s):
        iid = name2id.get(s["name"])
        if not iid: return None
        r = conn.execute("SELECT in_sale_count FROM price_history WHERE item_id=? AND date=?", (iid, s["date"])).fetchone()
        return r["in_sale_count"] if r and r["in_sale_count"] is not None else None

    matched = sum(1 for s in sigs if s["name"] in name2id)
    out = {"source": "item_backtest_full_2025.json (v2-T4, 317 signals)", "n_signals": len(sigs),
           "matched": matched, "generated": "2026-08-10"}

    # 1) 价格带 × 低在售(<200) 交叉（与 T3 同口径）
    cross = {}
    for plo, phi, plab in ((0, 100, "<100"), (100, 1000, "100-1000"), (1000, 10**9, ">1000")):
        rows = []
        for s in sigs:
            ins = in_sale(s)
            if ins is None or ins >= 200: continue
            if not (plo <= s["entry_price"] < phi): continue
            s2 = dict(s); s2["_in_sale"] = ins
            rows.append(s2)
        st = stat(rows); st.update(cluster(rows))
        st["by_family"] = dict(Counter(fam(r) for r in rows))
        st["median_in_sale"] = round(statistics.median([r["_in_sale"] for r in rows]), 1) if rows else None
        cross[f"{plab} & in_sale<200"] = st
    out["price_cross_low_liq"] = cross

    # 2) 高价×低在售桶构成 + 日期分布（候选信号集）
    hi_rows = []
    for s in sigs:
        ins = in_sale(s)
        if ins is None or ins >= 200 or s["entry_price"] < 1000: continue
        s2 = dict(s); s2["_in_sale"] = ins
        hi_rows.append(s2)
    out["hi_candidate"] = {
        "n": len(hi_rows),
        "win14": stat(hi_rows)["win14"], "avg14": stat(hi_rows)["avg14"],
        "events": cluster(hi_rows)["events"],
        "by_month": dict(Counter(s["date"][:7] for s in hi_rows)),
        "by_family": dict(Counter(fam(s) for s in hi_rows)),
        "chg8_over3_share": round(100.0 * sum(1 for s in hi_rows if s.get("chg7") is not None and s["chg7"] > 3) / len(hi_rows), 1) if hi_rows else None,
    }

    # 3) 消融：候选信号与 chg8 门剔除集重叠度（chg8 门=8日动量>3%，回放 chg7 字段）
    chg8_removed = { (s["name"], s["date"]) for s in sigs if s.get("chg7") is not None and s["chg7"] > 3 and "\u4f9b\u7ed9\u6536\u7f29" in (s.get("action_label") or "") }
    hi_keys = { (s["name"], s["date"]) for s in hi_rows }
    overlap = chg8_removed & hi_keys
    out["ablation_with_chg8"] = {
        "hi_candidate_keys": len(hi_keys), "chg8_removed_keys": len(chg8_removed),
        "overlap": len(overlap), "overlap_share_of_hi": round(100.0 * len(overlap) / len(hi_keys), 1) if hi_keys else None,
        "overlap_share_of_chg8": round(100.0 * len(overlap) / len(chg8_removed), 1) if chg8_removed else None,
        "conclusion": "overlap<30% => 候选独立于 chg8 门，联合闸门有独立边际价值；>=30% => 高度重叠，优先合并/关闭" if hi_keys else "no data",
    }

    # 4) 只读模拟：剔除高价×低在售信号（不建模去重链，第一阶近似）
    drop = { (s["name"], s["date"]) for s in hi_rows }
    kept = [s for s in sigs if (s["name"], s["date"]) not in drop]
    base = stat(sigs); base.update(cluster(sigs))
    vari = stat(kept); vari.update(cluster(kept))
    out["sim_drop_hi_low_liq"] = {"base": base, "variant": vari,
        "delta": {"win14_pp": round(vari["win14"] - base["win14"], 1), "avg14": round(vari["avg14"] - base["avg14"], 2) if base["avg14"] else None}}
    conn.close()

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()