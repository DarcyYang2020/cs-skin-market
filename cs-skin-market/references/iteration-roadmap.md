# 迭代方案（Iteration Roadmap）

> **迭代闭环规则（2026-08-06 定稿）**：迭代执行 → 学习/试错 → 提炼新思路 → 映射为迭代项 → 更新本方案 → 按优先级继续迭代。
> 分工：本文件 = 计划（接下来做什么）；`decision-log.md` = 历史（为什么 / 试错细节）。
> **历史版本细节（v1~v70）+ 新思路映射 + 批次/状态追踪 + 各技术方案 已归档至 `references/archive/doc-compact-2026-08-18/iteration-roadmap-archive-2026-08-18.md`**。

## 版本摘要表（v1~v71，详细全文见归档卷）

| 版本 | 日期 | 摘要 |
|---|---|---|
| v81 | 2026-08-21，PM 立项（用户需求），新增功能 | 新增 AUTH-1「用户登录门禁」立项卡——不登录仅可看大盘（/ 只读），其余 7 页面 + 39 API 需登录；单用户凭据走 .env 先例（G-1 同款 CS_MARKET_PASSWORD）；starlette SessionMiddleware（补 itsdangerous）+ 登录页 + 导航登录态；不动引擎/决策 |
| v80 | 2026-08-20，PM 立项（CQ 差异表评估），研究预注册 | 新增 CQ-ADD-1「牛市上行段高选择性候选验证」立项卡——CQ 全链闭环（CP→CQ→CR/CS→CT，commit 7cd1f9f）差异表「该加 1」唯一候选；前置 CE bull_steady 证伪关联（宽触发稀释买书 A2 拒）；须预注册高选择性窄化判据，族开回放 + 完整四关 + ③审 |
| v79 | 2026-08-20，用户方法论裁定，旧路径取消 | **族划分重构旧路径（C1–C5）整体取消**（decision-log CN，commit 1e9475f）：C1-UNIFY 回滚（taxonomy 14细族/8键→6细族/3键，8 文件还原 3a31bb1）、C2-RISE-ACCUM 取消（②引擎独立全量证伪 chg7>10，CM）、C3/C4/C5 确认关闭；理由=374 有偏样本旧产物被「完全重构」（引擎独立扫描）新方法取代；冒烟 131/0/0、ENGINE_VERSION v2-T13；研究窗口聚焦新路径 |
| v78 | 2026-08-20，PM 立项（C2 候选移交），研究预注册 | 新增 C2-RISE-ACCUM「rise_accum 追涨腿收紧（chg7 下限 3→10）」立项卡——②预注册草案已备（references/c2-rise-accum-prereg-2026-08-20.md + decision-log CK，commit ee0c9ff）；样本内候选仅出研究，完整四关后交③审；验收=delta 零漂移 + 四关 + 附加否决线（⚠️ 2026-08-20 17:2x 已被 v79 取消——②引擎独立全量证伪，见 CM/CN） |
| v77 | 2026-08-20，PM 验收，零信号发射改动 | **C1-UNIFY 验收通过、关闭**（decision-log CJ）：独立核验冲突清零（base 组 64 条冲突 0）+ 新分布 6 组与 CG 预注册逐项一致 + 冒烟 131/0/0 + ENGINE_VERSION v2-T13；C2（rise_accum chg7 下限 3→10）按接力登记可另行立项 |
| v76 | 2026-08-20，PM 立项（C1 候选移交），零信号发射改动 | 新增 C1-UNIFY「三口径统一」立项卡——②候选移交（decision-log CG，commit 3a31bb1 已回滚生产代码、方案细节保留）；展示键 3→8 / 细族 6→14 / base 独立 / signal_guidance 派生；纯展示层零发射改动，ENGINE_VERSION v2-T13 不变；验收=冲突清零 + 冒烟 131/0/0 |
| v75 | 2026-08-20，用户实测否决，UI 回滚 | **UI 系列回滚（decision-log UI-R）**：用户实测反馈「除引擎/研究划分外，其他 UI 不如上个版本」→ 恢复 watchlist/checkup/discover/search/replay + analysis 等 partials + style.css 至 cc83e69 原版（UI-1/UI-3 验收结论作废）；**仅保留引擎/研究划分**（/ops 路由 + ops.html + engine_telemetry partial + 导航 + dashboard 3 卡拆分）；修复 /ops 404（根因：服务器未重启）；冒烟 131/0/0、ENGINE_VERSION 仍 v2-T13；commit b1d20a5 |
| v74 | 2026-08-20，PM 验收，零引擎变更 | **UI-1/UI-2/UI-3 三卡全部验收关闭，UI 系列收官（2026-08-20 15:5x 被用户实测否决，详见 v75/UI-R）**。UI-1（token 化止血 + regime-s2 对比度 + 文档归档）→ UI-2（首屏 7→3 拆分 + /ops 引擎研究视图）→ UI-3（discover/search/replay + analysis partials token 化 + emoji 语义 badge 化）均经 PM 独立只读核验通过；冒烟 131/0/0 保持、ENGINE_VERSION 仍 v2-T13 |
| v73 | 2026-08-20，UiDesigner 立项，零引擎变更 | 新增 UI-1/UI-2/UI-3 三卡——UI 全站优化（A+ token化止血 + 首屏拆分 + 系统化），纯 CSS/HTML/模板层，不动引擎/路由行为/测试，冒烟 131/0/0 不回退 |
| v72 | 2026-08-19，PM 立项，零引擎变更 | 新增 DATA-1「全池 3 年历史补全」立项卡（用户带话立项，交②执行）——解决品类孤品无历史→族划分失真；数据就绪后接力族划分重做+新信号验证（另立卡） |
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

### PM 验收结论（2026-08-18）
- **结果：通过，DOC-COMPACT-1 关闭。**
- 对照项逐项核验：
  1. 主文件行数：`decision-log.md` 4757 → 573/586（≤1500 ✅）；`iteration-roadmap.md` 823 → 262（≤500 ✅）；其余 11 个候选按实际评估报告，本轮不激进压缩。✅
  2. 归档卷完整：`references/archive/doc-compact-2026-08-18/` 下 `decision-log-archive-2026-08-18.md`（4517 行）+ `iteration-roadmap-archive-2026-08-18.md`（700 行），主文件头部/索引含归档链接，可定位原编号/章节。✅
  3. 预注册清单：`references/doc-compact-plan-2026-08-18.md` 已落盘，处置与清单一致。✅
  4. 指针同步：`PROJECT_STRUCTURE.md` 新增 `archive/doc-compact-2026-08-18/` 条目；AGENTS.md 无被归档内容活跃引用，无需改动。✅
  5. 活跃内容保留：`iteration-roadmap.md` 保留版本摘要表 + 当前基线 + 未收口台账 + 活跃立项卡（CLEANUP-1/DISPLAY-1/DISPLAY-2/DOC-COMPACT-1）及 PM 验收结论；`decision-log.md` 保留 AM~AZ 最新战役 + 审计条目 + 归档索引。✅
  6. 冒烟与编码：decision-log BA 记录 **131 passed / 0 failed / 0 skipped**，`tests/check_encoding.py` PASS；文档压缩未改变测试数。✅
  7. 交付物：doc-compact-plan ✅ + 归档卷 ✅ + decision-log BA 条目 ✅ + commit（用户确认已随本次提交入库；BA 未登记 hash，如需可补记）。✅

---

## DISPLAY-3 单品报告语境收敛（2026-08-18 立项，交②算法研究专家执行）

### 立项卡
- **目标**：消除单品报告里重复/冲突的期望语境，收敛为单一、互补的展示语义：
  1. **删除**「大盘语境行」中的「当下期望」（旧读 `_exp_period_continuous_curve.json` 均值曲线）——与 DISPLAY-2「单品短期期望」查表中位数完全重叠，两个「14d 期望」会打架；
  2. **删除**「大盘语境行」中的「大盘前视 period_forward」（该时期大盘自身前视 14d/30d）——与 DISPLAY-2 时期先验语义重叠，且大盘仪表盘已有；
  3. 大盘语境只保留**「时期 + 动作区」**（如 S3空仓 / P抄底）；
  4. **保留**独特性状态行（长持 60d/180d 结构与 7d/14d 短期期望互补）；**F6 供给锁仓是否并入 S1/S2 供给收缩特性仅作评估项**，本次不强制实施。
- **预注册判据**：
  1. `webapp/analysis_service.py` 中删除 `_point_in_time_expectancy` 调用及其追加的「当下期望：...」文案；若 `_point_in_time_expectancy` 无其他活跃引用则一并删除函数，有则保留并标注仅供其他入口。
  2. `webapp/analysis_service.py` 大盘语境行只保留 `当前 {period}——{action_note}`（或等价「时期+动作区」），不再拼接 `period_forward` 的 14d/30d 前视数字。
  3. `webapp/templates/partials/analysis.html` 同步删除/收敛对应文案，DISPLAY-2「短期期望」卡保持不变，成为单品报告 7d/14d 期望的唯一入口。
  4. 独特性状态行保持 DISPLAY-1 现有结构；F6 并入评估只允许输出评估结论，不得未经 PM/用户确认直接改变展示。
  5. 纯展示收敛：不触碰引擎/信号族/守卫链/proximity/组合层；不 bump ENGINE_VERSION；不改基线数字。
- **验收标准**：
  1. 单品报告不再出现两个「14d 期望」数字；大盘语境行不再出现「当下期望」「大盘自身前视 14d/30d」字样。
  2. 大盘语境行仍显示时期与动作区；DISPLAY-2 短期期望卡正常渲染。
  3. `_point_in_time_expectancy` 调用已删除；若函数无引用则已删除或标记废弃，`_exp_period_continuous_curve.json` 不再被单品报告读取。
  4. 独特性状态行保留；F6 并入评估结论已写入 decision-log（可评估为不并入）。
  5. `tests/test_smoke.py` **当前 131 passed / 0 failed 不得回退**（用户口述 130 为旧基线，以当前 131 为准）；`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍为 `v2-T13`。
  6. 交付物：decision-log 条目（改动点 + F6 评估结论）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：不碰融合决策/信号族/守卫链/proximity/期望机制/组合层/基线；不新增数据采集；不 bump ENGINE_VERSION；不删除独特性状态行；F6 并入不得在未确认时落地。

### PM 验收结论（2026-08-18）
- **结果：通过，DISPLAY-3 关闭。**
- 对照项逐项核验：
  1. 大盘语境行已收敛为「当前 {时期}——{动作区}」，`_fd_display` 中不再拼接 `period_forward` 14d/30d，也不再调用 `_point_in_time_expectancy`。✅
  2. `_point_in_time_expectancy` 整函数已删除，`_exp_period_continuous_curve.json` 不再被单品报告读取（保留为 build 产物存证）。✅
  3. DISPLAY-2「短期期望」卡保持为单品报告 7d/14d 期望唯一入口，模板无「当下期望」「period_forward」残留。✅
  4. 独特性状态行保持 DISPLAY-1 结构；F6 并入评估结论已写入 decision-log BB：**不并入**（F6=高位供缩警示，S1/S2 trait=正向吸筹信号，语义相反且位置条件不同）。✅
  5. 冒烟与编码：decision-log BB 记录 **131 passed / 0 failed / 0 skipped**，`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。✅
  6. 交付物：decision-log BB 条目 ✅ + commit（BB 未登记 hash，需研发/外部补交后视为最终闭环）。✅

---

## DISPLAY-5 单品短期期望·展示校准收口（2026-08-18 立项，③审计#3 复审路径⑤，交②算法研究专家执行）

### 立项卡
- **目标**：按 `references/item-shortterm-expectancy-display-calibration.md`（decision-log BC~BI 收官 + ③审计#3 复审路径⑤「展示校准豁免预测验证」口径）落地——当单品分析处于「S3 弱市阴跌 + chg30 ≤ −5%（深跌）」时，在短期期望卡片追加一行诚实标注，不改变预测算法与决策。
- **预注册判据**：
  1. 触发条件固定为：当前时期 = `S3弱市阴跌` 且 `chg30 ≤ −5%`；其他时期/浅跌不追加该行。
  2. 追加文案（含数字）必须与审计认可的展示校准口径一致，至少包含：
     `深跌阴跌 regime：历史同态 14d 中位数 −8.0%、翻正率 23%（n=8314），该 regime 为历史未出现的新 regime，无样本外能力，外推·低置信，由 B 通道(~2027-04)/live pilot 承担`。
  3. 数据来源：`data/_exp_stage14_p1c_extrapolation.json` 的 `S3阴跌--15~-5` 桶（n=8314 / fwd14_med=-7.97 / win=23.1），数字可读表或硬编码，但必须与产物一致。
  4. **不得修改** `pipeline/shortterm_expectancy.py::compute_shortterm_expectancy`（查表/预测逻辑不动），不得把 chg30 条件化写入预测算法；DISPLAY-2 短期期望卡主体数字保持不变。
  5. 纯展示：仅 `webapp/analysis_service.py` + `webapp/templates/partials/analysis.html`；不碰引擎/信号族/守卫链/proximity/组合层/基线；不 bump ENGINE_VERSION。
- **验收标准**：
  1. S3 深跌时短期期望卡显示该诚实标注行；S3 浅跌/其他时期不显示。
  2. `compute_shortterm_expectancy` 未被修改（可 diff 验证）；展示标注明确带「无样本外能力，外推·低置信，由 B 通道/live pilot 承担」，不声称预测。
  3. `tests/test_smoke.py` **当前 131 passed / 0 failed 不得回退**；`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。
  4. 交付物：decision-log 条目（触发条件 + 文案 + 数据源核对）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：不把深跌 S3 的 −8%/23% 作为「预测」落地；不改 `compute_shortterm_expectancy`；不 bump ENGINE_VERSION；不新增数据采集；不碰决策/基线。

### PM 验收结论（2026-08-18）
- **结果：通过，DISPLAY-5 关闭。**
- 对照项逐项核验：
  1. 触发条件：`analysis_service.py` 仅在 `period == "S3弱市阴跌"` 且 `market_signal()["chg30"] <= -5` 时设置 `regime_note`；其他时期/浅跌不追加。✅
  2. 文案与数据：`regime_note` 文案含「深跌阴跌 regime：历史同态 14d 中位数 −8.0%、翻正率 23%（n=8314）…无样本外能力，外推·低置信，由 B 通道(~2027-04)/live pilot 承担」；与 `_exp_stage14_p1c_extrapolation.json` S3 深跌桶（n=8314 / −7.97 / 23.1）一致。✅
  3. 不改算法：`pipeline/shortterm_expectancy.py::compute_shortterm_expectancy` 零改动；DISPLAY-2 主体数字不变；不 bump ENGINE_VERSION。✅
  4. 渲染：`analysis.html` 在短期期望卡「本品特性」下渲染 ⚠️ regime_note。✅
  5. 冒烟与编码：decision-log BK 记录 **131 passed / 0 failed / 0 skipped**，`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。✅
  6. 交付物：decision-log BK 条目 ✅ + commit（BK 未登记 hash，需研发/外部补交后视为最终闭环）。✅

---

## DISPLAY-6 单品报告冗余模块下架（2026-08-18 立项，交②算法研究专家执行）

### 立项卡
- **目标**：按用户裁定「短期期望无用 + 大盘语境冗余」，下架单品分析报告的：
  1. **短期期望卡片**（DISPLAY-2 `compute_shortterm_expectancy` 注入 + DISPLAY-5 深跌 S3 标注）；
  2. **大盘语境行**（DISPLAY-3「当前时期+动作区」）。
  保留**独特性状态行**（唯一有长持结构信息增量）。纯展示删除，不改变任何引擎/决策/信号族/基线。
