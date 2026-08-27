# CS-Model 项目文件功能说明

> 本文档为项目文件结构唯一事实源（AGENTS.md/SKILL.md 不再维护重复文件树）。

> 最后更新: 2026-08-27（Wave6 运维层落地：ops.py / ops_tool.py / OPS_RULES；W7-2 steamdt 蓄水池采集脚本；EXEC-2 自动盯盘链）

## 目录结构

```
cs-skin-market/
├── run_server.py              # Web 服务入口（uvicorn，唯一启动方式）
├── run_daily_collect.py       # 每日自动采集总调度
├── run_daily_monitor.py       # 每日健康监控入口
├── run_data_health.py         # 数据源健康检查（全量可采集品动态基线，写 health_checks）
├── run_health_monitor.py      # 健康监控独立入口（run_monitor，退出码 0/2 供告警）
├── run_night_push.py          # 夜间推送调度
├── backup_db.py               # SQLite online backup（每日，保留 14 份）
├── collect_data_reserve_p0.py # P0 数据储备采集（活跃池基本面+求购日聚合，研究层，默认 dry-run）
├── collect_data_reserve_p1.py # P1 数据储备采集（存世量+系列面板+大户Top20，研究层，默认 dry-run）
├── collect_steamdt_reserve.py # W7-2 steamdt 蓄水池采集（市场级指数/成交/在线/板块 → raw.db，默认 APPLY，决策 EY+EZ）
├── exec2_auto_watch.py        # EXEC-2 自动盯盘链（活跃池/自选+持仓融合决策重算 + 新 buy S3 推送，幂等；决策 HC；HG 增量：G1 csQAQ 风控护栏 + G2 进度 source=auto）
├── notify_alert.py            # 告警/监控推送（钉钉 webhook，.env NOTIFY_WEBHOOK_URL 配置；O4 三档路由 --level）
├── ops_tool.py                # 运维 CLI（Wave6 O1-O4：kill switch / 审计 / 告警 / 交易监控，独立于 webapp）
├── install_tasks.ps1          # Windows 计划任务安装（每日采集/备份/告警）
├── install_hooks.ps1          # pre-commit hook 安装
├── deploy_server.ps1          # 服务部署脚本
├── start_webapp.bat           # Windows 一键启动
├── requirements.txt           # Python 依赖
├── AGENTS.md / SKILL.md       # Agent 指令 / Skill 定义
├── agents/openai.yaml         # Agent 展示配置
├── design-system/             # UI/UX 设计系统文档
├── pipeline/                  # 核心分析引擎（见下）
├── webapp/                    # Web 层（见下）
├── tests/                     # 冒烟测试 + 编码健康 + 回放快照
├── references/                # 策略文档 + 研究脚本（见下）
├── docs/archive/              # 已归档文档（code_structure 等）
└── data/                      # 运行时数据（market.db + 回放/研究产物 JSON）
```

## `pipeline/` 核心引擎

### 入口与配置

| 文件 | 功能 |
|---|---|
| `config.py` | 全局配置中心：评分权重、阈值（含 PARAM_REGIME 参数台账 / J2_THRESHOLDS / ENGINE_VERSION 引擎版本号）、路径 |
| `db.py` | SQLite 存储：全表 CRUD + schema 版本化（schema_version 表 + SCHEMA_VERSION） |

### 数据采集层

| 文件 | 功能 |
|---|---|
| `collector.py` | csQAQ HTTP：大盘指数/品类排名/搜索/hash→good_id（requests） |
| `collector_csqaq.py` | csQAQ Playwright：单品搜索/详情/90日K线/深历史（响应拦截 `chart/info` API，StatTrak/纪念品过滤） |
| `collector_snapshot.py` | 全市场快照：get_page_list 翻页拉全市场价格+在售数，存 market_snapshot（每周一） |
| `collector_monitor.py` | 大户集中度快照：`monitor/rank` 每周 Top50，存 monitor_rank_snapshot |

### 分析引擎

