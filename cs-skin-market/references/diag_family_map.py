# -*- coding: utf-8 -*-
"""族划分静态审计：产出「族映射全表」（引擎11族 × taxonomy × signal_guidance 三口径对照）。

只读，落盘 data/_exp_family_map_2026-08-19.json（原始产物，交③审计独立判）。
不写生产库、不改引擎/展示代码。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import item_analysis as ia  # noqa: E402
from pipeline.config import SIGNAL_FAMILY_TAXONOMY  # noqa: E402

# signal_guidance 的映射规则（batch_scan.py:15-54，按关键字顺序）
SIGNAL_GUIDANCE_RULES = [
    ("恐慌", "panic", "恐慌共振"),
    ("超跌", "oversold", "超跌反弹"),
    ("长持", "longhold", "长持结构"),
    ("吸筹", "accumulate", "周期吸筹"),
    ("__else__", "base", "低位低估"),
]

# taxonomy 细族 → 展示键（fine_to_display）
TAXO_FINE_TO_DISPLAY = SIGNAL_FAMILY_TAXONOMY["fine_to_display"]
TAXO_FINE_ORDER = SIGNAL_FAMILY_TAXONOMY["fine_order"]


def guidance_for(label: str):
    """按 signal_guidance 关键字规则归类一个 action_label。"""
    for kw, st, tl in SIGNAL_GUIDANCE_RULES:
        if kw == "__else__":
            return st, tl
        if kw in label:
            return st, tl


def taxo_fine_for(label: str):
    """按 taxonomy assign_fine_family 归类（fine_keywords 关键字匹配，兜底 base）。"""
    for fk in TAXO_FINE_ORDER:
        kw = SIGNAL_FAMILY_TAXONOMY["fine_keywords"].get(fk)
        if kw and kw in label:
            return fk
    return "base"


def taxo_display_for(label: str):
    return TAXO_FINE_TO_DISPLAY[taxo_fine_for(label)]


engine_families = []
for fam in ia.SIGNAL_FAMILIES:
    label = fam.label
    engine_families.append({
        "key": fam.key,
        "label": label,
        "priority": fam.priority,
        "limit": fam.limit,
        "signal_guidance": guidance_for(label)[0],
        "taxonomy_fine": taxo_fine_for(label),
        "taxonomy_display": taxo_display_for(label),
    })

# taxonomy 细族 vs 引擎族对齐
taxo_vs_engine = {}
for fk in TAXO_FINE_ORDER:
    eng = [f["key"] for f in engine_families if f["taxonomy_fine"] == fk]
    taxo_vs_engine[fk] = {
        "taxonomy_label": SIGNAL_FAMILY_TAXONOMY["fine_labels"].get(fk),
        "taxonomy_display": TAXO_FINE_TO_DISPLAY.get(fk),
        "engine_keys": eng,
        "note": "" if eng else "taxonomy 有此细族、引擎无独立 SignalFamily",
    }

# 189 信号三口径实际分布
replay = json.load(open(ROOT / "data" / "_exp_cycle_replay_period_route.json", encoding="utf-8"))
sigs = replay["signals"]
from collections import Counter
by_label = Counter(s["action_label"] for s in sigs)

# 冲突清单
conflicts = [
    {"point": "deep_value", "engine": "有族", "taxonomy": "独立展示键 deep_value",
     "signal_guidance": "base（'深值' 不含恐慌/超跌/长持/吸筹）"},
    {"point": "deep_dip", "engine": "无独立族（supply_accum 的 P0-7b 例外派生）",
     "taxonomy": "细族 deep_dip→accumulate", "signal_guidance": "base（'深度回调低吸' 不含'吸筹'两字）"},
    {"point": "rise_accum/rise_contract/volatile_accum", "engine": "有族",
     "taxonomy": "无映射（assign_fine_family 兜底 base）", "signal_guidance": "accumulate（含'吸筹'）"},
    {"point": "rs_accum/ct_accum", "engine": "有族", "taxonomy": "无映射（兜底 base）",
     "signal_guidance": "longhold（含'长持'）"},
    {"point": "second_wave", "engine": "有族", "taxonomy": "无映射（兜底 base）",
     "signal_guidance": "base（else）"},
    {"point": "xishou_mid", "engine": "有族", "taxonomy": "无映射（兜底 base）",
     "signal_guidance": "oversold（含'超跌'）"},
    {"point": "弱市抗跌（历史遗留）", "engine": "无此族（旧引擎残留 label）",
     "taxonomy": "无", "signal_guidance": "base（else）"},
]

out = {
    "meta": {"date": "2026-08-19", "role": "algorithm-research (read-only static audit)",
             "n_engine_families": len(engine_families),
             "taxonomy_fine_order": TAXO_FINE_ORDER,
             "taxonomy_display_keys": SIGNAL_FAMILY_TAXONOMY["display_keys"],
             "signal_guidance_rules": SIGNAL_GUIDANCE_RULES},
    "engine_families": engine_families,
    "taxonomy_vs_engine": taxo_vs_engine,
    "signal_189_by_action_label": dict(by_label.most_common()),
    "conflicts": conflicts,
}
json.dump(out, open(ROOT / "data" / "_exp_family_map_2026-08-19.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("saved data/_exp_family_map_2026-08-19.json")
print(json.dumps(out, ensure_ascii=False, indent=1))
