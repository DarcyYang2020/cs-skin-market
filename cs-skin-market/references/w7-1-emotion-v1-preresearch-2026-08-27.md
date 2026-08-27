# W7-1 内生情绪 v1 · 预研准备（②算法研究窗口交付）

- **卡**：roadmap v82 W7-1（挂账等数据：内生情绪 v1）
- **背景**：R5（v0 内生情绪分）2026-08-27 收口，verdict=无增量证伪成立（decision-log DY，③审计 DZ 通过）；v1 是 v0 升级版，补盘口因子看能否翻盘。
- **状态**：**预研准备（不立执行卡、数据未够）**——等 W7-2 steamdt 积累够（3-6 月）后由②交付预注册判据再立卡。
- **红线**：候选须来自引擎独立扫描、不照镜子（C2 教训）；pre-registered 方法论要求样本外/积累，不能即采即落。

---

## 0. 预研结论速览（PM 三问）

| # | 问题 | 结论 |
|---|---|---|
| ① | v1 因子组成 | bid + spread + turnover + steamdt（成交额，W7-2 新采） |
| ② | D2/D7 已采字段可用性/覆盖度/可否回测 | **bid ✅ 可回测**（1157 天全量、fit 774 天、buy_price_max 100% 非空、R1 组9 已评 86.9% 覆盖）；**spread ✅ 可回测**（price×bid 派生，R1 组9 已评 86.9%）；**turnover ⚠️ 仅 2 天快照，不可回测**；**lowest_sell/sell_count（D2 卖侧）⚠️ 仅 207 行（08-27 起采），不可回测** |
| ③ | 预研方法论文档 | 见 §3：R1-R5 同款「预注册判据 → 增量 IC → 四关验证」评估 v1 增量信息 |

---

## 1. v1 因子组成（预注册草案，非冻结）

**v1 = v0 基础（恐慌分 + 供给/动量调节）+ 盘口增量因子**：

| 因子 | 数据源 | 是否新采 | 角色 |
|---|---|---|---|
| 恐慌分（approx_sentiment） | price_history 派生 | 否 | 主组件（v0 复用，R1 已评 +0.142 候选·无增量） |
| 供给变化 sc30 | price_history.in_sale_count | 否 | 调节（R1 已评条件 IC 候选） |
| 动量 chg7 | price_history 派生 | 否 | 调节（R1 已评 −0.130 不稳定） |
| **bid**（buy_price_max） | **bid_history（已采未用 = 富矿）** | 否 | **增量主候选**（R1 组9 已评弱/无效 −0.011，v1 侧重合成非线性） |
| **spread**（price×bid 派生） | bid_history × price_history | 否 | 增量候选（R1 组9 已评不稳定 −0.097） |
| **turnover**（成交额/成交量） | item_fundamental_snapshot（已采但仅 2 天） | 否（存量） | 增量候选（**数据不足，先挂**） |
| **steamdt 成交额** | W7-2 新采 | **是** | 增量候选（**数据前置，等 3-6 月积累**） |

**v1 合成形式（草案）**：`emo_v1 = clip(emo_v0 + w3·bid_norm + w4·spread_norm + w5·turnover_norm + w6·steamdt_norm, 0, 100)`——**具体权重/合成形式须在正式预注册判据中冻结**（本稿仅预研，不冻结任何参数）。

---

## 2. 数据可用性核验（2026-08-27 只读实测）

> 口径：fit 段 = date < 2025-08-10（oos_zone val_start，D6）；与 R1 同源（生产库 market.db + 回放库 name 桥）。

### 2.1 bid_history（D2 已采，主富矿）
| 项 | 实测值 |
|---|---|
| 表结构 | `date, item_id, good_id, item_name, source, platform, buy_price_last/min/max/mean, buy_num_*, point_count, created_at, lowest_sell, sell_count`（D2 卖侧列） |
| 总行数 / 天数 | **231,816 行 / 1,157 天**（2023-06-27 ~ 2026-08-27） |
| **fit 段（<2025-08-10）** | **151,474 行 / 774 天**（2023-07 起每月 29-31 天全量） |
| buy_price_max 非空率 | **100%**（231,816/231,816） |
| 覆盖 good_id | 244（矩阵 name 桥命中 221/231，R1 组9 实测覆盖率 86.9%） |
| **可否回测** | ✅ **可**——R1 组9 已按主评 IC 跑过：**bid IC14 = −0.011（弱/无效）**；v1 侧重合成后是否产生增量 |
| lowest_sell / sell_count（D2 卖侧列） | 非空仅 **207 行**（2026-08-27 随 p0 --apply 开始落库，历史无）→ **暂不可回测**，前向积累 |

### 2.2 spread（price×bid 派生，不新采）
- 派生：`spread = price_history.price_rmb − bid_history.buy_price_max`（R1 组9 口径，name 桥对齐）。
- **可否回测**：✅ 可——R1 组9 实测覆盖 86.9%、**IC14 = −0.0965（不稳定，滚动同号 0.1875）**；v1 侧重合成非线性。

