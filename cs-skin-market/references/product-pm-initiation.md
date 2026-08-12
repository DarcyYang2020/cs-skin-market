# 产品优化立项书（2026-08-12）· 交付引擎侧评估

> 来源：references/product-pm-review.md（PM 评估）→ 本文档为立项转化版，供引擎侧评估实现可行性与边界。
> 用途：引擎侧（策略会话）逐项评估 A 线（零引擎参数，可直接实施）与 B 线（需回测/数据支撑）后，把通过的条目折入 references/iteration-roadmap.md。
> 纪律（沿用 references/project-principles.md）：涉引擎参数/信号规则的改动 = 回测先行 + 三件套（信号数/胜率/期望增量）+ 前后半段一致性 + 轻量置换；新信号族过 A2（walk-forward + 时间聚类 + 置换检验）。
> 定论基线只读：2026-08-10 四项审计 / I-13 / T4 / M-5 / W-3 / S-2 等，不重跑、不推翻，只能在其上扩展。

---

## 0. 立项摘要

- **北极星**：连续 30 天有新增执行记录（含买入/补仓）→ 解锁 A1-4 滑点校准（executions≥20）、真实 vs 纸面对照、2% 成本假设实盘验证（first-principles-gap.md 断点 1/2）。
- **A 线 · 产品体验优化（8 项，零引擎参数）**：修复/落地既有承诺功能 + 展示层聚合，引擎侧只做「口径确认 + 字段暴露」，不改任何决策行为。
- **B 线 · 策略与数据能力建设（7 项，需引擎侧评估/回测/数据支撑）**：先给评估结论（可行性 + 成本 + 回测方案），再决定是否立项。
- **引擎侧首批交付物（2026-08-12 已交付）**：回答 Q1-Q8 的评估结论（见 §3）；其中 Q1（signal_tracking 0 行诊断）与 Q3（回放产物 regime 分层）已实证答复并落地（A-1 恢复+对账、B-1 只读聚合），见 decision-log 2026-08-12 条目。

### 总览表

| 编号 | 事项 | 线别 | 引擎侧角色 | 依赖/前置 | 预估 |
|---|---|---|---|---|---|
| A-1 | 生产 buy 信号记录链路核验与补挂 | A | 口径确认 + 诊断（已落地） | Q1/Q2 ✅ | 2026-08-12 |
| A-2 | 执行环轻推（已记录状态/7天提醒/参考价一键确认） | A | 口径确认 | Q7 可选 | 2-3 天 |
| A-3 | 「今日关注」卡片 + 买点队列 v0 | A | 字段确认 | Q4 | 2-3 天 |
| A-4 | 文案口径清扫（replay 页头数据化 + 硬编码扫描） | A | meta 字段清单 | 无 | 0.5-1 天 |
| A-5 | 贴纸「观察桶·禁 buy」隔离标注 | A | 标记字段确认 | Q5 | 0.5 天 |
| A-6 | /checkup 双口径桥接 + 执行校准进度条 | A | 无（复用现有产物） | 无 | 1 天 |
| A-7 | 组合闸门状态接入组合仪表盘 | A | 字段确认 | Q6 | 1 天 |
| A-8 | 推送分层降噪（消费端） | A | 无（阈值不动） | Q8 可选 | 1 天 |
| B-1 | 期望条按 market regime 分层展示 | A（原 B 升线） | 只读聚合脚本（已落地） | Q3 ✅ | 2026-08-12 |
| B-2 | 求购因子验证与展示（F-2） | B | 90+ 天样本后三件套 | 样本积累 | 待 F-2 |
| B-3 | 贴纸吸筹正式 A2（W-3） | B | n 积累 + regime 分层 A2 | 时间簇≥3 | 积累中 |
| B-4 | 钉钉 action 卡片一键执行（F-7） | B | 幂等/回链设计 | 资金安全设计 | 待定 |
| B-5 | 成本建模进回测（F-4） | B | 成本函数库 | A1-4 样本 | 待定 |
| B-6 | monitor 提醒层阈值评审（可选） | B | 若调需评审/回测 | 用户确认 | 待定 |
| B-7 | 买点队列 v2「队列→引擎判定」对照（研究） | B | 新信号族研究，A2 前置 | Q4 后 | 不排期 |

---

## 1. A 线：产品体验优化（零引擎参数）

> 原则：不改信号、不调阈值、不重跑回放；引擎侧配合 = 确认口径 + 暴露只读字段 + 给出诊断结论。落地条目按纪律在 decision-log.md 记一行「展示/监测口径」。

