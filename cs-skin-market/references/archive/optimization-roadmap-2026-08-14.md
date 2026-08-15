# 系统优化路线图（2026-08-14）
> 已归档（2026-08-15）。唯一活 roadmap 为 `iteration-roadmap.md`；未收口问题已折入 iteration-roadmap，本文仅存证不再维护。

本文件汇总 2026-08-14 三轮问题审计后的统一优化路线。  
原则：先地图后基准，先证据后修改；不改任何未确认的引擎参数、阈值、信号族或决策行为。

## 0. 总判断

1. 一个 `in_sale_count`，四套口径：`avg7<10`、最新在售 `200/100`、`supply_depth` 最新一条、流动性深度分五档。
2. 守卫链靠隐式顺序，没有规则表；谁先拦、谁后升级、谁豁免，只能读代码推演，无法审计。
3. 回放与生产口径分叉：`bid_support` 回放中性 50、`survive_count` 回放为 0、旧 317 信号是旧 `<15` 地板产物。
4. 组合/仓位/退出没有闭环：信号族固定仓位与基础分档是策略层缺口，组合回测没有复现单品止损。
5. 最大结构性风险：深值/恐慌/供给收缩均为后置升级，实际**旁路**部分前置守卫，属于“不该买时买”的风控方向，不是“误伤机会”。

## 1. 数据边界（2026-08-14 核证）

| 数据 | 最早日期 | 317 信号覆盖 |
|---|---:|---:|
| price_history | 2025-08-14 | 317 / 317 |
| survive_history | 2026-02-14 | 225 / 317 |
| bid_history | 2026-05-15 | 133 / 317 |
| item_fundamental_snapshot | 2026-08-13 | 0 / 317 |

结论：`DECISION-4` 只能做“可用数据的守卫对齐 + 缺失守卫双向敏感性”，不能伪造完整生产等价回放。

## 2. 执行顺序

### Phase 0｜地图与基准
- `0.1` P-E：从代码生成守卫链 DAG + 规则表，不改行为，只做唯一事实源。
- `0.2` DECISION-4：守卫覆盖审计 + 当前生产口径对齐重放 + 缺失守卫双向敏感性。
- 产物：`_exp_guard_coverage.json`、`_exp_aligned_replay_v2T4.json`。

### Phase 1｜只读探针
- `P-A`：`supply_depth` 最新一条 vs 近 7 日中位数敏感性。
- `P-D`：`LIQ-RATIO-1` 前瞻交叉验证，明确无历史回放。
- `P-F`：旁路守卫影响量化，为 `DECISION-2/3/8` 提供是否修复的证据。
- `P-B`：`panic 0.25/0.35`、`supply_accum 0.15/0.20` 两格仓位复验。
- `P-C`：`hold21` vs 带 `stop/take` 组合回测 A/B。

### Phase 2｜低风险数据修正
- `DECISION-6`：`in_sale=0/缺失` 绕过地板的边界修复。
- `POOL-2`：`supply_depth` 稳健取值；落地后强制重跑对齐重放 + 双基线 `sync_expectancy_config` + P-B/P-C，且全部在 HIST-FULL vs CLEAN-CUR 双口径报告。
- `POOL-1/POOL-3`：淘汰标记结构化、观察期机制。

### Phase 3｜研究 A2
- `LIQ-RATIO-1`：前瞻 + 生产验证。
- `POS-8`：仅补 `panic 0.25/0.35`、`supply_accum 0.15/0.20`。
- `EXIT-9/10/11`：退出语义 + 组合止损 A/B。
- `POOL-4`：金额地板/冲击成本。
- `DECISION-5`：Z 门与周期反转对齐。
- `DECISION-2/3/8`：旁路守卫显式化/风控修复。

### Phase 4｜结构与展示
- `DECISION-10`：把 Phase 0 的规则表固化进文档和测试。
- `DECISION-7/9`：空洞与重叠审计。
- `POOL-5`：高分榜改名。
- `POOL-6`：非枪皮品类显式标注。
- `POS-12`：评级/仓位文案对齐。

## 3. 硬依赖

- `P-E → 所有探针`
- `DECISION-4 → P-B/P-C`
- `POOL-2 落地 → 重放 + sync + P-B/P-C 复核`
- `LIQ-RATIO-1 → 仅前瞻，禁止等历史回放`

## 4. 问题台账

### A. 数据口径与流动性
- `LIQ-RATIO-1`｜相对挂单率方向证伪（2026-08-15），不立项。P1。
- `POOL-1`｜双层淘汰口径并存、`notes` 自由文本不可回滚。P1。
- `POOL-2`｜`supply_depth` 取最新一条，单日脏值三处漂移。P0/P1。
- `POOL-3`｜自动淘汰无观察期。P1。
- `POOL-4`｜200/100 按单价而非成交金额。P1。
- `DECISION-6`｜`in_sale=0/缺失` 绕过地板。P0。

