# ③独立审计 · R3 策略隔离评估复核（2026-08-27）

**审计对象**：②R3 执行（decision-log DV + `data/_exp_family_isolation_2026-08-27.json` + 6 族单开回放 `data/_exp_family_<key>_replay_2026-08-27.json` + 当前引擎无注入参照 `data/_exp_current_engine_fullpool_2026-08-27.json` + 研究脚本 `references/run_family_isolation_replay.py` / `r3_family_isolation_four_gates.py`）
**审计员**：窗口③（独立审计 / 刹车）
**红线执行**：只认 R3 预注册判据（`references/r3-family-isolation-prereg-2026-08-27.md`，DR PM 冻结）+ 产物事实；DV 自述仅对照；**独立复算核验**（审计脚本 `references/_audit_r3_recompute.py`，独立实现 G3/重叠/相关/period/delta/G4 置换 + 复用生产设施 a2_emission/b1 重跑 G1/G2；SQL 直查版本冻结；独立重跑冒烟）。

---

## 一、判据口径对照（预注册 §3 四关 vs 执行实现）

| 关 | 预注册通过线（DR 冻结） | 实现（four_gates） | 对照 |
|---|---|---|---|
| G1 A2 发射复算 | fit p_avg ≤0.05 **且** val 不显著即证伪（val p 趋近 1.0 = 无样本外证据） | `passed = fit_p≤0.05 AND val_p<0.05`（a2_emission.analyze，n_iter=500 seed=42 regime=all） | ✅ 一致 |
| G2 组合级 | 风险调整后收益 ≥ 基线同口径；主比 Calmar/maxDD，次比总收益；劣化 ≥10pp 即不过 | `passed = fam_total≥0 AND (base_total−fam_total)≤10 AND (fam_dd−base_dd)≤10`（b1.simulate 同口径 hold21/成本2%，**两臂均未传 cap/熔断**） | ⚠️ 见登记 1（实现细节） |
| G3 前后半段 | 切点 2025-08-10；fit win14≥60% **且** val win14≥60% 且期望为正；val 不显著即证伪 | `passed = fit_win14≥60 AND val_win14≥60 AND val_avg14>0` | ✅ 一致 |
| G4 置换检验 | val 段收益差 p ≤0.05 才非随机；p 趋近 1 = 证伪 | `passed = p_avg<0.05`（a2_emission._perm_p，n_iter=500 seed=42，无放回抽样/book 不足放回） | ✅ 一致 |

硬判据汇总（任一关不过 → 从多策略候选划掉）与预注册一致 ✅。

## 二、四关核验（独立复算，逐族）

**复算方法**：审计脚本独立实现 G3（按 SPLIT=2025-08-10 分组重算 win14/avg14）、G4 置换（独立代码 seed=42 复现 + seed=7 敏感性）、G3/重叠/相关/period/delta 全部独立实现；G1 调 a2_emission.analyze 重跑、G2 调 b1.simulate/metrics 重跑。**9 项核验全部 PASS，数字与主产物完全一致**（审计产物 `data/_audit_r3_recompute_2026-08-27.json`）。

| 族 | 信号 | G1 A2 | G2 组合级 | G3 前后半段 | G4 置换 | verdict |
|---|---|---|---|---|---|---|
| panic | 155 | F（fit n=0 → p=None） | F（total 908 vs 1510，maxDD −139.9 vs −30.9） | F（fit n=0） | **P（0.018）** | 证伪 ✅ |
| deep | 47 | F（added=0 → p=None） | F（total 299 vs 1510；maxDD −20.4 改善 10.5pp） | **P（64.0% / 72.7%）** | F（0.11） | 证伪 ✅ |
| rise | 370 | F（fit 0.002 显著 / val 0.994 证伪） | F（235 vs 1510） | F（48.5% / 53.9%） | F（0.998） | 证伪 ✅ |
| supply | 52 | F（fit n=0 → p=None） | F（87 vs 1510） | F（50.0% / 70.8%） | F（0.574） | 证伪 ✅ |
| reversal | 285 | F（fit 0.0 / val 1.0） | F（321 vs 1510） | F（61.1% / 45.6%） | F（1.0） | 证伪 ✅ |
| base | 213 | F（fit 0.07 不显著 / val 1.0） | F（229 vs 1510） | F（67.1% / 52.4%） | F（1.0） | 证伪 ✅ |

