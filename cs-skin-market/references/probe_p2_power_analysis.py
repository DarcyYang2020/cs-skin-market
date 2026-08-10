# -*- coding: utf-8 -*-
"""P-2 功效分析：高价×低在售候选的样本量需求（只读，不依赖采集网络）。

1) 断档精确边界：price_history.in_sale_count 各月非零计数（2026-02~04 污染范围复核）
2) 干净段（2026-05-01 起）信号分桶：价格带 × 在售量，n/win14/avg14/事件
3) 两比例检验功效：区分「高价×低在售」与对照桶胜率差异所需每组样本量（近似公式，单侧 α=0.05, power=0.8）
4) 积累速率：2026-05 起月均信号数 → 达到目标样本所需月数

产物：data/_exp_p2_power_analysis.json
"""
import json, sqlite3, statistics, math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
OUT = ROOT / "data" / "_exp_p2_power_analysis.json"
CLEAN_START = "2026-05-01"  # 在售量恢复连续采集起点

def z_sample_size(p1, p2, alpha=0.05, power=0.8):
    """两比例检验（近似公式，单侧）。p1=候选桶胜率, p2=对照桶胜率。返回每组所需样本量。"""
    z_a = 1.6449  # 单侧 0.05
    z_b = 0.8416  # power 0.8
    d = abs(p1 - p2)
    if d <= 1e-9:
        return None
    n = ((z_a + z_b) ** 2) * (p1 * (1 - p1) + p2 * (1 - p2)) / (d ** 2)
    return math.ceil(n)

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

    # 1) 断档精确边界：按月统计有在售量记录的天数与全零天数
    month_stats = {}
    for r in conn.execute("""
        SELECT substr(date,1,7) ym, COUNT(*) days, SUM(CASE WHEN in_sale_count>0 THEN 1 ELSE 0 END) nonzero
        FROM price_history WHERE date>='2026-01-01' GROUP BY ym ORDER BY ym"""):
        month_stats[r["ym"]] = {"days": r["days"], "nonzero_days": r["nonzero"] or 0,
                                "nonzero_share": round(100.0 * (r["nonzero"] or 0) / r["days"], 1)}

    # 2) 干净段信号 + 在售量
    clean = []
    for s in sigs:
        if s["date"] < CLEAN_START: continue
        ins = in_sale(s)
        s2 = dict(s); s2["_in_sale"] = ins
        clean.append(s2)

    def stat(rows):
        n = len(rows)
        if n == 0:
            return {"n": 0, "win14": None, "avg14": None, "events": None}
        w = sum(1 for r in rows if r["net14"] > 0)
        ev = len(set(r["date"] for r in rows))
        return {"n": n, "win14": round(100.0 * w / n, 1),
                "avg14": round(statistics.mean([r["net14"] for r in rows]), 2),
                "events": ev}

    def fam(s):
        l = s.get("action_label", "")
        if "\u6050\u614c" in l: return "panic"
        if "\u6df1\u503c" in l: return "deep"
        return "accum"

    # 分桶（干净段）：价格带 × 在售量档
    buckets = {}
    bands = ((0, 100, "<100"), (100, 1000, "100-1000"), (1000, 10**9, ">=1000"))
    for plo, phi, plab in bands:
        for slo, shi, slab in ((1, 199, "1-199"), (200, 999, "200-999"), (1000, 10**9, ">=1000")):
            key = f"{plab} x in_sale {slab}"
            rows = [s for s in clean if s["_in_sale"] is not None and slo <= s["_in_sale"] <= shi and plo <= s["entry_price"] < phi]
            st = stat(rows)
            st["by_family"] = dict(Counter(fam(r) for r in rows))
            st["median_in_sale"] = round(statistics.median([r["_in_sale"] for r in rows]), 1) if rows else None
            buckets[key] = st

    # 对照口径：高价(>=1000) 按在售量分档（干净的）
    hi_liq = [s for s in clean if s["_in_sale"] is not None and s["_in_sale"] < 200 and s["entry_price"] >= 1000]
    hi_ok = [s for s in clean if s["_in_sale"] is not None and s["_in_sale"] >= 200 and s["entry_price"] >= 1000]
    hi_all = [s for s in clean if s["_in_sale"] is not None and s["entry_price"] >= 1000]

    # 3) 功效估算
    scenarios = {}
    def scen(name, p1, p2, n1, n2):
        need = z_sample_size(p1, p2)
        scenarios[name] = {
            "p1_candidate": p1, "p2_control": p2,
            "diff_pp": round(100 * abs(p1 - p2), 1),
            "n_per_group_needed": need,
            "current_n1": n1, "current_n2": n2,
            "feasible": (need is not None and n1 >= need and n2 >= need),
        }
    scen("T3观察差 27pp", 0.537, 0.806, len(hi_liq), len(hi_ok))
    scen("保守差 11pp", 0.60, 0.71, len(hi_liq), len(hi_ok))
    scen("接近基线 1pp", 0.70, 0.71, len(hi_liq), len(hi_ok))

    # 4) 积累速率（干净段月均信号数，按高价桶口径）
    months = sorted(set(s["date"][:7] for s in clean))
    per_month = {m: sum(1 for s in clean if s["date"][:7] == m) for m in months}
    n_months = max(1, len(months))
    avg_month = len(clean) / n_months
    hi_liq_month = len(hi_liq) / n_months
    need_27 = scenarios["T3观察差 27pp"]["n_per_group_needed"]
    months_for_27 = math.ceil(need_27 / hi_liq_month) if hi_liq_month > 0 and need_27 else None

    out = {
        "generated": "2026-08-10",
        "clean_start": CLEAN_START,
        "source": "item_backtest_full_2025.json (v2-T4 317) + price_history 联查在售量",
        "n_signals_total": len(sigs), "n_signals_clean": len(clean),
        "month_gap_analysis": month_stats,
        "clean_buckets": buckets,
        "hi_price_control": {
            "hi_all": stat(hi_all), "hi_liq_lt200": stat(hi_liq), "hi_liq_ge200": stat(hi_ok)},
        "power_analysis": scenarios,
        "accumulation_rate": {
            "months": per_month, "n_months": n_months,
            "avg_signals_per_month": round(avg_month, 1),
            "avg_hi_liq_per_month": round(hi_liq_month, 2),
            "months_to_reach_n35": months_for_27,
        },
        "conclusion": (
            "若真实胜率差≈27pp：每组仅需 ~35 条，按当前速率约 X 个月可积累；"
            "若真实差≈11pp：每组需 ~228 条，依赖扩池后样本速率；"
            "若真实差≈1pp：不可行（>2.5 万条/组）。恢复扩池前可用 2026-05 起干净段先做描述性监测，正式三件套待样本达标。"
        ).replace("X", str(months_for_27) if months_for_27 else "N/A"),
    }
    conn.close()
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()