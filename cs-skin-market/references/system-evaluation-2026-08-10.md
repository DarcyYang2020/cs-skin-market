# 系统全貌多专业角度评估（2026-08-10）

> 评估范围：cs-skin-market 系统全貌（数据/工程/产品/风控流程/领域特性/安全），聚焦「评估指标体系第一性审计」未覆盖部分；指标审计已定论结论直接引用、不重跑。
> 方法约束：必读文档（根/子 AGENTS.md、PROJECT_STRUCTURE.md、project-principles.md、iteration-roadmap.md v1-v49、decision-log.md 最近 12 章节、git log -20）+ 代码走读 + 数据实证（market.db 只读查询、回放/基准/监测产物）。
> 基线说明：工作区 5 个未提交文件（2026-08-10 未持仓修复 + decision-log 条目，见 git status）视为当前基线；本评估只读不改码。
> 结论三档：✅ 确认适用 / ⚠️ 需修正（附证据）/ ⏳ 待数据或回测验证。优先级：P0 影响决策正确性 / P1 影响使用效率与可信度 / P2 优化打磨。改动成本：小=≤0.5 人天，中=0.5~2 人天，大=>2 人天或分期。

## 0. 数据基线快照（market.db 只读，2026-08-10）

- items 189（good_id>0:188；自选 38；持仓 7；淘汰/存世量过低 11）——「260 品池」为规划目标，实际 188
- **（2026-08-11 更新）** items 326（扩池 +135 后）/ **活跃池 203**（收敛定论：刀 71 + 手套 14 + 非崭新出厂 27 标记淘汰，数据保留）/ 自选 39（含持仓 6）；price_history 56,471 行
- price_history 43,755 行 / 188 品，窗口 2025-08-10 ~ 2026-08-10（恰为 365 天保留上限）
- executions 7 条；signal_tracking 生产 1 条（engine v2-I13）
- health_checks 最近 3 次 FAIL：全市场快照 4404 行 > 3500 阈值（连续 3 天，阈值未随池扩容更新）；2026-08-09 单品 K 线覆盖 147/188 < 85%
- 回放基线：item_backtest_full_2025.json（365d 窗口，332 信号，win14 69.9% / avg14 +15.36，net 扣 2%）
- 基准对照：benchmark_compare.json（策略 +83.65%/-13.05% vs 池内等权 +252.31%/-55.59% vs 大盘 -24.2%/-58.21%）

## 1. 量化策略 / 金融工程（仅限指标审计未覆盖的策略层）

**总体判断：✅ 结构合格；⚠️ 2 处需修正；⏳ 2 处待回测/数据验证。**

- ✅ **信号族覆盖度与闸门链完整**：4 个 buy 信号族（panic_resonance / deep_value / panic_easing / supply_accum）+ 基础族 + 超跌反弹例外，守卫链 守卫1 → 升级族1 → 守卫2 → 分级仓位 → 供给扩张过滤 → 后置族 层次清晰（item_analysis.py:979-1072 注册制；:1218-1219 _GUARD1/_GUARD2；:1502-1530 顺序）；F-3.5 流动性闸门堵住「降级后升回 buy」绕过路径（decide_fusion_signal 检查 not fd.liquidity_filtered）。与 AGENTS.md 闸门链描述一致。
- ⚠️ **A1-1 周期洗盘降级与「洗盘期最优」结论方向相反（P0，成本中）**：2026-08-10 审计定论「洗盘期 win14 82.2%/+18.9、win30 +30.6 最优」（decision-log 四项审计），周期评分权重 consolidation=2.5 最高（item_analysis.py:630-634）；但 `compute_fusion_decision` 在 `cycle_phase=="consolidation"` 且基础 buy 时仍降级 watch「周期洗盘·观望」（trend_health.py:900-906）。当前 82.2% 是降级存在下的回测口径——降级只压制基础族 buy（低估+TH≥55），但评分奖励洗盘、决策层却压洗盘，方向矛盾。**需回测 A/B（环境变量开关，如 CS_ENGINE_NO_CONSOLIDATION_DOWNGRADE=1）**：移除降级后信号数/胜率/期望三件套。若证实正优化再落地（PARAM_REGIME 台账 + 回放产物同步）。注意：信号族路径（supply_accum 等）在洗盘期仍可升级 buy，本项只影响基础族。
- ⚠️ **A1-2 deep_value 情绪窗口存在 66-74 无主区（P1，成本中）**：deep_value 要求 `40<=sent<=65`（item_analysis.py:1014），panic 要求 `sent>=75`（:986），panic_easing 要求 `55<=sent<=80` 但需 `mchg30<=-15 且 stopped`（:1034）。sent∈[66,74] 且不满足 easing 条件的深值品无 buy 路径。**回测验证**：放开 deep_value 上限 65→75（或新增 sent 66-74 的族条件）在 365d 回放上的边际信号与期望（数据现成，无需新采集）。此项属「新增信号条件」，须 A2 三件套（walk-forward + 聚类 + 置换检验）后落地。
- ⚠️ **A1-3 组合层绩效归因缺失（P1，成本中）**：benchmark_compare.json 只有总量对照（83.65% vs 252.31% vs -24.2%），结论「引擎边际价值在风控（maxDD 13.05% vs 55-59%）」成立，但「策略为何低于池内等权」未分解——是入场择时、14d 持有退出、cap0.8 仓位上限还是池内暴涨品主导（note 已提示 2025 低价品暴涨主导）？**建议基于回放产物做族级/月度/持仓期贡献归因脚本**（纯分析，不动引擎），把「低于等权」拆成可解释分量。低成本高解释力。
- ⏳ **A1-4 执行/滑点假设待实盘校准（P1，数据依赖）**：回测统一扣 2% 双边成本，breakeven 17.36%（cost_sensitivity.json）显示口径保守；executions 表已记录 advice_price 与成交价（滑点口径=成交价÷现价-1），但样本仅 7 条。**等 executions ≥20 条后校准**（F-4 成本建模待做，roadmap 已列）。
- ⏳ **A1-5 求购单/存世量的边际价值未验证（P2，数据依赖）**：bid_support 目前仅「求购承接弱 score<=25 拦截」+ watch 态增强（item_analysis.py:1144-1160）；存世量仅 survive<3000 拦截（:1098-1105），均未进评分。bid-data-accumulation.md 在积累中——**积累 90+ 天后再验证「求购断层收窄→价格」边际信息**，与开箱量观察项同级，不提前投产。
- ✅ **A1-6 组合层自洽**：cap0.8 强化（b1_risk_validation_v2.json：no cap +1118.94%/-44.68% → cap0.8 +193.30%/-9.39% 旧口径）、单票 30% 仅提示不拒绝（回测证伪硬上限）、熔断 10% 降级为监测器（portfolio_risk.py 头注释）——三个 B1 参数语义与证据一致，归因结论「边际价值在风控」成立。

