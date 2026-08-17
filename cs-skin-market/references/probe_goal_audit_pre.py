# -*- coding: utf-8 -*-
"""只读审计：目标×理念核对前置检查（2026-08-17）。

1) fixture 独特性品在官方 189 信号的覆盖（发声通道现状）；
2) 族特征卡是否含事件窗分层（X-8 统计口径要求）；
3) 模拟盘 20 笔判据实现状态。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ("M4A4 | 合纵 (崭新出厂)", "AK-47 | 抽象派 1337 (崭新出厂)",
           "FN57 | 霸意大名 (崭新出厂)", "格洛克 18 型 | 异星世界 (崭新出厂)")

d = json.load(open(ROOT / "data" / "_exp_cycle_replay_2026.json", encoding="utf-8"))
sig = d["signals"]
print("== 官方 189 信号里 fixture 品覆盖 ==")
for name in FIXTURE:
    rows = [s for s in sig if s["name"] == name]
    print("  %-40s n=%d %s" % (name, len(rows), sorted({s["action_label"] for s in rows})))

cards = json.load(open(ROOT / "data" / "family_feature_cards.json", encoding="utf-8"))
k0 = next(iter(cards["families"]))
print("\n== 族特征卡结构（顶层键）==", sorted(cards["families"][k0].keys()))
print("事件窗分层存在:", "event" in cards["families"][k0] or "swan" in cards["families"][k0])

st = json.load(open(ROOT / "data" / "paper_trading_status.json", encoding="utf-8"))
print("\n== 模拟盘 status 键 ==", sorted(st.keys()))
print("20 笔判据评估字段存在:", any("criteria" in k or "verdict" in k or "n20" in k for k in st))