| 文件 | 功能 |
|---|---|
| `item_analysis.py` | 单品分析主入口：信号族注册制 + 大盘五时期状态桶（2026-08-16）+ 12 闸门融合决策 |
| `index_analysis.py` | 大盘分析引擎：估值+情绪+资金+趋势+周期+融合决策 |
| `trend_health.py` | 趋势健康度（单品+大盘共用）+ 融合决策 |
| `market_th.py` | 大盘趋势健康度 |
| `market_macro.py` | 宏观情绪/资金面（贪婪指数/在线人数/点卡溢价等） |
| `market_context.py` | 大盘上下文构建（供单品分析参考，state_bucket 状态桶） |
| `valuation.py` | 估值分位（百分位 + Z-score + 估值标签） |
| `supply.py` | 供给分析（在售量变化率 + 吸筹/派发检测，唯一量源） |
| `buy_distance.py` | 买点参考位量化（批量扫描排序/信号提取用；展示卡片 F-3.8 移除） |
| `portfolio_risk.py` | B1 风险预算层（组合回撤熔断 + 单票敞口提示） |
| `signal_tracking.py` | 生产实盘信号跟踪（J-2 C 通道：记录 buy 信号 → 14/30 交易日回填） |
| `monitor.py` | M1/M2 监控模式（每日自选品异动事件生成 + 日报 + 钉钉推送，纯提醒层，只读引擎输出） |
| `item_categories.py` | 品类识别（M-6，discover 无磨损品类进发现榜） |
| `market_period.py` | 大盘五时期生产持久化（market_state_daily.json，纯计算/持久化） |
| `market_signal.py` | 大盘自身信号 + 风险仪表（A/D 模块，引擎无关） |
| `paper_trading.py` | 模拟盘 v2（生产镜像，buy 自动建仓/到期/止盈止损/供给扩张全止损；建仓受 O2 kill switch 闸控） |
| `ops.py` | 运维层核心（Wave6 O1-O4：kill switch 双通道 / 操作审计 config_audit / 结构化日志 log_event / 交易级监控 run_ops_monitor；阈值在 config.OPS_RULES） |
| `pool_log.py` | 池维护台账（F-3.2，追加写 pool_maintenance_log.jsonl） |

### 回测/研究公共

| 文件 | 功能 |
|---|---|
| `backtest_common.py` | 回测公共：build_market_context / patch_sentiment / approx_sentiment |
| `backtest_methodology.py` | A2 三件套：walk_forward_split / signal_cluster_report / permutation_baseline |

### 批量扫描与仪表盘

| 文件 | 功能 |
|---|---|
| `batch_scan.py` | 自选批量扫描（信号提取/按建议执行/组合建议/距买点列） |
| `scan_tasks.py` | 批量扫描异步任务（进度落盘/逐品分析/缓存归档） |
| `discover_tasks.py` | 发现高分品异步任务（池内扫描/搜索扩池/贴纸榜） |
| `dashboards.py` | 仪表盘数据（数据积累进度/J-2 三通道/组合仓位，纯展示层） |
| `factor_monitor.py` | 因子衰减监控 |

## `webapp/` Web 层

| 文件 | 功能 |
|---|---|
| `main.py` | FastAPI 应用：全部 REST API + Jinja2 渲染 + 批量扫描进度落盘持久化 |
| `analysis_service.py` | 公共分析服务层：analyze_fresh 统一核心 + 锚价校验/DB K线兜底/market_snapshot 等助手 |
| `evaluate_service.py` | **Wave4 E3/E4 评估层数据服务**：聚合 E1 质量门/E2 费率校准/R1 因子/R2 registry/R3 隔离/b1 组合 → /api/evaluate/data（三层展示 + 质量标签 + 风险归因） |
| `render_html.py` | HTML 渲染纯函数（报告/发现榜/闪光图） |
| `static/css/style.css` | 全局样式 |
| `static/js/app.js` | 前端交互（HTMX/模态/表单） |
| `templates/` | `base/dashboard/search/watchlist/discover/replay/checkup/ops/evaluate + partials/analysis,analysis_results,dashboard_refresh,discover_html,engine_telemetry,exec_modal,index_analysis,index_card,scan_html` |

## `tests/` 测试

| 文件 | 功能 |
|---|---|
| `test_smoke.py` | 冒烟测试（2026-08-17 记录 129 用例；0 failed 为硬指标，CS_MODEL_SKIP_NET=1 时离线跳过网络用例，skip 数随环境浮动） |
| `check_encoding.py` | 仓库文本编码健康检查（UTF-8 无 BOM / 无乱码） |
| `snapshots/replay_v2.json` | 回放口径快照（aggregate+月度，防无意漂移） |

## `references/` 策略文档与研究脚本

### 文档