## 2. 数据工程 / 数据质量

**总体判断：✅ 主干合格（串品防护+审计 SOP 属行业级）；⚠️ 3 处需修正；⏳ 1 处待验证。**

- ✅ **采集链路可证伪、可审计**：串品防护已下沉到全部写库入口——fetch_item_detail（collector_csqaq.py:417-442 锚校验重试）、fetch_kline_90d（:748-887 双锚 + _pick_best_chart + 可疑重试）、discover 消费前双校验（webapp/main.py:1880-1920）、批量扫描 kline_price_sane（analysis_service.py:159）+ anchor_override（:226）；8 节「全库审计 SOP」完整（data-layer.md §8，触发场景/步骤/回放联动/证据留存）。
- ⚠️ **B-1 price_history 每日全窗口覆盖，防污染仍有残余风险（P0，成本中）**：`save_price_history_batch` 为 `INSERT OR REPLACE`（db.py:550-563），每日采集会把 90 天窗口整体重写；8/9 两次串品污染事件（火卫一、48 品批量）根因都是「单次坏 chart 整段覆盖落库」。锚校验显著降低概率，但**校验是概率性防御，覆盖式写入是结构性风险**。建议：改为「增量追加 + 差异行更新」（只写 date > 库内 max(date) 的新行 + 当日最新行），坏数据只污染当日行，且留 UPDATE 变更日志（复用 8/9 审计思路：仅改 price/in_sale、保留 volume/created_at）。
- ⚠️ **B-2 回测池（98 老品）与生产池（188 品）脱节（P1，成本中）**：回放 args `pool: "A(98老品,365天窗口)"`（item_backtest_full_2025.json），生产活跃池约 177 品；F-3 扩池新增品无回测覆盖，实盘信号（signal_tracking 生产 n=1）与回测口径（332 信号）断层，J-2 C 通道生产门控 `min_filled14=20` 需长期积累。**建议**：回测池扩展到活跃池（至少 90d 窗口品），或产物明示「回测仅覆盖 A 池老品」的样本偏差。注意保留策略 365 天与 365d 回测窗口的上限关系（2026-08-10 已接受此口径）。
- ⏳ **B-3 在售量聚合口径存疑（P1，成本小-中）**：`_chart_to_daily_ohlc` 日内 10 分钟点聚合取「当日最后一个 in_sale_count 点」（collector_csqaq.py:125），非日均/中位；8/9 审计发现 31 品 SALE 系统性偏差 30-500% 且归因为「chart num_data 与 DB 落库口径系统性偏差」——该根因未彻底闭环（48 品已回填，但聚合规则本身未改）。**验证**：对 num_data 做「末点 vs 中位数 vs 均值」三口径对比，统一聚合规则并重跑回放（回放同源纪律）。
- ⚠️ **B-4 单品主动分析强制当天新鲜，限流预算与体验紧张（P2，成本小）**：KLINE_FRESH_SINGLE=0（analysis_service.py:47-49）→ 每次单品分析都触发实时 Playwright 采集（30-60s），与批量扫描 3 天容忍不一致；HTTP 直连有 1.1s 节流但 Playwright 路径无请求级节流。建议：单品分析「当日已采则 6h 内复用 + 显式强制刷新」双轨（force_refresh 已存在），并给 Playwright 采集加节流/退避。
- ⚠️ **B-5 健康检查告警噪声与覆盖缺口并存（P2，成本小）**：health_checks 连续 3 天 FAIL——① 全市场快照 4404 行 > 3500 阈值：基线 1468 行是池扩容前口径，阈值未随池大小归一（疑似误报）；② 2026-08-09 K 线覆盖 147/188 < 85%：当日采集确有缺口但无失败品清单。建议：快照阈值按池大小比例化、K 线覆盖失败品逐品落台账（notify_alert 22:00 已有 FAIL 告警通道）。
- ✅ **B-6 新鲜度分级与限流预算匹配**：SINGLE=0 / BATCH=3 / DISCOVER=3 与每日 ~166 品 K 线全量 + 周度快照降频（省 ~9-11 分钟/天，run_daily_collect.py）合理；保留策略（365/90/7 天 + VACUUM + 14 份备份 + 台账）闭环完整。

