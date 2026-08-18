# 单品短期期望信号 · 落地规格（候选·复审版，2026-08-18）

> 交③审计的候选交付物（复审版，回应 ③审计#1 驳回）。研究结论见 decision-log AS~AX，原始产物 `data/_exp_*.json`。
> 反过拟合声明：所有数字/机制均为**样本内候选**，落地须样本外（B 通道 ~2027-04）或 live pilot；③审计独立判通过后方可改 `pipeline/` / `webapp/` 代码。

## 一、定位（两个入口）

| 入口 | 回答 | 关系 |
|---|---|---|
| **融合决策**（现有） | 「这品过没过守卫/路由，能不能买」 | 主，可执行，不动 |
| **单品短期期望**（本信号，新） | 「这品现在 7d/14d 期望多少、翻正率多少」 | 辅，**纯展示，不进决策** |

本信号**不改任何 buy/watch/action/limit**，只追加展示模块，与融合决策并列、不互斥。

## 二、输出（展示规格）

单品分析报告追加「短期期望」模块：

```
短期期望（历史同态 · 非本次预测）
  当前市场：{时期}（进入第 N 天）
  7d 期望  {+X.X%} · 翻正率 {Z%}（n={Y}）
  14d 期望 {+X.X%} · 翻正率 {Z%}（n={Y}）
  本品特性：{驱动特征说明}（{时期}期，本品偏{强/弱}）
```

- 期望 = **中位数**（非均值）；翻正率 = 历史同态样本 fwd>0 占比。
- 时点超界直接显示尾部渐近值（如 S3 第 44 天 = −7.7%），不标注「外推」。

## 三、机制（层次收缩 k=20）

输入：某品 t 时刻状态 → 输出 7d/14d 期望中位数 + 翻正率 + n。

1. **时期×时点先验**（大方向）：period = `state_bucket(chg180,chg30)`；先验 = `median[fwd|period,period_days]`（收缩向 `median[fwd|period]` 再向全局中位数）；时点超界 → 该时期末 5 日中位数。
2. **分时期单品特性**（本信号核心价值，**仅 P/S1/S2 期启用**，发射侧样本外验证稳定）：

| 时期 | 驱动特征 | 特性分数 | 发射侧样本外（stage8/9） |
|---|---|---|---|
| P 恐慌 | 超跌深度 | `-(z_chg7+z_chg3+z_z)/3` | ✓ 稳定（spearman 0.02→0.20，Top−Bottom +23.3pp） |
| S1 牛市 | 供给收缩 | `-z_supply30` | ✓ 稳定（−0.03→0.16，+16.3pp） |
| S2 回调 | 供给收缩 | `-z_supply30` | ✓ 稳定（−0.08→0.07，+6.2pp） |
| S3 阴跌 | （趋势强度，**样本外失效，不启用**） | — | ✗ spearman 0.005→−0.060 |
| S4 反弹 | 无 | — | ✗ 无信号 |

   - 特性分数三分位桶，`median[fwd|period,特性桶]` 收缩向时期先验。
3. **输出**：`E_item` = 特性桶中位数（P/S1/S2），否则 `E_base` = 时期先验（S3/S4）。

## 四、关键证据（发射侧 + 置换，回应 ③审计#1）

- **置换检验**（`_exp_stage7_permutation.json`，n_perm=500，seed=42+p，非地板值）：打乱特性标签后 Top−Bottom 差归零——P 真实 +23.81 vs 置换 +0.04（p=0.0000）、S1 +4.63（p=0.0000）、S2 +2.04（p=0.0000）、S3 +6.31（p=0.0000，但样本外失效）、S4 +0.45（p=0.012）。→ 特性信号统计显著，非 2 事件巧合。
- **发射侧回放**（`_exp_stage8_emission.json`，SPLIT=2025-08-10 fit/val）：P/S1/S2 单品特性样本外提升排序能力（见上表）；S3 趋势特性样本外失效、S4 无。
- **逐信号明细**（`_exp_stage9_emission_signals.json`，36654 条 val 段）：每条含 date/item_id/period/特性分数/pred_base/pred_on/fwd14_actual，供独立复算。
- **口径统一**：先验中位数 = 查表产物（walk-forward train 拟合，SPLIT 前），**不再引用全样本 AM 数字**（旧 S3 −3.9% 与 walk-forward −7.54% 矛盾已废除，以查表产物为准）。

## 五、落地实现（审计通过后）

- **离线查表**：`references/build_shortterm_table.py` → `data/_exp_shortterm_table.json`（`时期×时点×特性桶 → fwd7/fwd14 中位数 + 翻正率 + n`，walk-forward train 拟合，版本化）。
- **在线接入**（纯展示）：`pipeline/shortterm_expectancy.py` 纯函数 `compute_shortterm_expectancy(period, period_days, chg7, chg3, z, th, supply30)`；`webapp/analysis_service.py` 单品报告追加模块。
- **配置**：`config.py` 新增 `SHORTTERM_EXPECTANCY` 台账（k=20、特性桶边界、特征权重、TABLE_PATH）；不 bump ENGINE_VERSION（纯展示）。
- **测试**：`tests/test_smoke.py` 新增 `t_shortterm_expectancy`（机制单测 + 渲染 + 不进决策断言）。

## 六、反过拟合声明与可持续优化

- **样本内候选**：落地须 B 通道 2027-04 重验或 live pilot（C 通道自动熔断）。
- **P 期稀缺**：P 期仅 2 事件（五合一 + 炼金），超跌特性外推性待 A 通道第 3 事件。
- **S3/S4 限制**：S3 仅 2026 一段（32 天）无法补第三独立切点，趋势特性样本外失效已如实剔除；S4 无特性。
- **可持续优化**：查表版本化 + 三通道监测，新数据到后重跑 build_shortterm_table + walk-forward。

## 七、交③审计原始产物清单

`_exp_universe_panel_v2.json` / `_exp_stage1b_target_redefinition.json` / `_exp_stage3_selection_score.json` / `_exp_stage6_period_item_mechanism.json` / `_exp_stage7_permutation.json` / `_exp_stage8_emission.json` / `_exp_stage9_emission_signals.json`；decision-log AS~AX。
