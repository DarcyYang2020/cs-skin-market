# CS-Skin-Market 项目代码文件说明

> 最后更新: 2026-07-21

## 项目概述
CS饰品投资分析系统，提供大盘分析、单品分析、持仓管理三大功能模块。
基于 FastAPI + Playwright(csqaq/steamdt) + SQLite 技术栈，运行在 http://127.0.0.1:8000/。

---

## 核心管线 (pipeline/)

### db.py — 数据库管理
- SQLite 数据库初始化（items/snapshots/market_index/positions/backtest_results 等表）
- CRUD: 自选管理（watchlist_add/update/remove/list）
- 持仓管理（add_position/close_position/get_open_positions/get_position_pnl）
- 数据存储（save_price_history_batch/upsert_item）
- 设置键值存储（get_setting/set_setting）
- 快照查询（get_latest_snapshot_report/watchlist_list_with_snapshots）

### collector.py — 大盘指数采集
- 使用 requests（非 Playwright）从 csqaq 获取大盘指数数据
- fetch_market_index() -> MarketIndex(value, change_7d, mood)
- fetch_sector_flow() -> 板块资金流向数据
- fetch_index_kline() -> 大盘90日K线

### collector_csqaq.py — csqaq 数据采集（Playwright）
- 浏览器全局复用（_get_browser()） 5分钟回收
- search_good_id(query) -> 搜索饰品返回 good_id
- fetch_item_detail(good_id) -> 获取详情（价格、K线、在售量等）
- fetch_kline_90d(good_id) -> 单独获取 90日 K 线
- 数据源：悠悠有品（platform=2），自动过滤 StatTrak/纪念品

### collector_steamdt.py — steam.douyu 成交量采集（Playwright）
- fetch_steamdt_volume(steam_name) -> 获取当日推算成交量
- merge_daily_volume(daily_bars, steamdt_vol) -> 合并成交量到K线

### item_analysis.py — 单品分析引擎（主入口+各模块汇总）
- run_item_analysis() 完整分析管线（10大模块）
- 内置模块：估值定位、周期判定、流动性评分、涨跌概率预测、价值评分、庄盘检测、趋势健康度、融合决策、估值宫格、买卖区间
- 数据类: ItemAnalysisResult / ItemPositionIntel / CycleAnalysis / ValueScore / WhaleIntel / LiquidityScore / TrendHealth / PriceZones

### index_analysis.py — 大盘分析引擎
- analyze_index_full() 完整指数分析管线
- 模块：大盘百分位/Z-score、均线系统、成交量分析、市场情绪、综合指数、抄底就绪度、市场周期判定、融合决策、操作计划

### trend_health.py — 趋势健康度引擎（单品+大盘共用）
- compute_trend_health() -> 6维度趋势评分（持续性/均线结构/陡度/量价/关键位/异常）
- compute_fusion_decision() -> 融合趋势+周期+估值的最终决策
- 维度：方向动量、均线系统、量价关系、趋势一致性、波动率

### market_th.py — 大盘趋势健康度
- compute_market_trend_health() -> 大盘专属趋势评分
- compute_market_fusion_decision() -> 大盘融合决策

### market_macro.py — 宏观情绪与资金面
- 市场广度、贪婪指数、在线人数、充值卡溢价、抄底就绪度

### market_context.py — 市场背景分析
- 大盘联动性、相关性矩阵、Beta系数

### valuation.py — 估值系统
- compute_valuation_grid() -> 估值宫格（3x4矩阵），基于百分位x波动率的二维分类
- calc_percentile() / calc_zscore() / get_valuation_from_prices()

### supply.py — 供给分析
- analyze_supply() -> 在售量趋势、吸筹/派发检测

### trends.py — 多时间框架趋势分析
- analyze_trends() -> 7d/30d/90d 动量、MA交叉、波动率

### batch_scan.py — 批量扫描
- _portfolio_advice() -> 持仓个性化建议生成（根据成本/数量/现价）
- batch_scan_watchlist() -> 共享浏览器批量分析所有自选

### config.py — 配置与评分权重
- 代理设置、评分权重表、止盈止损参数、TH阈值常量

### scorer.py — 六维度评分模型（旧版，单品分析不再使用）
### regime.py — 市场状态识别（旧版）
### portfolio.py — 持仓管理（旧版）
### reporter.py — Markdown报告（旧版）
### backtest.py — 策略回测（旧版）
### watchlist.py — 自选管理（旧版）
### cli.py — 命令行入口（旧版）

---

## Web 应用 (webapp/)

### main.py — FastAPI 路由与业务逻辑
- 页面路由：/（大盘仪表盘）、/search（单品搜索分析）、/watchlist（持仓管理）
- 分析路由：/api/items/analyze（搜索栏分析）、/api/watchlist/{id}/analyze（自选分析）
- 批量扫描：POST /api/watchlist/batch-scan-selected（勾选物品批量分析）
- 报告查询：GET /api/watchlist/{id}/report（读取最新快照）
- 持仓管理 CRUD：添加/编辑/删除自选、设置总资产

### 模板 (templates/)
- base.html — 布局骨架+导航栏
- dashboard.html — 大盘仪表盘页面
- search.html — 单品搜索分析页面
- watchlist.html — 持仓管理页面
- partials/analysis.html — 单品分析结果面板（含分析时间戳）
- partials/analysis_results.html — 分析结果列表组件
- partials/dashboard_refresh.html — 大盘刷新局部更新
- partials/index_analysis.html — 大盘分析面板
- partials/index_card.html — 大盘指数卡片
- partials/sectors_card.html — 板块资金流卡片

### 静态资源
- static/css/style.css — 全局样式（浅色主题+深色侧栏+响应式）
- static/js/app.js — 前端交互（HTMX 扩展、Loading状态、模态框、表单处理）

---

## 服务器与入口

### run_server.py — 服务器启动脚本
- 使用 Windows 默认 ProactorEventLoop（不再设置 SelectorEventLoopPolicy）
- 启动 uvicorn 服务，绑定 127.0.0.1:8000
- 自动检测 Python 路径和项目目录

### start.bat — Windows 一键启动脚本

---

## 数据流总览

`
用户操作 → webapp/main.py (FastAPI端点)
  → collector_csqaq.py (csqaq搜索+K线+详情)
    collector_steamdt.py (成交量补充)
    collector.py (大盘指数)
  → item_analysis.py / index_analysis.py (分析编排)
    ├─ scorer.py (评分)
    ├─ valuation.py (估值)
    ├─ trends.py (趋势)
    ├─ supply.py (供给)
    ├─ trend_health.py (趋势健康度)
    └─ market_context.py / market_macro.py (大盘)
  → db.py (存储快照+价格)
    reporter.py / partials/*.html (报告渲染)
  → 用户查看分析报告
`

## 数据库表结构
| 表 | 用途 |
|---|---|
| items | 物品基本信息、自选标记、持仓数据 |
| snapshots | 分析快照（含完整报告HTML），按item_id+date查询最新 |
| analysis_results | 搜索页分析结果持久化 |
| price_history | 90日K线价格数据 |
| market_index | 大盘指数历史数据 |
| positions | 持仓记录 |
| settings | 键值对设置（总资产、缓存等） |
| backtest_results | 回测结果 |