## 3. 软件工程 / 架构

**总体判断：✅ 分层方向正确；⚠️ 3 处需修正；无硬阻塞。**

- ✅ **模块边界**：analysis_service.py 抽取统一分析核心（2026-08-07）、决策核心收敛为 decide_fusion_signal 注册制、数据层手册唯一权威（data-layer.md）——分层与文档一致。
- ⚠️ **C-1 单文件膨胀 + 双渲染体系（P1，成本大，分期）**：webapp/main.py 2615 行（路由+页面编排+HTML 拼装）、item_analysis.py 1978 行、batch_scan.py 918 行（内含 build_scan_html 用 Python f-string 拼 HTML，:815-918）、db.py 1063 行；Jinja 模板与 Python HTML 拼装两套渲染并存，易漂移且放大 XSS 面（虽有 _esc）。建议：HTML 拼装迁 Jinja 宏/组件；main.py 按域拆（scan/discover/exec/monitor 路由模块）。纯工程，不碰决策。
- ⚠️ **C-2 测试盲区（P1，成本中）**：90 项冒烟以纯函数/单测为主；路由集成测试仅 1 个 HTTP smoke（t_http_api_smoke）；6 项联网采集用例被 CI 跳过（SKIP_NET）；**2026-08-10 reload=True 事故是用户报告而非 CI 捕获**——缺「启动配置健康断言」。建议：① 新增启动配置断言测试（reload=False、DB 预热、路由表完整性）；② Playwright 可启动的标记性检查纳入手动/定时回归（不阻塞离线 CI）。
- ⚠️ **C-3 错误处理与可观测性不一致（P2，成本小-中）**：批量扫描/发现任务级 try/except 吞异常返回空（8/10 曾静默无结果）；部分错误裸写文件（webapp/main.py:1248 手写 snapshot_error.log）；错误文案截断 100-200 字符。建议：统一异常→进度文件→前端可见错误通道，日志统一 logging + 结构化字段。
- ✅ **C-4 并发模型合理**：Playwright 浏览器单例 5 分钟回收（collector_csqaq.py:20-58）+ 批量扫描搜索串行/采集并发 2（clamp 1-3，webapp/main.py:1263-1300）+ 锚校验兜底脏 chart；discover 逐品串行。设计有据（8/4 串品事故 → 8/10 锚校验自愈后放开并发）。
- ⚠️ **C-5 任务生命周期管理缺失（P2，成本小）**：_scan_progress/_discover_progress 为模块级内存 dict（webapp/main.py:1015），重启即失（磁盘进度兜底可读）；无取消/超时/全局并发上限。建议：任务表落库 + 超时回收。

## 4. 产品 / 交互

**总体判断：✅ 主路径闭环；⚠️ 2 处需修正；无阻塞。**

- ✅ **核心用户路径顺畅**：搜索→分析→决策条（动作徽章+回测期望徽章+溯源折叠）→一键执行（共享 exec-modal）→复盘对照卡（F-2）→信号中心/批量扫描历史归档；F-3.16 自选路径收敛（只允许主动加入）合理。
- ⚠️ **D-1 信息过载风险（P1，成本中）**：单品报告聚合 6 维评分 + 决策条 + 距买点 + 价格区间 + 期望徽章 + 补仓/止损双卡 + 敞口警示（analysis.html 20KB partial、watchlist.html 57KB）；普通用户认知负担高。建议分层展示：默认只展示「动作 + 一句原因」，细节（溯源/区间/徽章明细）折叠。纯展示层；注意监控 near_buy / 自选排序信息面联动。
- ⚠️ **D-2 排序依据不可见（P2，成本小）**：F-3.8 移除「距买点展示模块」后，自选页排序/监控 near_buy 仍读 proximity（monitor.py:21 NEAR_BUY_MIN=60），用户看到排序却看不到理由。建议自选页给一行「接近买点度 xx%」说明（信息层变更，须同步监控/排序口径）。
- ⚠️ **D-3 监控推送→动作闭环不可度量（P1，成本中）**：M3 双时段推送（12:00/21:30，monitor.py:257-288）已上线且幂等，但「推送→用户是否执行→效果」无归因（executions 仅 7 条、推送无 push_id 关联）。建议：推送事件记 settings/表 + exec-modal 记录「来源推送」，为 F-7（钉钉卡片一键执行）攒前置数据。
- ✅ **D-4 决策信号可理解性达标**：动作徽章 + deduction_sources 中文映射（_SOURCE_LABELS）+ 期望 tooltip + 术语表 + 买点缺口白话化，经 v30 PM 轮迭代已较完善。