- `decision-log.md` — 关键决策历史（去量/扩池/补仓止损等全部决策）；`iteration-roadmap.md` — 迭代方案（版本历史 + 状态追踪）
- `terminology.md` — 口径词表（HIST-FULL=317 / CLEAN-CUR=230 / SIGNAL_FAMILY_TAXONOMY / BASELINE_LEDGER / calmar_standard 唯一标尺）
- `project-principles.md` — 项目三原则 + 数据先行/风控上线标准/J-2 复验条款
- `engine-unified.md` — 统一大脑架构（信号族注册制 + 期望条件表 + 参数治理）
- `data-layer.md` — **数据层手册**（数据源/采集链路/每日任务/表结构/维护/故障 SOP，唯一权威）
- `pool-maintenance.md` — 260 品池专项维护（淘汰/台账/增量评估决策点）
- `stop-loss-strategy.md` — 补仓/止损矩阵（F-3.7，第一性原理 + 回测 + 维护条款）
- `trading-strategies.md` — 交易策略手册；`th_calibration.md` — TH 三区校准研究
- `backtest-methodology.md` — 回测方法学（A2 工作流）
- `data-source-health.md` — 数据源健康检查口径；`cs-knowledge.md` — csQAQ 接口/CS 市场知识
- `trend_leg_research.md` / `first-principles-gap.md` / `bid-data-accumulation.md` — 专项研究（趋势腿 / 第一性差距 / 求购单数据积累）

### 研究脚本（产出 `data/*.json`）

- `j2_channel_monitor.py` — J-2 三通道监测（A 恐慌事件/B 新数据天数/C 胜率+期望）→ `j2_channel_status.json`
- `refit_pipeline.py` — Phase 3 重拟合流水线（A2 三件套 + 达标判定）→ `refit_pipeline_report.json`
- `portfolio_backtest.py` — Phase 2 组合层回测（cap 变体）→ `portfolio_backtest.json`
- `b1_risk_backtest_v2.py` — B1 风险预算 v2 复验 → `b1_risk_validation_v2.json`
- `cost_sensitivity.py` — 成本敏感性 → `cost_sensitivity.json`
- `supply_quality.py` — 在售量质量诊断 → `supply_quality.json`
- `benchmark_compare.py` — 策略 vs 池/指数基准 → `benchmark_compare.json`
- `collect_bid_observations.py` — B-5 求购观察累积（supply_contract/优先两模式，写 `bid_observations`）
- `cap_family_backtest.py` / `s3_bucket_replay.py` — cap 族级/分桶复验
- `sync_expectancy_config.py` / `sync_replay_snapshot.py` — 期望统计/回放口径同步
- `j1_event_counts.py` — 各族独立事件数 → `signal_event_counts.json`
- `run_item_backtest_full.py` — 全窗口单品回放（产出 HIST-FULL 冻结归档 `item_backtest_full_2025.json`；E2 起费率读 `config.BACKTEST_FEES` 买0/卖1）
- `run_item_backtest_fullpool_parallel.py` — 全池并行回放（3 年窗口；E2 起费率 config 化）
- `run_fee_calibration.py` — **Wave4 E2 费率校准**（买0/卖1 vs 旧 2%：重算 net + 小样本真重跑对照）→ `_exp_v2t13_fee_cal_2026-08-27.json` / `_exp_fee_calibration_2026-08-27.json`
- `run_quality_gate.py` — **Wave4 E1 回测质量门 5 项**（纯标准库 ADF/KPSS 自实现）→ `_exp_quality_gate_2026-08-27.json`
- `backfill_cycle_window.py` — 回放池 A 96 品 3 年历史回填（v69，写死 96 品，仅存证）
- `backfill_full_pool.py` — DATA-1 全池 3 年历史回填（非印花非角色 240 品，good_id 对齐，去重不覆盖）→ `_exp_data1_plan.json` / `_exp_data1_audit.json`
- `trend_leg_*.py / th_*_study.py / topup_replay.py / tranche_fit*.py / c1_p10_replay.py / advice_layer_fit.py / portfolio_cap_fit.py` — 历史研究脚本
- `scripts-archive/` — 已下线脚本归档（成交量时代等，仅存证）
- `archive/` — 已完成专项文档存证（2026-08-18 CLEANUP-1 归档 17 篇：optimization-* 2026-08-14 两份 + 外审立项基线/一次性审计/过时交接等，清单见 `cleanup-plan-2026-08-18.md`）
- `archive/doc-compact-2026-08-18/` — 长文档归档压缩卷（2026-08-18 DOC-COMPACT-1）：`decision-log-archive-2026-08-18.md`（历史决策 2026-08-03~08-18 全文）+ `iteration-roadmap-archive-2026-08-18.md`（版本历史 v1~v70 + 各技术方案）；清单见 `doc-compact-plan-2026-08-18.md`

## 数据文件（data/）

