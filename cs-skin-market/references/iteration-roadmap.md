# 迭代方案（Iteration Roadmap）

> **迭代闭环规则（2026-08-06 定稿）**：迭代执行 → 学习/试错 → 提炼新思路 → 映射为迭代项 → 更新本方案 → 按优先级继续迭代。
> 分工：本文件 = 计划（接下来做什么）；`decision-log.md` = 历史（为什么 / 试错细节）。
> **历史版本细节（v1~v70）+ 新思路映射 + 批次/状态追踪 + 各技术方案 已归档至 `references/archive/doc-compact-2026-08-18/iteration-roadmap-archive-2026-08-18.md`**。

## 版本摘要表（v1~v71，详细全文见归档卷）

| 版本 | 日期 | 摘要 |
|---|---|---|
| v71 | 2026-08-18，PM 同步，零引擎变更 | 路线图补录 2026-08-16~18——① 大盘五时期路由 v2-T13 落地（PERIOD_… |
| v70 | 2026-08-15，进行中 | 新引擎 v3「收益增强器」技术方案（外审方案基线 `references/v3-engine-e… |
| v69 | 2026-08-15，进行中 | 历史扩窗口重拟合技术方案（外审立项基线 `references/cycle-refit-2026… |
| v68 | 2026-08-15，进行中 | BUY-1 求购直连技术方案（外审立项基线 `references/optimization-i… |
| v67 | 2026-08-15，进行中 | csQAQ 长历史回补 + supply_depth_missing 口径修复——确认 `/in… |
| v66 | 2026-08-15，进行中 | LIQ-RATIO-1 方向证伪收口 + EXIT-9/10/11 ATR 网格不立项——相对挂… |
| v65 | 2026-08-14，已完成 | v2-T8 真基线重跑 + below_floor 吸筹旁路修复——`compute_fusio… |
| v64 | 2026-08-14，已完成 | 族分类唯一事实源 + 中间数废弃——新增 `pipeline/config.py:SIGNAL_… |
| v63 | 2026-08-14，已完成 | 双基线落地——HIST-FULL（官方 317，v2-T4/T5）与 CLEAN-CUR 并存；… |
| v62 | 2026-08-14，进行中 | v2-T7 流动性地板泄漏修复——below_floor 与 missing 同样禁后置升级，堵… |
| v61 | 2026-08-14，进行中 | DECISION-6 落地——in_sale NULL/2026-02~04 断档显式缺失并禁 … |
| v60 | 2026-08-14，进行中 | 专家三残留风险收口——风险2 共享底层污染排查（未污染，官方基准/归因仍成立）、风险1 deep… |
| v59 | 2026-08-14，进行中 | 专家优化机会 #5/#8/#3 阶段0 三探针 + #6 成本影子 + #1 期望+Calmar… |
| v58 | 2026-08-13，进行中 | 直连 API 数据储备排期——P0 已完成（活跃池基本面+求购历史），P1 首批已完成（存世量+… |
| v57 | 2026-08-13，计划 | 产品侧下一版迭代方案（A-9 落地后）——A-9 验收 + 采集预算回收观测、A-2 执行环轻推… |
| v56 | 2026-08-13 | 贴纸模块降级——停采停扫 + 观察桶冻结 + 保留静态研究资产；159 个非自选/持仓贴纸标记 … |
| v55 | 2026-08-13 | 主引擎优先落地——A1-2 deep_value sent 66-74 无主区复验不落地；主引擎… |
| v54 | 2026-08-13 | signal_tracking 唯一一行乱码修复（备份可回滚）+ 供给×求购观察层落地（`pro… |
| v53 | 2026-08-13 | PANIC-ALIGN-1 阶段0完成——回放恐慌 92 条全部为价格近似情绪；真实贪婪情绪与近… |
| v52 | 2026-08-13 | PORT-1 组合风险预算阶段0完成——317 信号只读组合模拟，vol/regime/vol_… |
| v51 | 2026-08-13 | 量化优化六项补充立项——PORT-1 组合风险预算 / PANIC-ALIGN-1 恐慌口径一致… |
| v50 | 2026-08-13 | 量化优化三项立项排期——EXIT-1 路径依赖退出（P0）/ LIQ-1 流动性成本感知仓位（P… |
| v49 | 2026-08-10 | 四项审计落地（周期权重反转 / panic 分级仓位修复 / 概率去 z 化 / 供给降仓证伪）… |
| v48 | 2026-08-09 | F-3.6 价格串品治理——fetch_kline_90d 加悠悠锚校验 + 全库体检修正（用户… |
| v47 | 2026-08-08 | F-3.5 高分品模块治理——磨损/类型过滤 + 流动性闸门（用户报「渐变斑纹存世量少在售量更少… |
| v46 | 2026-08-08 | F-3.4 discover 改为从池内跑（用户「寻找高分品模块能不能改为从池子里跑」）——不再… |
| v45 | 2026-08-08 | F-1.1 信号→动作统一映射（用户反馈「回调中·关注对应什么动作？筑底对应什么？批量扫描太乱」… |
| v44 | 2026-08-08 | F-3 采集复用优先（用户「采取最优采集方案，不要重复采集」）——DB 新鲜度复用 + 失败重试… |
| v43 | 2026-08-08 | P0 第一性原理落地第一批——F-1 一键执行录入 + F-2 执行复盘对照卡（用户「开始」后实… |
| v42 | 2026-08-08 | 第一性原理差距分析落档 + P0-P2 落地计划（用户问「离真正好用的量化工具还差什么」，确认「… |
| v41 | 2026-08-08 | 每日采集提前至 18:00 + 晚间推送解耦（用户「数据采集提前」）： |
| v40 | 2026-08-08 | 大盘采集 401 自动重绑 IP（用户报「获取大盘数据失败」）： |
| v39 | 2026-08-08 | 求购数据持久化（数据储备，为后续版本迭代验证求购因子攒样本；决策/展示零改动）： |
| v38 | 2026-08-08 | 买点路径达标度展示优化（用户追问「81% 是什么 / 横杠是什么」，纯展示层）： |
| v37 | 2026-08-08 | 系统冗余清理全量落地（用户「都做」，先删 dashboard 信号中心再批量清理）： |
| v36 | 2026-08-08 | 监控推送改纯文字自包含——移除内网 URL，danger/warn 明细直接列出（用户反馈手机无… |
| v35 | 2026-08-08 | 监控日报双时段推送——午间 12:00 + 晚间 21:30（用户建议，纯提醒层）： |
| v34 | 2026-08-08 | M2 钉钉推送配置验证 + send() errcode 加固（用户提供 webhook 后收尾… |
| v33 | 2026-08-08 | M2 监控钉钉推送（用户确认 M1 后实施，纯提醒层）： |
| v32 | 2026-08-08 | M1 监控模式落地（用户确认方案后实施，纯提醒层，冻结纪律内）： |
| v31 | 2026-08-08 | 每日采集优化——全市场快照/大户集中度降为每周一（用户「检查每日采集内容，有无没必要采集的数据」… |
| v32 | 2026-08-08 | Discover 高分品报告串品修复（采集层+展示层，决策零改动）——用户「高分品里 沙漠之鹰 … |
| v30 | 2026-08-07 | PM 方案展示层落地（P0-P2，引擎零改动）——用户「以专业产品经理角度分析系统不足并提出优化… |
| v29 | 2026-08-07 | Phase 3 重拟合流水线 + Phase 4 工程化落地——用户「继续 Phase 3 和 … |
| v28 | 2026-08-07 | 生产实盘信号跟踪落地（J-2 C 通道实盘化）——用户「对系统有价值就做」；把 C 通道从「37… |
| v27 | 2026-08-07 | J-2 三通道监测落地（展示层）——用户反馈「弄不明白了，按最优路线落地」；调研确认 I-8 引… |
| v26 | 2026-08-07 | 第二轮复验收口（I-9 / I-7 / J-2 / I-8）——用户提出「恐慌独立事件本就少且不… |
| v25 | 2026-08-07 | 旧引擎官方 88 基准终审删除——v24 刻意保留的 `data/item_backtest_l… |
| v24 | 2026-08-07 | 旧引擎（成交量时代）终审删除——用户确认后一次性清除 18 项：凭据 |
| v23 | 2026-08-07 | 旧引擎（成交量时代）残留审计与清理——复查发现活代码 1 个去量残留 bug： |
| v22 | 2026-08-07 | 研究工程收口 · 期望统计单一事实源 + 基准对照 + 参数冻结（③④⑤）—— |
| v21 | 2026-08-07 | 分析路径重构 · 抽公共分析服务层（工程）——新增 `webapp/analysis_servi… |
| v20 | 2026-08-07 | B1 风险预算层 v2 复验（引擎升级 → 风险参数重验）——去量引擎 370 信号跑同款组合模… |
| v19 | 2026-08-07 | P0 数据层去量 + P3 在售量增强 + P4 解冻全面落地（批次执行）——webapp 移除… |
| v18 | 2026-08-07 | 去量引擎 v2 = v1 + I-13 深值大盘上涨禁买——v1 回放对比基线（96品池，202… |
| v17 | 2026-08-07 | 废除成交量 · 以在售量+价格重构（用户决策）——证据链：sim_vol 激活实验 458→47… |
| v16 | 2026-08-06 | P2 开箱量因子预研（研究先行·结论暂缓）——接口实测（stat/case/chart **仅 … |
| v15 | 2026-08-06 | J-3 信号族样本深度落地 + P1 执行参考价——升级 j1_event_counts.py … |
| v14 | 2026-08-06 | csQAQ 接口迁移（数据源修复）——绑定 IP 后旧直连端点仍 401，确诊为接口改版永久废弃… |
| v13 | 2026-08-06 | 模拟量激活实验 + 趋势腿边界验证——2025 全年回放核实（25 牛市段 deep_value… |
| v12 | 2026-08-06 | 系统整理——清理过时数据与文档：删除 26 个日志/可再生的回放临时产物（advice/deep… |
| v11 | 2026-08-06 | TH 矫正预研与落地——TH 三区语义确立（<35 恐慌黄金坑 / 35-54 摩擦带 / >=… |
| v10 | 2026-08-06 | 黑天鹅事件日历落地——新增 EVENT_CALENDAR（纪念品炼金 05-25 / 黄盾 07… |
| v9 | 2026-08-06 | 数据对接修复——信号复盘升级 K-2 503 信号（88 旧基准废弃）、期望统计三键重算（pan… |
| v8 | 2026-08-06 | K-2 守卫统一实验落地——deep_value 叠加供给扩张闸门（剔除 91 个供给扩张坏信号… |
| v7 | 2026-08-06 | 阶段4 展示层接入——状态桶标注上线单品报告决策条（引擎口径），展示层恐慌判定 80→75 对齐… |
| v6 | 2026-08-06 | 统一大脑阶段3 架构重构落地（信号族注册制 + 六态状态桶 + 统一决策核心，581 信号全字段… |
| v5 | 2026-08-06 | 统一大脑方案建立（引擎结构整理文档 + 阶段1 条件期望表 + 581 信号全窗口回放）→ 阶段… |
| v4 | 2026-08-06 | 牛市段趋势腿研究（2025-01-01~10-31 同物品池）→ 学到新思路（S3 强牛段有效但… |
| v3 | 2026-08-06 | J-1 胜率事件上下文落地 → 学到新思路（n 大≠事件多：deep_value 241=13 … |
| v2 | 2026-08-06 | 第一批 I-3 存量审计完成 → 学到新思路（事件级样本是硬约束），新增 J-1/J-2 两项映… |
| v1 | 2026-08-06 | 初始基线。9 项映射源自 2026-08-05 C1/B1 执行中沉淀的 6 条新思路（见 de… |

---

## v71 主路径收官 +「拿历史均值当引擎买点」战役闭环（2026-08-18，PM 同步）

> 本版为路线图补录（decision-log 已更新至 AM，roadmap 此前停在 v70）。只做计划与验收状态同步，零引擎变更。

### 主路径三步（全部完成，勿重做）
1. **(1) 大盘引擎完善**：五时期 taxonomy + 时期路由 v2-T13 落地（PERIOD_ROUTE_BAN 默认开；官方产物 233→189 信号，组合 +397.02%/−14.09%，前后半段双正，置换 p_total=0.000 / p_dd=0.035）。详见 decision-log Y/Z。
2. **(2) 大盘帮助单品**：13 探针全部按预注册判据跑完——通过 = 相对强度(P4) + 独特性六形式升格(P13)；证伪/维持 = 11 项（S1 结构性负增量接受、时期注入/豁免/共振/折让全部证伪）。落地候选 RS/CT 长持族发射口径三关不过，维持默认关；30 天冷却+长持容量预算补漏仍不过，维持默认关。详见 decision-log AD~AH。
3. **(3) 单品回看大盘**：审计通过（大盘引擎无逻辑错误）；三处数据诚实性修正落地（P 事件窗标注 / P 共振证据 / S3-S4 独特性指针）。正式重验窗口 = B 通道 2027-04。长持 sleeve 预算测试（25/30 两档）全部证伪关闭。详见 decision-log AI/AJ。

### AM 战役验收（PM 对照预注册判据关闭）
- **立项目标**：找到所有「拿历史均值当引擎买点」的地方，建立「当下条件期望 ②」替代历史均值误用。
- **预注册判据（原文见 decision-log AM）**：②机制 = E[fwd14 | 时期, 时点]（k=20 收缩，n<5 回退「样本不足」），单品特征不进 ②；A/B/C/E 类语义隔离或修复全部落地。
- **验收结果**：**达标关闭**。E 类修复（proximity base 路径 th 倒置 + supply 补 chg8 门）落地；A 类语义隔离落地；修 1（②接入 webapp 展示）落地；冒烟 130 passed / 0 failed。战役闭环完成。

### 当前基线（唯一口径，PM 验收时点）
- 引擎版本 **v2-T13**；官方 HQ 口径：**189 信号，3 年组合 cap0.8/hold21/2%，+397.02%/−14.09%**。
- HIST-FULL = `data/item_backtest_full_2025.json`（317 信号，冻结归档）；CLEAN-CUR = `data/_exp_v2t9_win_replay.json`（230 信号，仅展示参考）。
- 冒烟 **130 passed / 0 failed**；编码健康 PASS。
- J-2 三通道：A 独立恐慌事件 2/3；B 样本外窗口约 2027-04-25；C 月度胜率/期望监测运行中。
- 模拟盘 −9.99%（1 平仓，判据 1/20 积累中）；实盘 S3 弱市阴跌持续 44 天（2026-08-17）。

### 未收口候选台账（不重复立项，等用户排期或触发条件）
- 研究层可立即立项（用户已暂缓）：SUPPLY-CONF-1 提前（buy_price 3 年已直连）、收藏品 vs 箱子货分类研究。
- 待触发：PANIC-ALIGN-1、BID-1、LIQ-1、M-1、M-3/M-4、deep_value 仓位放大 A2、TREND-TIGHT-1 待样本重开。
- 已证伪关闭（只登记）：长持 sleeve、C/D/RS/CT 组合整合、时期杠杆/注入/豁免/共振。

---

## CLEANUP-1 工程卫生清理专项（2026-08-18 立项，交研发执行）

### 立项卡
- **目标**：清理冗余/过时文档与零引用文件，使仓库实际文件与 `PROJECT_STRUCTURE.md`（唯一事实源）一致，降低维护噪音。**不改变活跃引擎、测试、基线数字与任何信号逻辑。**
- **预注册判据（删除/迁移动作前必须全部满足，禁止先删后补）**：
  1. 先落盘 dry-run 清理清单 `references/cleanup-plan-2026-08-18.md`（或 `data/_exp_cleanup_plan_*.json`）。清单即预注册，实际处置必须与清单逐项一致；清单外文件一律不得动。
  2. 每个候选必须含 5 字段：`路径 / 分类 / 处置方式 / 引用检查证据（全仓 rg：活跃代码+测试+活跃文档引用数）/ git 跟踪状态`。
  3. 候选必须属于以下预注册分类之一：
     a. 已明确标注 superseded / deprecated / archived 的文档或脚本；
     b. 全仓零引用的历史研究脚本（一次性探针、拟合脚本），且已有替代入口或产物已归档；
     c. 重复归档文件（多份相同内容分散在不同目录，保留一份、其余删除或归档）；
     d. `data/` 中带 `_deprecated_` 后缀、或 decision-log 已宣布废弃、且不在本卡白名单的中间研究产物；
     e. 临时文件（`.tmp` / 文本类 `.bak` / 旧日志），只登记或移入 `data/_cleanup_quarantine/`，不直接物理删除。
  4. 每个删除候选必须**同时**满足：活跃引用数 = 0（decision-log/iteration-roadmap/PROJECT_STRUCTURE 仅以「已归档/已废弃/历史存证」方式提及的，须在清单中标注为历史存证引用，不计活跃引用）；不在白名单；处置方式与分类匹配。
  5. 执行前确认 `git status` 干净；tracked 文件删除后可经 git history 恢复；untracked 文件先移动 `data/_cleanup_quarantine/` 保留 7 天，再物理删除。
  6. 处置后必须跑 `python tests/test_smoke.py`（**130 passed / 0 failed，不得低于立项时基线**）与 `python tests/check_encoding.py`（PASS），并附结果于 decision-log 条目。
  7. 涉及 `data/` 的任何处置，执行前先在 decision-log 留言占坑（文件清单 + 执行时段），确认不与运维采集/备份/计划任务冲突；冲突则暂停并交 PM 协调。
- **白名单（绝对不删）**：
  - 根目录：`run_*.py`、`backup_db.py`、`collect_data_reserve_p0.py`、`collect_data_reserve_p1.py`、`notify_alert.py`、`install_tasks.ps1`、`install_hooks.ps1`、`deploy_server.ps1`、`start_webapp.bat`、`requirements.txt`、`AGENTS.md`、`SKILL.md`、`PROJECT_STRUCTURE.md`、`agents/openai.yaml`、`design-system/`。
  - `pipeline/`、`webapp/`、`tests/` 全部活跃文件。
  - `references/` 活跃文档与脚本：`decision-log.md`、`iteration-roadmap.md`、`multi-agent-governance.md`、`terminology.md`、`data-layer.md`、`project-principles.md`、`engine-unified.md`、`market-bucket-alignment.md`、`historical-average-misuse-audit.md`、`current-state-expectancy-design.md`、`backtest-methodology.md`、`cs-knowledge.md`、`data-source-health.md`、`pool-maintenance.md`、`stop-loss-strategy.md`、`trading-strategies.md`、`th_calibration.md`、`trend_leg_research.md`、`first-principles-*.md`、`market-help-item-plan.md`、`market-engine-completion-plan.md`、`market-module-first-design.md`、`paper-trading-design.md`、`proximity-research-proposal.md`、`step3-market-review-study.md`、`two-day-synthesis.md`、`signal-family-registry.md`、`window-prompts.md`，以及 `PROJECT_STRUCTURE.md` / `AGENTS.md` 活跃条目中列出的所有脚本。
  - `data/` 基线白名单：`market.db`、`item_backtest_full_2025.json`（HIST-FULL）、`_exp_v2t9_win_replay.json`（CLEAN-CUR）、`j2_channel_status.json`、`benchmark_compare.json`、`portfolio_attribution.json`、`signal_event_counts.json`、`market_state_daily.json`、`equal_weight_baseline.json`、`pool_maintenance_log.jsonl`，以及所有由活跃脚本当前产出、未标 deprecated、未被 decision-log 宣布废弃的 `_exp*.json`。
  - 所有 `.db` / `.bak` / `.log` 运行时文件：**不物理删除，只登记清单交运维窗口处理**。
- **验收标准**：
  1. dry-run 清单与实际处置逐项一致（无清单外删除；清单内不处置项须注明原因）。
  2. 处置后全仓无悬空引用（rg 指向不存在文件 = 0）；冒烟 **130 passed / 0 failed（不得低于立项时基线）**；编码健康 PASS。
  3. `PROJECT_STRUCTURE.md` / `AGENTS.md` 完成同步：已删除文件不再作为活跃条目出现（历史存证引用除外）。
  4. 交付物：`references/cleanup-plan-2026-08-18.md` + decision-log 条目（清单与处置结果）+ commit。
  5. PM 对照本卡逐项验收；不达标回炉；若发生不可恢复误删，专项判定失败并执行回滚。
- **红线**：不碰活跃引擎 / 测试 / 基线数字；不删 `.db` / `.bak` / `.log`；本轮不做目录结构大重构（**仅允许单文件移入 `references/scripts-archive/` 或 `references/archive/`；禁止整目录搬迁 / 目录重命名 / 变更 import 结构**）；清理必须可逆（git history + quarantine）。

### PM 验收结论（2026-08-18）
- **结果：通过，CLEANUP-1 关闭。**
- 对照项逐项核验：
  1. dry-run 清单与实际处置一致：`references/cleanup-plan-2026-08-18.md` 列 17 篇归档 + 3 类 `.bak` 登记 + 明确不处置清单；实际归档 17 篇（`references/archive/` 全部在册，`git mv` 可逆），清单外零改动。✅
  2. 全仓无活跃悬空引用：`family-boundary-arbitration-v2.md` 对 v1 引用已改 `archive/...`；历史存证引用（decision-log/iteration-roadmap）按预注册豁免。✅
  3. 冒烟 130 passed / 0 failed / 0 skipped；`check_encoding.py` PASS（hard 0，10 个 `?` 为历史已知脏名）。✅
  4. 文件结构同步：`PROJECT_STRUCTURE.md` line 145 archive 条目已更新并指向 cleanup-plan；AGENTS.md 无归档文件活跃引用，无需改动。✅
  5. 交付物：cleanup-plan ✅ + decision-log AO 条目 ✅ + commit ✅（AO commit hash 已补记 `0e7831e` + `2f7cbcb`）。
- **遗留 `.bak` 事故快照（15 份）**：运维域 12（`market.db.bak-*` 9 + `market.bak-*` 3，生产库，待运维按数据层 SOP 清理）；研究域 3（`replay_v2t6_win.bak-*` 2 + `item_backtest_full_2025.json.bak-*` 1，②自清）。保留规则待运维确认。


---

## DISPLAY-1 单品报告「独特性[假设验证]」展示优先级重构（2026-08-18 立项，交②算法研究专家执行）

### 立项卡
- **目标**：单品报告「独特性[假设验证]」目前命中几条就并列几条、无优先级；改为**主形式置顶 + 其余折叠为「另 N 项并存」+ F6 供给锁仓警告独立置顶**，让研究提示有主次、可读性更好。纯展示层改动，不动引擎/测试/基线。
- **预注册判据（研发必须先按此实现，禁止先跑再改判据）**：
  1. 主形式优先级固定为：**RS30 相对强度 > F1 逆市走强 > F5 平静期异动 > F2 逆市抗跌 > F3 低相关独立 > F4 领先见底**。
  2. 主形式 = 按上述优先级取**第一个命中**的形式；其余命中形式折叠为**「另 N 项并存」**（N = 非 F6 命中数 − 1；若只有 1 条非 F6 命中则无折叠行）。
  3. **F6 供给锁仓**命中时，作为独立警告置顶展示，不参与主形式排序，也不计入「另 N 项并存」数量；若 F6 未命中则不出现该警告。
  4. 无任何命中时，维持现状（不显示该区块）。
  5. 所有命中仍必须保留「假设验证，不改变决策」研究口径语义；折叠后的其余形式名称/证据仍可展开查看（文案沿用现有研究口径提示，不新增数字口径）。
  6. 只允许改动展示组装层（`webapp/analysis_service.py` 的 `_uniqueness_lines`/`_uniqueness_note` 返回结构与 `webapp/templates/partials/analysis.html` 的 `research_caveats` 渲染）；**不得改动任何命中检测阈值、信号逻辑、数据读取、基线数字**。
- **验收标准**：
  1. 造出 0 / 1 / 多条非 F6 / 多条含 F6 等典型命中组合，界面表现分别符合：无区块 / 单条直接展示 / 主形式置顶 + 「另 N 项并存」折叠 / F6 警告独立置顶 + 主形式与折叠逻辑不变。
  2. 主形式顺序与预注册优先级完全一致；「另 N 项并存」的 N 正确。
  3. 现有 `tests/test_smoke.py` 仍 **130 passed / 0 failed / 0 skipped**，`tests/check_encoding.py` PASS；不新增/修改测试用例，不碰引擎参数与基线。
  4. 交付物：decision-log 条目（改动点 + 展示效果说明）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：不触碰引擎判定、信号族注册、proximity、期望机制、测试/基线；不新增数据采集或研究口径；不改 F6 命中条件本身。

### PM 验收结论（2026-08-18）
- **结果：通过，DISPLAY-1 关闭。**
- 对照项逐项核验：
  1. 结构化返回已实现：`_uniqueness_hits` 返回 `{'warning','main','others'}`；`_uniqueness_note` 改返回 dict 或 None；`_fd_display` 将 dict 放入 `research_caveats`。✅
  2. 主形式优先级与预注册一致：RS30(0) > F1(1) > F5(2) > F2(3) > F3(4) > F4(5)，`hits.sort(key=优先级)` 取第一个为主形式。✅
  3. F6 供给锁仓独立为 `warning`，不参与排序、不计入 `others`；模板先渲染 warning 再 main 再 `others` 折叠「另 N 项并存」。✅
  4. 0 / 1 / 多条非 F6 / 多条含 F6 组合均有明确渲染路径；旧平铺字符串走 else 分支兼容。✅
  5. 冒烟与编码：decision-log AP 记录 `tests/test_smoke.py` **130 passed / 0 failed / 0 skipped**，`tests/check_encoding.py` PASS，未增改测试用例；未触碰引擎/基线。✅
  6. 交付物：decision-log AP 条目 ✅ + commit（AP 未记录 hash，需研发/外部补交后视为最终闭环）。⚠️
- **非阻塞备注（后续可顺手修，不影响关闭）**：`_uniqueness_hits` 在数据不足时提前返回 `[]`，与自身 docstring「返回 dict」不一致；`_uniqueness_lines` 作为扁平兼容包装若被外部以短数据直接调用会访问 `h["warning"]` 报错。当前 `_uniqueness_note` 已前置 `len(rows)>=90`/`hist>=62` 守卫，生产无触发路径；建议研发在下次展示层维护时把提前返回改为 `{"warning":None,"main":None,"others":[]}`。

---

## DISPLAY-2 单品短期期望信号落地（2026-08-18 立项，③审计#2 有条件通过，交②算法研究专家执行）

### 立项卡
- **目标**：按复审版落地规格 `references/item-shortterm-expectancy-landing-spec.md` 将「单品短期期望信号」落地为**纯展示模块**：单品报告追加「短期期望」卡片，输出 7d/14d 期望中位数 + 翻正率 + n；机制 = 时期×时点先验 + 分时期单品特性（P超跌/S1S2供缩，S3/S4 只用先验）。**不进融合决策、不改任何 action/limit、不 bump ENGINE_VERSION。**
- **预注册判据（落地必须逐条兑现③审计#2 的 5 项条件，缺一不可）**：
  1. **纯展示硬约束**：ENGINE_VERSION 不 bump；新增「不进决策」断言测试过测（`compute_shortterm_expectancy` 不得写入/覆盖 `fusion_decision.action/action_label/position_limit` 等决策字段）。
  2. **S3/S4 限制**：S3/S4 不得启用单品特性，只用时期先验；若未来要扩大范围，必须重过发射侧检验 + ③审计。
  3. **查表口径**：`references/build_shortterm_table.py` 生成 `data/_exp_shortterm_table.json` 必须用 **SPLIT(2025-08-10) 前的 walk-forward train 拟合**，版本化（含版本号/生成时间/SPLIT/口径字段），与 stage8/9 发射侧口径一致。
  4. **可复现性**：补齐 stage7 可复现性字段（n_perm、seed、p 计算方法）；统一 base 口径（stage8/9 的 pred_base 必须一致，消除「stage8 spearman_base 无法从 stage9 复现」的漂移）。
  5. **P 期外推声明**：P 期仅 2 事件，展示模块/文档必须声明由 B 通道（~2027-04）或 live pilot（C 通道熔断）承担外推验证，不得声称已外推可靠。
- **验收标准**：
  1. ③审计#2 的 5 项条件逐条可验证（decision-log 落地条目中逐项打勾）。
  2. 新增 `pipeline/shortterm_expectancy.py` 纯函数 + `config.SHORTTERM_EXPECTANCY` 台账；查表产物 `data/_exp_shortterm_table.json` 含版本化元信息且口径与 stage8/9 一致。
  3. 单品报告按规格展示「短期期望」模块：7d/14d 中位数 + 翻正率 + n + 「本品特性」；S3/S4 不显示单品特性说明（只显示时期先验）；时点超界显示尾部渐近值。
  4. `tests/test_smoke.py` 新增 `t_shortterm_expectancy`（机制单测 + 渲染 + 不进决策断言）并全部通过；现有用例不得回退。
  5. `python tests/test_smoke.py` 0 failed；`python tests/check_encoding.py` PASS；`ENGINE_VERSION` 保持 v2-T13 不变（可测试断言）。
  6. 交付物：decision-log 落地条目（5 项条件逐项证据）+ `_exp_shortterm_table.json` + commit；PM 对照本卡验收，不达标回炉。
- **红线**：不触碰融合决策/信号族/守卫链/proximity/期望机制/组合层；不改 S3/S4 特性启用范围；不新增数据采集；不 bump ENGINE_VERSION；不改基线数字。

### PM 验收结论（2026-08-18）
- **结果：通过，DISPLAY-2 关闭。**
- 对照项逐项核验：
  1. 纯展示硬约束：`ENGINE_VERSION` 仍为 `v2-T13`；`tests/test_smoke.py::t_shortterm_expectancy` 含「返回无 action/action_label/position_limit/limit/buy/watch/avoid」断言；`compute_shortterm_expectancy` 只返回展示 dict。✅
  2. S3/S4 限制：`pipeline/shortterm_expectancy.py::_TRAIT_ENABLED={0,1,2}`，查表 `trait_enabled` 仅 P/S1/S2；S3/S4 走 prior/prior_tail。✅
  3. 查表口径：`data/_exp_shortterm_table.json` 含 `schema_version/table_version/data_cutoff=2025-08-09/split=2025-08-10/base_definition`；`build_shortterm_table.py` 明确 train=SPLIT 前拟合。✅
  4. 可复现性：decision-log AZ 记录 stage7 补 `seed=42/seed_scheme/p_method`、stage8/9 补 `pred_base_definition` 统一 base 口径；查表 `base_definition` 同步说明。✅
  5. P 期外推声明：查表记录 split/data_cutoff，规格 §六保留 B 通道/live pilot 声明，展示模块带「历史同态·非本次预测」。✅
  6. 落地物：`pipeline/shortterm_expectancy.py`、`references/build_shortterm_table.py`、`data/_exp_shortterm_table.json`、`config.SHORTTERM_EXPECTANCY`、`webapp/analysis_service.py` 注入、`analysis.html` 卡片、`tests/test_smoke.py::t_shortterm_expectancy` 均已核验存在。✅
  7. 冒烟与编码：decision-log AZ 记录 **131 passed / 0 failed / 0 skipped**，`tests/check_encoding.py` PASS。✅
- **备注**：AZ 未记录 commit hash，需研发/外部补交后视为最终闭环（同 DISPLAY-1 处理）。


---

## DOC-COMPACT-1 长文档归档压缩专项（2026-08-18 立项，交②算法研究专家执行）

### 背景统计（当前行数，2026-08-18 PM 只读盘点）
| 文件 | 行数 | 建议 |
|---|---|---|
| `references/decision-log.md` | 4757 | 优先归档压缩（保留近期条目 + 索引 + 归档卷链接） |
| `references/iteration-roadmap.md` | 823 | 优先归档压缩（版本历史压成摘要表，保留活跃立项/待办/验收） |
| `references/cs-knowledge.md` | 429 | 可评估拆分/压缩（接口知识可归档旧版本） |
| `AGENTS.md` | 340 | 可评估压缩历史结论区，保留总纲/纪律/活跃配置 |
| `references/data-source-health.md` | 295 | 可评估压缩历史检查口径，保留当前 SOP |
| `references/first-principles-market-fit.md` | 298 | 可评估压缩为结论摘要 + 归档过程稿 |
| `references/engine-unified.md` | 266 | 可评估压缩历史设计过程，保留当前架构 |
| `references/first-principles-modules-fit.md` | 229 | 可评估压缩为结论摘要 + 归档过程稿 |
| `references/data-layer.md` | 188 | 活跃手册，仅可压缩冗余历史说明，不整体归档 |
| `PROJECT_STRUCTURE.md` | 184 | 仅清理过时条目，不压缩主体 |
| `references/trading-strategies.md` | 182 | 可评估压缩历史研究，保留当前策略表 |
| `references/trend_leg_research.md` | 159 | 可评估压缩为结论摘要 |
| `references/current-state-expectancy-design.md` | 152 | 可评估压缩为设计定稿摘要 |
| 其余 references/*.md | ≤142 | 暂不压缩，或仅随清单评估 |

### 立项卡
- **目标**：对超长/过时内容累积明显的文档做**归档压缩**，主文件瘦身但保留可追溯性（索引 + 归档卷链接 + 决策编号不丢）。不物理删除任何仍有引用价值的决策/口径/审计证据。
- **预注册判据（必须先落盘清单再动）**：
  1. 先产出 `references/doc-compact-plan-2026-08-18.md`：每个候选文件的行数、压缩方式（整体归档 / 拆分归档 / 摘要替换）、保留范围、归档卷路径、引用检查证据。
  2. 仅处理上述候选清单中 PM 已列出的文件；清单外文件一律不动。
  3. `decision-log.md` 压缩后必须保留：最新战役（AQ~AY 及之后）+ 全部审计条目 + TOC/索引 + 归档卷链接；历史决策编号/结论仍可在归档卷检索。
  4. `iteration-roadmap.md` 压缩后必须保留：活跃立项卡（CLEANUP-1/DISPLAY-1/DISPLAY-2/DOC-COMPACT-1）+ 当前基线 + 未收口台账 + 版本摘要表；历史版本细节移归档卷。
  5. 所有归档卷放入 `references/archive/` 或新增 `references/archive/doc-compact-2026-08-18/`，文件名带日期；原文件顶部/索引必须指向归档卷。
  6. 压缩后全仓 `rg` 无悬空引用（指向归档卷的引用除外）；TOC/锚点可跳转。
- **验收标准**：
  1. 主文件行数显著下降（目标：decision-log ≤1500、iteration-roadmap ≤500；其余候选按实际可压缩量报告）。
  2. 归档卷完整保留被移出的决策/口径/审计内容，且索引可定位到原编号/章节。
  3. `tests/test_smoke.py` **130 passed / 0 failed / 0 skipped（不得因文档压缩改变测试数）**；`tests/check_encoding.py` PASS。
  4. `PROJECT_STRUCTURE.md`/AGENTS.md 中对归档卷的指针已同步。
  5. 交付物：`references/doc-compact-plan-2026-08-18.md` + 归档卷 + decision-log 条目 + commit；PM 对照本卡验收，不达标回炉。
- **红线**：不删任何仍被活跃引用/审计依赖/决策编号依赖的内容；不碰代码/测试/引擎/基线；不改变文档语义；不把活跃手册（data-layer/terminology/project-principles）整体归档。