## 5. 风险管理 / 资金管理（执行流程层）

**总体判断：✅ 已止损感知落地；⚠️ 1 处 P0 冲突风险；P2 若干。**

- ⚠️ **E-1 止损矩阵与补仓建议双计算路径可产生矛盾建议（P0，成本小）**：`_stop_loss_plan`（batch_scan.py:129-226）与 `_portfolio_advice` 补仓分支（batch_scan.py:228-460）**独立计算**、互不感知。场景：阴跌中继（大盘 30 日 -15%~-5%、sent<80）+ 深度低估（pct≤25、th≥40、z≤-0.5、大盘TH≥45、融合 buy）——止损路径给出「减半止损」（sell），补仓路径给出「可分批补仓」（buy），两卡并存即矛盾。F-3.13 只在展示层统一「建议动作」，计算层无互斥优先级。**建议**：计算层规定互斥优先级（止损/清仓动作 > 补仓动作，供给扩张/阴跌中继状态下禁补仓建议），并补 t_f37 扩展用例（止损+补仓共存场景断言）。已执行的「已止损感知」（F-3.14）方向正确，但只覆盖止损侧，未约束补仓侧。
- ⚠️ **E-2 建议 vs 执行差异无跟踪（P2，成本小）**：「建议卖出 14 件 → 实际 0 件」无提醒/无记录；executions 记录靠用户自觉。建议：批量扫描/报告建议与 executions 比对，显示「建议未执行」标记（信息层）。
- ✅ **E-3 执行记录闭环自洽**：F-3.9 编辑/回滚、F-3.10 已实现盈亏同步 + 滑点口径（成交价÷现价-1）、advice_price 自动带入、复盘对照卡——设计完整；样本不足（7 条）是数据问题非设计问题。

## 6. CS 饰品市场领域特性

**总体判断：✅ 引用去量 v2 结论成立；⏳ 2 处数据驱动项；P2 若干。**

- ✅ **F-3 平台差异/唯一量源/限量品定价覆盖合理**：定价锚 悠悠>Buff>C5GAME（平台在售量可差 42%，v32 实证）；in_sale_count 唯一量源（去量 v2 战略决策引用）；ATH 模式（无历史参考）+ 庄家检测 + 存世量闸门 + 活跃池淘汰（<10 件/周）覆盖限量品特征。
- ⚠️ **F-1 事件驱动仅历史日历，无未来事件（P2，成本小）**：EVENT_CALENDAR 仅 3 个历史事件（config.py）+ settings.event_active 手动开关；Major/赛事/大促/新箱等未来事件无日历（F-6 待做观察项）。建议先做「未来事件日历 + 决策条提示」（非决策，纯提示层）。
- ⏳ **F-2 流动性陷阱区分不足（P2，数据依赖）**：supply_depth<15 闸门 + 流动性分覆盖「有价无市」；但「在售量低但求购活跃」与「在售量高但无成交」未区分——求购数据已积累（bid-data-accumulation.md）未接入流动性判定。**等 90+ 天求购数据后验证**。
- ⏳ **F-4 唯一量源平台口径漂移标记（P2，成本小）**：锚校验兜底防 Buff/Steam chart 误入（30% 在售容差），但供给分析直接吃悠悠口径，锚失效时无显式标记。建议供给特征加「口径漂移风险」flag（信息层）。

## 7. 安全 / 合规 / 成本

**总体判断：✅ 本地部署面收敛；⚠️ 2 处凭据问题；P2 若干。**

- ⚠️ **G-1 csQAQ API token 内嵌默认值并已提交 git（P0，成本小）**：config.py:22 `API_TOKEN = os.environ.get("CSQAQ_API_TOKEN", "RMYAF1H7O8O4N1Q2B6J0F1F2")`——凭据入库（git ls-files 确认 pipeline/config.py 被跟踪）。建议：移除默认值（env-only），并轮换当前 token。
- ⚠️ **G-2 钉钉 webhook 无加签（P2，成本小）**：.env `NOTIFY_WEBHOOK_URL` 仅 access_token（文件已 gitignore，但泄露面=本机文件/备份）；DingTalk 支持加签（secret 签名）。建议开启加签 + 文件 ACL 收紧。
- ✅ **G-3 部署面收敛**：服务仅绑定 127.0.0.1（run_server.py）、无公网面、.env gitignore 正确。
- ⚠️ **G-4 Playwright 采集路径无请求级节流（P1，成本小-中）**：HTTP 直连有 API_RATE_LIMIT=1.1s，Playwright 采集（每日全量 + 单品实时）无节流；8/9 审计需「夜间限流保护」说明上游受限。建议：Playwright 采集加节流/退避 + 每日采集失败率入台账监控（pool_maintenance_log 已有 kline_ok 字段可扩展）。
- ⚠️ **G-5 bind_local_ip 公网白名单机制脆弱（P2，成本小）**：出口 IP 轮换触发 401 风暴（8/6 事故），现已有重试+浏览器兜底缓解；建议失败计数入台账告警。