### B. 单品决策结构
- `DECISION-1`｜稳定性分与恐慌/超跌买点方向相反。P1。
- `DECISION-2`｜大盘走弱与深值/恐慌的隐式旁路。P1。
- `DECISION-3`｜连买抑制与供给收缩的隐式旁路。P1。
- `DECISION-4`｜回放/生产守卫分叉。P0。
- `DECISION-5`｜Z 门与周期反转方向不一致。P2。
- `DECISION-7`｜`sent∈(30,40)`、`pct∈(20,25)` 族覆盖空洞。P2。
- `DECISION-8`｜供给扩张过滤与供给收缩吸筹语义冲突。P2。
- `DECISION-9`｜阈值边界重叠。P2。
- `DECISION-10`｜守卫链无规则表。P0。

### C. 评分、仓位与退出
- `POS-7`｜族级固定仓位与基础分档的策略缺口。P2。
- `POS-8`｜族级仓位网格未复验。P1。
- `EXIT-9`｜组合回测未复现单品止损。P0/P1。（2026-08-15 不立项，维持 hold21）
- `EXIT-10`｜退出规则混用固定倍数与 ATR。P2。（同批不立项；ATR 网格无稳定增量）
- `EXIT-11`｜`hold21` 与 `take` 触发顺序未定义。P2。（同批不立项；hold21 仍为组合层退出）
- `POS-12`｜评级线与仓位线间隙。P3。

## 5. 已修正口径

- 深值、恐慌、供给收缩均为后置升级，实际绕过部分前置守卫，不是被前置守卫误伤。
- `supply_accum` 的 `prices>=8` 是价格序列长度，不是价格下限。
- 317 信号回放有回放流动性分和旧 `<15` 地板；`bid/survive` 是中性/0 兜底，等于未开火。
- 仓位覆盖在代码里确定，族级固定优先；不存在同信号随机走两条路径的 bug。
- 预筛 `pct_quick` 与决策层分位窗口基本同源，主要是高分榜命名不诚实。

## 6. Phase 0/1 执行结果（2026-08-14 收尾）

- ✅ `0.1 P-E`：`references/guard-chain-map.md` + `data/_exp_guard_chain_map.json`（代码生成，行为未改）。
- ✅ `0.2 DECISION-4`：对齐生产口径后 290 buy 为后续 P-B/P-C 基线；`data/_exp_guard_coverage.json` / `_exp_aligned_replay_v2T4.json`。
- ✅ `P-A`：中位数口径仅 4 条翻转，不落地；根因并入 `DECISION-6/POOL-2`。
- ✅ `P-D`：LIQ-RATIO-1 前瞻桶弱于对照但 n=7，不落地；继续生产侧积累。
- ✅ `P-F`：旁路为有意正优化，不补闸。
- ✅ `P-B`：panic 与 supply_accum 仓位变体均恶化；**deep_value 0.15 落地（v2-T5）**。
- ✅ `P-C`：组合 stop/take 使 Calmar 36.42→16.72，不落地；hold21 是组合优势来源。
- ✅ POOL-2（CLEAN-CUR 复核，2026-08-14）：supply_depth 最新 vs 近7日中位数仅 1 降级 / 0 升级，不落地，转数据治理；`probe_pool2_supply_depth_clean.py` → `data/_exp_pool2_supply_depth_clean.json`。
- `LIQ-RATIO-1` 已方向证伪（2026-08-15），不立项；`EXIT-9/10/11` 已不立项（2026-08-15）；后续仍开放：`DECISION-5/7/9`；DECISION-6/v2-T7/v2-T8 已完成。
## 7. 专家复核补正（2026-08-14）

- ✅ 止损路径信任提示已加到持仓建议卡（`analysis.html`）。
- ✅ deep_value 落地证据等级改为“低置信/方向性”，并挂 deep 成交≥30 / 生产 N≥30 复验触发器。
- ✅ 后置族旁路表写入 `decision4-guard-coverage.md`。
- ✅ Calmar 唯一标尺：`references/calmar_standard.py` + `data/_exp_calmar_standard.json`；EXIT-1 组合模拟与门槛符号已修复并重跑。
- `LIQ-RATIO-1` 已方向证伪、不立项；`EXIT-9/10/11` 已不立项并维持 hold21；双基线展示与 POOL-2 复核已落地。

## 8. 专家残留风险收口（2026-08-14）

