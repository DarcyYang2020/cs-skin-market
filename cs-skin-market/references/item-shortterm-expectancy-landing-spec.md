# 单品短期期望信号 · 落地规格（候选，2026-08-18）

> 本文 = 交③审计的正式候选交付物。研究结论见 decision-log AS/AT/AU/AV，原始产物 `data/_exp_*.json`。
> 反过拟合声明：本文所有数字/机制均为**样本内候选**，落地须样本外（B 通道 ~2027-04）或 live pilot 验证；③审计独立判通过后方可改 `pipeline/` / `webapp/` 代码。

## 一、定位（两个入口）

| 入口 | 回答 | 关系 |
|---|---|---|
| **融合决策**（现有） | 「这品过没过守卫/路由，能不能买」 | 主，可执行，不动 |
| **单品短期期望**（本信号，新） | 「这品现在 7d/14d 期望多少、翻正率多少」 | 辅，**纯展示，不进决策** |

本信号**不改任何 buy/watch/action/limit**，只追加一个展示模块，与融合决策并列、不互斥。

## 二、输出（展示规格）

单品分析报告追加「短期期望」模块：

```
短期期望（历史同态 · 非本次预测）
  当前市场：{时期}（进入第 N 天）
  7d 期望  {+X.X%} · 翻正率 {Z%}（n={Y}）
  14d 期望 {+X.X%} · 翻正率 {Z%}（n={Y}）
  本品特性：{驱动特征说明}（{时期}期，本品偏{强/弱}）
```

- 期望 = **中位数**（非均值，防暴涨品拉高）。
- 翻正率 = 历史同态样本中 fwd>0 占比。
- 时点超界（period_days > 该时期历史最长）：直接显示尾部渐近值（如 S3 第 44 天 = −7.7%），不标注「外推」。

## 三、机制（三层，层次收缩 k=20）

输入：某品 t 时刻状态 → 输出 7d/14d 期望中位数 + 翻正率 + n。

1. **时期×时点先验**（大方向）：
   - period = `state_bucket(chg180, chg30)`（P/S1/S2/S3/S4），period_days = 连续运行天数。
   - 先验 = `median[fwd | period, period_days]`（收缩向 `median[fwd | period]`，再收缩向全局中位数）。
   - 时点超界 → 该时期末 5 日中位数（尾部渐近）。
   - **先验中位数（全样本口径，供参考）**：P +10.2% / S1 +1.3% / S2 +0.9% / S3 −3.9% / S4 −0.3%。

2. **分时期单品特性**（这个品 vs 别的品，本信号的核心价值）：
   | 时期 | 驱动特征 | 特性分数 |
   |---|---|---|
   | P 恐慌 | 超跌深度 | `-(z_chg7 + z_chg3 + z_z)/3`（越超跌越高） |
   | S1/S2 | 供给收缩 | `-z_supply30`（越收缩越高） |
   | S3 阴跌 | 趋势强度 | `z_th - z_supply30`（逆势强势越高） |
   | S4 反弹 | 无 | 用时期先验（反抽陷阱，无单品特性） |
   - 特性分数三分位桶（高/中/低），`median[fwd | period, 特性桶]` 收缩向时期先验。

3. **输出**：`E_item = 特性桶中位数`（有特性信号的时期 P/S1/S2/S3）；否则 `E_base = 时期先验`（S4）。

## 四、关键证据（跨切点稳定，decision-log AV）

分时期单品特性 Top20% vs Bottom20% 中位数差（三切点 walk-forward，全部方向一致）：

| 时期 | 特性 | Top−Bottom 差（三切点） |
|---|---|---|
| P 恐慌 | 超跌深度 | 23.81 / 23.31 / 30.65 pp |
| S1 牛市 | 供给收缩 | 7.36 / 12.97 / 样本不足 |
| S2 回调 | 供给收缩 | 4.91 / 9.49 / 4.32 |
| S3 阴跌 | 趋势强度 | 2.09 / 2.09 / 2.53 |
| S4 反弹 | 无 | −0.2 / −0.2 / 0.31（无信号） |

**时期先验（大方向）**：P 期大涨率 50% / S3 期 8%，period 预测大涨 AUC 0.60~0.71（decision-log AS）。

## 五、落地实现（审计通过后）

- **离线查表**（版本化，可持续优化）：`references/build_shortterm_table.py` → `data/_exp_shortterm_table.json`（`时期×时点×特性桶 → fwd7/fwd14 中位数 + 翻正率 + n`）。
- **在线接入**（纯展示，读查表 + 单品状态）：`pipeline/shortterm_expectancy.py` 纯函数 `compute_shortterm_expectancy(period, period_days, chg7, chg3, z, th, supply30) → dict`；`webapp/analysis_service.py` 在单品报告追加该模块。
- **配置**：`config.py` 新增 `SHORTTERM_EXPECTANCY` 参数台账（收缩 k=20、特性桶边界、特征权重、TABLE_PATH），`ENGINE_VERSION` 不 bump（纯展示，无引擎行为变更）。
- **测试**：`tests/test_smoke.py` 新增 `t_shortterm_expectancy`（机制单测 + 展示渲染断言 + 不进决策断言）。

## 六、反过拟合声明与可持续优化

- **样本内候选**：本文机制在 180 品 × 3 年回放样本内拟合，落地须 B 通道（~2027-04）重验或 live pilot（C 通道月度胜率/期望监测自动熔断）。
- **P 期稀缺**：P 期仅 2 事件（五合一 + 炼金），超跌特性外推性待 A 通道第 3 独立恐慌事件。
- **可持续优化**：查表版本化（schema 版本 + 数据截止日），新数据/新事件到后重跑 build_shortterm_table + 三通道监测。

## 七、交③审计的原始产物清单

- `data/_exp_universe_panel_v2.json`（宇宙面板）
- `data/_exp_stage1b_target_redefinition.json`（目标重定义）
- `data/_exp_stage3_selection_score.json`（超跌分数）
- `data/_exp_stage6_period_item_mechanism.json`（分时期单品特性，核心证据）
- decision-log AS / AT / AU / AV（研究结论账本）