- **G4 置换敏感性**：seed42 复现主产物 p 值全一致；seed7 下方向稳定（panic 0.012、deep 0.138、rise/supply/reversal/base 不变）——**无边缘抖动，结论不依赖 seed 选择** ✅
- **四关判定**：每族至少 2 关不过（panic/deep/supply 的 G1 因 fit 段无新增信号直接无证据）；6 族全证伪与主产物一致 ✅
- **结论稳健性（重点复核 DV 观察 1 是否影响结论）**：即便对 G1「对比基线偏严」口径放宽（只看其余关），deep 仍过不了 G4（p=0.11），rise/reversal/base 过不了 G3/G4，panic 过不了 G1/G3（fit 段 0 信号）——**没有任何一族在放宽任一关后能全过四关**，"6 族全证伪"结论不依赖 G1 口径 ✅

## 三、差异化三表核验（独立复算）

| 表 | 核验结果 |
|---|---|
| 信号重叠矩阵 | Jaccard 全 ≤0.025（max reversal×base 0.025），远低于 0.5 非独立线 → 各族发射足迹高度独立 ✅（与 DV 一致） |
| 收益相关矩阵 | \|r\|≥0.5：rise×base 0.684 / reversal×base 0.662 / reversal×rise 0.506（临界冗余，未到 0.7 冗余线）；低相关真差异化：deep×rise 0.264 / supply×deep −0.002 / supply×reversal −0.005 ✅（与 DV 一致） |
| 时期覆盖表 | 分化真实：panic 管 P（152/avg+30.7）、deep 管 S2（41/avg+18.5）、rise 管 S1（190/avg+17.2）、supply 管 S1（39）、reversal/base 广覆盖 ✅；**_period 字段独立重建 market_ctx 重算，6 族 1122 信号 mismatch=0** ✅ |

三表数字与主产物完全一致；独立 ≠ 够格（发射足迹独立是必要条件，四关已判定单族不足格子策略）。

## 四、组合测试与形态裁定（核验通过）

- candidates = []（6 族全证伪）→ 无法组合 → `multi_strategy_verdict = 候选族不足 2 个，无法组合——多策略形态不成立` ✅（预注册 §5 口径）
- 基线全引擎组合 Calmar 48.97（total +1510.9% / maxDD −30.9%）远高于任何单族（4.72~19.79）→ **引擎价值在融合而非单族**，单引擎（融合决策）维持为架构终态 ✅
- 组合测试未触发等权/A2 加权分支（无候选），禁优化器纪律无触碰 ✅

## 五、守院核验（通过）

| 项 | 核验 |
|---|---|
| **oos_zone 守院** | 回放逐信号 `oos_guard.require_fit(prereg=...)` 接线（代码核验 ✅）；val 段仅 G2/G3/G4 预注册验证动作触碰（预注册 §6.3 声明 ✅）；panic 全部 155 信号在 val 段（2025-10-24 起）、fit 段 0 信号 → G1/G3 证伪正是「防事件簇幸存者偏差」设计意图的正确执行 ✅ |
| **版本冻结** | SQL 直查 replay_cycle_win.db：items 405 / price_history 259,222 / market_index 1015，与 meta 声明完全一致 ✅ |
| **零漂移** | 基线族信号（品,日,net14 同键）保持核验：panic/supply/rise/reversal 缺失 0；deep missing 4（real 2=去重自约束 / legacy 2=基线旧产物）；base missing 5（全部去重自约束）——归因成立，非引擎漂移 ✅；当前引擎无注入 376 信号与基线 376 同数（DV 声明的 4 条差异=引擎演进已记录）✅ |
| **候选来源声明** | 6 族=现有生产族（v2-T13 SIGNAL_FAMILIES 已注册）；rise_contract/xishou_mid/second_wave 默认关族经 env 开启并声明——无新族注入 ✅ |
| **不碰生产** | 研究脚本不改 pipeline/；产物仅 `data/_exp_*.json`；不 bump ENGINE_VERSION ✅ |

