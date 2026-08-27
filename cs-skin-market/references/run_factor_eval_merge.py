# -*- coding: utf-8 -*-
"""R1 最终评估卡合并修正脚本（②算法研究窗口）

输入：
  - data/_exp_factor_eval_2026-08-27.json（主脚本 v5：19 因子 + 组9 占位卡）
  - data/_exp_factor_eval_g9_2026-08-27.json（组9 升主评真实结果，DE 修订）
处理：
  1. 组9 占位卡（cov=1.712 待数据）→ g9 真实卡（bid/spread 完整主评）；
  2. verdict 修正：非供给类因子按判据 §3 增量 IC 判定——IC 强且稳定但增量 IC<0.02 → 「候选·无增量」
     （sentiment IC14=0.142 稳定但增量 IC=-0.0008，approx_sentiment 是 chg7/chg14 的函数=动量反转镜像）；
  3. mchg 三因子 IC14={"n":0} 注记：市场因子截面常数，截面 IC 不适用（条件因子 regime 分段评估）；
  4. 重算 summary，写回同一文件。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "data" / "_exp_factor_eval_2026-08-27.json"
G9 = ROOT / "data" / "_exp_factor_eval_g9_2026-08-27.json"

INC_IC_MIN = 0.02  # 判据 §3：增量 IC < 0.02 = 无增量
SUPPLY_IDS = ("sc7", "sc30", "s7_ratio")  # 供给类走条件 IC 线，不套增量判定

d = json.load(open(MAIN, encoding="utf-8"))
g9 = json.load(open(G9, encoding="utf-8"))

cards = d["cards"]
g9_cards = {c["id"]: c for c in g9["cards"]}

fixed = []
for c in cards:
    cid = c["id"]
    # 1) 组9 替换
    if cid in ("spread", "bid") and cid in g9_cards:
        gc = g9_cards[cid]
        gc["single_period_dep"] = c.get("single_period_dep")
        fixed.append(gc)
        continue
    # 2) verdict 增量 IC 修正（非供给类、非核心、IC 强且稳定、增量<0.02 -> 候选·无增量）
    if (cid not in SUPPLY_IDS and cid not in ("mchg7", "mchg21", "mchg30")
            and c["verdict"] == "候选"):
        inc = (c.get("inc_ic") or {}).get("mean")
        if inc is not None and abs(inc) < INC_IC_MIN:
            c["verdict"] = "候选·无增量"
            c["verdict_note"] = ("IC 有效且稳定，但增量 IC=%.4f < 0.02（判据 §3）——"
                                 "信息与核心因子冗余，无新自由度" % inc)
    # 3) mchg 注记
    if cid in ("mchg7", "mchg21", "mchg30"):
        c["verdict_note"] = ('市场因子同截面常数，截面 IC 数学上无定义（{"n":0} 为正确结果）；'
                             "条件因子按 regime 分段评估，不做单因子主判")
    fixed.append(c)

# 重算 summary
GROUPS = {
    "组1 pct/z（价值）": ["pct", "z"],
    "组3 chg（动量）": ["chg7", "chg30", "chg90"],
    "组4 vol（波动）": ["vol7", "vol30"],
    "组5/6 sc/s7_ratio（供给，条件IC）": ["sc7", "sc30", "s7_ratio"],
    "组7 趋势健康度5维": ["th_persistence", "th_steepness", "th_structure", "th_supply", "th_anomaly"],
    "组8 sentiment（情绪）": ["sentiment"],
    "组10 mchg（市场环境，regime）": ["mchg7", "mchg21", "mchg30"],
    "组9 spread/bid（盘口，升主评 DE）": ["spread", "bid"],
}
by_id = {c["id"]: c for c in fixed}
summary = {}
for g, fids in GROUPS.items():
    summary[g] = [by_id[f]["verdict"] for f in fids if f in by_id]

d["cards"] = fixed
d["summary"] = summary
d["meta"]["verdict_refinement"] = (
    "合并修正：组9 升主评卡替换；sentiment 按判据 §3 增量IC<0.02 降为「候选·无增量」；"
    "mchg 截面常数注记；supply 类走条件 IC 线")
json.dump(d, open(MAIN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("=== 最终评估卡 summary（21 因子）===")
for k, v in summary.items():
    print(f"  {k}: {v}")
print(f"\nsaved -> {MAIN}")
