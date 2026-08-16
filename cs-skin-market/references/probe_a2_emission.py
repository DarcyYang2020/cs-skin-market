# -*- coding: utf-8 -*-
"""A2 第五件套驱动：对既有候选族回放产物跑发射侧检验（2026-08-16）。

- xishou_mid：_exp_xishou_mid_replay.json（200 信号，已提交）vs v2-T10 基线产物
- rise_accum：_exp_rise_accum_replay.json（202 信号，重放生成中/已生成）vs v2-T10 基线产物
输出：data/_exp_a2_emission.json；缺失的产物跳过并提示。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "references"))

from a2_emission import analyze, print_report  # noqa: E402

BASE = ROOT / "data" / "_exp_cycle_replay_2026.json"
OUT = ROOT / "data" / "_exp_a2_emission.json"


def main():
    cases = [
        ("xishou_mid", ROOT / "data" / "_exp_xishou_mid_replay.json", "惜售中段"),
        ("rise_accum", ROOT / "data" / "_exp_rise_accum_replay.json", "吸筹型上涨"),
    ]
    results = {}
    for name, path, kw in cases:
        if not path.exists():
            print(f"skip {name}: {path.name} 不存在（重放产物未就绪）", flush=True)
            continue
        res = analyze(str(path), str(BASE), kw, name)
        print_report(res)
        results[name] = res
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