## 8. 其他（文档/工程卫生）

- ⚠️ **H-1 文档漂移（P2，成本极小）**：根 AGENTS.md:49「评级: S>=3.5 / A 2.5-3.4 / B 1.5-2.4 / C<1.5」与代码 10 分制（S≥8 / A≥6.5 / B≥4.5，item_analysis.py:1739-1743）不符；PROJECT_STRUCTURE.md 行数描述（main.py 2386）与实际（2615）漂移。建议文档同步（纯文档）。
- ⚠️ **H-2 死代码/遗留（P2，成本极小）**：positions 表仅建表无读写（db.py:296，库内 1 行）；analyze_probability 首段 base_up 赋值被后段覆盖（item_analysis.py:544-548 vs 584-587）；_analyze_cycle 重复行 phase_label="拉升期"（item_analysis.py:353-354）。建议清理（不动引擎行为）。

## 9. 问题清单汇总

| ID | 角度 | 三档 | 优先级 | 问题 | 证据 | 成本 |
|---|---|---|---|---|---|---|
| E-1 | 5 风控执行 | ⚠️ | P0 | 止损「减半」与补仓「可分批」可并存矛盾 | batch_scan.py:129 vs :228 | 小 |
| B-1 | 2 数据 | ⚠️ | P0 | 90 天窗口每日 INSERT OR REPLACE 覆盖，污染残余风险 | db.py:550；8/9 两次事故 | 中 |
| G-1 | 7 安全 | ⚠️ | P0 | csQAQ token 内嵌默认值已入库 | config.py:22；git ls-files | 小 |
| A1-1 | 1 策略 | ⚠️ | P0 | 洗盘期评分最高但决策层降级 buy，方向矛盾 | trend_health.py:900-906 vs 审计结论 | 中（回测） |
| A1-2 | 1 策略 | ⏳ | P1 | deep_value sent 66-74 无主区 | item_analysis.py:986/1014/1034 | 中（回测） |
| A1-3 | 1 策略 | ⚠️ | P1 | 组合绩效无族级归因分解 | benchmark_compare.json | 中 |
| A1-4 | 1 策略 | ⏳ | P1 | 2% 滑点假设未实盘校准 | cost_sensitivity.json；executions=7 | 数据依赖 |
| B-2 | 2 数据 | ⚠️ | P1 | 回测池 98 老品 vs 生产 188 品脱节 | item_backtest_full_2025.json args | 中 |
| B-3 | 2 数据 | ⏳ | P1 | 在售量聚合取当日末点，口径未闭环 | collector_csqaq.py:125；8/9 SALE 偏差 | 小-中 |
| B-4 | 2 数据 | ⚠️ | P2 | 单品分析强制当天新鲜，实时采集成本高 | analysis_service.py:47-49 | 小 |
| B-5 | 2 数据 | ⚠️ | P2 | 健康检查快照阈值未随池扩容，连续 3 天 FAIL | market.db health_checks | 小 |
| C-1 | 3 工程 | ⚠️ | P1 | 单文件膨胀 + Jinja/Python 双渲染 | main.py 2615 行；batch_scan.py:815 | 大（分期） |
| C-2 | 3 工程 | ⚠️ | P1 | 启动配置无断言，reload 事故 CI 未捕获 | 8/10 decision-log；CI SKIP_NET | 中 |
| C-3 | 3 工程 | ⚠️ | P2 | 错误处理不一致（吞异常/裸文件日志） | webapp/main.py:1248 | 小-中 |
| C-5 | 3 工程 | ⚠️ | P2 | 内存态任务字典无生命周期管理 | webapp/main.py:1015 | 小 |
| D-1 | 4 产品 | ⚠️ | P1 | 单品报告信息过载 | analysis.html 20KB | 中 |
| D-2 | 4 产品 | ⚠️ | P2 | 排序依据 proximity 不可见 | monitor.py:21；F-3.8 | 小 |
| D-3 | 4 产品 | ⚠️ | P1 | 推送→执行闭环不可度量 | monitor.py:257；executions=7 | 中 |
| E-2 | 5 风控 | ⚠️ | P2 | 建议 vs 执行差异无跟踪 | batch_scan.py advice | 小 |
| F-1 | 6 领域 | ⚠️ | P2 | 无未来事件日历 | config.py EVENT_CALENDAR | 小 |
| F-2 | 6 领域 | ⏳ | P2 | 求购数据未进流动性判定 | bid-data-accumulation.md | 数据依赖 |
| F-4 | 6 领域 | ⏳ | P2 | 唯一量源口径漂移无标记 | collector_csqaq.py:392-415 | 小 |
| G-2 | 7 安全 | ⚠️ | P2 | 钉钉 webhook 无加签 | .env NOTIFY_WEBHOOK_URL | 小 |
| G-4 | 7 成本 | ⚠️ | P1 | Playwright 采集无节流，上游限流风险 | run_daily_collect.py；8/9 夜间保护 | 小-中 |
| G-5 | 7 安全 | ⚠️ | P2 | bind_local_ip 白名单机制脆弱 | collector.py:119-129 | 小 |
| H-1 | 8 文档 | ⚠️ | P2 | 评级口径文档漂移 | AGENTS.md:49 vs item_analysis.py:1739 | 极小 |
| H-2 | 8 卫生 | ⚠️ | P2 | positions 死表/概率死代码/重复行 | db.py:296；item_analysis.py:544/353 | 极小 |