### 2.3 item_fundamental_snapshot（turnover，已采但数据极少）
| 项 | 实测值 |
|---|---|
| 表结构 | `yyyp_*/buff_*/c5_*/steam_* 价格量, turnover_number, turnover_avg_price, sell_price_rate_*, rank_num, statistic, extra_json` 等 |
| 总行数 / 天数 | **409 行 / 仅 2 天**（2026-08-13、2026-08-27） |
| turnover_number 非空率 | 100%（但仅 2 个快照日，无历史序列） |
| **可否回测** | ❌ **不可**——仅 2 天快照，无时间序列，无法算 IC/回测；**存量即此，等后续每日积累** |

### 2.4 bid_observations（周度求购观察，B-5）
| 项 | 实测值 |
|---|---|
| 表结构 | `date, item_id, good_id, item_name, price_rmb, in_sale_count, bid_highest, bid_7d_chg, bid_30d_chg, spread_pct, spread_avg, quality_note, source` |
| 总行数 / 天数 | **7 行 / 4 天**（2026-08-13 ~ 2026-08-27，周度手动采样 limit 8） |
| **可否回测** | ❌ 不可（样本过少）；作为 bid 的**交叉验证/质量参考**，不进入 v1 主评 |

### 2.5 steamdt 成交额（W7-2 新采）
- **数据前置**：W7-2「steamdt/求购成交」合规累积口径（DU 挂账，3-6 个月再评），**未采、未定采**。
- v1 不依赖 steamdt 即可先评 bid/spread/turnover 增量；steamdt 到位后作为 v1 增量扩展（重新预注册）。

---

## 3. 预研方法论（v1 增量信息评估方案草案）

> 对齐 R1-R5 同款流程：**预注册判据 → 增量 IC 硬判据 → 族开回放 → 四关 → ③审计**。本稿为方法论骨架，**正式判据由②在数据齐备后交付、PM 冻结后方可执行**。

### 3.1 评估对象与顺序
1. **第一轮（存量数据可跑）**：v1a = v0 + bid + spread（bid_history 已够回测）——评估**盘口因子合成是否带来增量 IC**；
2. **第二轮（等 turnover 积累）**：v1b = v1a + turnover（item_fundamental_snapshot 需 ≥3 个月每日积累）；
3. **第三轮（等 W7-2）**：v1c = v1b + steamdt（W7-2 数据积累够后）。

### 3.2 预注册判据要素（跑前定死）
- **v1 合成定义**：组件 + 权重（**固定值禁优化**，权重变化=新预注册）+ 归一化（fit 段截面 rank，与 R5 同规则）；
- **增量 IC 硬判据**：对核心因子集（pct/z/chg30/sc30/vol30/mchg30，R1/R5 同款）截面回归取残差 → **增量 IC ≥0.02 且滚动同号月 ≥80% → 候选**；否则无增量/证伪登记（与 R5 完全同口径，保证可比）；
- **族开回放 + 四关**（若增量 IC 候选成立）：族开回放 → A2 发射复算 + 组合级 + 前后半段 + 置换检验（R3 同款四关）→ ③审计；
- **仅加分/过滤**：v1 若候选，仍按 v0 边界——**仅作引擎守卫/加分项，不进打分主干、不改族触发**；
- **oos_zone 守院**：探索仅 fit 段（require_fit，D6）；val 仅预注册声明的复验触碰；
- **候选来源声明**：候选须来自引擎独立扫描（bid/spread/turnover 为新增未用数据维度，非引擎已发射信号分桶选阈值——**不照镜子，C2 教训**）。

### 3.3 前置依赖
- **数据**：bid_history ✅（已够）；turnover ❌（需积累 ≥3 月）；steamdt ❌（W7-2 积累 3-6 月）；
- **S1/D2**：D2 卖侧列（lowest_sell/sell_count）前向积累中；S1 悠悠账号 PM 拍板默认不开（DU），不影响 v1a/v1b（bid 主价已有）；
- **D6 oos_guard** ✅（R1 接线，R5 沿用）。

### 3.4 关键预期（诚实登记，非判据）
- R1 组9 已证 **bid/spread 单因子弱/无效或不稳定**（日频截面 IC 层面）——v1 翻盘机会在**合成非线性交互**（与 v0 逻辑一致），但 R5 已证 v0 合成亦无增量；**v1 大概率延续无增量结论**，仍需按流程验证一次（正负都登记）。

---

## 4. 交接与流向

- **产物**：本预研文档（references/w7-1-emotion-v1-preresearch-2026-08-27.md）——数据可用性核验 + 方法论骨架；
- **不立执行卡**：turnover/steamdt 数据未够，按 PM 指令维持挂账；
- **触发条件**：①bid/spread 存量评估可随时启动（v1a，待 PM 立卡/②交付正式判据）；②turnover 积累 ≥3 月；③W7-2 steamdt 积累够（3-6 月）→ ②交付 v1 预注册判据 → PM 冻结 → 执行。
- **状态**：**预研准备完成（2026-08-27）**，登记 decision-log；W7-1 维持挂账（等数据）。