### A-1 生产 buy 信号记录链路核验与补挂（数据/监测层）—— 2026-08-12 已落地
- **目标**：让 J-2 C 通道「生产实盘判定」真正积累；「回放告警 vs 实盘 0 样本」的并排不再误导。
- **诊断结论（Q1，2026-08-12 实证）**：
  1. **链路本身是通的**：`record_buy_signal` 有两个挂接点——`webapp/analysis_service.py:646`（analyze_fresh，2026-08-07）+ `pipeline/scan_tasks.py:187`（batch_scan）。PM 版「只在 scan_tasks 挂接、analysis_service 只 import」判断不成立。
  2. signal_tracking **曾有 1 行**：`monitor_events` id=459（08-09 `new_buy_signal`，AK-47 轨道 Mk01，入场 ¥717.49，dedup_key 带旧 id 59）可证。
  3. **行在 2026-08-11 items id 重排后丢失**：commit `1060af7` 明确记录「同步更新 8 张引用表」；备份证据——`data/market.db.bak-before-reindex-20260811` 有 1 行；`data/market.db.bak-execadvice-20260812`（08-12 13:43）已是 0 行。
  4. 后续 0 行**正常**：08-12「已到买点」是 near_buy proximity 100%（watch 级）非 fusion buy；弱市下近 8 天无新 buy。
  5. 根因隐患：`signal_tracking` 表定义含 `ON DELETE CASCADE`（`pipeline/signal_tracking.py:26`），items 物理删除/重排是唯一清空路径。
- **落地（2026-08-12）**：
  1. 备份回填 1 行：`data/market.db.bak-before-reindex-20260811` → 当前 `market.db`（id 59→44，去重键校验后插入），monitor 事件留存不变。
  2. 级联防护：`pipeline/signal_tracking.py` 新增 `reconcile_production_signals(conn, date)`（snapshots 当日 buy/oversold_buy vs signal_tracking 当日新增查缺失，只读）；`run_daily_collect.py` 每日任务挂接，缺失留痕 `data/signal_tracking_reconcile.jsonl`，异常不中断采集。
  3. data-layer.md §4 维护清单补充「items 物理删除/重排前必须检查 signal_tracking」防护说明。
- **验收**：① 诊断结论落 decision-log（2026-08-12）；② 备份行已恢复且 monitor 事件留存不变；③ t_signal_reconcile 冒烟覆盖缺失检测（101 passed）。
- **预估**：已完成（原 1-2 天）。

### A-2 执行环轻推（体验线）
- **目标**：buy/add 侧录入摩擦降到最低，向北极星推进（现 buy/add 执行 0 条）。
- **内容**：① 报告/批量扫描 buy 行「✅ 已记录执行」持久状态（近 7 天同品同信号查 executions）+ 7 天未录提醒（E-2「建议未执行」标记扩展）；② 执行弹窗成交价预填当前锚价、一键确认（保留可编辑，去掉二次确认；/api/watchlist/executions/ref-price 现有逻辑）；③ watchlist「我的执行」汇总入口前置（watchlist.html:186 卡片区）。
- **引擎侧任务**：确认「已记录执行」判定口径（同品 + 建议日期窗口 + action 类别）；评估是否值得加 advice_id 让 executions 可回链 signal_tracking（见 Q7，若做属表结构变更，需引擎侧排期）。
- **验收**：录入 1 笔 buy 后报告按钮变「已记录」；7 天未录的 buy 建议在自选页有标记。
- **预估**：2-3 天。

### A-3 「今日关注」卡片 + 买点队列 v0（体验线）
- **目标**：把 8/12 出现的 4 条 near_buy 100% 事件（data/market.db monitor_events）变成「今天该看谁」的一屏；填补 monitor 只读提醒 → Web 找品的断层。
- **内容**：① watchlist/dashboard 顶部「📌 今日关注」卡片：当日 near_buy/stop_loss/price_spike 事件聚合 + 一键打开报告（6h 报告缓存命中 <100ms）；② 队列排序主口径 = proximity（buy_distance.py:190 已产出 gap_pct/gap_rmb/scenario/z_gap/th_gap），buy 信号置顶，每行带采集时间。
- **引擎侧任务**：确认 proximity 输出结构是否足够支撑队列排序；评估是否补「最近 buy 信号日期/7 天去重」字段（Q4）。
- **红线**：队列只聚合展示 fusion_decision/proximity 输出，**不接线新信号**；「接近买点 ≠ 买点，以报告决策条为准」提示必须保留。
- **验收**：队列排序与批量扫描/报告口径一致（t_buy_queue 冒烟）；每行显示采集时间；点击报告 <100ms。
- **预估**：2-3 天。