## 10. 落地路线建议

**第一批（P0，先做，均可立即开工）**
1. E-1 止损/补仓互斥优先级（计算层 + t_f37 扩展用例）——成本小，直接消除矛盾建议
2. B-1 price_history 增量写策略（含变更日志）——成本中，结构性防污染
3. G-1 csQAQ token 环境变量化 + 轮换——成本小
4. A1-1 洗盘降级 A/B 回测（CS_ENGINE_* 开关 + 三件套 + 实验产物 data/_exp_*.json 归档）——回测先行，不动线上行为

**第二批（P1，提升可信度与效率）**
5. B-2 回测池对齐活跃池（或产物明示样本偏差）
6. B-3 在售量三口径验证 + 聚合规则统一（改后重跑回放+sync 联动）
7. A1-3 组合族级归因脚本（纯分析）
8. C-2 启动配置断言 + 路由离线冒烟扩展
9. G-4 Playwright 采集节流 + 失败率台账
10. A1-2 deep_value sent 窗口回测（A2 三件套）
11. D-3 推送→执行归因（push_id）

**第三批（P2，打磨，可并行）**
12. C-1 拆模块/渲染统一（分期工程）
13. B-5 健康检查阈值归一 + 失败品清单
14. D-1/D-2 展示层分层与排序说明
15. F-1 未来事件日历（纯提示层）
16. G-2 钉钉加签；G-5 401 失败台账
17. H-1/H-2 文档同步与死代码清理（随手可做）

**需冻结等数据/回测的项**：A1-4（滑点实盘校准，executions≥20）、A1-5/F-2（求购数据 90+ 天）、F-4（口径漂移标记验证）、B-6（研究库分离）。

**执行纪律**：涉及引擎决策参数的改动（A1-1、A1-2）回测先行 + 三件套（信号数/胜率/期望增量）+ 实验产物归档 + 环境变量开关；新信号族过 A2；纯展示/工程层（E-1 展示约束、D-1、C-1 等）注明信息层影响面（监控 near_buy / 自选排序 / 批量扫描排序）；改动后 tests/test_smoke.py 全量通过且不破坏 t_param_regime / t_expectancy_sync / t_replay_snapshot；产物变更走「回放同源，改产物必须重跑同步」。

## 11. 落地状态（2026-08-10 更新，原始清单保留为基线）

**第一批（P0，已提交 adfe6ab）**：E-1、B-1、G-1、B-5、C-2、H-1、H-2、A1-1（A/B 证实保留现状）✅。

**第二批（已提交，见 decision-log「系统全貌评估第二批落地」）**：
- A1-2 ✅（已量证，结论=不落地：sent 66-74 43 条 win74.4%，39 条深值特征中 34 条 panic 已覆盖，base 子集 9 条平庸；deep_value 放开上限边际价值低）
- A1-3 ✅（`references/portfolio_attribution.py` → `data/portfolio_attribution.json`：供给吸筹 +34.2pp / 恐慌 +21.65pp / 深值 +13.98pp）
- B-2 ✅（`data/_exp_pool_90d.json`：扩池仅 97 品=基线 96+1 新品，三件套与基线一致；结构性约束=新品 <90d 进不了 365d 回测，回测池维持 A 池 + 明示样本偏差）
- B-3 ✅（`references/sale_caliber_compare.py` → `data/sale_caliber_compare.json`：末点 vs 中位/均值偏差>20% 属偶发非系统，3 品成功各 0-1 天，现行末点口径保留）
- G-4 ✅（采集退避 1.5s + K线失败台账 kline_fail_count/names）
- D-3 ✅（executions.source 列 + push_id 幂等 JSON + `references/push_exec_attribution.py`，转化率 5.2% 样本不足仅参考）