- **预注册判据**：
  1. `webapp/analysis_service.py` 删除：`_shortterm_expectancy_note` 调用及 `fd["shortterm_expectancy"]` 注入、`regime_note` 设置；删除「大盘语境：当前 {时期}——{动作区}」caveat 追加；若 `_shortterm_expectancy_note` 无其他引用则一并删除函数。
  2. `webapp/templates/partials/analysis.html` 删除：短期期望卡渲染块（`{% if fusion_decision.shortterm_expectancy %}...{% endif %}`）；不再渲染任何「短期期望」「7d 期望」「14d 期望」「深跌阴跌 regime」内容；不再渲染「大盘语境」。
  3. 保留：独特性状态行（`_uniqueness_note` + 模板 mapping 分支）与 DISPLAY-1 结构；保留其他研究口径提示（族特征/F 判别等）。
  4. `pipeline/shortterm_expectancy.py` 与 `data/_exp_shortterm_table.json`：允许归档为研究存证或保留但确保无活跃引用；**不得修改 `compute_shortterm_expectancy` 逻辑**；不得触碰其他引擎/决策/信号族/基线。
  5. 纯展示：不 bump ENGINE_VERSION；不新增数据采集；不改基线数字。
- **验收标准**：
  1. 单品报告不再显示短期期望卡（无「短期期望」「7d 期望」「14d 期望」「深跌阴跌 regime」等文案）；不再显示「大盘语境：当前」。
  2. `analysis_service.py` 无 `_shortterm_expectancy_note` 调用/`shortterm_expectancy` 字段/`regime_note` 注入；模板无对应渲染块。
  3. 独特性状态行仍正常显示；其余研究口径提示不受影响。
  4. `pipeline/shortterm_expectancy.py` 与查表产物无活跃引用或已归档为研究存证；`ENGINE_VERSION` 仍 `v2-T13`。
  5. `tests/test_smoke.py` **当前 131 passed / 0 failed 不得回退**；`tests/check_encoding.py` PASS。
  6. 交付物：decision-log 条目（删除点 + 研究存证去向）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：不碰融合决策/信号族/守卫链/proximity/组合层/基线；不 bump ENGINE_VERSION；不删除独特性状态行；不改 `compute_shortterm_expectancy` 逻辑（仅允许归档/去引用）。

### PM 验收结论（2026-08-18）
- **结果：通过，DISPLAY-6 关闭。**
- 对照项逐项核验：
  1. 短期期望卡已下架：`analysis_service.py` 无 `_shortterm_expectancy_note` 调用/`fd["shortterm_expectancy"]`/`regime_note`；模板无「短期期望」「7d 期望」「14d 期望」「深跌阴跌 regime」渲染块。✅
  2. 大盘语境行已下架：`_fd_display` 无 `market_signal` 调用与「大盘语境：当前…」caveat；模板无对应渲染。✅
  3. 独特性状态行保留：`_uniqueness_note` + 模板 mapping 分支仍在，DISPLAY-1 结构未动；其余研究口径提示保留。✅
  4. 研究存证：`pipeline/shortterm_expectancy.py` + `data/_exp_shortterm_table.json` + `config.SHORTTERM_EXPECTANCY` 保留为研究存证，`compute_shortterm_expectancy` 逻辑零改动；webapp 无活跃引用。✅
  5. 冒烟与编码：decision-log BL 记录 **131 passed / 0 failed / 0 skipped**，`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。✅
  6. 交付物：decision-log BL 条目 ✅ + commit（BL 未登记 hash，需研发/外部补交后视为最终闭环）。✅

---

## EXEC-1 P0 执行飞轮（2026-08-18 立项，交②算法研究专家执行）

### 立项卡
- **目标**：把「发现 → 分析 → 决定 → 执行 → 复盘」跑通，驱动真实执行记录增长到 **≥20 条有效记录**，解锁 A1-4 成本/滑点校准与真实组合净值复盘。纯产品/展示/数据闭环改动，不碰引擎/决策/信号族/基线。
- **预注册判据**：
  1. 执行记录零摩擦：单品报告、批量扫描、discover 高分榜、watchlist 四处均保留/补齐「一键记录执行」入口（复用共享 exec-modal，已有能力不重造）。
  2. 未记录 buy 提醒：watchlist 对近 7 天已出现 buy 但未记录执行的条目给出明确提醒/待决策状态（已有雏形则强化到可操作）。
  3. 自动结算与滑点：执行记录到期自动结算（14/30 日）、滑点展示（advice_price vs exec_price）保持可用；复盘页真实 vs 纸面（executions vs signal_tracking）对照卡可解释。
  4. 不新增数据采集、不改引擎/决策/信号族/守卫链/组合层/基线；不 bump ENGINE_VERSION；不触碰 `pipeline/shortterm_expectancy.py` 研究存证逻辑。
  5. 冒烟不得回退：当前 **131 passed / 0 failed**；`tests/check_encoding.py` PASS。
- **验收标准**：
  1. 四处入口均能一键记录执行，且记录后自动同步持仓/到期结算/滑点。
  2. watchlist 未记录 buy 提醒可看到、可点击记录。
  3. 复盘页真实 vs 纸面对照卡正常展示；`executions` 从当前基线增长，2 周内达到 **≥20 条有效记录**（含手动/一键录入；已有历史记录算入）。
  4. `tests/test_smoke.py` **131 passed / 0 failed 不得回退**；`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。
  5. 交付物：decision-log 条目（改动点 + 当前 executions 基线 + 达成情况）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：不碰融合决策/信号族/守卫链/proximity/组合层/基线；不新增数据采集；不 bump ENGINE_VERSION；不删已有执行记录能力；不把模拟盘/真实盘口径混为一谈。

### PM 验收结论（2026-08-18）
- **结果：通过（实现验收），EXEC-1 关闭；过程目标待观测。**
- 对照项逐项核验：
  1. 四处一键执行入口核对：单品报告（analysis.html buy 按钮）✓、批量扫描（`batch_scan._exec_btn`）✓、discover（经单品报告入口）✓、自选（`openExecManual`）✓；记录后自动同步持仓 / 14-30 日自动结算 / 滑点均已有。✅
  2. 未记录 buy 提醒：`page_watchlist` 注入 `monitor.unrecorded_buys`，watchlist 今日关注卡新增「📝 未记录执行」行（蓝底 + 记录执行 + 报告）。✅
  3. 复盘对照：真实 vs 纸面（executions vs signal_tracking）复盘能力已有，未破坏。✅
  4. 冒烟与编码：decision-log BM 记录 **131 passed / 0 failed / 0 skipped**，`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。✅
  5. 过程目标：`executions` 当前基线 **8 条**（BM 已登记）；2 周内 ≥20 为**观测目标**，非本改动即时验收项。PM 后续按 BM 基线跟踪，达标后另行登记；若到期未达标，再评估是否需要更强提醒/激励。✅
  6. 交付物：decision-log BM 条目 ✅ + commit（BM 未登记 hash，需研发/外部补交后视为最终闭环）。✅

---

## DISPLAY-7 信号复盘数据源更新到当前基线（2026-08-18 立项，交②算法研究专家执行）

### 立项卡
- **目标**：将 `/replay` 信号复盘页数据源从 `data/item_backtest_full_2025.json`（317 信号，v2-T4/T5 旧引擎冻结基线）切换到 `data/_exp_cycle_replay_period_route.json`（189 信号，v2-T13 官方 HQ 口径），使复盘页展示当前基线。
- **预注册判据**：
  1. 仅切换 `webapp/main.py` 的 `api_signals_replay` 读取文件路径（一行改动）及页面 meta 口径说明同步；不改字段结构、不改渲染逻辑。
  2. 目标文件 `data/_exp_cycle_replay_period_route.json` 必须存在且 `signals` 字段结构与旧文件一致（signal 明细字段可被现有复盘页渲染）。
  3. 页面 meta 口径说明同步为：**189 信号 / v2-T13 / 官方 HQ 口径**，并注明旧 317 基线已冻结为历史存证（不在复盘页主数据源使用）。
  4. 纯数据源切换：不碰引擎/决策/信号族/基线数字；不 bump ENGINE_VERSION；不新增数据采集。
  5. 冒烟不得回退：当前 **131 passed / 0 failed**；`tests/check_encoding.py` PASS。
- **验收标准**：
  1. `/replay` 页面加载后显示 **189 信号**，且页面口径标注为 v2-T13 / 官方 HQ（可含旧 317 存证说明）。
  2. 信号明细列表/聚合/事件标注等现有功能在新数据源下正常渲染（不依赖旧文件独有字段）。
  3. `item_backtest_full_2025.json` 仍保留为 HIST-FULL 冻结基线，但不作为 `/replay` 主数据源。
  4. `tests/test_smoke.py` **131 passed / 0 failed 不得回退**；`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。
  5. 交付物：decision-log 条目（数据源切换 + 口径说明）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：不碰引擎/决策/信号族/守卫链/组合层/基线数字；不 bump ENGINE_VERSION；不新增数据采集；不改变信号复盘页功能范围。

### PM 验收结论（2026-08-18）
- **结果：通过，DISPLAY-7 正式关闭（2026-08-18，BUG-1 已恢复冒烟 131/0/0）。**
- 对照项逐项核验：
  1. 数据源切换：`api_signals_replay` 已改读 `data/_exp_cycle_replay_period_route.json`（189 信号 v2-T13 官方 HQ），字段结构兼容（date/name/entry_price/fwd_series/fwd14/fwd30），渲染逻辑零改动。✅
  2. 页面口径：`meta` 含 `engine="v2-T13"` / `caliber="官方 HQ 口径"` / `frozen_note`，replay.html 同步展示「189 信号 · v2-T13 · 官方 HQ」+ 旧 317 冻结说明。✅
  3. 旧基线保留：`item_backtest_full_2025.json` 仍为 HIST-FULL 冻结存证，不作 `/replay` 主数据源。✅
  4. 引擎/基线未触碰：`ENGINE_VERSION` 仍 `v2-T13`；未改信号/决策/基线。✅
  5. 冒烟：BN 记录 **130 passed / 1 failed / 0 skipped**，1 个失败 = `t_live_snapshot_sync`（TH 窗口 off-by-one，独立于 DISPLAY-7）；编码 PASS。→ 按立项卡条件已由 BUG-1 修复后满足：BO 记录 131/0/0，`t_live_snapshot_sync` 恢复通过 → DISPLAY-7 正式关闭。✅
  6. 交付物：decision-log BN 条目 ✅ + commit（BN 未登记 hash，需补记后最终闭环）。✅

---

## BUG-1 TH 窗口 off-by-one 修复（2026-08-18 立项，交②算法研究专家执行）

### 立项卡
- **目标**：修复 `market_index_stats` 与 `build_market_context` 对大盘 TH 计算窗口不一致的问题（live 用 `values[-90:]` 90 值，backtest 用 `values[i-90:i+1]` 91 值），使 live 大盘 TH 与回测口径一致，恢复 `t_live_snapshot_sync` 通过和冒烟 131/0/0。
- **预注册判据**：
  1. 先确认设计口径：以 `build_market_context`（回测/统一口径，含当前日共 91 值）为事实源；`market_index_stats` 对齐到同一窗口语义（含当前日）。
  2. 只改窗口切片/输入长度，不改 TH 评分公式、阈值、情绪/周期等任何引擎参数。
  3. 若修复导致 live/回测信号或基线数字变化，必须先回测先行 + 登记 decision-log，并评估是否需要 ENGINE_VERSION bump；若仅对齐口径且无信号变化，则不 bump。
  4. 不新增数据采集；不碰其他引擎/决策/信号族/基线。
  5. 冒烟必须恢复 **131 passed / 0 failed**；`tests/check_encoding.py` PASS。
- **验收标准**：
  1. `t_live_snapshot_sync` 通过；冒烟 **131 passed / 0 failed / 0 skipped**。
  2. `market_index_stats` 与 `build_market_context` 的 TH 窗口长度/语义一致（可测试断言或代码审查确认）。
  3. 无其他测试回退；`ENGINE_VERSION` 如未发生信号/基线变化则保持 `v2-T13`（如有变化按预注册判据处理）。
  4. 交付物：decision-log 条目（根因 + 修复 + 对信号/基线影响说明）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：不改变 TH 公式/阈值/参数；不新增数据采集；不 bump ENGINE_VERSION（除非评估必须且已走审计）；不掩盖测试失败。

### PM 验收结论（2026-08-18）
- **结果：通过，BUG-1 关闭。**
- 对照项逐项核验：
  1. 根因确认：`market_index_stats` 原用 90 值窗口，`build_market_context` 用 91 值含当日窗口；TH 差 2 分（33 vs 35）。✅
  2. 修复内容：`analyze_index(market_history[-91:])` + `compute_market_trend_health(values[-91:])`，仅改窗口切片，未改 TH 公式/阈值/情绪/周期。✅
  3. 影响评估：live TH 33→35 与回测事实源一致；未跨越任何守卫/族闸门阈值，无信号/基线变化，`ENGINE_VERSION` 保持 `v2-T13`。✅
  4. 冒烟与编码：decision-log BO 记录 **131 passed / 0 failed / 0 skipped**（`t_live_snapshot_sync` 恢复通过）；`tests/check_encoding.py` PASS。✅
  5. 交付物：decision-log BO 条目 ✅ + commit（BO 未登记 hash，需研发/外部补交后视为最终闭环）。✅

---

## DISPLAY-8 批量扫描估值列改大白话（2026-08-18 立项，交②算法研究专家执行）

### 立项卡
- **目标**：把批量扫描结果「估值列」从「低估/合理/高估/泡沫 + pct=X%」改为一句人话，只回答「贵不贵」，不暗示「可不可买」（买不买交给距买点列）。
- **预注册判据**：
  1. 映射固定为：
     - `undervalued` → **「历史低位，比较便宜」**
     - `fair` → **「价格适中」**
     - `overvalued` → **「历史高位，偏贵」**
     - `bubble` → **「历史顶点，太贵了」**
  2. 仅改 `webapp/templates/partials/scan_html.html` 的估值单元格文案；估值判定阈值/评分/引擎/决策逻辑一律不动。
  3. 主文案必须是一句人话，不再以「低估/合理/高估/泡沫」作为主答案；pct 可保留为次要小字或移除，但不得作为主答案，且不得暗示买卖建议。
  4. 口径与距买点对齐保持不变（低估线同为 pct≤30），不新增/修改任何判定。
  5. 纯展示：不 bump ENGINE_VERSION；不新增数据采集；不改基线数字。
  6. 冒烟不得回退：当前 **131 passed / 0 failed**；`tests/check_encoding.py` PASS。
