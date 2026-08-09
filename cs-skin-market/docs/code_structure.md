# CS-Skin-Market 项目代码文件说明

> 最后更新: 2026-08-04

## 项目概述
CS饰品投资分析系统，提供大盘分析、单品分析、持仓管理三大功能模块。
基于 FastAPI + Playwright(csqaq) + SQLite 技术栈，运行在 http://127.0.0.1:8000/。定价锚：csQAQ DOM 悠悠有品价；量源 = csQAQ chart 在售量（2026-08-07 去量，悠悠成交量采集器与 uu_headers 已删除）。

---

## 核心管线 (pipeline/)

### db.py — 数据库管理
- SQLite 数据库初始化（items/snapshots/market_index/positions/backtest_results 等表）
- CRUD: 自选管理（watchlist_add/update/remove/list）
- 持仓管理（add_position/close_position/get_open_positions/get_position_pnl）
- 数据存储（save_price_history_batch/upsert_item）
- 设置键值存储（get_setting/set_setting）
- 快照查询（get_latest_snapshot_report/watchlist_list_with_snapshots）
- 执行记录（P0-2）：add_execution/list_executions/delete_execution/settle_execution/closing_price_on

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

### collector_youpin.py — 悠悠有品成交量采集【2026-08-07 已删除】
- 引擎去量（v2）后，采集器与 data/uu_headers.json 登录凭据一并删除；历史 volume_day 数据保留归档。

### item_analysis.py — 单品分析引擎（主入口+各模块汇总）
- run_item_analysis() 完整分析管线（10大模块）
- 内置模块：估值定位、周期判定、流动性评分、涨跌概率预测、价值评分、庄盘检测、趋势健康度、融合决策、估值宫格、买卖区间
- 数据类: ItemAnalysisResult / ItemPositionIntel / CycleAnalysis / ValueScore / WhaleIntel / LiquidityScore / TrendHealth / PriceZones

### index_analysis.py — 大盘分析引擎
- analyze_index_full() 完整指数分析管线
- 模块：大盘百分位/Z-score、均线系统、市场情绪、综合指数、抄底就绪度、市场周期判定、融合决策、操作计划

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
- extract_signals() -> 信号提取（可分批补仓/建议止损/已到买点）
- _exec_btn() -> 按建议执行按钮（建仓/补仓/减仓/止损）


### collector_snapshot.py — 全市场快照采集（2026-08-04）
- fetch_market_snapshot(max_pages, page_size) -> 路由改写 get_page_list 翻页拉全市场价格/在售数（悠悠锚价）
- 存 market_snapshot 表，挂 run_daily_collect.py 每日任务；为全市场选品/估值分布积累面板

### run_backfill_history.py — 单品历史深度回填（2026-08-04）
- fetch_history_deep(good_id, min_date="2025-01-01")：simple/chartAll(plat=2) 多窗口向前翻页补 2025-01-01 起缺失价格
- db.backfill_price_missing 仅补缺失日期，不覆盖已有 volume_day/in_sale_count
### dashboards.py — 仪表盘数据（P0-3/P0-4）
- data_progress() -> 数据积累进度：大盘指数/K线覆盖度/在售量覆盖（含 90 天目标剩余自然日）
- portfolio_dashboard() -> 组合仓位：持仓分布/仓位比例/集中度 + 最近扫描时间（读 batch_scan_latest.json 的 time；并发建议仓位占用 2026-08-09 移除）
- 纯展示层，不触碰信号引擎

### config.py — 配置与评分权重
- 代理设置、评分权重表、止盈止损参数、TH阈值常量

### buy_distance.py — 距买点 v3（2026-08-07）
- 下跌寻底企稳闸门（3日转涨+未创新低）/ 供给吸筹场景 / 大盘 TH 三区化
- 输出 stabilizing / th_zone / supply_signal，前端徽章展示（纯展示层，不动信号引擎）
### signal_tracking.py — 生产实盘信号跟踪（J-2 C 通道，2026-08-07）
- record_buy_signal 去重记录 / backfill 按信号日后第 14/30 交易日回填真实价格（net 扣 2% 双边成本）
### portfolio_risk.py — B1 风险预算层（2026-08-05）
- 组合回撤熔断（10%，破位转质量监测器）+ 单票敞口提示（30%，只提示不拒绝）
### backtest_common.py / backtest_methodology.py — 回测公共 + A2 三件套
- build_market_context / patch_sentiment / approx_sentiment；walk_forward_split / signal_cluster_report / permutation_baseline
### factor_monitor.py — 因子衰减监控

---

## Web 应用 (webapp/)

