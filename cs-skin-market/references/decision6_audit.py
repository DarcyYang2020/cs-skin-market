# -*- coding: utf-8 -*-
"""DECISION-6 翻转审计（只读，不重放、不改引擎参数）。

对比对象：
- old = data/_exp_guard_coverage.json（DECISION-4 对齐 290，旧读取口径）
- new = data/_exp_guard_coverage_decision6.json（DECISION-6 新读取口径）

同时读当前生产库活跃池，统计 NULL/断档与真实 0 两类计数。
输出 data/_exp_decision6_audit.json。
"""
import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAP = ("2026-02-01", "2026-04-30")


def missing(raw, date):
    return raw is None or GAP[0] <= (date or "")[:10] <= GAP[1]


def load(path):
    with open(ROOT / path, encoding="utf-8") as f:
        return json.load(f)


def main():
    old = load("data/_exp_guard_coverage.json")
    new = load("data/_exp_guard_coverage_decision6.json")
    old_by = {(s["name"], s["date"]): s for s in old["signals"]}
    transitions = Counter()
    replay_flips = []
    for s in new["signals"]:
        key = (s["name"], s["date"])
        old_a = old_by.get(key, {}).get("aligned_action")
        new_a = s.get("aligned_action")
        transitions[(old_a, new_a)] += 1
        if old_a in ("buy", "oversold_buy") and new_a not in ("buy", "oversold_buy") and s.get("supply_depth_missing"):
            replay_flips.append({
                "name": s["name"], "date": s["date"],
                "old": old_a, "new": new_a,
                "supply_depth": s.get("supply_depth"),
            })

    conn = sqlite3.connect(ROOT / "data" / "market.db")
    conn.row_factory = sqlite3.Row
    items = conn.execute(
        """SELECT id, name, notes, in_watchlist, holding FROM items
           WHERE good_id>0 AND (in_watchlist=1 OR holding=1 OR notes IS NULL
             OR (notes NOT LIKE '%存世量过低%' AND notes NOT LIKE '%活跃池淘汰%'))"""
    ).fetchall()
    latest = conn.execute(
        """SELECT p.item_id, p.date, p.in_sale_count
           FROM price_history p
           JOIN (SELECT item_id, MAX(date) d FROM price_history GROUP BY item_id) x
             ON x.item_id = p.item_id AND x.d = p.date"""
    ).fetchall()
    by_id = {r["item_id"]: r for r in latest}
    production_missing = []
    production_zero = []
    for it in items:
        r = by_id.get(it["id"])
        if r is None:
            continue
        if missing(r["in_sale_count"], r["date"]):
            production_missing.append({"name": it["name"], "date": r["date"], "raw": r["in_sale_count"]})
        elif r["in_sale_count"] == 0:
            production_zero.append({"name": it["name"], "date": r["date"]})
    conn.close()

    out = {
        "generated": "2026-08-14",
        "replay": {
            "old_aligned_n": len([s for s in old["signals"] if s.get("aligned_action") in ("buy", "oversold_buy")]),
            "new_aligned_n": len([s for s in new["signals"] if s.get("aligned_action") in ("buy", "oversold_buy")]),
            "supply_missing_rows": sum(1 for s in new["signals"] if s.get("supply_depth_missing")),
            "supply_missing_gap_rows": sum(1 for s in new["signals"] if s.get("supply_depth_missing") and GAP[0] <= (s.get("date") or "")[:10] <= GAP[1]),
            "supply_missing_null_rows": sum(1 for s in new["signals"] if s.get("supply_depth_missing") and not (GAP[0] <= (s.get("date") or "")[:10] <= GAP[1])),
            "buy_flips_due_missing": len(replay_flips),
            "transitions": {f"{a}->{b}": n for (a, b), n in sorted(transitions.items())},
            "flip_examples": replay_flips[:20],
        },
        "production": {
            "active_candidates": len(items),
            "missing_latest": len(production_missing),
            "true_zero_latest": len(production_zero),
            "missing_buy_flip_proxy": 0,
            "missing_examples": production_missing[:20],
            "true_zero_examples": production_zero[:20],
        },
    }
    with open(ROOT / "data" / "_exp_decision6_audit.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
