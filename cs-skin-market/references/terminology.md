# 口径词表（Terminology）

> 工程卫生收口建立的唯一术语指针。文档中凡出现下列口径，应指向本文，禁止再引用历史中间数或多种读法。

## 双基线
- `HIST-FULL = 317`：历史全窗口冻结基线；`data/item_backtest_full_2025.json`，v2-T4/T5，不可复现，作为 C 通道监测主口径。
- `CLEAN-CUR = 230`：当前引擎回填后干净基线（NULL + 0-value gap 回填）；`data/_exp_v2t9_win_replay.json`，v2-T9，仅展示参考。
- 引用数据定义请取 `pipeline/config.py:BASELINE_LEDGER`；禁止直接使用 290/140/163/150 等中间数作为基线。

## 信号族分类
- 唯一事实源：`pipeline/config.py:SIGNAL_FAMILY_TAXONOMY`。
- 展示键：`panic` / `deep_value` / `accumulate`。
- `accumulate` 是展示聚合键，语义 = supply_accum + deep_dip + base，不等于 `supply_accum`细族；不要把 142/198/212 这类不同时期统计当成同一口径。

## Calmar 唯一标尺
- 唯一口径：`references/calmar_standard.py` + `data/_exp_calmar_standard.json`。
- EXIT 门槛待定语义：`Calmar 提升 ≥15%` 应统一为 walk-forward 折上 Calmar 均值的相对提升；样本不足无 fold 时改用全局 Calmar 绝对差 ≥1.0 且前后半段方向一致。

## 使用规则
- 活跃文档（AGENTS / PROJECT_STRUCTURE / roadmap / 研究报告）不得裸写 317 / 230 / accumulate 等口径，应指向本文或代码唯一事实源。
- `decision-log.md` 为历史账本，原文不改；其中旧口径仅代表当时判断，不作为当前基线。

## 强制规则

- 任何新文档/新代码不得裸写 317 / 230 / accumulate 等口径，必须指向本文或代码唯一事实源。