- **验收标准**：
  1. 批量扫描估值列按上述映射显示一句话人话；不再出现「低估/合理/高估/泡沫」作为主标签（可接受作为 tooltip/隐藏口径说明，但主显示必须是新文案）。
  2. 估值判定逻辑、阈值、评分、引擎/决策输出均未改变（可 diff 验证）。
  3. `tests/test_smoke.py` **131 passed / 0 failed 不得回退**；`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。
  4. 交付物：decision-log 条目（映射表 + 改动点）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：不碰估值判定/阈值/评分/引擎/决策/基线；不 bump ENGINE_VERSION；不新增采集；不把「贵不贵」暗示成「买不买」。

### PM 验收结论（2026-08-18）
- **结果：通过，DISPLAY-8 关闭。**
- 对照项逐项核验：
  1. 映射正确：`scan_html.html` 估值单元格使用 `{'undervalued':'历史低位，比较便宜','fair':'价格适中','overvalued':'历史高位，偏贵','bubble':'历史顶点，太贵了'}.get(...)`，未知值兜底原值。✅
  2. 主文案已改人话：不再显示 `r.valuation_tier` 英文键/「低估/合理/高估/泡沫」主标签；pct 保留为次要小字。✅
  3. 零改动：估值判定/阈值/评分/引擎/决策/距买点口径未动；不新增采集；不 bump ENGINE_VERSION。✅
  4. 冒烟与编码：decision-log BP 记录 **131 passed / 0 failed / 0 skipped**，`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。✅
  5. 交付物：decision-log BP 条目 ✅ + commit（BP 未登记 hash，需研发/外部补交后视为最终闭环）。✅


















---

## DATA-1 全池 3 年历史补全（2026-08-19 立项，用户带话立项，交②算法研究专家执行）

### 背景与动机（PM 只读盘点，数字已核实）
- **问题**：生产库 405 品中，非印花非角色饰品约 241 品；其中**只有 92 品历史 first_date < 2025-08-01**（能覆盖 2025 恐慌事件 + 2025 牛市段），**66 品完全无历史**（含新加手套 9、武器箱、挂件、冷门枪等），其余大量品历史起点为 2026-05-10（生产库 365 天保留策略的截断）。→ 「品类孤品无历史 → 族划分失真、2025 信号缺失无法归因」的数据面证据确凿。
- **先例已实测**：v2-T9（2026-08-15）确认 csQAQ `/info/chart` `period=1095` 返回 2023-06-01 起 1171 根日线（`main_data`=价格、`num_data`=在售量）；`references/backfill_cycle_window.py` 已建 `data/replay_cycle_win.db` 并回填过回放池 A 96 品 120,641 行（2023-06-01~2026-08-14）。本卡是**同一机制的存量扩容**（96 品 → 全池 241 品）。
- **范围口径（dry-run 前须核对）**：目标 = 405 − 印花 160 − 角色（清单）。印花 160 = `name LIKE '印花 |%'`（排除枪皮「M4A1消音版 | 印花集」，其名含「印花」但属枪皮）；角色清单（用户口径 4，实际核查 5，dry-run 以清单为准）：
  `指挥官 梅 "极寒" 贾米森 | 特警` / `海军上尉里克索尔 | 海军水面战中心海豹部队` / `陆军中尉普里米罗 | 巴西第一营` / `亚诺（野草） | 游击队` / `德拉戈米尔 | 军刀勇士`（注意「亚诺」用全角括号）。
- **目标库**：`data/replay_cycle_win.db`（3 年历史只进回放库；生产库 365 天保留策略不动）。
- **与 BQ 诊断联动**：本卡为研究窗口 2026-08-19 只读诊断（decision-log BQ「信号族分类审计 + 池子品类覆盖诊断」→ `data/_exp_family_audit_2026-08-19.json`）的**数据底座落地**——BQ 确诊「族三口径冲突（base 兜底 80 条混 4 语义）/ 2025-02~04 信号真空 / 孤品无历史（树篱迷宫仅 96 天）」并建议扩池为数据层职责；本卡补齐 3 年历史后，BQ 子题②「急跌型恐慌」探针可在全历史窗口重跑，族划分重做另立卡。

### 立项卡
- **目标**：把全池非印花非角色饰品（约 241 品，含手套/匕首/冷门枪/箱/挂件）的 3 年（period=1095）价格 + 在售量历史补齐到回放库 `replay_cycle_win.db`，使**回放池内每品 first_date 早于 2025-08-01**，覆盖 2025 恐慌事件与 2025 牛市段；为后续族划分重做与新信号验证提供完整数据底座。本卡只到「数据就绪」，族划分重做与新信号验证在数据验收通过后**另立卡**交②。
- **预注册判据（执行窗口必须先按此做，禁止先跑再改判据）**：
  1. **dry-run 先行**：基于 `references/backfill_cycle_window.py` 改造（允许新增独立脚本，不得改动既有回放脚本的活跃行为），先 `--dry-run` 产出**精确目标清单**落盘 `data/_exp_data1_plan.json`：含每品名称 / 是否已有历史 / first_date / 需补日期数 / 排除理由（印花 160 + 角色清单）；**清单即预注册**，实际回填品必须与清单一致，清单外零改动；若清单总数 ≠ 241（角色 4 vs 5 差异），以清单为准并在清单内登记差异说明。
  2. **数据源与字段**：csQAQ `/info/chart` `period=1095`（`main_data`=价格 → `price_rmb`、`num_data`=在售量 → `in_sale_count`），与 v2-T9 实测口径一致；沿用采集纪律（单浏览器会话 / 失败重试退避 / K 线失败台账），避开每日 18:00 全量采集窗口执行，冲突先在 decision-log 占坑。
  3. **去重不覆盖**：回填前按 `(item_id, date)` 与库中已有数据去重，只补缺失日期，**不覆盖已有值**；回填完成后必须做二次审计（gap 区间行数变化 / 区间外已有值零覆盖 / `failed_goods=0`），审计口径参照 v2-T9 回填审计（decision-log 归档卷）。
  4. **只写回放库**：不得写生产库 `market.db`；不改引擎/决策/信号族/守卫链/组合层/基线；不 bump ENGINE_VERSION；不改 `pipeline/` 活跃逻辑（脚本可新增于 `references/`）。
  5. **回放产物保护**：回填前若需重建 `replay_cycle_win.db` 或以任何方式改动既有回放库，必须先备份既有库（`.bak` 按研究域自清规则）并在 decision-log 占坑；不得删除/覆盖任何 `_exp_*.json` 回放产物。
  6. 冒烟不得回退：当前 **131 passed / 0 failed**；`tests/check_encoding.py` PASS。
- **验收标准（PM 对照）**：
  1. `data/_exp_data1_plan.json` 与实际回填逐项一致（无清单外回填；清单内未回填品须注明原因）。
  2. **覆盖率**：目标池（约 241 品）中每品 `price_history.first_date < 2025-08-01` 覆盖率达到 100%，或列出无法覆盖品及其原因（如 2024 年后上市新品、无 num_data 品——该类登记为「数据源无历史」而非「回填失败」）；目标池内无 first_date 停留在生产库 365 天截断起点（2026-05 前后）的品。
  3. 去重审计：已存在日期零覆盖；补入日期数 = 清单预估（允许 ±5%）；`failed_goods=0`。
  4. 冒烟 **131 passed / 0 failed 不得回退**；`tests/check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。
  5. 交付物：改造脚本（或新脚本）+ `data/_exp_data1_plan.json` + 回填产物（回放库）+ decision-log 条目（含二次审计数字）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：不写生产库；不改引擎/决策/基线/测试；不 bump ENGINE_VERSION；不删改 `_exp_*.json` 回放产物；不把回放库 3 年历史当实时价格回灌生产；不把「回填后重做族划分 + 新信号验证」混入本卡（数据就绪后另立卡）。
- **后续接力（登记，不并入本卡）**：数据验收通过 → ②重做族划分（241 品 3 年窗口）→ 新信号验证走预注册探针 + ③审计；届时 PM 按需立「族划分重做」卡。

### PM 验收结论
- **结果：通过，DATA-1 关闭（2026-08-19，PM 独立只读核验，未采信执行窗口自述）。**
- 对照项逐项核验：
  1. 清单与实际一致：`data/_exp_data1_plan.json`（240 品 = 405−印花160−角色5，差异已登记 note；清单即预注册）与实际回填一致——inserted_dates 145,692 与 dry-run 预估完全一致，清单外零改动。✅
  2. 覆盖率：good_id>0 的 224 品中 **222 品 first_date<2025-08-01（99.11%）**；2 品豁免 = `AK-47 | 流金王朝`（接口最早 2025-09-25）/ `挂件 | 丁烷拍档`（接口最早 2025-10-09），均 2025-09~10 上市新品 → 「数据源无历史」豁免（非回填失败）；16 品 no_good_id（2026-08-19 当日新加品，csQAQ 无 good_id 映射）登记跳过。✅
  3. 去重审计：`overwritten_existing=0`（overwrite_check_count=120,641 全量比对）；PM 独立查库 `(item_id,date)` 重复组数=0；inserted_dates 145,692 与预估一致；`failed_goods=0`。✅
  4. 冒烟与编码：PM 亲自重跑 **131 passed / 0 failed / 0 skipped**；`check_encoding.py` PASS（hard 0，warnings 为历史已知脏名）；`ENGINE_VERSION` 仍 `v2-T13`。✅
  5. 交付物：`references/backfill_full_pool.py` + `_exp_data1_plan.json` + `_exp_data1_audit.json` + 回放库（120,641→266,333 行，238 品）+ decision-log BS + commit `f5c2d05`/`fade8a9`（PM 已验）。✅
  6. 抽查：专业手套翠绿之网 / AK-47 二西莫夫 / 反恐精英武器箱 各 1175 行、in_sale 全非空、2023-06-01~2026-08-18。✅
- **遗留待办（不阻塞关闭，登记）**：16 品 no_good_id（今日新增）无 3 年历史，待 csQAQ good_id 映射建立后小补（交运维/研发登记）；PM 侧落盘（roadmap v72 + decision-log BR/验收）待统一 commit。
- **接力登记**：族划分重做 + 新信号验证待 PM 另立卡（数据底座已就绪）。

---

## UI-1 全站 UI 止血：token 化 + 对比度 + 文档归档（2026-08-20 立项，UiDesigner 提出，交前端/研发窗口执行）

### 背景与动机（UiDesigner 实地评审，全站指纹已扫描）
- 设计系统 `webapp/static/css/style.css` v3 本身成熟（indigo 主色 / IBM Plex Sans / 4px 间距 / 44px 触控 / reduced-motion / skip-link / focus-visible），但**页面层几乎未用**：全站 6 整页 + 4 partials 大量内联 `style=`、硬编码 rgba 裸写、emoji 当唯一状态载体。
- 量化指纹（templates 扫描）：watchlist 内联192/硬色10/emoji31（最重）、dashboard 内联89/硬色10、checkup 内联42/硬色3（regime-s2 对比度不达标）、analysis partial 内联86、index_analysis partial 内联48、discover 内联21/硬色1/emoji8、replay 内联23/emoji3、search 内联9（btn-scan 重复定义）。
- 文档漂移：`design-system/cs-market/MASTER.md` 是失效深色 OLED 概念稿（自称"禁止浅色模式/禁止 emoji"），与已落地浅色 indigo v3 冲突，且 `pages/` 空置从未管辖页面。

### 立项卡
- **目标**：让 style.css v3 token 真正生效——补一组语义工具类、以 watchlist 为样板去内联/硬色、修 checkup regime-s2 对比度到 AA、归档失效 MASTER.md；**纯 CSS/HTML，零功能变更**。本卡为 UI 系统化（UI-3）的先行止血。
- **预注册判据（执行窗口必须先按此做，禁止先改再定判据）**：
  1. **补 token 工具类**：`style.css` 新增 `.tint-accent`(rgba(79,70,229,.1)) / `.bg-inset-2`(rgba(15,23,42,.04)) / `.bg-amber`(rgba(245,158,11,.08)/.12) / `.bg-purple`(rgba(139,92,246,.12)) / `.border-blue`(#2563EB) 等，覆盖全站裸 rgba 模式。
  2. **watchlist 样板**：内联 192 → 抽 partial + 工具类；裸 `rgba(245,158,11,..)` / `rgba(139,92,246,..)` / `rgba(15,23,42,0.5/0.2)`（加载层）全部替换；趋势列 `📈/📉/➖` 加文字（涨/跌/平）或 `aria-label`。
  3. **checkup regime-s2**：`#1890ff`/`#e6f7ff`（Ant 蓝）改为 `--blue` #2563EB 体系或加深文字色，使对比度 ≥ 4.5:1。
  4. **文档归档**：`MASTER.md` 更新为"实际系统 = style.css v3 浅色 indigo"，删"禁止浅色/禁止 emoji"等过时条款；`pages/` 补各页规格（可选）。
  5. **禁令**：不动 `main.py` / 引擎 / `pipeline/` / 测试；不 bump `ENGINE_VERSION`；不改任何功能行为（仅视觉 token 化，渲染结果应像素一致）。
  6. 冒烟不得回退：当前 **131 passed / 0 failed**；`tests/check_encoding.py` PASS。