**第三批（P2，已提交，见 decision-log「系统全貌评估第三批落地」）**：
- C-3 ✅（snapshot_error.log 统一写 data/ 目录）、C-5 ✅（任务防重复并发 _active_task）、D-2 ✅（核查=自选页已显示接近买点度）
- E-2 ✅（持仓建议列「建议未执行」标记，近30天 executions 比对）
- F-1 ✅（未来事件日历框架：upcoming_events + dashboard 提示卡，事件由用户配置）
- F-4 ✅（口径漂移审计日志 data/caliber_override_log.jsonl）
- G-2 ✅（钉钉加签 NOTIFY_WEBHOOK_SECRET 可选）、G-5 ✅（bind 失败台账 data/bind_fail_log.jsonl）

- B-4 ✅（单品分析「当日已采 6h 内复用」双轨，KLINE_FRESH_SINGLE_HOURS=6，force_refresh 不受影响）
- 数据质量定期复核 ✅（`references/data_quality_review.py` 每周抽样复核：持仓+自选+活跃池随机，周日自动触发；三层机制见 data-layer.md §8，决策见 decision-log「数据质量定期复核」）

- D-1 ✅（2026-08-10 落地，见 decision-log「D-1 单品报告分层落地」）：关键指标条 / 供给·流动性·庄家折叠为 details（摘要一行），首屏保留动作+一句原因+操作核心，纯展示层。
- 组合层研究 ✅（2026-08-10，见 decision-log「组合层敏感性研究 + 出场口径对齐 hold21」）：cap 网格验证 0.8 为平衡点维持不变；组合模拟口径 hold14→hold21 对齐单品建议层，基准产物重跑（strategy +183.94%/-9.08%，maxDD 改善 4pp）。

- P-1 ✅（2026-08-10 落地，见 decision-log「第一性原理测试 P-1 正式引擎 A/B + chg8 门落地」）：吸筹族新增 chg8（8 日动量）>3% 禁买门（T4 第一性原理审计候选），正式 A/B 基线 332→变体 317 信号（−26 剔除 +11 去重链解锁），win14 69.9→71.0%、wavg14 20.47→21.04、wwin14 74.4→75.4%、事件 14→15 不降、win30 不劣化，全指标改善无劣化；标准回放产物 317 信号 + 同步链重跑（sync_expectancy_config / sync_replay_snapshot / benchmark_compare / portfolio_attribution），ENGINE_VERSION v2-I13→v2-T4。
- P-0/T1 ✅（2026-08-10 证据链更新）：greedy 持久化机制验证通过（60 天覆盖）；T1 探针 = 日级不一致（corr 0.26）但决策级零影响。
- P-0/T1 扩展 ✅（2026-08-10，见 decision-log「第一性原理审计扩展执行」）：T0 每日覆盖监测已挂接每日任务；T1 第二轮同数据对照回放修正「决策级影响为零」——deep_value 族触发域受情绪口径影响实质存在（近似高估 13 条且多为负贡献，deep win 20.0% vs 11.1%），panic/accum 低敏感；deep 参数不调、外推置信度低标注维持。
- P-2 预评估 + 功效分析 ✅（降级为观察项，2026-08-10）：高价×低在售候选被 2026-02~04 在售量断档污染（317 信号 48%=0，高价品 92/154），T3「win 53.7% 劣化」为断档伪信号——干净段（2026-05 起 133 信号）高价×低在售 n=7 win71.4% vs 高价×在售≥200 n=47 win72.3% 无差；功效估算真实差 27pp 需每组 35 条（现 7/47，速率 2.33/月）；无正向证据 → 观察项，扩池优先级让给其他候选；数据层断档标注（data-layer.md §6）保留。
- P-2 观察项样本加速 ✅（2026-08-11，见 decision-log「P-2 定向扩池完成」）：扩池后 P-2 样本 7/47 → 36 品（31 新增，价≥1000 × 悠悠在售 100–200），正式三件套仍待 90d K 线自然积累（新入库品仅 8/11 单日）。
- 池子收敛定论 ✅（2026-08-11，见 decision-log「池子收敛定论：活跃池 203 品」）：刀 71 + 手套 14 + 非崭新出厂 27 标记淘汰（数据保留可回滚），活跃池 326 → 203，用户确认「暂时不扩容」；「260 品规划目标」作废。
扩池扫描 ✅（2026-08-11 csQAQ 已恢复：current_data/info 200、chart 端点通；16 品 force 重采完成，见 decision-log 同日条目）→ **已完成扩池**：csQAQ get_rank_list 批量扩池 135 品（items 191→326，超 260 目标；8/11 K 线 277 品），P-2 样本 36 品，见 decision-log「P-2 定向扩池完成」；discover 搜索段加重试为后续备用。
- 报告缓存标志改版 ✅（2026-08-11，见 decision-log「报告缓存标志改版」）：单品报告去「本次分析使用数据库缓存数据」卡片、批量扫描去 ⚠️缓存 标签，统一改为显示「数据采集于 {时间}」，纯展示层。

