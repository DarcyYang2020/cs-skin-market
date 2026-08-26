# -*- coding: utf-8 -*-
"""R2 因子注册表 md 视图生成器（②算法研究窗口）
读 data/factor_registry.json → 渲染 references/factor-registry.md（人工视图，可重复生成）。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "data" / "factor_registry.json"
VIEW = ROOT / "references" / "factor-registry.md"

doc = json.load(open(REG, encoding="utf-8"))

lines = [
    "# 因子注册表（factor_registry 人工视图）",
    "",
    f"- **机器事实源**：`data/factor_registry.json`（schema v{doc['schema_version']}，{doc['generated']}）",
    f"- **来源**：{doc['source']}",
    f"- **数量**：{doc['count']} 因子",
    "- **说明**：registry 状态 = 新管线（预注册→评估→四关→③审计）准入状态；引擎现状因子为历史累积（v2-T13 规则融合，未逐个走新管线），其取舍由 R3 策略隔离评估裁决——状态为证伪/存档 ≠ 引擎立即移除",
    "",
    "| id | name | category | role | status | in_engine | IC14 | 同号月 | 增量IC | 覆盖率 | 备注 |",
    "|---|---|---|---|---|---|---|---|---|---|---|",
]
for f in doc["factors"]:
    q = f.get("quality") or {}
    ic = (q.get("IC14") or {}).get("mean")
    roll = (q.get("rolling_stability") or {}).get("same_sign_ratio")
    inc = (q.get("inc_ic") or {}).get("mean")
    cov = q.get("coverage")
    note = f.get("cs_note") or ""
    if len(note) > 40:
        note = note[:40] + "…"
    lines.append(
        f"| {f['id']} | {f['name']} | {f['category']} | {f['role']} | **{f['status']}** | "
        f"{f.get('in_engine') or '—'} | {ic if ic is not None else '—'} | "
        f"{roll if roll is not None else '—'} | {inc if inc is not None else '—'} | "
        f"{cov if cov is not None else '—'} | {note} |"
    )

lines += [
    "",
    "## 状态分布",
    "",
]
from collections import Counter
cnt = Counter(f["status"] for f in doc["factors"])
for s, n in sorted(cnt.items()):
    lines.append(f"- **{s}**：{n}")

open(VIEW, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(f"view -> {VIEW} ({doc['count']} rows)")