- **验收标准（UiDesigner 对照）**：
  1. grep 全站 `templates/` 无裸 `rgba(15,23,42` / `rgba(245,158,11` / `rgba(139,92,246` / `#1890ff`（允许 `var()` 内或注释）。
  2. watchlist 内联 `style=` 数从 192 显著下降（目标 < 40）且裸色值清零；视觉回归无破损。
  3. regime-s2 对比度工具测 ≥ 4.5:1。
  4. MASTER.md 无"禁止浅色模式"/"禁止 emoji"等过时条款。
  5. 冒烟 **131 passed / 0 failed 不回退**；`check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。
  6. 交付物：改动文件 + decision-log 条目 + commit；对照本卡验收，不达标回炉。
- **红线**：不碰引擎/决策/路由/测试；不 bump ENGINE_VERSION；不改功能行为；不创建设计系统以外的样式体系。
- **后续接力（登记，不并入本卡）**：UI-2（首屏拆分）→ UI-3（系统化其余整页/partials）。

### PM 验收状态（2026-08-20 独立只读核验，⚠️ 已作废——2026-08-20 15:5x 用户实测否决，详见 v75 / decision-log UI-R）
- **核验方式**：PM 未采信执行窗口自述，独立读原始产物（style.css 逐行 grep / templates 全局裸 rgba 扫描 / 亲自重跑冒烟+编码 / 读 MASTER.md / 取真实色值用 WCAG 公式重算对比度）。
- **逐项结论**：
  - C1 模板无裸 rgba：**通过（最终复核）**。原先 3 处（`index_card.html:39`、`index_analysis.html:25,73`）已按严格口径清零、新增 `--green-border-strong`/`--amber-border-strong` token 已落地 ✅；PM 按用户提醒的「**全局 `grep -rn "rgba(" webapp/templates/`、`不带 -v var(--`**」方法复核，发现 **`dashboard.html:24` 仍有裸 `rgba(239,68,68,0.08)`**（红色崩溃告警框背景，同行含 `var(--red)`，`grep -v "var(--"` 会整行吞掉漏检）——研发补 `535eaba` 改 `var(--red-bg)` 后，PM 于 2026-08-20 15:15 后重跑 `grep -rn "rgba(" webapp/templates/` **零命中**，C1 字面+全局双通过。另 `render_html.py:128`/`main.py:1004` 裸 rgba 属 discover 页（UI-3 范围，不计入 UI-1）。
  - C2 watchlist 去内联：**通过**（192→9，裸色零命中）。
  - C3 regime-s2 对比度：**通过**（新增 `--blue-text:#1D4ED8` 五类共用；重算 白卡 5.83 / inset 5.35 / hover 5.59，全表面 ≥5；commit `6c59d64`；原研发报 4.55 经独立重算实为 4.50 且 inset 仅 4.13，已纠正）。
  - C4 MASTER.md：**通过**（已归档为浅色 v3 事实源，无"禁止浅色模式"过时条款；第 22 行为合理 emoji 新规）。
  - C5 冒烟/编码/版本：**通过**（131 passed/0 failed；encoding PASS；ENGINE_VERSION 仍 v2-T13）。
  - C6 交付物：**通过**（commit `6c59d64`/`76112ef`/`535eaba` 在库；本状态文本 + decision-log 关闭条目由 PM 落盘）。
- **遗留与处置（待裁决）**：C1 的 3 处裸 rgba 落在 `index_card`/`index_analysis` 两个 partial（本属 UI-3 范围）。两种收口方式：① **严格（推荐）**：在 UI-1 内把这 3 行迁到 `.bg-inset-2` + 新增 `--green-border-strong`/`--amber-border-strong` 用于 index_analysis:73 动态边框，C1 字面通过、UI-1 关闭；② **收窄口径**：把 C1 验收文字改为"watchlist+checkup 无裸 rgba"（对齐 UI-1 实际范围），2 个 partial 标记为 UI-3 承接，UI-1 现价关闭。两种均不碰引擎/路由/测试。
- **遗留与处置（更新）**：C1 原 3 处已清零；现余 `dashboard.html:24` 裸 `rgba(239,68,68,0.08)` 待迁（改 `var(--red-bg)`，与既有 `--red-bg:rgba(220,38,38,0.1)` 同系近似；不碰引擎/路由/测试）。该处迁完且全局 `grep -rn "rgba(" webapp/templates/` 零命中后，C1 字面+全局双通过、UI-1 正式关闭。
- **状态**：**✅ 已关闭**（2026-08-20 15:15 后 PM 重验，C1~C6 全过）。关键抓手：C1 用用户提醒的 `grep -rn "rgba(" webapp/templates/`（不带 `-v`）最终复核零命中，坐实并修复了 `-v var(--` 漏检坑（dashboard:24 裸 rgba 同行含 var(--red)）。UI-2（首屏拆分 /ops）、UI-3（系统化其余页）按序挂账待接力。

## UI-2 首屏信息架构拆分：投资视图 + /ops 引擎研究视图（2026-08-20 立项，UiDesigner 提出，交前端/研发窗口执行）

### 背景与动机
- `dashboard.html` 首屏堆 7 卡：综合指数/市场状态/模拟盘（投资视图）+ 引擎状态 J-2/未来事件/数据健康/数据积累进度（研发遥测），普通用户被 J-2 三通道/信号族样本深度/去簇胜率淹没。与项目多 agent 治理呼应：投资者视图与引擎/研究视图应物理分离。
- 遥测数据接口已存在：`/api/data/progress`（J-2 三通道/信号族样本深度/去簇胜率/重拟合触发）、`/api/health/status`、`/api/portfolio/dashboard`、`/api/paper/status`；`main.py` 现有 6 路由无 `/ops`。

### 立项卡
- **目标**：首屏改为 3 卡投资视图（综合指数+情绪 / 市场状态·该怎么做 / 模拟盘精简），新增 `/ops` 独立路由承载全部研发遥测；普通用户首屏路径零处出现 J-2/去簇术语。
- **预注册判据**：
  1. `dashboard.html` 首屏 7 卡 → 3 卡（删 4 张遥测卡，其"该怎么做"语义上移至市场状态卡作为主 CTA）。
  2. 新增 `templates/ops.html`（复用 `base.html`）+ `main.py` `@app.get("/ops")` 路由（GET，渲染 ops.html；数据复用现有 `/api/data/progress` + `/api/health/status`，不新造接口）。
  3. `base.html` 导航加"引擎/研究"项 → `/ops`（用既有 `.nav-link` token）。
  4. 抽遥测为 `templates/partials/engine_telemetry.html` partial 供 `/ops` 复用（可选，降耦）。
  5. 不动引擎/决策/信号族/守卫链/组合层；不 bump ENGINE_VERSION；不改数据接口逻辑（仅前端编排）。
  6. 冒烟 131/0/0 不回退。
- **验收标准**：
  1. 首屏卡片 ≤ 3；首屏 `dashboard.html` + `app.js` grep 无 `J-2` / `去簇` / `信号族样本` 字样。
  2. `/ops` 可独立访问，4 块遥测数据完整（对照 `/api/data/progress` 字段）。
  3. 导航"引擎/研究"跳转正确、高亮正确。
  4. 冒烟 131/0/0；`ENGINE_VERSION` 仍 `v2-T13`。
- **红线**：同 UI-1；不把引擎/研究视图做成"新功能"，仅重排既有遥测。
- **后续接力**：UI-3（系统化其余页面 token 化）。

### PM 验收状态（2026-08-20 独立只读核验，⚠️ 已作废——2026-08-20 15:5x 用户实测否决，详见 v75 / decision-log UI-R）
- **核验方式**：不采信执行窗口自述，独立读原始产物（dashboard.html 全卡结构 / ops.html + engine_telemetry.html 4 块遥测逐块核对 / main.py 路由与传参 / base.html 导航高亮逻辑 / 亲自重跑冒烟+编码 / ENGINE_VERSION 取值）。
- **逐项结论（对照立项卡验收标准）**：
  1. 首屏卡片 ≤ 3 + 术语零命中：**通过**。按立项卡 7 卡口径（综合指数/市场状态/模拟盘 + 4 遥测卡），首屏剩 3 区块：`market-index-block`（index_card 综合指数 + index_analysis 大盘分析明细）、市场状态·该怎么做（主 CTA 上移）、模拟盘精简；遥测 4 卡（引擎状态 J-2 / 未来事件 / 数据健康 / 数据积累进度）已物理移出 dashboard → 全部收进 `engine_telemetry.html` partial。`dashboard.html` + `app.js` grep `J-2`/`去簇`/`信号族样本` **零命中** ✅。
  2. `/ops` 独立访问 + 4 块遥测完整：**通过**。`main.py:267 @app.get("/ops")` 渲染 ops.html（extends base.html，page-header + include engine_telemetry.html）；partial 内 4 块齐：引擎状态(J-2 监测) / 未来事件 / 数据健康 / 数据积累进度（内含 J-2 三通道 A/B/C、信号族样本深度 HIST-FULL/CLEAN-CUR、去簇对照、重拟合触发）；数据复用 `/api/data/progress` + `/api/health/status`，**零新造接口** ✅。
  3. 导航跳转 + 高亮：**通过**。`base.html:57` 新增「引擎/研究」`href="/ops"` + `{% if active_page=='ops' %}class="active" aria-current="page"{% endif %}`；`/ops` 路由传 `active_page="ops"` ✅。
  4. 冒烟/编码/版本：**通过**。PM 亲自重跑 **131 passed / 0 failed / 0 skipped**；encoding PASS；`ENGINE_VERSION` 仍 `v2-T13`（config.py:445 赋值确认）✅。
- **口径备注（明示防歧义）**：首屏「≤3 卡」按立项卡自身的区块级口径计数（综合指数区块含 index_analysis 的大盘分析明细子卡——决策/四宫格/抛压/大盘阶段，均属投资视图既有内容，非 UI-2 引入、非遥测卡）；若按 HTML `.card` 元素级计数则远超 3，UI-3 阶段可作信息密度优化项。
- **交付物**：commit `92eeb44`（UI-2 split dashboard 7→3 + /ops + engine_telemetry partial）；本状态文本 + decision-log 条目由 PM 落盘。
- **状态**：**✅ 已关闭**（2026-08-20 15:35 后 PM 重验，标准 1~4 全过）。**UI-3 按序接力**。

## UI-3 UI 系统化：其余整页 + partials token 化 + emoji 语义规范（2026-08-20 立项，UiDesigner 提出，交前端/研发窗口执行，挂账后续）

### 背景与动机
- UI-1/UI-2 覆盖 watchlist/checkup/dashboard 后，剩余：整页 discover(21/1/8)/replay(23/3)/search(9，btn-scan 重复)；partials analysis(86)/index_analysis(48)/analysis_results（被 report modal 复用）。问题与 UI-1 同源（内联/硬色/emoji），需统一收口。

### 立项卡
- **目标**：discover/replay/search 整页 + analysis/index_analysis/analysis_results partials 全面 token 化；落地 emoji 语义规范（图标型可保留，禁止 emoji 当唯一状态载体）。
- **预注册判据**：
  1. `discover.html` 批量扫描结果面板套统一 card/table token；`render_html.py` → `discover_html.html` partial 同步改。
  2. `search.html` 删内联 `<style>` 重复 `.btn-scan` 定义，统一 `style.css`。
  3. `analysis`/`index_analysis`/`analysis_results` partials 抽公共 partial + token 化；评级 S/A/B/C 用 badge（非 emoji+色块裸写）。
  4. **emoji 语义规范**：图标型 emoji（🔍📊）作装饰可保留；**禁止 emoji 当唯一状态载体**（趋势📈/评级🔴须配文字或 `aria-label`）；或统一迁移 Lucide SVG。
  5. `replay.html` 残留内联 token 化（低优先）。
  6. 不动引擎；不 bump ENGINE_VERSION；冒烟 131/0/0。
- **验收标准**：
  1. 各页内联 `style=` 数较基线下降（discover 21→<10；search 9→0 重复定义消除；analysis 86→<30；index_analysis 48→<20）。
  2. emoji 当唯一状态载体清零（grep 无无文字兜底的 📈/🔴 状态用法）。
  3. 冒烟 131/0/0；`ENGINE_VERSION` 仍 `v2-T13`。
- **红线**：同 UI-1/UI-2。
- **执行顺序（登记）**：watchlist→checkup（UI-1）→ dashboard/ops（UI-2）→ discover→analysis→index_analysis→search→replay（UI-3）。

### PM 验收状态（2026-08-20 独立只读核验，⚠️ 已作废——2026-08-20 15:5x 用户实测否决，详见 v75 / decision-log UI-R）
- **核验方式**：不采信执行窗口自述，独立扫描各页内联 `style=` 计数（与立项基线对比）/ emoji 状态载体全局 grep / 评级 badge 落地 / discover_html partial 同步 / 裸 rgba 不回退复核 / 亲自重跑冒烟+编码 / ENGINE_VERSION 取值。
- **逐项结论（对照立项卡验收标准）**：
  1. 各页内联 `style=` 降幅：**全部达标**。discover 21→**1**（<10 ✅）、search 9→**0** 且内联 `<style>` 归零、`.btn-scan` 重复定义消除（统一到 style.css:330 唯一定义 ✅）、analysis 86→**11**（<30 ✅）、index_analysis 48→**7**（<20 ✅）、replay 23→**1**、analysis_results→**1**。残留 1~2 处均为合理动态样式（progress-fill 宽度 / JS 动态色 / rank_style 动态 rank 样式），非硬编码色值。
  2. emoji 语义清零：**通过**。状态型 emoji（趋势 📈/📉/➖、评级 🔴🟢🟡）grep **零命中**（无文字兜底的状态 emoji 清零）；评级 S/A/B/C 已 badge 化——`.grade-s/a/b/c` 四档 token badge 落地（style.css:384-387，`--green-bg`/`--blue-bg` 等 token + `--blue-text`）；装饰型 emoji（🔍📊📡 等）按规范保留。
  3. 冒烟/编码/版本：**通过**。PM 亲自重跑 **131 passed / 0 failed / 0 skipped**；encoding PASS；`ENGINE_VERSION` 仍 `v2-T13`（config.py:445 赋值确认）✅。
- **附加核验**：裸 rgba 全局 `grep -rn "rgba(" webapp/templates/` **零命中**（UI-1 成果未回退）✅；`render_html.py` → `discover_html.html` partial 同步落地（内联 1 处动态样式）✅。
- **交付物**：commit `7eb9d2a`（UI-3 systematize discover/search/replay + analysis partials，inline 86→11、52→7、emoji text fallback）；本状态文本 + decision-log 条目由 PM 落盘。
- **状态**：**✅ 已关闭**（2026-08-20 15:48 后 PM 重验，标准 1~3 全过）。**UI-1/UI-2/UI-3 全部收官，UI 系列完结。**

---

## C1-UNIFY 三口径统一（2026-08-20 立项，②候选移交，交研发窗口执行）【⚠️ 已取消——2026-08-20 17:2x 用户方法论裁定，见 v79 / decision-log CN】

### 背景与动机（PM 只读核查，已核实）
- **候选来源**：decision-log CG 条目（②研究产出，完整方案细节保留）；commit `3a31bb1` 已按角色边界回滚生产代码（②只做研究、落地须 PM 立项→研发执行），回滚后 8 文件还原至 `b1d20a5` 状态、冒烟 131/0/0 复验。
- **问题**：族划分三口径（引擎 SIGNAL_FAMILIES / config 展示键 / signal_guidance 关键词匹配）互不统一 → family_map 冲突清单 80 条 base 兜底（深值/吸筹型上涨误归 base），展示分类失真。
- **当前现状（PM 独立核实）**：`SIGNAL_FAMILY_TAXONOMY` 细族 6、展示键 3（panic/deep_value/accumulate）；`signal_guidance` 用自身关键词匹配（未用 assign_fine_family）；`ENGINE_VERSION` 仍 `v2-T13`；pipeline/tests/webapp 工作区无未提交生产改动。

### 立项卡
- **目标**：三口径统一——`config.SIGNAL_FAMILY_TAXONOMY` 细族 6→14、展示键 3→8（panic/deep_value/accumulate/rise/longhold/oversold/base/weak_market），`signal_guidance` 改用 `assign_fine_family` 派生展示键，`base` 从 accumulate 独立；**纯展示层、零信号发射改动**，ENGINE_VERSION `v2-T13` 不变。本卡按 decision-log CG 条目方案落地（改动点 1~5 + 踩坑固化）。
- **预注册判据（执行窗口必须先按此做，禁止先改再定判据）**：
  1. **config.py**（唯一事实源）：`SIGNAL_FAMILY_TAXONOMY` 细族 6→14 = 引擎 `SIGNAL_FAMILIES` 11 族 + `base`（分批建仓=融合基础买点）+ `deep_dip`（深度回调低吸=P0 超跌）+ `weak_market`（弱市抗跌=历史遗留）；展示键 3→8（panic/deep_value/accumulate/rise/longhold/oversold/base/weak_market）；`base` 从 accumulate 独立（C1 前 accumulate=supply+deep_dip+base，C1 后不含 base）；fine_order 按关键字特异性排序、`分批建仓`最后兜底。
  2. **batch_scan.py signal_guidance**：废除自身关键词匹配，改用 `assign_fine_family`→展示键；仅对 taxonomy 未识别的历史/通用标签（周期吸筹/超跌反弹）保留关键词兜底；补 deep_value/rise/weak_market 持有指引。
  3. **sync_expectancy_config.py**：小样本组（n<5，如弱市抗跌 n≈2）跳过期望统计（无统计意义）——修复 C1 8 组下 render None 崩溃。
  4. **连带数据重跑（4 处）**：`ITEM_EXPECTANCY_STATS`（HIST-FULL 4 组：panic 92 / deep_value 27 / accumulate 176 / base 22）+ `ITEM_EXPECTANCY_STATS_CLEAN_CUR` + `data/signal_event_counts.json`（J-3 进度卡）+ `data/portfolio_attribution.json`（8 组归因）。
  5. **测试更新**（`tests/test_smoke.py` 2 处）：t_replay_source / t_data_progress 的硬编码 3 分组（恐慌/深值/else→accumulate）改用 `display_key_for_label`（单一事实源），小样本组同口径跳过。
  6. **文档同步**：`references/terminology.md` / `AGENTS.md` 口径同步（C1 前 accumulate 含 base n=198 归因 +111.69pp；C1 后 accumulate 不含 base n=176 归因 +95.72pp、base 独立 22 条 +19.66pp）。
  7. **禁令**：不改信号发射/决策/守卫链/组合层；不 bump ENGINE_VERSION；不写生产库；不回改 C1 前任何行为。
  8. 冒烟不得回退：当前 **131 passed / 0 failed / 0 skipped**；`tests/check_encoding.py` PASS。
- **验收标准（PM 对照 CG 条目验证节）**：
  1. **冲突清零**：基线 374 信号中「深值/吸筹型上涨 误归 base」= 0（C1 前 deep_value→base、rise_accum→base 兜底）。
  2. 新 signal_type 分布：panic 149 / accumulate 82 / deep_value 48 / base 64 / rise 29 / weak_market 2（基线 374 滤污染后）。
  3. 冒烟 **131 passed / 0 failed / 0 skipped 不回退**；`check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。
  4. 模板零硬编码 signal_type（UI 安全）；4 处数据重跑产物与 CG 数字一致（HIST-FULL 4 组 n 值）；8 文件落地 + decision-log 落地条目 + commit；PM 对照本卡验收，不达标回炉。
- **红线**：零信号发射改动；不 bump ENGINE_VERSION；不写生产库；不把 C1 与族划分重构/新信号族混入本卡。
- **后续接力（登记，不并入本卡）**：C1 落地后，C2（rise_accum chg7 下限 3→10，证据最充分）可另行立项；C3/C4/C5 按 CE 闭环结论挂账（C1 外暂无新族落地项）。

### PM 验收结论（2026-08-20 ✅ 通过，关闭）
- **核验方式**：不采信执行窗口自述，独立只读核验原始产物（config.py taxonomy 直查 / signal_guidance 实现直读 / 独立对 374 基线信号重算分布 / base 组标签内容审计 / 4 处数据产物直查 / 亲自重跑冒烟+编码 / ENGINE_VERSION 取值）。
- **逐项结论（对照本卡验收标准）**：
  1. **冲突清零：通过**。独立用 `signal_guidance` 对 `_exp_cycle_replay_fullpool_2026.json` 377 信号滤污染 3 条（流金王朝×2/丁烷拍档×1）= 374 重算：base 组 64 条全部为「🟢 分批建仓」标签，含深值/吸筹/恐慌/涨 的冲突标签 **= 0**（C1 前 deep_value→base、rise_accum→base 兜底已消除）✅
  2. **新分布 6 组：通过**。panic **149** / accumulate **82** / deep_value **48** / base **64** / rise **29** / weak_market **2**，合计 374、无未知键，与 CG 预注册逐项一致（longhold/oversold 当前基线 0 属数据现状）✅
  3. **冒烟/编码/版本：通过**。PM 亲自重跑 **131 passed / 0 failed / 0 skipped**；encoding PASS；`ENGINE_VERSION` 仍 `v2-T13`（config.py:506 赋值确认）✅
  4. **交付物：通过**。config 细族 14/展示键 8、signal_guidance 用 assign_fine_family（历史标签兜底）、sync 小样本跳过（n<5）、4 处数据产物直查一致（EXPECTANCY_STATS HIST-FULL panic 92/deep_value 27/accumulate 176/base 22 + CLEAN-CUR + 进度卡 + 归因）、test_smoke 2 处改 display_key_for_label、terminology/AGENTS 同步、commit `dd8c47c` 在库 ✅
- **口径备注**：rise_contract（深收缩）/deep_dip（深度回调）映射到 accumulate 展示组为设计如此（terminology「accumulate 展示组 = supply_accum + deep_dip + rise_contract + volatile_accum + second_wave」），非误归。
- **状态**：**✅ 已关闭**（2026-08-20 16:38 后 PM 重验，标准 1~4 全过）。**C2（rise_accum chg7 下限 3→10，证据最充分）按接力登记可另行立项**；C3/C4/C5 按 CE 闭环结论挂账。

---

## C2-RISE-ACCUM rise_accum 追涨腿收紧（chg7 下限 3→10）（2026-08-20 立项，②预注册草案移交，交②研究窗口执行）【⚠️ 已取消——②引擎独立全量证伪 chg7>10（decision-log CM），随旧路径一并取消，见 v79 / decision-log CN】

### 背景与动机（PM 只读核查，已核实）
- **候选来源**：decision-log CE 闭环（C2 为唯一独立落地候选）+ H3 验证（`_exp_h2h3_family_boundary_2026-08-20.json`）；②预注册草案已落盘 `references/c2-rise-accum-prereg-2026-08-20.md` + decision-log CK（commit `ee0c9ff`），本卡直接提取。
- **当前现状（PM 独立核实）**：`pipeline/item_analysis.py:1262` rise_accum trigger 现为 `chg7 > 3`；上限 `_rise_chg7_cap()` 默认 15（item_analysis.py:1124）；TH≥55 环境门 / `supply_change_30d > 5` / `s7 ≤ 0.85*s30` / limit 0.05 / priority 28 / dedup 28 均在；`references/run_family_variant_replay.py` 注入机制在库；基线全池回放 `_exp_cycle_replay_fullpool_2026.json` 374 信号（滤污染 3 条）中 rise_accum **29 条**，chg7 分桶 ≤5:4 / 5<chg7≤10:11 / >10:14 与草案 H3 表一致。
- **样本内证据（非结论）**：chg7 3~10 段 win 18.2% / avg −4.58（温和追涨陷阱）；>10 段 win 50% / avg +24.0（强势追涨段）。剔除 rise_accum 后全样本 win14 71.9%→75.1%；rise_accum 是唯一负中位数族（med14 −3.2）。

### 立项卡
- **目标**：研究 rise_accum 族 trigger 收紧为 `chg7 > 10` 后的全池回放表现——若四关通过则作为落地候选交③审计、PM 立项研发落地；**本卡仅研究，不落地**。候选锁定：只改 `chg7 > 3 → chg7 > 10`，上限 15 / TH≥55 / sc30>5 / s7≤0.85*s30 / limit / priority / dedup 等其余条件一律不动。
- **预注册判据（②必须先按此做，禁止先跑再定判据）**：
  1. **反过拟合声明（硬门槛）**：阈值 10 是 374 样本内按 chg7 分桶选出的候选（n=14 小样本），**只能作为候选阈值**；最终以四关 walk-forward 验证段（≥2025-08-10）为准——验证段 chg7>10 段不显著即**证伪**，不得以样本内数字辩护。
  2. **回放口径**：复用 `references/run_family_variant_replay.py` 注入机制，**替换 rise_accum 的 trigger**（非新增族）：运行时注入 `chg7 > 10` 版 trigger 到 `SIGNAL_FAMILY_BY_KEY["rise_accum"]`，同步重建派生结构（BY_KEY / _POST_FAMILIES / 买涨腿循环）；池 = 232 品 3 年（同基线全池回放口径）；env：CS_ENGINE_PERIOD_ROUTE=1；输出独立文件 `data/_exp_c2_rise_accum_replay_2026-08-20.json`。不改 pipeline/ 任何生产代码。
  3. **delta 清单（③硬验收，与 CE 同口径）**：①基线非 rise_accum 信号逐条字节一致（fwd/net 零漂移）——证明注入没污染其他族；②rise_accum 信号数变化 29 → N，列出 chg7 3~10 段被砍的 11 条明细；③displaced/relabeled：被砍信号是否被其他族重新捕获或彻底消失；④月度/单品分布（防单事件簇）。
  4. **完整四关（沿用 CC 否决线）**：A2 发射分布复算（`a2_emission.analyze(变体, 基线, "吸筹型上涨", "rise_accum")`——added/displaced 是否改善买书质量，验证段 win14 ≥ 基线 book 78.9% 贡献方向正确、p_avg 显著）→ 组合级（`b1_risk_backtest_v2.py` simulate：期望/胜率 ≥ 基线、maxDD 不恶化）→ 前后半段一致（切点 2025-08-10，两段方向一致）→ 置换检验（chg7>10 段 win/avg 相对随机子集显著）。
  5. **附加否决线（沿用 CC 预注册）**：单月信号占比 >50% 自动驳回。
  6. 冒烟不得回退：当前 **131 passed / 0 failed / 0 skipped**；`tests/check_encoding.py` PASS。
- **验收标准（PM 对照）**：
  1. delta 清单 4 项齐全：零漂移（基线非 rise_accum 字节一致）+ 29→N + 被砍 11 条明细 + displaced/月度分布。
  2. 完整四关逐关通过（A2 / 组合级 / 前后半段 / 置换），验证段（≥2025-08-10）chg7>10 显著；任一关不通过 = 证伪关闭，不替③改到通过。
  3. 产物落 `data/_exp_c2_rise_accum_replay_2026-08-20.json` + decision-log 落地条目（正/负结果一律登记）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：②只做研究——不落地生产代码、不改 pipeline/、不 bump ENGINE_VERSION、不写生产库；样本内只出候选；不替③"改到通过"；产物只写 `data/_exp_*.json`。
- **后续接力（登记，不并入本卡）**：四关通过 → 候选交③审计 → PM 立落地卡交研发；证伪则关闭并登记。
- **C3/C4/C5 排期结论（用户裁定 2026-08-20）**：C4（急跌型恐慌族）**已关闭不排期**——crash_vol 单月 100% 触 A2 否决线；C5（新老池）**已结论不排期**——不分池；C3（低吸按持有期重划）**不随 C2 排期**——C1 落地后 signal_guidance 已有 deep_value 21 日 / rise 14 日持有指引，核心主张被部分覆盖，剩余为展示层微调，视 PM 意愿单独评估或关闭。

### PM 验收结论
- （待②执行后对照本卡逐项验收）

---

## CQ-ADD-1 牛市上行段高选择性候选验证（2026-08-20 立项，CQ 差异表「该加 1」唯一候选，交②研究窗口执行）

### 背景与动机（PM 只读核查，已核实）
- **候选来源**：CQ 全链闭环（CP 预注册 → CQ 切分 → CR/CS ③审计 → CT 收尾，commit `7cd1f9f`）产出对照差异表 `_exp_optimal_partition_comparison_2026-08-20.json`——**「该加 1」= 牛市/强势上行段盲区**（PM 独立读产物确认：rise_accum verdict「该加（大盘上行段盲区，须高选择性；关联 CE bull_steady 证伪）」，unobserved_dims=[s7/s30 均值, market_th]）。
- **前置证伪关联（硬约束）**：CE 已证伪朴素版（bull_steady 族开回放 added 13,279 条，avg14 +5.99 vs 基线买书 +25.07，win14 49.1% vs 78.9% → A2 发射复算 FAILED）——**「宽触发族」不可落地**；CQ 数据支撑（leaf11/12 供缩更强 + 事件 7 个最稳）仅初判，**须高选择性窄化使信号量级与买书可比**，否则直接复用 CE 证伪结论。
- **切分数据背景**：CQ 切分 208,517 分析集 → 21 过 gate；牛市/强势上行 5 候选 49,421 条（大盘上行 mchg21>3.7~14.5 + 低波动 vol30≤82 + 供给收缩 sc30 −0.1~−10.8）；leaf8 n=27,677 超宽（窗口 72%）排除，leaf11/12 供缩更强、事件 7 个最稳。

### 立项卡
- **目标**：研究「牛市上行段高选择性窄化」候选族——若族开回放 + 完整四关通过，作为落地候选交③审计 → PM 立落地卡交研发；**本卡仅研究，不落地**。
- **预注册判据（②必须先按此做，禁止先跑再定判据）**：
  1. **高选择性窄化定义（候选锁定，跑前定死）**：以 CQ leaf11/12（供缩更强、事件 7 个最稳）为数据支撑，预注册窄化条件——须含大盘上行段（mchg21 上界）∩ 供给收缩（sc30 负区间）∩ 低波动（vol30 上界），并声明目标信号量级（与基线买书可比，参考 added 量级目标 ≤ 数百条而非万级）；窄化条件未预注册不得开跑。
  2. **反过拟合声明（硬门槛）**：CQ 切分区域为样本内观察，窄化阈值仅作候选；最终以 walk-forward 验证段（≥2025-08-10）为准，验证段不显著即证伪，不得以样本内数字辩护。
  3. **回放口径**：复用 `references/run_family_variant_replay.py` 注入机制（运行时注入新 trigger，非新增族属性改版；同步重建 BY_KEY/_POST_FAMILIES/买涨腿循环）；池 = 232 品 3 年（同基线全池回放口径）；env：CS_ENGINE_PERIOD_ROUTE=1；输出独立文件 `data/_exp_cq_add1_replay_2026-08-20.json`。不改 pipeline/ 生产代码。
  4. **delta 清单（③硬验收，与 CE 同口径）**：①基线非新族信号逐条字节一致（fwd/net 零漂移）；②added 数量与量级声明对照（防宽触发——若 added 万级直接对齐 CE 证伪）；③displaced/relabeled；④月度/单品分布（防单事件簇）。
  5. **完整四关（沿用 CC 否决线）**：A2 发射分布复算（`a2_emission.analyze(变体, 基线, ...)`——added 质量须与买书可比：val 段 win14 ≥ 基线 book 78.9% 贡献方向正确、p_avg 显著）→ 组合级（`b1_risk_backtest_v2.py` simulate：期望/胜率 ≥ 基线、maxDD 不恶化）→ 前后半段一致（切点 2025-08-10）→ 置换检验。
  6. **附加否决线（沿用 CC 预注册）**：单月信号占比 >50% 自动驳回；**added 量级万级（≥10,000）自动对齐 CE bull_steady 证伪结论驳回**。
  7. 冒烟不得回退：当前 **131 passed / 0 failed / 0 skipped**；`tests/check_encoding.py` PASS。
- **验收标准（PM 对照）**：
  1. 预注册窄化条件先行落盘（`references/cq-add1-prereg-2026-08-20.md` 或 decision-log 条目），未预注册即视为无效执行。
  2. delta 清单 4 项齐全（零漂移 + added 量级 + displaced + 月度分布）；added 量级与买书可比（非万级）。
  3. 完整四关逐关通过（A2 / 组合级 / 前后半段 / 置换），验证段显著；任一关不通过 = 证伪关闭。
  4. 产物落 `data/_exp_cq_add1_replay_2026-08-20.json` + decision-log 落地条目（正/负一律登记）+ commit；PM 对照本卡验收，不达标回炉。
- **红线**：②只做研究——不落地生产代码、不改 pipeline/、不 bump ENGINE_VERSION、不写生产库；样本内只出候选；不替③"改到通过"；产物只写 `data/_exp_*.json`。
- **后续接力（登记，不并入本卡）**：四关通过 → 候选交③审计 → PM 立落地卡交研发；证伪则关闭登记。CQ 差异表「该留 3」（恐慌共振/恐慌退潮/深值企稳）登记衔接事件级验证（A 通道≥3，J-2 监测既有）；「待补 7」挂账等特征矩阵补扫（含 s7/s30 均值/sent/TH/dd20）后下一轮对照。
- **遗留（登记，不阻塞）**：18:57 data 误删事件来源排查结果待④运维回填（CT 条目）。

### PM 验收结论
- **（自主模式执行，非独立人类，可复核）CQ-ADD-1 证伪关闭**（decision-log DB，2026-08-21 01:33 执行完成）：
  1. 预注册窄化条件先行落盘 ✓（`references/cq-add1-prereg-2026-08-20.md`）
  2. delta 清单 4 项齐全，**net_drift=0**、added=463（新族 460，非万级，与买书可比量级声明一致）✓
  3. 完整四关：**第一关 A2 FAILED**（val p_avg=1.0）、第二关新族独立组合 maxDD -70.65%（劣于基线 -30.85%）、第三关 val win14 44.7%<60 不可比、第四关置换 val p=1.0 不显著 → **任一不过即证伪关闭** ✗
  4. 产物已落：回放/delta/3年重算基线 + decision-log DB 条目；提交待与当日工作一并处理
- **验收结论**：不达标回炉 → **候选证伪，无落地卡**；CQ 差异表「该加 1」牛市上行段缺口维持未解（CE 朴素版 + CQ-ADD-1 窄化版双证伪）。「待补 7」按用户 07:56 诚实复核修正：**源自老引擎族概念、无新信息源、无正向信号，降级为存档挂账（研究债务），不再作为主动突破口**；未来仅当出现真正新信息源（情绪/资金流/事件类数据）时再评估，且须先预注册防多重比较。

---

## AUTH-1 用户登录门禁（2026-08-21 立项，用户需求，交研发窗口执行）

### 背景与动机（PM 只读勘察，已核实）
- **需求**：上线需要用户登录功能——不登录只能看大盘，其他功能需登录。
- **现状**：8 页面路由（/ 大盘 /ops /search /watchlist /checkup /replay /discover）+ **39 个 /api 接口**，**零鉴权基础**（无 session/login/auth/cookie/password 痕迹）；依赖栈 FastAPI + Jinja2Templates，无 SessionMiddleware；单用户本机工具（run_server host=127.0.0.1:8000）；凭据环境变量化先例 = G-1（`API_TOKEN = os.environ.get("CSQAQ_API_TOKEN")`，.env 已存在）。
- **技术前提（PM 已核实）**：`starlette.middleware.sessions.SessionMiddleware` 可用，但依赖 `itsdangerous` **未安装**（ModuleNotFoundError 实测）——需补装（唯一运行时新依赖）。

### 立项卡
- **目标**：加装登录门禁——**未登录仅可访问大盘页（/，只读）与登录页**；其余 7 页面（/ops /search /watchlist /checkup /replay /discover）+ 全部受保护 API 需登录。单用户（无注册），凭据环境变量化。**纯 webapp 层改动，不动引擎/决策/信号族。**
- **预注册判据（研发必须先按此做，禁止先改再定判据）**：
  1. **登录方案**：starlette `SessionMiddleware`（secret_key 从环境变量 `CS_MARKET_SESSION_SECRET` 读，未配置则生成随机临时 key 并告警）；登录态存 `request.session["auth"] = True`。
  2. **凭据**：单用户密码 = 环境变量 `CS_MARKET_PASSWORD`（G-1 同款 .env 先例；未配置时登录接口拒绝并报错提示，同 collector 缺配置报错语义）。无注册/无多用户/无找回。
  3. **登录页**：`templates/login.html`（复用 base.html 风格 token；表单 POST `/login` → 校验 → 成功写 session 跳回原页，失败提示）。登出 POST `/logout`（清 session）。
  4. **访问控制**：未登录访问受保护页面 → 302 重定向 `/login?next=<原路径>`；受保护 API → 401 JSON（未登录）或 403（已登录但无权限——本卡无角色，403 不适用，统一 401）。**大盘页 / 与大盘只读 API 豁免**（见验收 4 清单）。
  5. **导航**：base.html 导航显示登录态（未登录隐藏受保护入口或点击跳登录；已登录显示「退出」）。
  6. **豁免清单（预注册，PM 裁定）**：`/`（大盘页）、`/login`、`/logout`、`/static/*`、`/favicon.ico` 豁免；**大盘只读 API 豁免**：`/api/market/signal`（大盘信号——「看大盘」核心）、`/api/data/progress`、`/api/health/status`、`/api/portfolio/dashboard`、`/api/paper/status`（dashboard 页渲染依赖，只读展示）；**写操作一律保护**：`/api/market/refresh`、`/api/items/*`、`/api/watchlist/*`、`/api/backup/*`、`/api/discover/*`、`/api/analysis/*`、`/api/executions/*` 等。豁免清单以实际页面渲染依赖为准，研发实现时逐路由核对并登记。
  7. **安全底线**：密码比对用 `hmac.compare_digest`（防时序）；session cookie `httponly=True`（SessionMiddleware 默认）；明文密码不落库（环境变量只在进程内）。
  8. **禁令**：不改引擎/决策/信号族/守卫链/组合层；不 bump ENGINE_VERSION；不改 `pipeline/` 核心逻辑；登录不影响采集/回放/计划任务（后台任务不经 web 鉴权）。
  9. 冒烟不得回退：当前 **131 passed / 0 failed / 0 skipped**；`tests/check_encoding.py` PASS。
- **验收标准（PM 对照）**：
  1. **未登录**：`curl /` → 200（大盘可看）；`curl /watchlist` → 302 到 /login；`curl /api/watchlist/executions` → 401；`curl /api/market/signal` → 200（豁免）。
  2. **已登录**（cookie 会话）：`curl -c cookies -b cookies` 登录流程 → 全部页面 200、受保护 API 200。
  3. 错误密码 → 401/拒绝且不写 session；登出后受保护页恢复 302。
  4. 豁免清单逐项核对：大盘只读 5 API 未登录 200；写 API（market/refresh 等）未登录 401。
  5. 冒烟 **131 passed / 0 failed / 0 skipped 不回退**；`check_encoding.py` PASS；`ENGINE_VERSION` 仍 `v2-T13`。
  6. 交付物：main.py 鉴权改动 + login.html + 导航改动 + .env 样例（CS_MARKET_PASSWORD 说明，**不提交真实密码**）+ decision-log 落地条目 + commit；PM 对照本卡验收，不达标回炉。
- **红线**：不动引擎/决策/测试/基线；不 bump ENGINE_VERSION；凭据不提交代码库；登录功能不引入多用户/注册体系（本卡仅单用户门禁）。
- **后续接力（登记，不并入本卡）**：如需局域网访问（改 host 绑定 0.0.0.0）或 HTTPS/更强安全，另行立项。

### PM 验收结论（2026-08-21 ✅ 代码通过；⚠️ 部署缺口 1 项待运维配置后闭环）
- **核验方式**：不采信自述，独立 curl 实测运行中服务器 + TestClient 带 env 复现完整登录流程（未登录/错误密码/正确密码/登出/豁免清单）+ 亲自重跑冒烟+编码 + 读鉴权代码（_safe_next/hmac/session）+ ENGINE_VERSION 取值。
- **逐项结论（对照本卡验收标准）**：
  1. 未登录：`/` 200、`/login` 200、6 受保护页面全 302→`/login?next=`、受保护 API 全 401 ✅（curl 实测）
  2. 已登录：TestClient 带 `CS_MARKET_PASSWORD` 注入复现——POST /login 302 + **httponly cookie**、6 页面全 200、受保护 API 200 ✅
  3. 错误密码 401 且不写 session（后续仍 302）；登出后恢复 302 ✅
  4. 豁免清单：5 只读 API 未登录 200（market/signal、data/progress、health/status、portfolio/dashboard、paper/status）；写 API 401 ✅
  5. 冒烟 **131 passed / 0 failed / 0 skipped**（PM 重跑）；encoding PASS；`ENGINE_VERSION` 仍 `v2-T13`（config.py:445）✅
  6. 交付物：commit `5b621a4` + login.html + base.html 登录态 + requirements（itsdangerous==2.2.0）+ .env.example（不含真实密码）+ decision-log CY ✅；`_safe_next` 防 open redirect ✅；hmac.compare_digest ✅
- **⚠️ 部署缺口（唯一未闭环项）**：当前运行中服务器进程（PID 10580）env **未配置 `CS_MARKET_PASSWORD`** → `POST /login` 返回 500（设计内「未配置提示」行为，同 collector 缺配置语义；非代码 bug）。**待运维在 .env 配置 CS_MARKET_PASSWORD + CS_MARKET_SESSION_SECRET 后重启服务器**，登录即可用；配置后 PM 复测 POST /login 302 即闭环。
- **状态**：**代码验收通过；部署配置待运维（配置密码 + 重启）后闭环。**

---

## 六层架构 v1.0 执行待办（0–7 共 8 阶段，v82 起，PM 立卡批次）

> 来源：`references/cs-quant-architecture.md` §7.2 / §7.3；登记依据 decision-log **DC**（2026-08-27）。
> 流程纪律：每卡走「PM 立卡 → 研发/运维执行 → 冒烟 0 failed → ③审计 → 登记」。**研究类卡（R1–R5）须先由 ②算法研究窗口交付预注册判据/方案，PM 据以立卡**——卡已立但状态 = 待②预注册，研发不得先改。
> 依赖链（自上而下）：Wave1 数据地基 是 Wave2 研究入口 / Wave4 评估 的前置；Wave3 模拟盘 是 Wave6 交易级监控/kill switch 的数据基础；Wave5 中 X2 挂账等盘口数据（3-6 个月）。
> 原稿 §7.2 实际 25 项落地点（用户概称「24 项」）；本批次按 25 项立卡，告警路由保留为独立 O4。

### Wave 0 · 架构登记（decision-log DC，已完成）

- **ARCH-REG**：六层架构 v1.0 正式登记为设计唯一事实源；§7.2 待办按 8 阶段立卡启动。→ 见 decision-log DC，本段即立卡载体。**状态：已完成（登记）。**

### Wave 1 · 数据地基（owner：④运维 主 / 研发辅助；前置：无）

> **状态（2026-08-27 ③审计通过）**：③审计通过（四项登记：D1 口径/PM、D4 补跑、D6 Wave2 接线、D3 补用例）；D1–D7 全部通过/有条件通过，冒烟 140/0/0，不阻塞整体通过。
> **残余挂账（不阻塞整体通过，2026-08-27 ③复核确认）**：①DJ③ D4 rebuild_derived 补跑待②R1 稳定后④执行（目标回放库 = R1 在读库 `replay_cycle_win.db`）；②O4 ② 两项联动（cleaning_ledger 监控消费 + 备份新鲜度检查）代码层已实装（独立重跑冒烟 142/0/0 验证 PASS），③复核随 DJ③ 一并触发（D3/D4 收尾不与 O4 ② 混算）。

#### D1 · price_history 加 price_source 列
- **目标**：price_history 表新增 `price_source TEXT`，记录每条价格来源**平台**（锚定优先级 **yyyp>buff>c5>steam**，Steam 失真仅参考不落主价）；**csQAQ 为统一采集渠道（REST API），非锚定平台**；口径以 `config.PLATFORM_PRICE_SOURCE`（2=yyyp/1=buff/3=c5）为唯一权威，落地「单一事实源三铁律」之口径溯源。
- **预注册判据（PM 据 §1.2）**：①仅加列，不重建历史（历史行 price_source 回填为采集时实际源或 NULL 标记待补）；②写入点集中在 collector，锚定优先级逻辑从 config 读；③不破坏现有日采/回填脚本（CV 已定 1095 天保留期不变）。
- **验收标准**：①schema 迁移脚本可幂等重跑；②现有 131 冒烟 0 failed 不回退；③抽查 30 天 price_history，price_source 非空率 ≥ 采集覆盖；④数据不变量测试（见 D5）覆盖新列。
- **依赖**：无。**负责**：④运维。**状态**：✅ ③审计通过（2026-08-27；锚定口径 PM 拍板 DJ，架构/D1 卡已更正）。

#### D2 · bid_history 补卖侧列
- **目标**：bid_history 补 `lowest_sell / sell_count`（卖侧盘口），使买/卖双侧盘口齐备，支撑执行层模拟成交价校准与决策层流动性守卫。
- **预注册判据（§1.2③）**：①卖侧列来源 = csQAQ /info/good 已解析 OrderBook 的 sell 侧（collector 已解析未落库，见 §1.1 关键发现）；②日采累积（历史卖侧只能从现在积累，宜早）；③不新建独立表，沿用 bid_history。
- **验收标准**：①迁移可幂等；②冒烟 0 failed；③新采集行 lowest_sell/sell_count 非空率随积累提升（首周允许低，登记趋势）；④执行层 S2 可读取。
- **依赖**：无（与 D1 可并行）。**负责**：④运维。**状态**：✅ 研发落地（2026-08-27，待③审计）。

#### D3 · cleaning_ledger.jsonl + 规则配置化
- **目标**：清洗规则（闸门阈值/锚定优先级/污染清单/新鲜度缺失率）进 config（带参数/出处/生效日期），触警落 `data/cleaning_ledger.jsonl`，进每日健康检查统计。落地「规则配置化（已拍板）」。
- **预注册判据（§1.4）**：①config 新增 CLEANING_RULES 段（键=规则名/阈值/出处/生效日）；②触警时 append 一行 LEDGER（时间/规则/品/值/动作）；③健康检查统计读 LEDGER 计数；④不改动清洗函数逻辑本身，只把阈值外置。
- **验收标准**：①config 段可加载；②人为触发一条规则 → LEDGER 有记录 + 健康检查计数 +1；③冒烟 0 failed；④现有跨品一致性闸门（8/10 故障机制）不回退；⑤**O4 联动·cleaning_ledger 监控消费**：`route_alert` quality 档须读 `data/cleaning_ledger.jsonl` 计数触质量告警（非仅采集侧写入），随本卡一并实装。
- **依赖**：无。**负责**：④运维。**状态**：✅ ③审计通过（2026-08-27；**DJ 四项④ 已补：batch_guard→LEDGER 记录→count_since 计数+1→回滚 端到端冒烟用例 t_d3_batch_guard_e2e（冒烟 142/0/0），验收② 显式覆盖达成**）。

#### D4 · provenance.jsonl + 恢复演练脚本 + 每月演练
- **目标**：①派生级血缘 `data/provenance.jsonl`（脚本/输入源/参数/时间戳/版本）；②恢复演练脚本化（restore_from_backup.py + rebuild_derived.py 幂等）+ 台账 recovery_drill_log.jsonl + 每月一次全流程（PRAGMA integrity_check + 行数 + 抽样对比）。落 §1.5 治理。
- **预注册判据（§1.5，待③审计）**：①provenance 每次派生重建时 append；②restore/rebuild 脚本幂等可重跑；③每月演练落台账含 integrity_check 结果 + 行数对比；④台账格式固定可机器读。
- **验收标准**：①provenance.jsonl 在派生重建后自动更新；②rebuild_derived 幂等（跑两次结果一致）；③模拟一次恢复演练 → recovery_drill_log 有记录且通过；④冒烟 0 failed；⑤**O4 联动·备份新鲜度检查**：`route_alert` quality 档须读最新备份年龄超阈值（对齐 backup_db 保留 14 份口径）触质量告警，当前全库零命中，随本卡恢复演练一并实装。
- **依赖**：无（与 D1/D2/D3 并行）。**负责**：④运维。**状态**：✅ ③审计通过 + **DJ③ 已闭环（2026-08-27 02:05，decision-log DL）**：rebuild_derived 补跑两次幂等一致（405/259,222/1015）、provenance +2 留痕、恢复演练 PASS（台账 02:05:35）、冒烟 136/0/6、orphan_ph=0（item_id 口径统一）；验收①②③④ 全部达成，随③复核收口。

#### D5 · 数据不变量测试套件
- **目标**：独立测试套件覆盖 schema/范围/连续性/唯一性/日期不跳，每日采集后 + 每次回填/恢复后跑。落 §1.7②。
- **预注册判据（§1.7②）**：①新 pytest 模块 `tests/test_data_invariants.py`；②用例：price_history 日期连续不跳、主键唯一、值域范围（price>0、in_sale_count≥0）、schema 列存在；③接入每日任务与回填/恢复后钩子；④失败即阻断采集提交（或报警）。
- **验收标准**：①套件存在且可单独跑；②故意注入坏行 → 至少一条用例失败；③接入每日任务后无回归；④冒烟整体 0 failed（本套件计入）。
- **依赖**：D1/D2 schema 变更后补对应列用例。**负责**：④运维 + 研发。**状态**：✅ 研发落地（2026-08-27，待③审计）。

#### D6 · oos_zone 标记机制
- **目标**：验证段（≥2025-08-10）与 B 通道窗口（~2027-04-25）标记 oos_zone，研究准入前不得窥探/调参（反过拟合硬落地）。落 §1.7①。
- **预注册判据（§1.7①）**：①config 或元数据表定义 oos_zone 区间；②研究脚本入口强制检查当前窗口是否在 fit 段（违规则报错拦截）；③标记对评估层/研究层可见，对采集无影响；④不删除任何数据，仅加「禁区」元数据。
- **验收标准**：①oos_zone 定义可读；②研究回放脚本在 val 段触碰前若无预注册则报错；③B 通道窗口标记正确；④冒烟 0 failed。
- **依赖**：无（与研究层 R1 接入配合）。**负责**：④运维 + ②研究。**状态**：✅ ③审计通过（2026-08-27）+ **D6 oos_guard 接线已闭环（R1 评估脚本入口接 `require_fit`，DP；run_factor_eval.py / run_factor_eval_g9.py 入口强制 val 段拦截、val 未触碰；R5 沿用同款）；DJ 四项② 收口，③复核随 R1 一并达成**。

#### D7 · raw.db（高价值数据独立层）
- **目标**：高价值数据（订单簿/成交/存世量）独立 raw.db，append-only；价格历史不建 raw。落 §1.3 分层。
- **预注册判据（§1.3）**：①新建 raw.db（SQLite，独立文件，git 不跟踪）；②订单簿/成交/存世量写入 raw（加工层 market.db 仍权威）；③append-only（无 UPDATE/DELETE 路径）；④备份策略 = 双副本。
- **验收标准**：①raw.db 创建且写入路径存在；②确认无 UPDATE/DELETE 脚本触碰 raw；③加工层读取 raw 派生正常；④冒烟 0 failed。
- **依赖**：D2（卖侧盘口进 raw 候选）。**负责**：④运维。**状态**：✅ ③审计通过 + **供给策略已拍板并接入（2026-08-27 02:10，PM 裁定「接每日采集链」+ ④落地，decision-log DO）**：`run_daily_collect.py` 新增 `_run_data_reserve()`（浏览器任务后、健康监控前）每日调 p0 --apply（订单簿/成交全量→raw_order_book/raw_trade）+ p1 --apply --scope watchlist（存世量→raw_survive），raw 失败不阻断主采集；p0/p1 已小规模 dry-run 验证（2/2 OK）；**18:00 起每日采集后 raw.db 三表将累积行数**，验收①③ 随采集复查闭合。

### Wave 2 · 研究入口（owner：②算法研究窗口；前置：Wave1 D1/D5/D6）

> **研究类卡纪律**：R1–R5 卡已立，但**预注册判据须由 ②算法研究窗口先交付**（方案/脚本/判据草案），PM 据以冻结后研发/②方可执行。状态 = 待②预注册。禁止先改再定。

#### R1 · 因子评估脚本（10 组，截面 IC / 14-30 双前向 / 时期分段 IC）
- **目标**：按 §2.2 质量评估口径，对 10 组因子跑截面 IC + 14/30 双前向 + 时期分段 IC；覆盖率为辅；供给类看条件 IC；先不跑，全部确定后跑。
- **预注册判据（待②交付）**：②须交付——①评估脚本设计（IC 定义/前向窗口/时期分段口径/覆盖阈值）；②10 组因子清单与数据依赖（衔接 D6 oos_zone，仅 fit 段）；③增量 IC / 相关性去重（>0.8 冗余）方法；④组合用等权/IC 加权、禁优化器；⑤评估卡喂 factor_registry quality 字段。
- **验收标准（PM 据②判据冻结后定）**：①脚本可跑且输出 10 组 IC 表；②oos_zone 守住院（val 段未预注册不触碰）；③结果入 registry；④③审计复核口径；⑤冒烟 0 failed。
- **依赖**：D5/D6（不变量 + oos_zone）。**负责**：②研究。**状态**：✅ **完成（2026-08-27，21 因子评估卡 `data/_exp_factor_eval_2026-08-27.json`：cards=21、无新候选、供给条件IC 唯一正信号、oos_zone 守院 val 未触碰；decision-log DP/DL 上下文；待③审计口径复核 §7.1）**。

#### R2 · factor_registry.json 定稿
- **目标**：因子注册表 `data/factor_registry.json`（机器事实源）+ md 视图；13 字段（id/name/category/role/definition/data_dependency/version/source/quality/status/in_engine/cs_note/tested_at）；生命周期 = 入库即登记 → 评估 → 状态流转（候选/生产/证伪，证伪保留防重复挖）。落 §2.2。
- **预注册判据（待②交付）**：②须交付——①13 字段 schema 终稿（dtype/必填/枚举）；②生命周期状态机（候选→生产→证伪 流转规则）；③与 config（参数）/数据层（版本冻结）/③审计（核对清单）衔接接口；④md 视图生成脚本。
- **验收标准**：①registry 文件 schema 校验通过；②现有因子可入库登记；③状态流转脚本可用；④③审计复核（待③审计项）。
- **依赖**：R1（评估产出 quality）。**负责**：②研究。**状态**：✅ **判据已交付+冻结，registry 已落地（2026-08-27 02:15，decision-log DP）**——`data/factor_registry.json`（21 因子，schema 校验通过：候选 3/证伪 15/存档 3）+ `references/factor-registry.md` 视图 + 入库/视图脚本；待③审计复核 registry 口径（§7.1）。

#### R3 · 策略隔离评估预注册判据
- **目标**：为 §2.4 策略隔离评估（6 族：恐慌/深值/趋势买涨/供给/反转/基础）定稿预注册判据（每族四关通过线/相关性阈值/组合增益线）。落 §2.7。
- **预注册判据（待②交付）**：②须交付——①每族四关通过线（north_star 口径，含 val 段不显著即证伪硬判据，沿用 CQ-ADD-1 判据精神）；②信号重叠/收益相关/时期覆盖差异化三表定义；③组合测试 vs 单引擎增益线；④预注册/oos_zone/候选来源/正负登记规则。
- **验收标准**：①判据文档冻结；②可据以跑 6 族隔离评估；③③审计复核。
- **依赖**：D6（oos_zone）、R1（因子基础）。**负责**：②研究。**状态**：✅ **判据已冻结（2026-08-27 09:46，PM 裁定 DR，references/r3-family-isolation-prereg-2026-08-27.md）**：②据以开跑 6 族隔离评估（产物 `data/_exp_family_isolation_2026-08-27.json`，仅评估结论不改引擎）；红线：判据跑前定死/禁看结果调阈值/oos_zone 守院/不立落地卡。**✅ 执行完成（2026-08-27 17:58，decision-log DV）**：6 族独立族开回放 + 完整四关 + 差异化三表 + 组合测试全跑——**6 族四关全部证伪、多策略形态不成立（单引擎维持）**；三表显示族间低重叠+时期分化真实存在但独立子策略资格不成立，引擎价值在融合（基线 Calmar 48.97 vs 单族 4.7~19.8）；方法论观察（G1 对比基线口径对单族偏严等 4 项）已登记 DV；待③审计复核判据口径（§7.1）。

#### R4 · 挖掘流程启动清单落稿
- **目标**：§2.2 10 步挖掘流程 + §2.4 策略研究流程落为可执行启动清单（含候选来源声明/版本冻结声明/oos_zone 硬约束/落地挂监测四处补强）。落 §2.7。
- **预注册判据（待②交付）**：②须交付——①10 步清单每步交付物/准入 gate；②4 处补强（§2.4 补强4处）落到清单节点；③与生命周期台账/J-2 衔接。
- **验收标准**：①清单文档冻结且可执行；②与现有管线对齐无冲突；③③审计可读懂。
- **依赖**：R3。**负责**：②研究。**状态**：✅ **已交付即完成（2026-08-27，decision-log DP）**——10 步挖掘流程启动清单落稿（references/r4-mining-workflow-prereg-2026-08-27.md），后续挖掘照单执行。

#### R5 · 内生情绪 v0（价格/在售量可回测部分）
- **目标**：§2.5 内生情绪代理 v0 = 用价格/在售量可回测部分构建市场内生情绪（v0，非外部事件/社区，已取消）；作为加分/过滤因子。
- **预注册判据（待②交付）**：②须交付——①v0 情绪定义（价格动量/在售量变化/点差派生，纯回测可得）；②与现有因子正交性（增量 IC）；③仅作加分/过滤，不进决策主干；④oos_zone 守研究院。
- **验收标准**：①v0 脚本可算且入 registry；②增量 IC 报告；③不污染现有信号（仅加分）；④③审计。
- **依赖**：D2（点差派生）、R1。**负责**：②研究。**状态**：✅ **执行完成（2026-08-27 18:30，decision-log DY）**：v0 情绪评估（`data/_exp_emotion_v0_2026-08-27.json`）verdict=**无增量**——fit 增量 IC +0.0026 < 0.02 硬判据未过，val 复验 −0.0055 反向印证；组件 IC 与 R1 同量级（sentiment 0.158 / sc30 0.022 / chg7 −0.146）；oos_zone 守院（探索仅 fit，val 仅复验触碰）；仅筛查层不碰引擎不立落地卡。**移交③审计复核判据口径**；R5 完 → **R1–R5 全解冻，Wave4（E1–E4）可立卡**。

### Wave 3 · 模拟盘（owner：④运维 / 研发；前置：无，独立；S2 供 Wave6）

#### S1 · 悠悠有品采集可行性预研
- **目标**：§4.4 立「悠悠有品采集可行性预研」——内部 API 逆向 + Playwright 抓 DOM，确认在售列表/求购列表/成交记录可采（执行层补充数据，非主口径）。
- **预注册判据（§4.4/§4.7）**：①Playwright 浏览器层拦截内部接口（项目已有基建）；②输出可行性报告：可采字段/历史深度/反爬风险/频率；③不直接落库，仅预研结论。
- **验收标准**：①预研报告（可采/不可采/风险）；②若可行，给出后续 S2 采集方案草稿；③不动生产。
- **依赖**：无。**负责**：④运维（预研）。**状态**：✅ ③审计通过（DT，2026-08-27）；**悠悠登录账号用户 08-26 已登录（10天免登、~09-05 到期需续登；盘口采集已激活 raw_order_book/trade 今 18:08 起累积 503 行，非"默认不开"）**。

#### S2 · 模拟盘台账 + 交易域表
- **目标**：§4.5 补数据层「交易域」缺口——订单/成交/持仓/资金表；模拟账户（资金+库存）每次成交更新；成交记录（价/量/时/费率）落库。
- **预注册判据（§4.5）**：①新建交易域表（orders/fills/positions/cash）；②模拟成交规则（§4.3：买底价在售 0 费 / 卖必须有货 1% 费 / 多数量按底价）；③与真实库存可选同步；④不自动下单（Steam 风控红线）。
- **验收标准**：①表创建且写入路径；②模拟买入/卖出落 fills + 更新 positions/cash；③卖出无货拒单；④冒烟 0 failed；⑤费率 买0/卖1 与 E2 对齐。
- **依赖**：S1（悠悠数据可选增强，非硬前置）。**负责**：④运维 + 研发。**状态**：✅ ③审计通过（DT，2026-08-27：交易域 orders/fills + 费率买0/卖1 + 无货拒单 + 现金 bug 修复，144/0/0）。

#### S3 · 钉钉通知闭环
- **目标**：§4.2 决策层意向单 → 钉钉卡片通知 → 用户人工执行/回报 → 模拟账户更新 闭环。
- **预注册判据（§4.2）**：①意向单结构（品/方向/数量/参考价/理由/期望/风控标签）；②钉钉卡片推送（复用现有钉钉告警基建）；③回报入口（用户回填成交）→ 触发 S2 台账更新；④kill switch 可暂停出单/通知（衔接 O2）。
- **验收标准**：①意向单生成 → 钉钉收到卡片；②回报后台账更新且评估层可见；③未回报超时提示（衔接 O1）；④冒烟 0 failed。
- **依赖**：S2（台账）、O2（kill switch 暂停）。**负责**：④运维 + 研发。**状态**：✅ ③审计通过（DT，2026-08-27；**钉钉真实送达待生产 webhook 验证 / O1 回报超时两模式待运行确认，登记 DU**）。**关键词保证（2026-08-27 新增，研发落地，待③复核）**：代码侧已统一加「CS」前缀（`notify_alert.route_alert` 标题 `CS【{tag}】…` + `paper_trading.intention_card` 首行 `【CS 模拟盘意向单】`，O4 三档同根因）；**配置侧待群管理员**：钉钉机器人安全设置关键词须含「CS」（或「意向单」）——④实发验证仍 310000 关键词不匹配，代码侧已修、配置侧未就绪，到位后重发 `push_intention` 验证 errcode=0 闭环。

### Wave 4 · 评估（owner：②研究 / 研发；前置：Wave1 D6，Wave3 S2）

#### E1 · 回测质量门落地（5 项）
- **目标**：§5.1 回测质量门 5 项作为候选/策略准入前必过：①时序平稳性（ADF/KPSS）②特征无泄露 ③幸存者偏差核查 ④压力测试 ⑤成本真实化。
- **预注册判据（§5.1，待③审计口径）**：①5 项各自实现/脚本；②未过质量门不准入；③与现有四关管线衔接（不重复造轮）；④成本真实化用 E2 费率。
- **验收标准**：①质量门脚本可跑，输出 5 项状态；②现有候选回放先跑一遍质量门看通过率（登记基线）；③③审计复核口径（待③审计项）；④冒烟 0 failed。
- **依赖**：D6（oos_zone/幸存者偏差）、E2（费率）。**负责**：②研究 + 研发。**状态**：✅ **已执行（2026-08-27，研发落地，待③审计）**——`references/run_quality_gate.py`（纯标准库，ADF/KPSS 自实现）对 v2-T13 全池回放（376 信号）跑出 5 项质量门 **全部通过**：①平稳性 13/13 序列收益平稳（验证对象=价格/指数日收益比率形式，非信号日截面）②特征无泄露（源码扫描+特征定义）③幸存者偏差（回放池 vs 生产池比对）④压力测试（2024-02 崩盘/2025-10 回落/2026-02~04 流动性断档，窗口 avg14 全正）⑤成本真实化（FEE-CAL net=fwd−1.0% 与 config 一致）。产物 `data/_exp_quality_gate_2026-08-27.json`；待③审计复核口径（§7.1）。**③审计修复闭环（2026-08-27，audit-wave4-e1e4 + decision-log EC）**：幸存者门实现缺陷（items 表无 active/status 列 → prod_pool_size=0 假通过）已修（改 `is_discontinued=1` + 基准空抛错不静默 + 异常不吞），重跑 prod=405/eliminated=0 真通过；t_e1_quality_gate 补强 prod_pool_size>0 断言防回退。

#### E2 · 历史回测按 买0/卖1 重跑校准
- **目标**：§5.5 费率口径修正（买 0 / 卖 1 已拍板）——历史回测重跑校准，回测成本模型改不对称费率。
- **预注册判据（§4.3/§5.5）**：①回测引擎费率参数改为 买0/卖1（config 化）；②重跑现有基线/候选回放，输出新旧期望差异；③滑点模型随盘口数据（D2）积累后补（本卡仅费率）。
- **验收标准**：①费率参数生效且可复核；②重跑后期望统计同步 `config.ITEM_EXPECTANCY_STATS`（经 sync 脚本）；③冒烟 0 failed；④与 S2 模拟盘费率一致。
- **依赖**：无（独立）。**负责**：研发 + ②研究。**状态**：✅ **已执行（2026-08-27，研发落地，待③审计）**——①费率 config 化：`pipeline.config.BACKTEST_FEES={买0,卖1}` + `backtest_roundtrip_cost()`；回放脚本（run_item_backtest_full / fullpool_parallel）改从 config 读（**坑：config 返回百分比 1.0，backtest_item 的 cost 参数需小数 0.01**）；②校准：`references/run_fee_calibration.py` 对 v2-T13 全池产物（376 信号）按新费率重算 net（费率不影响信号判定，重算=重跑，小样本 5 品真重跑对照 **0 处不一致实证**）→ 差异表 `data/_exp_fee_calibration_2026-08-27.json`（avg14 全体 +1.00pp：ALL +19.26→+20.26，win14 74.5→77.1）+ 校准产物 `data/_exp_v2t13_fee_cal_2026-08-27.json`；③sync_expectancy_config 扩展第三基线 **FEE-CAL**（`ITEM_EXPECTANCY_STATS_FEE_CAL` + BASELINE_LEDGER 注册，不动冻结的 HIST-FULL/CLEAN-CUR）；滑点待 D2 盘口积累（判据③挂账）。

#### E3 · /evaluate 页（三层展示 + 质量标签）
- **目标**：§5.2 独立 /evaluate 页（研究视图下）：三层展示（信号级/策略族级/因子组合级）+ 质量标签纪律（未过质量门不展示）。
- **预注册判据（§5.2）**：①新路由 /evaluate + 模板；②三层数据来自评估层产物（E1 质量门状态、b1 组合模拟、因子 IC）；③质量标签绑定每条展示；④主界面保持决策视角（信号卡片），/evaluate 仅研究视图。
- **验收标准**：①页面可访问且三层数据正确；②未过质量门数据不展示（标签拦截）；③冒烟 0 failed；④不引入新引擎逻辑。
- **依赖**：E1（质量标签）、R1/R2（因子数据）、决策层现有。**负责**：研发（前端）+ ②研究。**状态**：✅ **已执行（2026-08-27，研发落地，待③审计）**——新路由 `GET /evaluate`（AUTH-1 登录保护）+ `GET /api/evaluate/data`；`webapp/evaluate_service.py` 聚合三层数据（信号级=族期望+最近信号 / 策略族级=组合+基准+月度+分布+净值曲线 / 因子级=R1 评估卡 21 因子+R2 registry）+ E1 质量门标签 + E2 差异表 + E4 风险归因；`webapp/templates/evaluate.html`（原生 JS/SVG 渲染，无新依赖）；base.html 导航加「评估中心」；零引擎改动（E3 验收④）。

#### E4 · 绩效仪表盘（OSkhQuant 形态参考）
- **目标**：§5.2/§5.3 绩效仪表盘——净值 vs 基准+回撤+胜率/期望/Calmar+月度热力图+收益分布+风险归因（按族/时期/品类）。仅借 OSkhQuant 形态，口径全用我们的。
- **预注册判据（§5.2/§5.3）**：①交互式资金曲线/回撤/买卖点/月度热力图（形态参考）；②风险归因（b1 组合模拟 closed 逐笔分组，无需新模型）；③集中度 top5>50% 警示；④质量标签纪律。
- **验收标准**：①仪表盘可渲染且数据准确；②归因分组正确；③③审计可读懂口径；④冒烟 0 failed。
- **依赖**：E1/E3、R3（隔离评估）。**负责**：研发 + ②研究。**状态**：✅ **已执行（2026-08-27，研发落地，随 E3 页内实现，待③审计）**——净值曲线（复用 b1v2.simulate cap0.8/hold21，64 点抽样 SVG 折线，绿=策略/灰=大盘同期归一化，末值 +266%）、月度热力图（逐月 avg14 条形）、收益分布（7 桶条形）、风险归因（按族=信号数×平均期望 / 按时期 _period / 按品类，B1 closed 逐笔汇总）、集中度 top5 占比 23.3%（<50% 正常，超阈警示）、胜率/期望/Calmar 卡片；口径注释均挂费率标签（组合级仍为 2% 双边，E2 校准后信号级 1%）。**③审计修复闭环（2026-08-27，audit-wave4-e1e4 + decision-log EC）**：两处归因缺陷已修——①按品类归因（原 372/376 落"其他"）改武器段英文映射表（步枪 197/手枪 52/冲锋枪 31/霰弹枪 4/手套 4/其他 88，items.weapon 列覆盖不足待采集补齐后切换）；②组合级 closed 逐笔（原 b1 产物无明细 n_trades=0）改从回放信号实时 b1v2.simulate（n=108/win 51.9%）。

### Wave 5 · 决策预留（owner：②研究 / 研发；前置：无硬前置）

#### X1 · 策略抽象层预留接口
- **目标**：§3.3② 触发/评分解耦 = 预留策略抽象层接口（暂不改生产）；隔离评估后数据说话再决定。
- **预注册判据（§3.3）**：①仅定义接口/抽象（不影响现有族制信号）；②不动生产引擎/决策逻辑；③预留点文档化；④后续多策略接入用。
- **验收标准**：①接口/抽象层代码存在且不改变现有行为；②冒烟 0 failed；③ENGINE_VERSION 不 bump（仅接口预留）。
- **依赖**：无。**负责**：研发。**状态**：待执行（预留，不急）。

#### X2 · 流动性守卫
- **目标**：§3.3④ 流动性守卫（深度不足不发/降权）等盘口数据积累（3-6 个月）后上。
- **预注册判据（§3.3④/§3.4）**：①依赖盘口深度（D2 sell 侧 + D7 raw 订单簿）；②守卫规则：深度不足禁买/降权；③接入决策层信号输出。
- **验收标准**：①盘口数据积累达标后交付方案；②不污染现有信号（仅守卫）；③③审计。
- **依赖**：D2/D7（盘口数据，3-6 个月积累）。**负责**：②研究 + 研发。**状态**：挂账等数据（3-6 个月）。

### Wave 6 · 运维（owner：④运维；前置：Wave3 S2/S3）

#### O1 · 交易级监控
- **目标**：§6.2① 模拟盘闭环状态监控——意向单已通知？回报超时（用户未回）？台账对账差异？
- **预注册判据（§6.2①）**：①监控项定义（通知成功/回报超时阈值/对账差异阈值）；②接入每日健康检查 + 钉钉告警；③读 S2/S3 台账。
- **验收标准**：①监控项可读且报警可达；②超时/差异触发告警；③冒烟 0 failed。
- **依赖**：S2/S3。**负责**：④运维。**状态**：**已执行（2026-08-27，冒烟 0 failed，③审计通过，decision-log DF/DG）**。实现：`pipeline/ops.py::run_ops_monitor`（对账差异 status.json vs 实库重算 / 自峰值回撤 / 连续拒单=当日 buy 信号−已建仓 / 数据源新鲜度 / 采集闸门=健康检查 FAIL 数；S3 回报超时阈值 24h 判据先行登记 WARN）；接入每日任务收尾（run_daily_collect）+ `/api/ops/monitor` + `ops_tool.py monitor`；FAIL 项经 O4 三档告警（trade/quality）。详见 decision-log DG（原 DD，编号撞车已修正）。**运行观察挂账（DU③，PM 2026-08-27）**：回报超时两模式（自动镜像=即时 filled 恒 PASS / 手动回报=ops.py⑥ 24h WARN）待模拟盘实际运行（出单→回报/超时）观察日志确认阈值无误报，观察期随每日运行自然闭环。

#### O2 · kill switch 运维端
- **目标**：§6.2② 全局/策略级一键停（出单/通知）运维入口——决策层风控链（§3.4）运维端。
- **预注册判据（§6.2②/§3.4）**：①运维端点（全局/策略级）；②独立于业务链（上层卡死也能触发）；③联动 S3 暂停出单/通知；④自动急停（连续拒单/回撤破阈/数据源异常/采集闸门触警）进健康检查。
- **验收标准**：①运维端可一键停；②自动急停条件可配；③冒烟 0 failed；④不引入业务风险。
- **依赖**：S3（出单/通知）、决策层风控。**负责**：④运维 + 研发。**状态**：**已执行（2026-08-27，冒烟 0 failed，③审计通过，decision-log DF/DG）**。实现：`pipeline/ops.py`（kill switch 状态文件 data/ops_kill_switch.json，全局/策略级(paper/notify) × 手动/自动双通道；自动急停=连续拒单/回撤破阈/数据源异常/采集闸门触警，只自动开闸不自动恢复）；独立于业务链（`ops_tool.py` CLI 直读写 + `/api/ops/kill-switch` 端点，webapp 卡死也能触发）；联动 paper_trading 建仓闸停 + monitor/notify 推送闸停；变更落 O3 审计台账（含 decision-log 引用）。③审计轻微建议（手动解除清 auto 记录）已实现。

#### O3 · 结构化日志 + 操作审计
- **目标**：§6.2③ 统一日志格式（级别/检索）+ 参数/配置变更审计（谁/何时/改了什么/依据哪个 decision-log 条目）——「参数调整走预注册」（§3.5）留痕。
- **预注册判据（§6.2③）**：①统一日志格式 + 检索；②配置变更审计落台账（含 decision-log 引用）；③与 D4 provenance 衔接（数据层血缘）。
- **验收标准**：①日志可检索；②一次配置变更 → 审计台账有记录且含 decision-log 引用；③冒烟 0 failed。
- **依赖**：D4（provenance）。**负责**：④运维。**状态**：**已执行（2026-08-27，冒烟 0 failed，③审计通过，decision-log DF/DG）**。实现：`pipeline/ops.py` 统一结构化日志 log_event（data/ops_log.jsonl，级别/来源/检索）+ 配置变更审计 config_audit（data/config_audit_log.jsonl，谁/何时/改了什么/decision-log 引用）；kill switch 变更自动落审计；/api/ops/audit + ops_tool.py audit 查询；与 D4 provenance/cleaning_ledger 同构（JSONL append-only）。

#### O4 · 告警分级路由
- **目标**：§6.2④ 告警三档路由——采集告警（现有）→ 质量告警（闸门触警/新鲜度/备份失败，D3/D4/D5）→ 交易告警（模拟盘/风控，O1/O2）到钉钉。
- **预注册判据（§6.2④）**：①三级告警定义 + 路由规则；②接入现有钉钉；③分级不漏报。
- **验收标准**：①三级告警可触发且路由正确；②与 D3/D4/D5/O1/O2 联动；③冒烟 0 failed。
- **依赖**：D3/D4/D5、O1/O2。**负责**：④运维。**状态**：**已执行（2026-08-27，冒烟 0 failed，③审计有条件通过，decision-log DF/DG）**。实现：`notify_alert.py::route_alert` 三档路由（collect 采集=现有 / quality 质量=闸门触警·新鲜度·备份 / trade 交易=O1/O2），标签前缀 + 每级独立 webhook env 覆盖（缺省走基础 webhook，分级不漏报）；推送动作写 ops_log 留痕；kill switch(notify) 拦截。**③审计：路由本体正确，D3 联动 ✅（health_fail→quality 告警+急停）**。
- **④显式待办（2026-08-27 ③审计要求，PM 排期并入 Wave1，随 Wave1 一并实装）**：①**D3 cleaning_ledger 监控消费**——随 D3 实装（health_monitor 当日计数，run_health_monitor.py:40）+ **④补 O4 侧消费**（run_ops_monitor「清洗台账消费」检查：当日触警→quality 轻提醒，ops.py ⑤a）；②**D4 备份新鲜度检查**——④补实装（run_ops_monitor「备份新鲜度」：最新备份年龄 ≥ backup_stale_days=2 → FAIL+quality 告警，非急停条件，ops.py ⑤b；阈值 config.OPS_RULES.backup_stale_days）。**两项已代码落地；O4 验收② 闭环 = DJ③（D4 rebuild 补跑，已完成）+ DJ④（D3 补用例 t_d3_batch_guard_e2e）→ ③复核通过（decision-log DN）→ O4 有条件通过转终态。**

### Wave 7 · 挂账等数据（§7.3 暂定/待数据项，不立执行卡，仅挂账）

> 以下为 §7.3 未决/暂定项，依赖新数据/样本外/B 通道，本批次**不立执行卡**，仅存档挂账；触发条件满足后由 ②研究交付预注册判据再立卡。

- **W7-1 内生情绪 v1**（bid/spread/turnover + steamdt 成交额，待采集可行性预研 + 积累 3-6 个月）—— 依赖 S1/D2。**v1a 执行完成（2026-08-27，decision-log FF）**：emo_v1a=clip(emo_v0+0.5·bid_norm+0.5·spread_norm,0,100)（w=0.5 固定禁优化，FC 冻结）；**verdict=无增量**——判据 A 增量 IC 0.0034（<0.02 且同号月 0.50<0.80）、判据 B 相对 v0 增量 IC 0.0107（<0.02）均未过，val 复验 A/B −0.0052/−0.0030 反向印证；组件 bid/spread 与 R1 组9 同量级（弱/无效）；oos_zone 守院、仅筛查层不碰引擎；**R5+v1a 合并口径：内生情绪合成方向整体无增量，登记防重复挖**；不触发四关；**③审计通过（decision-log GJ，2026-08-27）**。v1b(+turnover)/v1c(+steamdt) 数据到位后重新预注册；EF 预研（数据核验）与 EY（steamdt 预研）已在案。
- **W7-2 steamdt 成交额组件**（市场级活跃度，待 S1 可行性预研 + 历史深度）。**已立项蓄水池采集（2026-08-27，decision-log EY+EZ，PM 拍板）**：数据源=独立站 steamdt.com（非悠悠有品，youpin898.com/steamdt 404）；市场级 GET API 零鉴权可采（大盘指数/成交额/成交量/新增额/新增量/在线人数/三级板块指数，字段存证 `data/_exp_w7_2_steamdt_probe.json`）；单品级 10min 数据受 108 风控（二期 WS/页面自动化）；历史深度=当日小时级+页面 K 线，无批量全历史（回测弱、价值在积累，契合 3-6 月合规累积）；蓄水池方案=raw.db 两表（raw_steamdt_market/blocks）每日 1 次挂 18:00 链。**分工：落库代码归研发（✅ 已交付 collect_steamdt_reserve.py，FI）→ ④运维接入 18:00 链（✅ GI 首跑成功）→ ③审计复核（✅ HA 通过）→ 积累观察（3-6 月）**。
- **W7-3 多策略形态**（**R3 已裁决关闭：多策略形态不成立、单引擎维持为终态**，2026-08-27 DV；6 族独立子策略资格全不成立，引擎价值在融合，不另立多策略形态窗口）。
- **W7-4 B 通道样本外**（~2027-04-25，样本外验证窗口）。
- **W7-5 滑点模型**（待盘口数据 D2/D7）。
- **W7-6 信号强度→仓位**（position_limit 信号驱动，等 A2 期望成熟 + 预注册）。
- **W7-7 退出策略研究**（卖出侧固定规则，待执行层盘口数据）。
- **W7-8 特征三口径 v0 暂定**（截面 rank/价格带+品类中性化/前向填充+flag，用结果说话可调）—— 待 R1/R4 评估后定。
- **状态**：全部挂账待数据/触发；不并入活跃卡，复核时一并检查。