### A-4 文案口径清扫（体验线/信任线）
- **目标**：消除死文本口径漂移（replay.html:7「503 个 buy 信号 / 2025-01-01~2026-08-05」vs 现状 317 信号 / 365d 窗口）。
- **内容**：replay 页头改由 /api/signals/replay 的 meta（count/range/generated）注入；全仓 rg 扫「503|370|332|2025-01-01」等硬编码口径文案。
- **引擎侧任务**：给出官方口径常量清单（REPLAY 窗口 / 信号数 / ENGINE_VERSION / 成本 2%），供展示层引用；若已有 t_ 校验则沿用。
- **验收**：replay 页头与回放产物一致；无残留硬编码口径文案（可加 t_replay_page_copy 冒烟）。
- **预估**：0.5-1 天。

### A-5 贴纸「观察桶·禁 buy」隔离标注（体验线）
- **目标**：discover 贴纸高分（综合 9.4 居首）与「禁 buy」决策的视觉隔离，防误导（贴纸 buy 被观察桶守卫，S-2/W-3 结论）。
- **内容**：贴纸行/榜加「🧪 观察桶 · 未进 buy」徽章 + 综合榜顶部一行说明。
- **引擎侧任务**：确认贴纸判定/标记字段的权威来源（当前守卫隐式实现，Q5）——若建议暴露 sticker_bucket 只读字段，属字段新增，评估成本。
- **验收**：贴纸行有观察桶标注；综合榜与贴纸榜口径说明清晰。
- **预估**：0.5 天（不含引擎侧字段新增）。

### A-6 /checkup 双口径桥接 + 执行校准进度条（体验线/信任线）
- **目标**：① 解释「回放告警（信息级）≠ 实盘劣化」；② 把 A1-4 门槛（executions≥20）产品化为进度条，给录入动机。
- **内容**：C 通道区块固定一行桥接说明；watchlist 执行区显示「录入 N/20 解锁滑点/胜率校准」进度（dashboards.py execution_review 同源）。
- **引擎侧任务**：无（复用 j2_channel_monitor.py 产物与 executions 统计）。
- **验收**：checkup 两口径解释清晰；进度条 N 与实际一致。
- **预估**：1 天。

### A-7 组合闸门状态接入组合仪表盘（体验线）
- **目标**：熔断 10% / 单票敞口 30% 提示（B1 层参数已有，纯提示）在 UI 可见。
- **内容**：组合仪表盘（/api/portfolio/dashboard）加熔断状态卡（读 portfolio_risk.drawdown_status，已产出 peak/current/drawdown_pct/breaker_active）+ 单票敞口提示列（single_position_exposure，阈值 30%）。
- **引擎侧任务**：确认 drawdown_status 字段语义与单票敞口计算口径（Q6）；**参数本身不动**。
- **验收**：仪表盘显示组合回撤与熔断状态；敞口超 30% 的单品有提示徽章。
- **预估**：1 天。

### A-8 推送分层降噪（体验线）
- **目标**：单次推送 37-51 条事件噪音下降；高价值事件（新 buy / 持仓破位）不被淹没。
- **内容**：持仓 danger 置顶；near_buy 降为「仅计数 + Top3 品名」；只动 monitor.py _build_push_text 消费端。
- **引擎侧任务**：无（事件生成阈值 near_buy 60 / stop_loss 0.75 / supply_shift 区间本次不动；若评估该调，走 B-6）。
- **验收**：推送明细条数下降；持仓 danger 恒置顶。
- **预估**：1 天。

---

---

## 2. B 线：策略与数据能力建设（需引擎侧评估 / 回测 / 数据支撑）

> 每条先给「引擎侧评估结论」再立项；凡动参数/信号/回放产物的条目，回测方案按 §4 模板执行。

### B-1 期望条按 market regime 分层展示（展示层 + 引擎数据聚合）—— 2026-08-12 升 A 线并已落地
- **现状**：报告期望条只给全窗口 win14/avg30（365d 回放 317 信号口径），与当前 regime（如「阴跌中继区」）无关联；j2_channel_status.json C.monthly 显示 2025-11/12 月 14d 仅 64.3%/54.5%——全窗口均值会掩盖 regime 差异。
- **Q3 结论（2026-08-12 实证）**：回放产物 `data/item_backtest_full_2025.json` **每条信号已含** `sentiment / market_th / mkt_chg30 / market_cycle`（无需补列、无需重跑回放）；状态桶可直接套 `pipeline/market_context.py:161 state_bucket`（六态），重跑成本 ~0。
- **落地（2026-08-12）**：只读聚合脚本 `references/expectancy_by_regime.py` → 产物 `data/_exp_expectancy_by_regime.json`（regime × 族 panic/deep_value/accumulate 的 n/win14/avg14/win30/avg30，net 已扣 2%，win = net>0；族口径同 `ITEM_EXPECTANCY_STATS` 展示键，`t_expectancy_sync` 未触碰）。展示层接入属 A 线后续（前端任务）。
- **决策点**：不动任何阈值；只新增「当前 regime 下的历史分位胜率」展示口径。
- **回测要求**：不涉及参数，不强制三件套；产物是新增只读聚合，不改变 `item_backtest_full_2025.json`，无需走 sync 链重跑。

