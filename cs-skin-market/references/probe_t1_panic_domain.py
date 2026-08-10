# -*- coding: utf-8 -*-
"""T1 扩展：panic 族触发域一致性——强制近似情绪回放 vs 基线（真实贪婪）对比。

只读研究（monkey-patch 仅在进程内）：patch backtest_common.real_greedy_sentiment -> {}
使 build_market_context 全程用价格近似情绪；与基线 _exp_supply_chg8_cap_baseline.json
（真实贪婪尾部）对比窗口 2026-06-11~2026-08-05 内的信号集与 sent 域分布。
产物：data/_exp_t1_panic_domain.json
"""
import os
os.environ["CS_ENGINE_SUPPLY_ACCUM_CHG8_CAP"] = "0"  # 与基线同配置（无 chg8 门）
import sys, json
from datetime import datetime
from pathlib import Path
sys.path.insert(0, ".")
import importlib.util

_ARCHIVED = Path(__file__).resolve().parent / "scripts-archive" / "run_item_backtest.py"
spec = importlib.util.spec_from_file_location("rib", str(_ARCHIVED))
rib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rib)

from pipeline import backtest_common as bc
from pipeline.backtest_common import build_market_context
from pipeline import db

# 强制近似情绪
bc.real_greedy_sentiment = lambda start=None: {}

def pool_a_items():
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT i.id, i.name, MIN(p.date) first_date
           FROM items i JOIN price_history p ON p.item_id = i.id
           GROUP BY i.id HAVING first_date <= '2025-08-10'""").fetchall()
    conn.close()
    return {r["id"]: r["name"] for r in rows if r["name"] not in rib.EXCLUDED_ITEMS}

def main():
    START, END, WARMUP = "2026-06-11", "2026-08-05", 30
    rib.patch_sentiment(50.0)
    market_ctx = build_market_context("2026-05-01", end=END)  # 提前 40 天保证 warmup 期 ctx 可用
    items = pool_a_items()
    results = []
    for n_i, (iid, iname) in enumerate(sorted(items.items()), 1):
        r = rib.backtest_item(iid, iname, START, END, WARMUP, market_ctx, cost=0.02)
        results.append(r)
    sigs = [s for r in results for s in r.get("signals", []) if s.get("fwd14") is not None]
    out = {
        "mode": "approx_only (real_greedy_sentiment patched to {})",
        "window": [START, END], "n_signals": len(sigs),
        "signals": sigs,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    with open("data/_exp_t1_panic_domain.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    from collections import Counter
    def fam(s):
        l = s.get("action_label", "")
        if "\u6050\u614c" in l: return "panic"
        if "\u6df1\u503c" in l: return "deep"
        return "accum"
    print("approx-only signals:", len(sigs), "| by_fam:", dict(Counter(fam(s) for s in sigs)), flush=True)
    print("saved data/_exp_t1_panic_domain.json", flush=True)

if __name__ == "__main__":
    main()