### main.py — FastAPI 路由与业务逻辑
- 页面路由：/（大盘仪表盘）、/search（单品搜索分析）、/watchlist（持仓管理）
- 分析路由：/api/items/analyze（搜索栏分析）、/api/watchlist/{id}/analyze（自选分析）
- 批量扫描：POST /api/watchlist/batch-scan-selected（勾选物品批量分析）
- 报告查询：GET /api/watchlist/{id}/report（读取最新快照）
- 持仓管理 CRUD：添加/编辑/删除自选、设置总资产
- 批量扫描历史：GET /api/watchlist/scan-history[٭{scan_id}]（归档列表与详情）
- 执行记录：GET/POST /api/watchlist/executions、DELETE /api/watchlist/executions/{eid}（GET 时自动结算到期记录）
- 仪表盘：GET /api/data/progress、GET /api/portfolio/dashboard

### analysis_service.py — 公共分析服务层（2026-08-07）
- analyze_fresh 统一分析核心（单品/搜索/自选三路径复用）+ build_analysis_ctx
- 助手：anchor_override / kline_db_fallback / kline_price_sane / market_snapshot / save_analysis_result

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

### 静态资源
- static/css/style.css — 全局样式（浅色主题+深色侧栏+响应式）
- static/js/app.js — 前端交互（HTMX 扩展、Loading状态、模态框、表单处理）

---

## 服务器与入口

### run_server.py — 服务器启动脚本
- 使用 Windows 默认 ProactorEventLoop（不再设置 SelectorEventLoopPolicy）
- 启动 uvicorn 服务，绑定 127.0.0.1:8000
- 自动检测 Python 路径和项目目录

### run_daily_collect.py — 每日自动采集总调度
- 大盘/宏观/全市场快照/大户集中度/K线全量刷新（每日无条件）+ 数据健康检查 + J-2 三通道刷新 + 信号跟踪回填 + DB 每日备份
- 计划任务 CS_Daily_Collect 每日 21:30

### run_data_health.py / run_health_monitor.py — 数据源健康检查
- run_data_health.py：全量可采集品动态基线 + 85% 阈值，写 health_checks 表
- run_health_monitor.py：run_monitor() 独立入口，退出码 0/2 供告警调度

### backup_db.py — 每日 SQLite 在线备份
- sqlite3 backup API → data/backup/market_YYYYMMDD_HHMMSS.db，保留 14 份

### notify_alert.py — 健康告警推送
- 健康检查 FAIL 时推钉钉（.env 配 NOTIFY_WEBHOOK_URL，未配置静默）

### start_webapp.bat — Windows 一键启动脚本
- 原 start.bat 冗余已删除（2026-08-07 清理），仅保留带标题横幅的 start_webapp.bat（同样调用 run_server.py）

---

## 回测工具（根目录脚本）

### run_backtest.py — 大盘信号回测
- 逐日重放大盘融合引擎，输出 buy/oversold_buy 信号 + fwd14/fwd30/max_dd
- 每个信号携带 position_limit（全局仓位上限）与市场 regime
- 用法：`python run_backtest.py [--start 2025-11-02] [--cluster 3]`

### run_portfolio_backtest.py — 组合级执行回测（P0-1/P0-2）
- 信号 → 引擎仓位 → 止盈/止损/最长持仓/下一信号退出 → 复利资金曲线
- 输出年化 / 最大回撤 / 夏普 / 盈亏比 / 胜率 / 期望值 / 最长连亏 + 牛熊切片
- `--scan` 跑退出规则网格（止损 -15~-30 × 止盈 15~30 × 持仓 14/30/60 天）
- 结果持久化：data/portfolio_backtest_latest.json + backtest_results 表

### run_item_backtest.py — 单品信号回测
- 逐品重放单品引擎，输出信号 fwd14/fwd30，支持 --all / 指定物品 / 分层统计

## 数据流总览

```
用户操作 → webapp/main.py (FastAPI端点)
  → collector_csqaq.py (csqaq搜索+K线+详情)
    collector.py (大盘指数)
  → item_analysis.py / index_analysis.py (分析编排)
    ├─ valuation.py (估值) / supply.py (供给·在售量)
    ├─ trend_health.py (趋势健康度) / buy_distance.py (距买点)
    └─ market_context.py / market_macro.py / market_th.py (大盘)
  → db.py (存储快照+价格)
    webapp/templates/partials/*.html (报告渲染)
  → 用户查看分析报告
```

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
| executions | 执行记录+复盘（P0-2） |
| macro_history | 每日宏观快照（贪婪指数/点卡价） |
| market_snapshot | 全市场每日快照（价格+在售数） |
| monitor_rank_snapshot | 大户集中度每日 Top50 |
| health_checks | 数据源健康检查结果 |
| signal_tracking | 生产 buy 信号跟踪（J-2 C 通道） |
| schema_version | schema 版本记录（Phase 4） |