### B-2 求购因子验证与展示（F-2，90+ 天样本）
- **现状**：snapshots 已落 bid_highest/bid_7d_chg/spread_pct/spread_avg/bid_30d_chg 5 列（bid-data-accumulation.md）；bid_30d_chg 口径不可信仅存档；bid_count 是估算不持久化。
- **引擎侧任务**：样本 ≥60-90 天后执行验证计划（质量守卫 → 因子检验「供给收缩 × 求购配合 vs 背离」14/30d 胜率与期望 → 口径复验 → 决策融入与否）；**展示层加「求购断层」提示列仅在验证通过后议**（现计划明确不展示）。
- **回测要求**：若并入族条件/守卫 = 新因子 → 三件套 + A2（walk-forward + 聚类 + 置换）。

### B-3 贴纸吸筹正式 A2（W-3）
- **现状**：探索版 39 前视 win30 69.2%（候选，未达 A2）；66 信号跟踪已挂每日任务（w3_signal_tracker.py）；alpha 口径 = 相对市场选品 alpha（crash +7.4% / calm +9.3%），绝对收益依赖市场。
- **引擎侧任务**：n 积累（pending 27 落地）+ 时间簇 ≥3 + regime 分层检验 + walk-forward 前半段补齐 + supply 在售量维度探索；全部通过前不进 buy、零引擎参数。
- **回测要求**：A2 三件套 + regime 分层判定。

### B-4 钉钉 action 卡片一键执行（F-7）
- **现状**：推送纯文本无链接（安全有意）；D-3 转化 5.2%；executions API 已有幂等/去重基础（UNIQUE 约束 + advice_date 语义）。
- **引擎侧任务**：评估 advice→exec 回链设计（Q7：advice_id / 信号 ID 是否值得加）；二次确认 + 幂等 + 资金安全设计文档；**不做**：无确认直接下单类操作。
- **前置**：A-8 推送降噪先行（否则 action 卡片会被噪音淹没）。

### B-5 成本建模进回测（F-4）
- **现状**：回放统一扣 2% 双边（run_item_backtest_full.py:52 cost=0.02）；cost_sensitivity.py 已有雏形未接入官方基准链；A1-4 等 executions≥20 校准。
- **引擎侧任务**：A1-4 样本到位后，把 2% 升级为「价差 + 手续费 + 流动性冲击（in_sale_count 越小冲击越大）」成本函数库；评估对基准产物（item_backtest_full_2025.json）与 sync 链的影响。
- **前置**：北极星（执行环日常化）→ A1-4 样本。

### B-6 monitor 提醒层阈值评审（可选）
- **现状**：near_buy 60 / stop_loss 0.75 / supply_shift (-20,30) / price_spike 8.0 为提醒层参数（monitor.py，人工确认不回测拟合）。
- **引擎侧任务**：若 A-8 降噪后仍觉噪音，评估阈值是否需要调整——提醒层参数改动走单独评审（影响面 = monitor_events 生成与推送），必要时给简单回测/事件统计支撑；本次默认不动。

### B-7 买点队列 v2「队列触发 → 引擎判定」对照（研究项）
- **现状**：A-3 队列只聚合；用户可能「接近买点就手痒」。
- **引擎侧任务**：评估「队列触发（proximity≥60/100%）→ 引擎 buy 是否兑现」的对照统计设计（属新信号族研究，须 A2 三件套 + 事件级样本），作为未来「是否把 proximity 升级为决策输入」的证据；**在 A2 通过前不接决策**。
- **排期**：不排期，随 A-3 数据积累。

---

## 3. 引擎侧评估重点问题清单（Q1-Q8，首批交付物）