## 六、DV 4 项方法论观察复核结论

| # | DV 观察 | 审计复核 |
|---|---|---|
| 1 | G1 对比基线口径对单族系统性偏严（基线含该族信号 → added 天然少 → fit_p 常 None） | **成立**。属预注册 DR 冻结口径，②如实执行；**不影响结论**——放宽 G1 亦无一族能全过四关（见 §二 结论稳健性） |
| 2 | G2 单族 vs 全引擎总收益对比信号量不对称（47~370 vs 376），maxDD 维度单族不劣 | **成立**。总收益差天然爆表（+602~+1423pp）；maxDD 改善属实（deep −20.4 / supply −18.5 / reversal −16.2 vs −30.9）；但 Calmar 各族 4.72~19.79 均远低于基线 48.97，G2 结论不受影响 |
| 3 | deep 为相对最强（G3 PASS + maxDD 改善 + val avg14 +35.8），仅显著性未过（G1 fit added=0 / G4 p=0.11） | **成立**。G4 p=0.11 在 seed7 下 0.138 稳定不显著；G1 无 fit 段样本内证据；样本 22（val）统计功效不足。**证伪符合预注册硬判据（任一关不过即划掉），非人为放行** |
| 4 | panic 事件簇依赖（val 段 155 信号集中 2026-05 单事件簇，无样本外证据） | **成立**。fit 段 0 信号 → G1/G3 证伪是预注册设计意图的正确执行；G4 p=0.018 显著仅说明单一事件内有效，n=1 事件簇不可外推。证伪正当 |

**结论**：4 项观察全部成立，均**不推翻**「6 族全证伪 → 多策略形态不成立」结论；deep 为相对最强但不足格，属于筛查层的正当证伪（不强推弱证据）。

## 七、非阻断登记（不影响裁定）

1. **G2 实现口径说明**（判据措辞与实现细节出入）：预注册 §3.2 语义为「劣化 ≥10pp 即不过」（单向，回撤比基线深 10pp 以上不过）；实现中 `d_dd = fam_dd − base_dd ≤ 10` 为双向门槛——**回撤改善 >10pp 亦判不过**（deep +10.47 / supply +12.33 / reversal +14.61 均因此 F）。由于三族 `d_total_pp` 均 >1000（远超 10pp 上限），即使按单向语义 G2 仍全部 F——**verdict 不受影响**。另：G2 两臂均未传 cap/熔断（裸跑模拟，与生产 cap0.8 口径不同），两臂同口径可比，相对比较有效；panic maxDD −139.9 含裸跑因素。登记供 PM 知悉（判据修订须重新预注册，本次按 DR 冻结口径执行）。
2. **冒烟测试环境登记**：独立重跑 142 passed / 2 failed / 0 skipped——2 个失败均为 `SKIP_NET` 标记的联网 API 用例（`market index API` / `item search suggest API`，依赖 csQAQ 外部数据源，当前环境不可达）；`CS_MODEL_SKIP_NET=1` 复跑 138 passed / 0 failed / 6 skipped（非网络用例全过）。**R3 研究产物（data/_exp_*.json + references 脚本）零回归**；与 DT（144/0/0，网络可用时）的差异为环境网络状态，非代码回归。待网络恢复后复核一次即可闭环。

## 八、裁定

- **R3 策略隔离评估复核通过**：6 族四关独立复算全一致、全部证伪；差异化三表数字一致；组合测试 0 候选 → **多策略形态不成立、单引擎（融合决策）维持为架构终态**——与 DV 结论一致，且结论对 G1 口径放宽、G4 seed 选择均稳健。
- **守院合规**：oos_zone 守院（fit 段探索、val 段仅预注册验证）、版本冻结 405/259,222/1015、零漂移归因成立、候选来源=现有生产族无注入、正负登记齐备。
- **不踩红线**：R3 仅到筛查层（产评估卡，不改引擎、不立落地卡）；审计未替②调参、未改判据到通过；两项非阻断登记（G2 实现口径说明 + 冒烟网络环境）移交 PM。
- 无生产改动、不 bump ENGINE_VERSION ✅。