- 四模块第一性原理审计立项 ✅（2026-08-11，见 `references/first-principles-modules-fit.md` + iteration-roadmap 状态追踪 M-1~M-6）：抛压衰竭择时（M-1）/ composite 消融（M-2）/ discover alpha（M-3）/ 执行复盘口径（M-4）已立项；M-6 候选未立项。
- M-2 composite 消融检验 + M-5 TH 偏移反向 ✅（2026-08-11，见 decision-log「M-2 composite 消融检验 + M-5 TH 偏移反向落地」）：TH 与 net14 负相关 -0.344 坐实加分方向错误，`item_analysis.py:674` TH 偏移系数 1.0→-1.0（展示层排序，不落引擎），反向变体 Q5 win14 67.2%→73.4%；探针 `references/probe_composite_ablation.py` → `data/_exp_composite_ablation.json`。
- M-1 抛压衰竭大盘择时阶段 0 预跑 ✅（2026-08-11，见 decision-log「M-1 抛压衰竭大盘择时检验 · 阶段 0 预跑」）：触发桶（sp>=85，n=18）win14 44.4% 与对照桶（drop20<=-7，n=54）完全相同，无择时区分度，触发集中于 2 个独立恐慌事件；n<30 只报告不判定，`market_th.py:527-537` 暂不调整，待独立事件>=3 复验。
- M-6 discover 发现空间扩展阶段 1 ✅（2026-08-11，见 decision-log「M-6 discover 发现空间扩展 · 阶段 1」）：新增品类识别模块 + 池内 discover 白名单扩展（印花×2/武器箱×2/挂件×1 进发现空间，角色×3 暂不入），discover_history 存档加 category（M-3 品类分桶基础），展示层品类列/热力图分桶；纯展示层+数据追踪，引擎参数零改动；阶段 2（scan-all 品类搜索词）待 csQAQ 稳定。
**仍待做（数据依赖/配置）**：F-2（求购数据 90+ 天）、A1-4（滑点校准，executions≥20）。C-1 已全部完成：渲染纯函数切 `webapp/render_html.py`、任务块切 `pipeline/discover_tasks.py`+`scan_tasks.py`、页面结构迁 Jinja（`templates/partials/discover_html.html`+`scan_html.html`，保留 markdown/SVG/单元格内容渲染器），冒烟 + Playwright 端到端通过。G-2 加签后 webhook 轮换待用户配置。 ?????????2026-08-11??monitor_rank_snapshot ?????????snapshots ?????? decision-log ?????

- P-2 正式分桶回测阶段 0 预跑 ✅（2026-08-11，见 decision-log「P-2 分桶回放阶段 0 预跑」+ `references/p2_backtest_plan.md`）：价≥1000 的 56 品只读回放 150 信号，P-2 桶 n=6 win14 83.3% vs 对照（365d）68.8% / 基线 71.0%，方向符合 H 但 n<30 不判定；进入阶段 1 积累期（单桶 n≥30 门槛）。
- 第四批 · 量化专家框架 ✅（2026-08-12 全部落地，见 decision-log「第四批 · 量化专家框架落地」）：④ 前后半段一致性制度化（PARAM_REGIME 改动必填前后半段对照 + 轻量置换 ≥200 次）、① 三要素元数据入册（SignalFamily 4 字段 + signal-family-registry.md 注册簿）、③ 去簇胜率主视图对照（进度卡 J-3「全量 69.9% vs 去簇 58.6%」双口径行，dashboards.dedup）、② C 通道族级失效监测（j2_channel_monitor._channel_c_family，族级 n≥5/14d<60%/30d<50%/连续2月<70%，dashboard「C 族级失效」行）。零决策参数，冒烟 100 passed / pyflakes 0。

- 贴纸 alpha 研究立项 ✅（2026-08-12，见 decision-log「贴纸 alpha 研究立项 + 阶段 0 预跑」）：深历史验证四案例（EG/G2/MOUZ/Fluxo）确认贴纸=百倍级事件脉冲 + 尖顶形态（种子 12 品 9/12 尖顶），原「低估区反弹 14d」A2 假设不适配；阶段 0 预跑支持 Major 日历周期方向（W25 赛前 +574.7% / W26 春季 +116.5% / 回落 -35.8%）；立项 S-1 深历史全量回填（P1，数据前提）→ S-2 Major 周期三件套（P1）→ S-3 战队 proxy+离场规则（P2）→ S-4 A2 假设修正（P2）→ S-5 EVENT_CALENDAR 补赛程（P2，用户配置）。零引擎参数改动，产物 `data/_exp_sticker_deep_seed.json` / `data/_exp_sticker_season0.json`。

## 附录：与「评估指标体系第一性审计」的边界

本评估直接引用、未重跑：六维权重（位置 40/周期 25/流动性 15/概率 20）、估值分位边界、供给吸筹/派发判定、评级切分（代码口径 8/6.5/4.5）、绩效口径（win14/30、net 2%）、持仓管理矩阵参数、TH/情绪/跌幅/牛熊结论、周期反转/panic 分级/概率去 z（2026-08-10 四项审计）。审计后新增的展示层改动（如 F-3.14 已止损感知）只审「改动本身」——见 E-1/E-2。
