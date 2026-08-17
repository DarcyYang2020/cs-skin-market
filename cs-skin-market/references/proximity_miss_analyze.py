# -*- coding: utf-8 -*-
"""距买点误导性探针——miss 归因分析（2026-08-18，预注册判据裁决）。

读取 data/_exp_cycle_proximity_miss.json，对 proximity_misses 做：
1. nearest 路径分布（6 条覆盖路径）
2. deduction_sources 语义分类（TH扣分/周期协调/守卫链/流动性/时期路由/融合例外/族源/空）
3. base 路径（低估区建仓）专项：th 分布 + 是否含 cycle_consolidation（判断是否 buy→降级）

输出 UTF-8 JSON 到 data/_exp_proximity_miss_analysis.json，避免 GBK 控制台乱码。
"""
import json
from collections import Counter, defaultdict

SRC = "data/_exp_cycle_proximity_miss.json"
OUT = "data/_exp_proximity_miss_analysis.json"

TH_SCORING = {
    "consolidation_phase", "high_consolidation", "distribution_cycle",
    "whale_pooling", "position_locked", "oversold_rebound_cap",
    "steepness_bottom_cap", "steepness_reversal_cap",
    "flat_strong_cap", "flat_improving_cap",
}
CYCLE_COORD = {
    "cycle_consolidation", "cycle_distribution", "cycle_accumulation_boost",
    "cycle_markup_boost", "cycle_accumulation_upgrade", "cycle_distribution_downgrade",
}
GUARD = {
    "market_weak_filter", "greedy_no_buy", "survive_too_low", "halfway_downgrade",
    "buy_cluster_dedup", "falling_knife_filter", "micro_th_weak", "bid_support_weak",
    "market_distribution_filter", "item_z_gate", "consecutive_buy", "supply_expansion_filter",
}
LIQUIDITY = {"liquidity_depth_gate", "liquidity_depth_missing"}
FUSION_EXC = {
    "oversold_buy_exception", "deep_dip_exemption",
    "cycle_accumulation_needs_market_drop", "market_relative_strength_upgrade",
}
FAMILY_SRC = {
    "deep_value_stable_market", "panic_resonance_upgrade", "supply_contraction_accumulation",
    "panic_easing_deep_bottom", "rise_accumulation", "rise_contract_accumulation",
    "rs_accum_strength", "ct_accum_strength", "volatile_accumulation",
    "second_wave_pullback", "xishou_mid_oversold",
}


def categorize(ds):
    """返回命中分类集合（一条 miss 可命中多类）。"""
    out = set()
    for s in ds or []:
        if s.startswith("period_route:"):
            out.add("route")
        elif s in TH_SCORING:
            out.add("th_scoring")
        elif s in CYCLE_COORD:
            out.add("cycle_coord")
        elif s in GUARD:
            out.add("guard")
        elif s in LIQUIDITY:
            out.add("liquidity")
        elif s in FUSION_EXC:
            out.add("fusion_exc")
        elif s in FAMILY_SRC:
            out.add("family_src")
        else:
            out.add("other:" + s)
    return out


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    misses = d.get("proximity_misses", [])

    # 1. nearest 分布
    nearest = Counter(m.get("nearest") for m in misses)

    # 2. 分类命中计数（多标签）
    cat_hit = Counter()
    # 每个 miss 的「唯一或首类」归因（优先级：guard > route > liquidity > cycle_coord > family_src > th_scoring > fusion_exc > empty）
    PRIORITY = ["guard", "route", "liquidity", "cycle_coord", "family_src", "th_scoring", "fusion_exc"]
    primary = Counter()
    for m in misses:
        cats = categorize(m.get("deduction_sources"))
        if not cats:
            cats = {"empty"}
        for c in cats:
            cat_hit[c] += 1
        chosen = "empty"
        for p in PRIORITY:
            if p in cats:
                chosen = p
                break
        if chosen == "empty" and cats != {"empty"}:
            # 只剩 other:xxx 或纯 family/th 之外
            chosen = sorted(cats)[0]
        primary[chosen] += 1

    # 3. base 路径专项
    base = [m for m in misses if m.get("nearest") == "低估区建仓"]
    base_th = [m["th"] for m in base if m.get("th") is not None]
    base_has_cycle_cons = sum(
        1 for m in base if "cycle_consolidation" in (m.get("deduction_sources") or []))
    base_has_family = sum(
        1 for m in base if any(s in FAMILY_SRC for s in (m.get("deduction_sources") or [])))
    base_has_guard = sum(
        1 for m in base if any(s in GUARD for s in (m.get("deduction_sources") or [])))
    base_th_only = sum(
        1 for m in base
        if categorize(m.get("deduction_sources")) == {"th_scoring"})

    # 4. 全库「纯守卫拦截」（deduction 含 guard 类，无论是否混其他）占比
    n_guard_any = sum(1 for m in misses if "guard" in categorize(m.get("deduction_sources")))
    n_route_any = sum(1 for m in misses if "route" in categorize(m.get("deduction_sources")))
    n_liquidity_any = sum(1 for m in misses if "liquidity" in categorize(m.get("deduction_sources")))
    n_cycle_any = sum(1 for m in misses if "cycle_coord" in categorize(m.get("deduction_sources")))
    n_th_any = sum(1 for m in misses if "th_scoring" in categorize(m.get("deduction_sources")))
    n_empty = sum(1 for m in misses if not (m.get("deduction_sources") or []))

    import statistics
    result = {
        "total_misses": len(misses),
        "nearest_dist": dict(nearest),
        "category_hit_multi_label": dict(cat_hit),
        "category_primary": dict(primary),
        "base_path": {
            "n": len(base),
            "th_min": min(base_th) if base_th else None,
            "th_max": max(base_th) if base_th else None,
            "th_mean": round(statistics.fmean(base_th), 2) if base_th else None,
            "n_with_cycle_consolidation": base_has_cycle_cons,
            "n_with_family_src": base_has_family,
            "n_with_guard": base_has_guard,
            "n_th_scoring_only": base_th_only,
        },
        "any_category": {
            "guard_any": n_guard_any,
            "route_any": n_route_any,
            "liquidity_any": n_liquidity_any,
            "cycle_coord_any": n_cycle_any,
            "th_scoring_any": n_th_any,
            "empty": n_empty,
        },
    }
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    print("total misses:", len(misses))


if __name__ == "__main__":
    main()
