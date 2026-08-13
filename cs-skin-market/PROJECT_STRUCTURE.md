# CS-Model 项目文件功能说明

> 本文档为项目文件结构唯一事实源（AGENTS.md/SKILL.md 不再维护重复文件树）。

> 最后更新: 2026-08-13（文档事实同步 + 数据卫生说明）

## 目录结构

```
cs-skin-market/
├── run_server.py              # Web 服务入口（uvicorn，唯一启动方式）
├── run_daily_collect.py       # 每日自动采集总调度（大盘/宏观/K线全量每日 + 全市场快照/大户集中度/B-5 求购观察每周一 + 数据健康 + J-2 刷新 + 信号回填 + 监控事件 + DB 备份）
├── run_data_health.py         # 数据源健康检查（全量可采集品动态基线，写 health_checks）
├── run_health_monitor.py      # 健康监控独立入口（run_monitor，退出码 0/2 供告警）
├── references/scripts-archive/ # 历史回测/回填脚本归档（run_backtest/run_item_backtest/run_item_exit/run_item_9grid/run_portfolio/run_backfill_history，2026-08-08；当前回测统一走 refit_pipeline.py）
├── backup_db.py               # SQLite online backup（每日，保留 14 份）
├── collect_data_reserve_p0.py # P0 数据储备采集（活跃池基本面+求购日聚合，研究层，默认 dry-run）
├── collect_data_reserve_p1.py # P1 数据储备采集（存世量+系列面板+大户Top20，研究层，默认 dry-run）
├── notify_alert.py            # 告警/监控推送（钉钉 webhook，.env NOTIFY_WEBHOOK_URL 配置）
├── install_tasks.ps1          # Windows 计划任务安装（每日采集/备份/告警）
├── install_hooks.ps1          # pre-commit hook 安装（提交前自动跑冒烟测试）
├── start_webapp.bat           # Windows 一键启动
├── AGENTS.md / SKILL.md       # Agent 指令 / Skill 定义
├── agents/openai.yaml         # Agent 展示配置
├── pipeline/                  # 核心分析引擎（见下）
├── webapp/                    # Web 层（见下）
├── tests/                     # 冒烟测试 + 编码健康 + 回放快照
├── references/                # 策略文档 + 研究脚本（见下）
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
| `collector_csqaq.py` | csQAQ Playwright：单品搜索/详情/90日K线/深历史（响应拦截 `chart/`info API，StatTrak/纪念品过滤） |
| `collector_snapshot.py` | 全市场快照：get_page_list 翻页拉全市场价格+在售数，存 market_snapshot（每周一） |
| `collector_monitor.py` | 大户集中度快照：`monitor/`rank 每周 Top50，存 monitor_rank_snapshot |

### 分析引擎

| 文件 | 功能 |
|---|---|
| `item_analysis.py` | 单品分析主入口：信号族注册制 + 六态状态桶 + 12 闸门融合决策 |
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
| `render_html.py` | HTML 渲染纯函数（报告/发现榜/闪光图） |
| `static/css/style.`css | 全局样式 |
| `static/js/app.`js | 前端交互（HTMX/模态/表单） |
| `templates/` | `base/dashboard/search/watchlist/discover/`replay + `partials/*` |

## `tests/` 测试

| 文件 | 功能 |
|---|---|
| `test_smoke.py` | 冒烟测试（104 用例（离线基线 98 passed / 6 skipped），支持 CS_MODEL_SKIP_NET 离线跳过网络用例） |
| `check_encoding.py` | 仓库文本编码健康检查（UTF-8 无 BOM / 无乱码） |
| `snapshots/replay_v2.`json | 回放口径快照（aggregate+月度，防无意漂移） |

## `references/` 策略文档与研究脚本

### 文档

- `decision-log.md` — 关键决策历史（去量/扩池/补仓止损等全部决策）；`iteration-roadmap.md` — 迭代方案（版本历史 + 状态追踪）
- `project-principles.md` — 项目三原则 + 数据先行/风控上线标准/J-2 复验条款
- `engine-unified.md` — 统一大脑架构（信号族注册制 + 期望条件表 + 参数治理）
- `data-layer.md` — **数据层手册**（数据源/采集链路/每日任务/表结构/维护/故障 SOP，唯一权威）
- `pool-maintenance.md` — 260 品池专项维护（淘汰/台账/增量评估决策点）
- `stop-loss-strategy.md` — 补仓/止损矩阵（F-3.7，第一性原理 + 回测 + 维护条款）
- `trading-strategies.md` — 交易策略手册；`th_calibration.md` — TH 三区校准研究
- `backtest-methodology.md` — 回测方法学（A2 工作流）
- `data-source-health.md` — 数据源健康检查口径；`cs-knowledge.md` — csQAQ 接口/CS 市场知识
- `trend_leg_research.md` / `first-principles-gap.md` / `bid-data-accumulation.md` — 专项研究（趋势腿 / 第一性差距 / 求购单数据积累）

### 研究脚本（产出 `data/*.`json）

- `j2_channel_monitor.py` — J-2 三通道监测（A 恐慌事件/B 新数据天数/C 胜率）→ `j2_channel_status.json`
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
- `run_item_backtest_full.py` — 全窗口单品回放（标准基准 `item_backtest_full_2025.json`）
- `t`rend_leg_*.`py` / `t`h_*_study.`py` / `topup_replay.py` / `t`ranche_fit*.`py` / `c1_p10_replay.py` / `advice_layer_fit.py` / `portfolio_cap_fit.py` — 历史研究脚本
- `scripts-archive/` — 已下线脚本归档（成交量时代等，仅存证）

## 数据文件（data/）

| 文件 | 说明 |
|---|---|
| `market.db` | SQLite 主库（gitignore） |
| `item_backtest_full_2025.json` | **标准回放基准**（去量 v2，365d 窗口 317 信号） |
| `item_backtest_full_2025.baseline450.`json / `.devol_v1.`json | 去量演进对比存档（旧引擎产物，仅存证） |
| `j2_channel_status.json` / `refit_pipeline_report.json` / `portfolio_backtest.json` 等 | 研究产物 |
| `backup/` | 每日 DB 备份（保留 14 份，gitignore） |
| `pool_maintenance_log.jsonl` | 池维护台账（daily/prune/discover 三类，F-3.2） |
| `scan_history/` / `scan_progress_*.`json / `batch_scan_latest.json` | 批量扫描归档/进度/缓存（gitignore） |

## 数据库表（schema_version = 1）

items / price_history / market_index / macro_history / snapshots / positions / settings /
executions（执行记录+复盘）/ market_snapshot（全市场快照）/ monitor_rank_snapshot（大户集中度）/
health_checks（数据健康）/ signal_tracking（生产信号跟踪）/ `backtest_results` / schema_version

## 运维

- 每日 18:00 定时采集：python `run_daily_collect.py`（Windows 计划任务 CS_Skin_DailyCollect；12:00 午间/21:30 晚间推送、22:00 健康告警、23:30 备份）
- 每日 23:30 DB 备份：python `backup_db.py`（保留 14 份）
- 健康告警：python `notify_alert.py` --monitor（钉钉 webhook）
- pre-commit：`install_hooks.ps1` → git commit 自动跑 test_smoke
- 本地/CI 冒烟：python `tests/test_smoke.`py（CI 设 CS_MODEL_SKIP_NET=1 跳网络用例）
- 完整调度与维护口径见 `references/data-layer.md`
