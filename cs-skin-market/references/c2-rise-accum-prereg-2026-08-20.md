# C2 预注册判据草案：rise_accum 追涨腿收紧（chg7 下限 3→10）

> 状态：**②研究候选预注册草案**（2026-08-20），供 PM 立项卡 v78 提取；②在出卡后照卡执行「预注册探针 → 回放 → 候选 → 交③审计」，研发接审计通过后的落地。
> 出处：decision-log CE 闭环（C2 为唯一独立落地候选）+ H3 验证（`_exp_h2h3_family_boundary_2026-08-20.json`）。

## 一、候选定义（锁定，跑前定死）

**把 `rise_accum` 族的触发条件 `chg7 > 3` 改为 `chg7 > 10`**（`pipeline/item_analysis.py:1262`）。
其余条件一律不动：上限 `_rise_chg7_cap()`（默认 15）、TH≥55 环境门、`supply_change_30d > 5`、`s7 ≤ 0.85*s30`、limit 0.05、priority 28、dedup 28。

语义：砍掉「温和追涨段」（chg7 3~10，样本内负期望），只保留「强势追涨段」（chg7>10，样本内正期望）。

## 二、证据基础（**样本内观察，不是结论**）

基线 374 信号中 rise_accum 29 条（净收益扣 2% 成本，fwd14）：

| chg7 分段 | n | win14 | avg14 |
|---|---|---|---|
| ≤5 | 4 | 25.0% | −1.94 |
| 5 < chg7 ≤ 10 | 11 | 18.2% | **−4.58** |
| >10 | 14 | 50.0% | **+24.0** |

旁证：剔除 rise_accum 后全样本 win14 71.9%→75.1%、avg14 +18.08→+18.80；rise_accum 自身是唯一负中位数族（med14 −3.2）。

**反过拟合声明（必须写进立项卡）**：阈值 10 是在 374 样本内按 chg7 分桶后选出的（n=14 的小样本），**只能作为候选阈值**，不得视为已验证结论。最终以四关的 walk-forward 验证段（≥2025-08-10）为准：若验证段 chg7>10 段不显著，候选证伪，不得以样本内数字辩护。

## 三、回放口径（研究脚本变体，不改 pipeline/）

- 复用 `references/run_family_variant_replay.py` 注入机制，**改为替换 rise_accum 的 trigger**（非新增族）：运行时注入 `chg7 > 10` 版 trigger 到 `SIGNAL_FAMILY_BY_KEY["rise_accum"]`，同步重建派生结构（BY_KEY / _POST_FAMILIES / 买涨腿循环）。
- 池：232 品 3 年（同基线全池回放 `_exp_cycle_replay_fullpool_2026.json`，374 信号）；env：CS_ENGINE_PERIOD_ROUTE=1。
- 输出独立文件：`data/_exp_c2_rise_accum_replay_2026-08-20.json`。

## 四、delta 清单（③硬验收，与 CE 同口径）

1. **基线非 rise_accum 信号逐条字节一致**（fwd/net 零漂移）——证明注入没污染其他族。
2. rise_accum 信号数变化：29（基线）→ N（变体）；列出 chg7 3~10 段被砍的 11 条明细。
3. displaced/relabeled：chg7 收紧后原 rise_accum 信号是否被其他族重新捕获、或彻底消失。
4. 月度/单品分布：新 rise_accum 信号的分布（防单事件簇）。

## 五、验收（完整四关，与 CE 同链路）

1. **A2 发射分布复算**：`a2_emission.analyze(变体, 基线, "吸筹型上涨", "rise_accum")`——added/displaced 是否改善买书质量（验证段 win14 ≥ 基线 book 78.9% 的贡献方向正确、p_avg 显著）。
2. **组合级**（`references/b1_risk_backtest_v2.py` simulate）：收紧后组合期望/胜率 ≥ 基线；maxDD 不恶化。
3. **前后半段一致**：切点 2025-08-10，两段方向一致。
4. **置换检验**：chg7>10 段的 win/avg 相对随机子集显著。
5. 附加否决线（沿用 CC 预注册）：单月信号占比 >50% 自动驳回。

## 六、成功判据（一句话）

收紧后 rise_accum 段整体正期望且验证段显著、组合级不劣化 → 候选成立交③审；否则证伪关闭。

## 七、红线

- 样本内只出候选，不落地；落地须 PM 立项 + 研发执行（②只研究）。
- 不替③"改到通过"；证伪就是证伪。
- 产物只写 `data/_exp_*.json`；不碰生产库。
