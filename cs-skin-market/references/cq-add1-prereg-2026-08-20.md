# CQ-ADD-1 窄化预注册（2026-08-20，②研究窗口，PM 立项 CU / roadmap v80 交办）

> 立项：CQ-ADD-1「牛市上行段高选择性候选验证」（decision-log CU，roadmap v80）。
> 目标：研究「牛市上行段高选择性窄化」候选族——族开回放 + delta 清单 + 完整四关通过后作为落地候选交③审计 → PM 立落地卡交研发；**本卡仅研究，不落地**。
> 判据先行：以下窄化条件与否决线在开跑前定死，禁止先跑再定判据。

## 一、候选锁定与数据支撑（CQ 切分产物，只读引用）

- CQ 全链（CP→CQ→CR/CS→CT）对照差异表「该加 1」= 牛市/强势上行段盲区；前置 CE bull_steady 证伪（宽触发 added 13,279 / val win14 49.1% avg14 +5.99 vs 基线 book 78.9% +25.07 → A2 FAILED）——**宽触发不可落地，须高选择性窄化**。
- 数据支撑区域（`_exp_optimal_partition_2026-08-20.json`，样本内观察，仅作候选依据）：
  - `tree_fwd30_leaf11`：n=5,453，rule `vol30<=79.39 AND mchg7>4.06 AND sc30<=33.11 AND mchg7<=5.73`；质心 sc30=−10.85 / vol30=43.25 / mchg21=5.2；gate30 pass（win 70.6% avg +19.93）；事件 4。
  - `tree_fwd30_leaf12`：n=5,196，rule `vol30<=79.39 AND mchg7>4.06 AND sc30<=33.11 AND mchg7>5.73`；质心 sc30=−10.41 / vol30=44.38 / mchg21=11.14；gate30 pass（win 56.2% avg +7.18）；**事件 7 个最稳**。

## 二、高选择性窄化条件（跑前定死）

新族键 `cq_add1`（标签「🟢 牛市上行·高选择性窄化·分批建仓」），触发器四条件 **AND**：

| # | 条件 | 字段口径 | 阈值依据 |
|---|---|---|---|
| 1 | **大盘上行段（上界）** | `drop21` = market_index 21 日变化率 %（backtest_common 口径 = 特征矩阵 mchg21，正=涨） | `3.7 < drop21 <= 15`（CQ 卡「mchg21>3.7~14.5」） |
| 2 | **供给收缩** | `supply_change_30d` = 在售量 30 日变化率 %（item_analysis F 字段 = 特征矩阵 sc30，负=收缩） | `supply_change_30d <= -5`（leaf11/12 质心 −10.4~−10.9 收紧） |
| 3 | **低波动** | `vol30` = 日收益 std 年化 %（`_vol_pct(prices,30)`，同 fullscan_features 公式） | `vol30 <= 50`（leaf11/12 质心 43~44 上界收紧） |
| 4 | **短周期大盘动量（辅助）** | `mchg7` = market_index 7 日变化率 %（`_build_mchg7`，同特征矩阵） | `mchg7 > 4`（leaf11/12 rule mchg7>4.06） |

- **量级预估（预注册声明）**：三条件 + 辅助条件在特征矩阵（231 品 239,826 行，2023-08-29~2026-08-18）交集 **2,322 行**；目标引擎 added **≤ 数百条**（与基线 377 条买书可比，非万级）。回放实际 added 以引擎为准（去重/优先序/limit 收敛）。
- **字段口径一致性**：drop21/sc30/vol30/mchg7 与特征矩阵 mchg21/sc30/vol30/mchg7 同源同公式（market_index 21/7 日变化、在售量 30 日变化、日收益 std 年化）。

## 三、判据与否决线（硬约束，跑前定死）

1. **added ≥ 10,000 自动驳回**：对齐 CE bull_steady 证伪（宽触发稀释买书，A2 必拒），不进入四关。
2. **单月信号占比 >50% 自动驳回**（沿用 CC 预注册附加否决线；防单事件簇）。
3. **验证段证伪**：walk-forward 验证段（≥2025-08-10）added 不显著即证伪——不得以样本内数字辩护。
4. **A2 质量对照**：val 段 win14/avg14 须与基线 book val（win14 78.9% / avg14 +25.07）贡献方向一致且 p_avg 显著（置换 n_iter=500）；远劣（如 win14 < 60%）即证伪。
5. **组合级**：期望/胜率 ≥ 基线且 maxDD 不恶化；**前后半段一致**（切点 2025-08-10）；**置换检验**通过。
6. **delta 清单 4 项（硬验收）**：①基线非新族信号逐条字节一致（fwd/net 零漂移）②added 数量与量级声明对照 ③displaced/relabeled ④月度/单品分布（防单事件簇）。

## 四、回放口径（复用 CE 注入机制）

- 脚本：`references/run_cq_add1_replay.py`（复制 `run_family_variant_replay.py` 变体，触发器换成 §二 四条件，族键 `cq_add1`；不改 pipeline/ 生产代码）。
- 池 = 232 品 3 年（同基线全池回放口径，排除贴纸/角色/2 污染品）；env `CS_ENGINE_PERIOD_ROUTE=1`。
- 输出：`data/_exp_cq_add1_replay_2026-08-20.json`（独立文件）。
- 同步重建：`SIGNAL_FAMILIES` / `SIGNAL_FAMILY_BY_KEY` / `_POST_FAMILIES` / `DEDUP_PRIO_BY_LABEL` / 买涨腿硬编码循环尾加 `cq_add1`（CE 同款三处派生结构 + exec 补丁）。

## 五、验证流水线（族开回放 → delta → 完整四关）

1. **smoke**（3 品）：基线信号字节一致核对 + 新族信号量级粗检。
2. **全池族开回放**：写 `_exp_cq_add1_replay_2026-08-20.json`。
3. **delta 清单**：审计脚本重算 added/displaced/matched/drift/relabeled/月度分布。
4. **完整四关**：
   - A2 发射分布复算：`a2_emission.analyze(cq_add1_replay, baseline, "cq_add1", label, regime="all")`（含置换 n_iter=500）
   - 组合级：`b1_risk_backtest_v2.simulate`（期望/胜率 vs 基线、maxDD）
   - 前后半段：切点 2025-08-10 分段统计（fit/val 一致）
   - 置换检验：`_perm_p`（p_avg/p_win，n_iter=500, seed=42）
5. 结果**正负一律登记** decision-log（CU 执行条目）+ commit，交 PM 对照本卡验收；③独立审计。

## 六、红线

- ②只做研究：不落地生产代码、不改 pipeline/、不 bump ENGINE_VERSION、不写生产库；样本内只出候选；不替③「改到通过」；产物只写 `data/_exp_*.json`。

## 七、参考基线数字（CE 复算，_audit_ce_verify_2026-08-20.py）

- 基线（`_exp_cycle_replay_fullpool_2026.json`）：总信号 377（全为买类）；fit win14 55.2% / avg14 +1.88；**val win14 78.9% / avg14 +25.07**（≥2025-08-10）。
- 切点：2025-08-10（CQ 全链统一 walk-forward 验证段起点）。