| # | 问题 | 影响条目 | 期望产出 |
|---|---|---|---|
| Q1 | signal_tracking 0 行：scan_tasks.py:187 记录分支为何未产生记录？（buy 稀缺 vs 分支异常 vs 事务问题） | A-1 | ✅ 已答（2026-08-12）：链路双挂接均通，行为重排级联删除丢失，已回填+对账 |
| Q2 | record_buy_signal 口径（entry/action_label/engine_version/去重键）与回放是否一致？analyze_fresh 补挂对 C 通道统计有无影响？ | A-1 | 口径确认 + 影响评估 |
| Q3 | 回放产物 item_backtest_full_2025.json 能否按 regime 分层聚合 14/30d 胜率？若需补 regime 列，重跑回放 + sync 链成本/风险？ | B-1 | ✅ 已答（2026-08-12）：字段齐备免重跑，B-1 只读聚合已落地 |
| Q4 | buy_distance proximity 输出（gap_pct/gap_rmb/scenario/z_gap/th_gap）是否足够支撑买点队列排序？是否补「最近 buy 信号日期/7 天去重」字段？ | A-3 / B-7 | 字段确认 |
| Q5 | 贴纸「观察桶·禁 buy」有无权威标记字段可暴露给展示层？（当前守卫隐式实现） | A-5 | 字段方案（可选） |
| Q6 | portfolio_risk.drawdown_status（breaker_active 等）与 single_position_exposure 30% 语义确认，展示层直接消费是否 OK？ | A-7 | 确认 |
| Q7 | executions.advice_signal 为自由文本无法回链 signal_tracking：加 advice_id/信号 ID 是否值得？（表结构变更，评估收益/成本） | A-2 / B-4 | ⏸ 暂缓（2026-08-12）：executions 仅 8 行，样本不足以评估回链收益，待 ≥20 行再审 |
| Q8 | monitor 提醒层阈值（near_buy 60 等）是否要评审调整？若不调，仅消费端降噪（A-8） | A-8 / B-6 | 结论 |

---

## 4. 回测/验证纪律（B 线任何动参数/信号条目必须遵守）

1. **三件套**：信号数 / 胜率 / 期望增量，逐层记录单层增量 + 叠加回归（project-principles.md「算法改动验证流程」四步）。
2. **前后半段一致性**：回测窗口按时间切半，两段方向一致才可落地（2026-08-12 第四批④）。
3. **轻量置换检验**：符号/随机置换 ≥200 次，报告 p 值或效果量；n<30 或事件簇受限时标注「样本不足仅记录」。
4. **新信号族 A2**：walk-forward OOS + 时间聚类去簇 + 置换检验，缺一不可（I-3 教训）。
5. **回放产物变更**：走「改产物必须重跑同步」链（sync_expectancy_config / sync_replay_snapshot / benchmark_compare / portfolio_attribution）+ t_expectancy_sync / t_replay_snapshot 硬校验。
6. **监测/展示口径变更**：decision-log.md 记一行，不触发回测（A 线全部 + B-1 若不重跑回放）。

---

## 5. 边界与不做清单

- **不做**：任何引擎参数/阈值/信号规则的直觉改动（禁止，回测先行纪律）；「买点队列接 buy 信号」（A2 前）；贴纸吸筹未过 A2 进 buy；求购因子未验证进决策；monitor 阈值未经评审调整。
- **不重跑/不推翻**：2026-08-10 四项审计 / I-13 深值企稳段限定 / T4 chg8 禁买 / M-5 TH 反向 / W-3 探索版结论 / S-2 贴纸与 Major 脱钩。
- **数据保护**：不动 price_history 历史行（B-1 增量写已生效）；不删数据；新增字段走 db.py 幂等迁移。

---

## 6. 排期与闭环

- **近 2 周（并行）**：A-1 ~ A-8 按依赖序推进（A-1 → A-2/A-3 → A-4~A-8 可并行）；B 线先交 Q1/Q3 评估结论，其余按样本/前置条件自然触发。
- **闭环标准（每项）**：tests/test_smoke.py 全绿（100/0/0）→ pyflakes 无告警 → 涉及展示口径的条目在 decision-log.md 记一行 → 服务重启生效（reload=False）。
- **与 roadmap 的关系**：A-1→J-2 配套；A-2→F-1 增强；A-3→F-7 轻量先行（monitor 消费端）；A-4→2026-08-12 口径审计延伸；A-5→S-2/W-3 展示落地；A-6→A1-4 门槛产品化；A-7→B1 提示层 UI；A-8→D-3 延伸；B-1 新（回放聚合）；B-2→F-2；B-3→W-3；B-4→F-7；B-5→F-4；B-6 新（提醒层评审）；B-7 新（研究）。
- **会话分工**：引擎侧改动集中在 pipeline/（item_analysis / signal_tracking / monitor / buy_distance / portfolio_risk / 回放产物）；A 线展示改动归前端短任务会话（webapp/main.py / templates）；避免并行改同一文件（AGENTS.md 会话分工约定）。