- **风险2 · 共享底层污染排查（已排查，未污染）**：`data/benchmark_compare.json` strategy full 与 `data/_exp_calmar_standard.json` official_317_v2T4 完全一致（total +200.55%、maxDD −9.13%）；`references/portfolio_attribution.py` 实时复算也与 `data/portfolio_attribution.json` 完全一致（deep_value +59.39pp、accumulate +111.69pp、panic +56.35pp）。因此 EXIT-1 的两处 bug 未污染共享 simulate/risk_metrics 链路，官方基准与 A1-3 归因数字仍成立。注意：旧文档中的供给吸筹 +34.2pp 来自更早 hold14/口径，不与当前唯一标尺的 +111.69pp 归因混用。
- **风险1 · deep 复验前置（已登记）**：`DECISION-6`、`EXIT-9/10/11` 完成后，或 deep 成交≥30 / 生产 buy N≥30 任一满足时，必须用 `references/calmar_standard.py` 唯一口径 + 年化 Calmar 复算 `aligned_290_v2T4` vs `aligned_290_deep_value_0.15`，并报告 maxDD 对 deep 单票的敏感性；未达标不得仅凭 ±1 笔 deep 修改结论。
- **风险3 · 止损提示覆盖（本轮扩展）**：`analysis.html` 已覆盖；`watchlist.html` 持仓表止损参考、破位提示与执行记录区统一补提示。批量扫描当前版本已无「建议止损/止盈」列，不重复新增入口。


## 9. DECISION-6 收口与队列重排（2026-08-14）

- ✅ `DECISION-6` 已落地：NULL/断档 → `supply_depth_status=missing_depth` 禁 buy；真实 0 维持旧口径。生产翻转 0；对齐回放翻转 150（290→140）。
- 产物：`data/_exp_guard_coverage_decision6.json` / `data/_exp_aligned_replay_decision6.json` / `data/_exp_decision6_audit.json`；脚本 `references/decision6_audit.py`。
- 官方 317 回放因 365d 保留已删除 2025-08-10 前数据，不可重跑；已备份并回滚，`sync_expectancy_config` 复跑无变化。
- **队列重排**：`POOL-2` 原「仅 4 条翻转」结论作废，必须在 DECISION-6 新口径（140 buy）上复核；随后 `LIQ-RATIO-1` → `EXIT-9/10/11`。
- **中间数废弃（2026-08-14）**：`290` / `140` / `163` / `149` 均为中间推导，**已废弃，不得作为基线**；唯一基线=HIST-FULL 317 / CLEAN-CUR 149（v2-T8），见 `config.BASELINE_LEDGER.deprecated_intermediates` 与 `SIGNAL_FAMILY_TAXONOMY`。


## 10. 常驻数据治理项（2026-08-14）

- **`DATA-GOV-1`（常驻，不再挂在 POOL-2/DECISION-6 名下漂）**：`in_sale_count` 的「缺失（NULL/断档）」与「单日脏值」是同一治理对象：读侧统一 missing 标记 + 写侧单日跳变闸门（已有 `_guard_batch_write` 可复用），目标让 supply_depth / 地板 / 供给收缩三处消费同一份「已治理」序列。触发条件：再次发现单日在售量跳变/污染或任一消费点因脏值判定反转时启动；启动后必须回测先行 + 三件套 + 双基线复跑 sync。


## 11. LIQ-RATIO-1 方向证伪收口（2026-08-15）

- ✅ `P-D-0` 通过：bid_history 91 天 / 202 品可用，同日 in_sale join 100%，ratio 极值已 winsorize。
- ✅ `P-D-1`：横截面高 ratio 反而更差（fwd14 31.37%→23.26%、fwd30 48.34%→25.30%）；时序 fwd14 仅胜率单点单调但 avg 全负、fwd30 反向。判定：**方向证伪，不立项，在新增证据前不再投入**；caveat=仅 2026-05 后单 regime 前瞻。
- 已完成：`EXIT-9/10/11` ATR 自适应止损网格（calmar_standard 唯一标尺 + HIST-FULL / CLEAN-CUR 双基线）不立项，维持 hold21；待定项=EXIT 门槛唯一语义。


## 12. EXIT-9/10/11 收口与 EXIT 门槛语义待定（2026-08-15）

- ✅ `EXIT-9/10/11` 不立项：双基线复算与官方/干净基线一致；全部 `atr_stop` / `atr_trailing` 变体未过预注册门槛，最接近的 `atr_stop_4.0` 全局 Calmar 仅 +5.41%（HIST-FULL）、CLEAN-CUR 近中性；CLEAN-CUR 后半段弱势段 ATR 止损无改善甚至更差。结论：维持 hold21。
- ⏳ 待定：两轮 EXIT 门槛语义统一——`Calmar 提升 ≥15%` 应统一为 walk-forward 折上 Calmar 均值的相对提升；样本不足无 fold 时改用「全局 Calmar 绝对差 ≥1.0 且前后半段方向一致」。登记在 `calmar_standard` 待定项，禁止与全局相对提升混用。
- 队列状态：本批优化候选（DECISION-6 → POOL-2 → LIQ-RATIO-1 → EXIT-9/10/11）已全部走完；转入自然积累，等待 A 通道独立事件 ≥3 或 B 通道 260 天（约 2027-04）。

