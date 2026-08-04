# CS-Model 项目文件功能说明

## 目录结构

```
cs-skin-market/
├── run_server.py              # Web 服务入口
├── run_backtest.py             # 大盘回测脚本（低层引擎逐日回放）
├── start_webapp.bat            # Windows 一键启动脚本
├── AGENTS.md                   # Agent 指令（SKILL 配套）
├── SKILL.md                    # Codex Skill 定义
├── agents/                     # Agent 配置
│   └── openai.yaml             # OpenAI 模型配置
├── pipeline/                   # 核心分析引擎
│   ├── config.py               # 全局配置（权重/代理/评分表/路径）
│   ├── collector.py            # 大盘/板块数据采集（Playwright）
│   ├── collector_csqaq.py      # csqaq.com 单品数据采集（搜索+K线+详情）
│   ├── collector_youpin.py     # 悠悠有品成交量采集
│   ├── collector_snapshot.py # 全市场快照（get_page_list 翻页，存 market_snapshot）
│   ├── db.py                   # SQLite 数据库（表结构+CRUD）
│   ├── item_analysis.py        # 单品分析引擎（主入口+各模块汇总）
│   ├── index_analysis.py       # 大盘分析引擎（融合决策+多维评分）
│   ├── trend_health.py         # 趋势健康度评分（单品+大盘共用）
│   ├── market_context.py       # 市场背景分析（大盘联动+相关性）
│   ├── market_macro.py         # 宏观情绪/资金面分析
│   ├── market_th.py            # 大盘趋势健康度
│   ├── valuation.py            # 历史估值分位（百分位+Z-score）
│   ├── supply.py               # 供给端追踪（吸筹/派发检测）
│   ├── batch_scan.py         # 自选批量扫描（信号提取/按建议执行）
│   ├── dashboards.py         # 仪表盘数据（数据积累进度/组合仓位）
│   └── factor_monitor.py     # 因子衰减监控
├── webapp/                     # Web 前端
│   ├── main.py                 # FastAPI 路由（全端点+HTML渲染）
│   ├── static/
│   │   ├── css/style.css       # 全局样式（浅色主题+响应式）
│   │   └── js/app.js           # 前端交互逻辑
│   └── templates/
│       ├── base.html           # 基础布局模板（左侧导航+右侧内容）
│       ├── dashboard.html      # 首页仪表盘
│       ├── search.html         # 单品搜索/分析页
│       ├── watchlist.html      # 自选+持仓管理页
│       ├── discover.html       # 发现高分品页（全武器扫描 TOP10）
│       └── partials/           # HTMX 局部刷新组件
│           ├── analysis.html        # 单品分析报告片段
│           ├── index_analysis.html  # 大盘分析报告片段
│           ├── index_card.html      # 大盘指数卡片
│           ├── sectors_card.html    # 板块资金流向卡片
│           └── dashboard_refresh.html # 仪表盘刷新片段
├── tests/                      # 测试
│   └── test_smoke.py           # 冒烟测试
├── references/                 # 参考文档
│   ├── analysis-engine.md      # 单品分析引擎设计文档
│   ├── market-engine.md        # 大盘分析引擎设计文档
│   ├── cs-knowledge.md         # CS 饰品市场领域知识
│   └── trading-strategies.md   # 交易策略手册
└── data/                       # 运行时数据（自动生成）
    └── market.db               # SQLite 数据库
```

---

## pipeline/ 核心引擎文件

### 入口与配置

| 文件 | 功能 |
|---|---|
| `config.py` | 全局配置中心：代理设置、评分权重表、磨损/稀有度/来源映射、止盈止损阈值、数据路径 |

### 数据采集层

| 文件 | 功能 |
|---|---|
| `collector.py` | 大盘指数采集、板块资金流向、市场状态数据，基于 Playwright |
| `collector_csqaq.py` | **核心采集**：csqaq.com 搜索→详情→K 线全链路。含 StatTrak/纪念品 过滤、90 日 K 线 API 拦截、Nuxt 3 数据解析 |
| `collector_youpin.py` | 悠悠有品成交量采集（HTTP，登录态 headers，10天有效） |

### 数据存储层

| 文件 | 功能 |
|---|---|
| `db.py` | SQLite 数据库：7 张表（items/price_history/market_index/snapshots/positions/settings/backtest_results），含自选 CRUD、90 天自动清理、VACUUM |

### 单品分析引擎

| 文件 | 功能 |
|---|---|
| `item_analysis.py` | **单品分析主入口**：编排全流程，汇总所有模块结果，输出统一的 `ItemAnalysisResult`。含：四因子评分、趋势健康度、估值分位、周期判定、涨跌概率、庄盘识别、融合决策 |
| `valuation.py` | 估值分位：30d/90d 百分位排名、Z-score、估值标签（低估/合理/高估/泡沫） |
| `supply.py` | 供给分析：在售数量变化率、供给趋势、吸筹/派发检测 |
| `trend_health.py` | 趋势健康度综合评分：持续性+均线结构+陡度+量价+关键位+异常检测，输出 0-100 分 |

