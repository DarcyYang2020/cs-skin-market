# 口径词表（Terminology）

> 工程卫生收口建立的唯一术语指针。文档中凡出现下列口径，应指向本文，禁止再引用历史中间数或多种读法。

## 双基线
- `HIST-FULL = 317`：历史全窗口基线（period-complete，含缺失深度 caveat）；`data/item_backtest_full_2025.json`，v2-T4/T5，不可复现；用于看引擎穿越完整周期的整体表现；C 通道监测主口径。
- `CLEAN-CUR = 230`：当前干净基线（data-clean，含缺早期牛市段 + panic 单事件 35.2% caveat）；`data/_exp_v2t9_win_replay.json`，v2-T9；用于看引擎在无污染数据上的表现；仅展示参考，不作监测告警。panic 族 35.2% 中 97.5%（79/81）是 2026-05 单事件恐慌，是本基线最不能外推之处。
- 引用数据定义请取 `pipeline/config.py:BASELINE_LEDGER`；禁止直接使用 290/140/163/149/150/297 等中间数作为基线。

## 信号族分类
- 唯一事实源：`pipeline/config.py:SIGNAL_FAMILY_TAXONOMY`。
- 展示键（C1 三口径统一，2026-08-20）：`panic` / `deep_value` / `accumulate` / `rise` / `longhold` / `oversold` / `base` / `weak_market`。
- 细族 = 引擎 `SIGNAL_FAMILIES` 11 族 + `base`（分批建仓=融合基础买点）+ `deep_dip`（深度回调低吸=P0 超跌）+ `weak_market`（弱市抗跌=历史遗留）；`signal_guidance` 已改用 `assign_fine_family`（废除自身关键词匹配）。
- `accumulate` 展示组 = supply_accum + deep_dip + rise_contract + volatile_accum + second_wave（低吸/吸筹类），**不含 base**（分批建仓独立展示组）；不要把 142/198/212 这类不同时期统计当成同一口径。C1 前 accumulate 含 base（如 HIST-FULL n=198），C1 后 base 独立（accumulate n=176），两口径不可混用。
- `weak_market`（弱市抗跌）为历史遗留 label（trend_health 旧路径，与 rs_accum/ct_accum 语义重叠），展示层单列，引擎路径未删。

## Calmar 唯一标尺
- 唯一口径：`references/calmar_standard.py` + `data/_exp_calmar_standard.json`。
- EXIT 门槛待定语义：`Calmar 提升 ≥15%` 应统一为 walk-forward 折上 Calmar 均值的相对提升；样本不足无 fold 时改用全局 Calmar 绝对差 ≥1.0 且前后半段方向一致。

## 使用规则
- 活跃文档（AGENTS / PROJECT_STRUCTURE / roadmap / 研究报告）不得裸写 317 / 230 / accumulate 等口径，应指向本文或代码唯一事实源。
- `decision-log.md` 为历史账本，原文不改；其中旧口径仅代表当时判断，不作为当前基线。

## 强制规则

- 任何新文档/新代码不得裸写 317 / 230 / accumulate 等口径，必须指向本文或代码唯一事实源。
