# 候选族预注册 · 族开回放 trigger 定义（2026-08-20，②）

> 承接 CC（③放行两候选进四关）+ CD（③拍板：研究脚本变体，否决改 pipeline/；复用回放内核、运行时注入两新族注册表、输出独立文件、交 delta 清单、先跑 3 品 smoke）。
> 本文锁定两候选族的**触发边界**与**注入口径**，跑族开回放前不改。

## 一、两候选族定义（trigger 来自扫描决策树叶规则）

| 项 | ① 牛市稳态上行 | ② 急跌高波动 |
|---|---|---|
| key | `bull_steady` | `crash_vol` |
| label | 🟢 牛市稳态上行·分批建仓 | 🟢 急跌高波动·分批建仓 |
| priority | 22 | 20 |
| limit | 0.12 | 0.10 |
| **trigger（AND）** | `vol30≤79.4 且 −7.3<mchg7≤4.1 且 drop21>3.7` | `vol30>79.4 且 vol7>421.2 且 mchg7≤−7.3 且 drop21>−48.4` |
| 语义 | 低波动 + 大盘温和上行 | 大盘 7 日急跌 + 单品极端波动（=原 H4 急跌型恐慌）|

## 二、特征单位映射（扫描特征 ↔ 引擎 F 上下文）

| 扫描特征 | 引擎可用 | 映射 |
|---|---|---|
| `vol30`（年化%）| F 无 | 注入时由 `F["prices"]` 现算：`std(近30日日收益)×√252×100` |
| `vol7`（年化%）| F 有 `vol7` 但为**原始 std**（非年化）| 注入时另算 `vol7_pct = std(近7日日收益)×√252×100`，阈值 421.2 用年化口径 |
| `mchg7`（大盘7日%）| F 无 | 注入时建 `{date: mchg7}` 全局查表（market_index 7 日涨跌）|
| `mchg21` | F 有 `drop21`（同符号，负=跌）| `drop21` 即 `mchg21`，阈值 3.7/−48.4 直接用 |

## 三、注入口径（研究脚本变体，不动 pipeline/）

1. **族注册表**：`ia.SIGNAL_FAMILIES`（tuple + 两族）、`ia.SIGNAL_FAMILY_BY_KEY`（重建 dict）、`ia._POST_FAMILIES`（重建 tuple，按 priority 降序）——三处**必须同步重建**（漏任一是③点名"tuple/派生列表漏 patch"）。
2. **消费路径**：① `bull_steady` 加进「买涨腿」硬编码循环（hold/reduce 段）；② `crash_vol` 进 `_POST_FAMILIES`（watch/avoid 段，priority 20 排 supply_accum 之后）。两族均**排在既有族之后**（break 语义）→ 只增不替，保证基线 374 逐条字节一致。
3. **去重优先级**：`ia.DEDUP_PRIO_BY_LABEL` 增 `牛市稳态上行:22`、`急跌高波动:20`。
4. **买涨腿 patch**：`inspect.getsource(decide_fusion_signal)` + 字符串替换 + `exec(..., ia.__dict__)`，仅把硬编码元组尾加 `"bull_steady"`。

## 四、验证判据（族开回放）

1. **delta 清单**：基线 374 信号（name/date/action_label/net14/net30）逐条字节一致；新增信号 = 仅两候选族发射（月度/单品分布随产物）。
2. **smoke**：全池前先跑 3 品（含 1 高波动品 + 2 有历史信号品），核对①既有信号逐条一致、②两新族确实发射（防 patch 漏）。
3. **② A2 否决线（③预注册）**：发射信号单月占比 >50% 自动驳回（本例预期 91.6% 挤 2025-10，预判被拒）。

## 五、反过拟合红线

- 阈值/单位/优先级/仓位全部本文锁定，跑后不改；族开产物 = 样本内候选，落地须四关 + 样本外/live。
- 只产出 `data/_exp_*.json` + 本预注册 + decision-log；不改 `pipeline/`、`webapp/`。