### 大盘分析引擎

| 文件 | 功能 |
|---|---|
| `index_analysis.py` | **大盘分析主入口**：综合估值+情绪+资金+趋势+周期，输出融合决策 |
| `market_th.py` | 大盘趋势健康度：类似单品 TH 但参数适配大盘特性 |
| `market_context.py` | 市场背景：大盘联动性、相关性矩阵、Beta 系数 |
| `market_macro.py` | 宏观面：市场情绪指标、资金流入流出、恐慌/贪婪指数 |

### 交易与组合

| 文件 | 功能 |
|---|---|
| `dashboards.py` | 仪表盘数据（纯展示层）：`data_progress` 数据积累进度（大盘/K线/真实成交量覆盖）、`portfolio_dashboard` 组合仓位（持仓分布 + 并发建议仓位占用 vs 0.8 上限） |

### 工具

| 文件 | 功能 |
|---|---|

---

## webapp/ Web 层

| 文件 | 功能 |
|---|---|
| `main.py` | FastAPI 应用：全部 REST API 端点 + Jinja2 模板渲染 + 报告 HTML 存储 |
| `static/css/style.css` | 全局样式：浅色主题、左侧导航栏（深色）+ 右侧内容区（浅色）、卡片/徽章/表格/响应式 |
| `static/js/app.js` | 前端交互：HTMX 扩展、Loading 状态、模态框、表单处理 |

### 模板（templates/）

| 文件 | 功能 |
|---|---|
| `base.html` | 布局骨架：左侧 220px 导航栏（大盘/搜索/自选/持仓），右侧内容区 `#main-content` |
| `dashboard.html` | 首页：大盘指数卡片 + 板块资金流向 + 大盘分析面板 |
| `search.html` | 单品搜索页：搜索框→即时分析→左侧结果列表+右侧分析详情 |
| `watchlist.html` | 自选管理页：自选表格 + 持仓管理 + 批量扫描 + 信号中心 + 执行记录与复盘 + 组合仓位仪表 |

### 局部模板（templates/partials/）

| 文件 | 功能 |
|---|---|
| `analysis.html` | 单品分析报告：估值定位+四因子+趋势健康度+周期判定+涨跌概率+庄盘识别+融合决策 |
| `index_analysis.html` | 大盘分析报告：估值仪表+情绪+资金+趋势+周期+融合决策 |
| `index_card.html` | 大盘指数卡片（首页） |
| `sectors_card.html` | 板块资金流向卡片（首页） |
| `dashboard_refresh.html` | 首页刷新片段 |

---

## 发现高分品模块 (/discover)

- 收敛范围：AK-47 / AWP / 沙漠之鹰 / M4A4 / USP / MP7 / SSG 08 / 法玛斯（仅崭新出厂）
- 预评分过滤：pct_quick > 75 直接跳过；大盘 TH<55 且 score<6 且 composite<5 过滤
- 综合排序：composite = score × (1 - pct/200) 估值折扣
- 缓存：data/discover_latest.json，可反复查看上次结果
- 异步：搜索+分析后台执行，前端轮询进度

## 批量扫描 + 信号中心 + 执行记录 (/watchlist)

- 选中自选物品 → POST /api/watchlist/batch-scan-selected 异步扫描，进度轮询
- 结果归档 data/scan_history/scan_*.json（保留 30 份）；信号中心提取可分批补仓/建议止损/已到买点，批量扫描按钮显示信号角标
- 执行记录：按建议执行或手动录入（executions 表），14/30 天到期自动按收盘价结算复盘
- 组合仓位仪表：持仓分布 + 并发建议仓位占用预警
- 持仓个性化建议：_portfolio_advice() 基于成本/数量/现价生成

## 回测工具 (run_backtest.py)

- 用法：`python run_backtest.py [--start 2025-11-02] [--end YYYY-MM-DD]`
- 逐日回放低层引擎函数，输出 buy 信号 + 14d/30d 前瞻收益 + 胜率
- 与真实引擎对齐：is_bear 直接计算（熊市持久性）、rally_decay/cap_triggered/selling_pressure 同逻辑
- 最新结果：14 信号 / 14d 胜率 86% / 均收益 +15.0%

## 数据流总览

```
用户操作 → webapp/main.py (FastAPI端点)
    ↓
collector_csqaq.py (csqaq搜索+K线+详情)
collector_youpin.py (悠悠有品成交量采集)
collector.py (大盘指数)
    ↓
item_analysis.py / index_analysis.py (分析编排)
    ├── valuation.py (估值)
    ├── supply.py (供给)
    ├── trend_health.py (趋势健康度)
    └── market_context.py / market_macro.py (大盘)
    ↓
db.py (存储快照+价格)
    ↓
用户查看分析报告
```
