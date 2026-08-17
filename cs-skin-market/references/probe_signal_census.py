# -*- coding: utf-8 -*-
"""官方 v2-T13 回放产物信号普查（2026-08-17，只读）：
族分布 / signal_type 分布 / 时期分布 / Top 品。
输出 data/_exp_signal_census.json。
"""
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.signal_tracking import family_key_for_label  # noqa: E402

REPLAY = ROOT / "data" / "_exp_cycle_replay_2026.json"
OUT = ROOT / "data" / "_exp_signal_census.json"

FAM_LABEL = {
    "panic_resonance": "恐慌共振", "panic_easing": "恐慌退潮", "deep_value": "深值企稳",
    "supply_accum": "供给收缩吸筹", "rise_accum": "吸筹型上涨(买涨腿)", "rise_contract": "深收缩慢涨",
    "volatile_accum": "震荡吸筹", "second_wave": "二波回调", "base": "基础融合(低位低估)",
    "oversold": "超跌反弹",
}


def main():
    d = json.load(open(REPLAY, encoding="utf-8"))
    sigs = d["signals"]
    fam = Counter(family_key_for_label(s.get("action_label") or "") for s in sigs)
    stype = Counter(s.get("signal_type") for s in sigs)
    items = Counter(s.get("name") for s in sigs)
    by_year = Counter(s["date"][:4] for s in sigs)

    print("官方 v2-T13 回放产物：%d 信号（引擎=%s，窗口=%s~%s，池=%s）" % (
        len(sigs), d["args"].get("engine"), d["args"].get("start"), d["args"].get("end"),
        d["args"].get("pool")))
    print("\n== 信号族分布 ==")
    for k, n in fam.most_common():
        print("  %-16s %-18s n=%d" % (k, FAM_LABEL.get(k, k), n))
    print("\n== signal_type 分布（回放器口径）==")
    for k, n in stype.most_common():
        print("  %-12s n=%d" % (k, n))
    print("\n== 年份分布 ==")
    for k in sorted(by_year):
        print("  %s: %d" % (k, by_year[k]))
    print("\n== Top 12 信号品 ==")
    for name, n in items.most_common(12):
        print("  %-40s n=%d" % (name, n))
    out = {"n": len(sigs), "args": d["args"], "family": dict(fam), "signal_type": dict(stype),
           "by_year": dict(by_year), "top_items": items.most_common(20)}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