| 文件 | 说明 |
|---|---|
| `market.db` | SQLite 主库（gitignore） |
| `item_backtest_full_2025.json` | **HIST-FULL 冻结归档**（去量 v2-T4/T5，365d 窗口 317 信号，不可复现） |
| `_exp_v2t7_win_replay_deprecated_20260814.json` | 已废中间产物（v2-T7 泄漏基线，仅存证） |
| `item_backtest_full_2025.baseline450.json / .devol_v1.json` | 去量演进对比存档（旧引擎产物，仅存证） |
| `j2_channel_status.json` / `refit_pipeline_report.json` / `portfolio_backtest.json` 等 | 研究产物 |
| `backup/` | 每日 DB 备份（保留 14 份，gitignore） |
| `pool_maintenance_log.jsonl` | 池维护台账（daily/prune/discover 三类，F-3.2） |
| `ops_kill_switch.json` / `config_audit_log.jsonl` / `ops_log.jsonl` / `ops_paper_peak.json` / `ops_monitor_latest.json` | Wave6 运维层运行时状态/审计/结构化日志/峰值台账（append-only，gitignore 级运行时产物） |
| `_exp_v2t13_fee_cal_2026-08-27.json` | **FEE-CAL 费率校准基线**（Wave4 E2：v2-T13 全池 + 买0/卖1，net=fwd−1.0%；BASELINE_LEDGER 注册） |
| `_exp_fee_calibration_2026-08-27.json` | Wave4 E2 新旧期望差异表（2% 双边 vs 买0/卖1） |
| `_exp_quality_gate_2026-08-27.json` | Wave4 E1 回测质量门 5 项状态（v2-T13 全池基线，2026-08-27 全通过） |
| `scan_history/` / `scan_progress_*.json` / `batch_scan_latest.json` | 批量扫描归档/进度/缓存（gitignore） |
| `_exp_w7_2_steamdt_probe.json` | W7-2 steamdt.com 市场级数据探针存证（决策 EY，字段对照解析用） |


## 文件/产物归口规则

- `references/` 根目录放活跳研究脚本与文档；已下线脚本归 `references/scripts-archive/`，已完成专项文档归 `references/archive/`。
- 研究产物命名约定：`references/probe_*.py` → `data/_exp*.json`；已废产物统一 `_deprecated_YYYYMMDD` 后缀并在本文数据文件表登记，禁止裸留。
- `data/market.db` 为二进制（不提交）；`data/*.json` 为研究产物（提交）；`discover_latest.json` / `batch_scan_latest.json` / `scan_history/` / `backups/` 为运行时缓存/归档（不提交）；`pool_maintenance_log.jsonl` 为台账（提交）。
- 口径词表：`references/terminology.md`（HIST-FULL=317 / CLEAN-CUR=230 / SIGNAL_FAMILY_TAXONOMY / BASELINE_LEDGER / calmar_standard 唯一标尺）。

- `references/` 分层规则：根目录放活跃策略文档/研究脚本；`scripts-archive/` 只放已下线脚本；`archive/` 只放已完成专项底稿。本轮不物理迁移；未来触发条件为根目录 .py/.md 增长到难以维护或出现导入环及维护问题，且必须单独一轮做 import graph + 108 断言映射验证。
- `tests/test_smoke.py` 本轮不拆分；后续拆分必须保持 108 用例一一对应、断言不丢，且与功能改动分开验证。
## 数据库表（schema_version = 4）

items / price_history / market_index / macro_history / snapshots / positions / settings /
executions（执行记录+复盘）/ market_snapshot（全市场快照）/ monitor_rank_snapshot（大户集中度）/
health_checks（数据健康）/ signal_tracking（生产信号跟踪）/ `backtest_results` / schema_version

## 运维

- 每日 18:00 定时采集：python `run_daily_collect.py`（Windows 计划任务 CS_Skin_DailyCollect；12:00 午间/21:30 晚间推送、22:00 健康告警、23:30 备份）
- 每日 23:30 DB 备份：python `backup_db.py`（保留 14 份）
- 健康告警：python `notify_alert.py` --monitor（钉钉 webhook；O4 三档路由 --level collect/quality/trade）
- 运维操作：python `ops_tool.py`（kill-switch on/off/status、audit、monitor、alert；webapp 端点 /api/ops/* 等价，登录保护）
- pre-commit：`install_hooks.ps1` → git commit 自动跑 test_smoke
- 本地/CI 冒烟：python `tests/test_smoke.py`（CI 设 CS_MODEL_SKIP_NET=1 跳网络用例）
- 完整调度与维护口径见 `references/data-layer.md`
