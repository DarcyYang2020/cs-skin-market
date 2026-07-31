# CS-Skin-Market — 项目说明

## 数据来源与采集

| 数据 | 来源 | 方式 | 说明 |
|---|---|---|---|
| 大盘指数 + 品类排名 | csQAQ API | HTTP GET（同步） | /api/v1/current_data?type=init + ?type=kline |
| 单品搜索 + 详情 + K线 | csQAQ Playwright | 浏览器自动化（异步） | 导航 goods/{id}，拦截 info/chart API |

**定价锚**: 悠悠有品 (platform=2) > Buff > C5GAME，Steam 价格不采用。

**K线数据**: csQAQ chart API 提供 90日日线 OHLCV（price + in_sale_count），成交量由 steamdt 单独采集后通过 merge_daily_volume() 合并。

**浏览器复用**: _get_browser() 全局单例，5 分钟超时重建。

**StatTrak 过滤**: 自动排除 StatTrak™ 和纪念品版本，仅分析普通版。名称匹配时优先 market_hash_name，失败则通过搜索栏降级查询。

## 单品分析引擎 (item_analysis.py)

run_item_analysis(name, prices, volumes, supply_hist, order_book, index_change_7d, market_history, market_pct_90d, market_zscore) 协调以下模块：

| 模块 | 函数 | 功能 |
|---|---|---|
| 估值定位 | _analyze_position | 90日百分位 + Z-score + 标签（低估/合理/高估/泡沫） |
| 周期判定 | _analyze_cycle | 四阶段：吸筹/拉升/出货/洗盘，含持仓时间计数 |
| 流动性评估 | score_liquidity | 三维 0-100：成交量(40%) + 价差(30%) + 在售深度(30%) |
| 涨跌概率 | analyze_probability | 均值回归 + 波动率分类 + 3/7/14日预测 |
| 投资价值 | compute_value_score | 1-10 分 + S/A/B/C 评级 |
| 庄盘识别 | analyze_whale | 四因子：价格异常 + 供给控盘 + 量价关系 + 波动率 |
| 趋势健康度 | compute_trend_health (trend_health.py) | 五维 0-100：持续性/陡度/均线结构/量价配合/异常缺口 |
| 融合决策 | compute_fusion_decision (trend_health.py) | 百分位 + TH + 周期 → 操作指令 |
| 估值宫格 | compute_valuation_grid (valuation.py) | 3×4 宫格（价格分位 × 趋势方向）+ 仓位建议 |
| 信号冲突 | detect_signal_conflicts | 跨模块矛盾检测（周期 vs 融合、估值 vs 趋势等） |

### 大盘分析引擎 (index_analysis.py)  v4.7
熊市持久性判定：is_bear = MA30 < MA90 且现价 < MA90（V型反弹后 MA30 必须完全站上 MA90 才出熊），
修复 6 月反弹末端假信号（回测 37→14 信号，14d 胜率 76%→86%）。

analyze_index_full(value, change_7d, mood, kline_data) 协调：

| 模块 | 功能 |
|---|---|
| 位置分析 | K线百分位 + Z-score（低估/合理/高估） |
| 周期判定 | 四阶段（吸筹/拉升/出货/洗盘） |
| 概率预测 | 大盘独立概率模型 |
| 价值评分 | 0-100 大盘估值分 |
| 融合决策 | 百分位 + TH + 周期 → 操作指令 |

**市地宏观 (market_macro.py)**: 涨跌比 + 贪婪指数 + 在线人数 + 活跃卡数 + 抄底信号

## Web 应用 (FastAPI + Jinja2 + htmx)

`ash
cd cs-skin-market && python run_server.py
# 或 python -m uvicorn webapp.main:app --host 127.0.0.1 --port 8000
`

| 页面 | 路由 | 说明 |
|---|---|---|
| 大盘仪表盘 | / | 大盘指数 + 市场宏观 + 融合决策 |
| 单品分析 | /search | 搜索 + 分析，结果持久化 |
| 持仓管理 | /watchlist | 自选列表 + 持仓管理 + 批量扫描 |
| 发现高分品 | /discover | 扫描全武器类型崭新出厂品，筛选 Top 10 |
| 自选管理 | /watchlist | 自选列表 + 持仓管理 |

**API 路由**:
| 方法 | 路径 | 功能 |
|---|---|---|
| POST | /api/market/refresh | 刷新大盘数据 |
| POST | /api/items/search | 搜索并分析单品 |
| GET  | /api/items/analyze | 单品分析（指定参数） |
| POST | /api/watchlist/add | 添加自选 |
| GET  | /api/watchlist/{id}/analyze | 自选单品分析 |
| GET  | /api/watchlist/{id}/report | 查看历史报告 |
| POST | /api/watchlist/assets | 设置资产规模 |
| POST | /api/watchlist/batch-scan-selected | 批量扫描自选 |
| GET  | /api/watchlist/batch-scan-progress/{scan_id} | 批量扫描进度轮询 |
| POST | /api/discover/scan-all | 扫描全武器类型，异步分析 |
| GET  | /api/items/discover-progress/{task_id} | 发现高分品进度轮询 |
| GET  | /api/discover/latest | 获取上次扫描缓存结果 |

**模板结构**:
`
webapp/templates/
  base.html              -- 公共布局（左侧栏 + Modal）
  dashboard.html         -- 大盘仪表盘页
  search.html            -- 单品分析页
  watchlist.html         -- 持仓管理页（自选+批量扫描）
  discover.html          -- 发现高分品页（全武器扫描 Top 10）
  partials/
    analysis.html        -- 单品分析结果部分
    index_analysis.html  -- 大盘分析结果部分
    index_card.html      -- 大盘指数卡片
    sectors_card.html    -- 品类排名卡片
    dashboard_refresh.html -- 仪表盘刷新区域
`

### 融合决策核心参数
- TH_STRONG = 55 (TH>=55 为强趋势)
- TH_NEUTRAL = 35 (TH>=35 为中性偏强)
- 百分位分档: <=30% 低估 / 30-70% 中性 / >70% 高估

### 发现高分品 (2026-07-28)
新页面 /discover，自动扫描 8 个热门武器类型的崭新出厂品：
- **扫描武器**：AK-47 / AWP / 沙漠之鹰 / M4A4 / USP / MP7 / SSG 08 / 法玛斯
- **过滤**：仅崭新出厂，排除 StatTrak/纪念品/匕首
- **去重**：每个武器类型最多 3 个 → 总计 ~20-24 个品
- **排序**：按评分降序取 Top 10
- **缓存**：结果存 data/discover_latest.json，24h 内可反复查看
- **异步**：搜索和分析都在后台执行，点击立即返回进度条

### 超跌买入例外 (P0, 2026-07-21)
当标准融合决策无法触发 buy 时，额外检查:
- 条件: pct<=15% + Z<=-2.0
- 跌速衰减: 最后2日不创新低 + 3日正收益
- 命中信号: 超跌反弹·分批建仓
- 回测: 2025-11~2026-07, buy信号16次, 14d胜率88%, 均收益+9.65%

### 抛压衰竭信号 (v4.6, 2026-07-31)

`compute_selling_pressure_exhaustion(prices)` (index_analysis.py)，熊市 V 型底部先行信号：
- 三维打分：3日跌速衰减（0-40）+ 3日无新低（0-30）+ 止跌企稳（0-30）
- **硬性门控**：20日跌幅 < -7% 才可触发 ≥70 观察级，< -12% 深度恐慌不限分
- 回测（2025-11-02 起）：8 触发/4 波段，30d 胜率 100%，均收益 +6.14%
- 融合决策：sp≥70 + 百分位≤20 → 🟡 抛压衰竭·底部观察；sp≥85 + 百分位≤15 + microTH≥55 → 🟢 分批建仓
- 大盘仪表盘 📉 抛压衰竭卡片

### 求购承接信号 (v4.6, 2026-07-31)

`compute_bid_support(order_book)` (item_analysis.py)，单品真实买盘意愿快照：
- 从页面原生「求购价」图表抓取 buy_price 序列（修复原直连 401 导致 order_book 恒为空的问题）
- order_book 扩展：spread_pct / highest_buy / bid_7d_chg / bid_30d_chg / spread_avg
- 三维评分（0-100）：断层宽度 + 断层收窄/扩张 vs 均值 + 求购价趋势
- 融合修正：≤25 且 buy → 🟡 求购承接弱·观望；≥75 + watch 低估 → 🟡 底部观察·承接增强
- 单品报告 🛒 求购承接卡片

### 单品回测工具 (run_item_backtest.py, 2026-07-31)

离线回放单品引擎（不采集、不联网），验证买入信号历史胜率：

```
python run_item_backtest.py --all --warmup 30 --stratify
python run_item_backtest.py --items "AWP | 冥界之河 (崭新出厂);AK-47 | 抽象派 1337 (崭新出厂)" --warmup 60
```

- 数据源: `price_history`（2026-04-21 起，按日期取最新采集去重）+ `market_index`（2025-11-02 起）
- 情绪: 离线回测用大盘价格近似（与 run_backtest.py 同一 approx_sentiment），实时引擎仍用贪婪指数
- 缺失成交量/在售/盘口历史 → 回测用中性默认值，信号带 data_quality 标注
- warmup=30 结果（2026-05-21~07-31, 67信号）: 14d胜率60.9%/均+15.7%, 30d胜率77%/均+29.3%
- 分层结论（支撑补仓阈值）: pct≤25&th≥40 → 14d胜率75%; pct 25~40(半山腰) → 14d胜率28%; 市场贪婪(sent≤30) → 30d胜率0%
- 输出: 控制台明细 + data/item_backtest_latest.json

### 持仓补仓建议 (batch_scan._portfolio_advice, 2026-07-31)

浮亏持仓按数据验证阈值分层（sentiment_score 由大盘贪婪指数计算，批量扫描时传入）：

- 市场贪婪 sent≤30 → 禁止补仓（30d 期望为负）
- pct 25~40 半山腰 → 暂缓补仓，等 pct≤25
- pct≤25 + 单品TH≥40 + z≤-0.5 + 大盘TH≥45 → 可分批补仓（14d 胜率 75%）
- pct≤25 但大盘TH<45 → 暂缓，等大盘共振
- 单品TH<30 → 止损优先（风险预算原则）

## 文件结构

`
cs-skin-market/
  AGENTS.md              -- 本文件
  SKILL.md               -- Codex Skill 元数据
  run_server.py          -- Web 服务启动脚本
  run_backtest.py        -- 大盘回测脚本（python run_backtest.py [--start 2025-11-02]）
  data/market.db         -- SQLite 数据库
  data/discover_latest.json -- 发现高分品缓存
  pipeline/
    config.py            -- 配置（TOKEN/BASE_URL/权重/参数）
    collector.py         -- csQAQ HTTP 采集（大盘指数/品类/搜索）
    collector_csqaq.py   -- csQAQ Playwright 采集（单品搜索/详情/90日K线）
    collector_steamdt.py -- steamdt Playwright 采集（成交量合并）
    db.py                -- SQLite 存储（items/price_history/snapshots/positions/settings）
    item_analysis.py     -- 单品分析主流程（协调10大模块）
    trend_health.py      -- 趋势健康度 + 融合决策
    valuation.py         -- 估值宫格（百分位 + Z-score + 3×4宫格）
    index_analysis.py    -- 大盘指数分析引擎
    market_macro.py      -- 市场宏观（涨跌比/贪婪/在线/活跃卡/抄底信号）
    market_th.py         -- 大盘趋势健康度 + 大盘融合决策
    market_context.py    -- 大盘上下文构建（供单品分析参考）
    supply.py            -- 供给端追踪
    batch_scan.py        -- 自选批量扫描
  webapp/
    main.py              -- FastAPI 应用
    templates/           -- Jinja2 模板
    static/css/style.css -- 样式
    static/js/app.js     -- 公共 JS（Modal/导航）
  references/            -- 文档（analysis-engine.md 等）
`

## 数据库表

| 表名 | 用途 | 关键字段 |
|---|---|---|
| items | 自选/持仓物品 | name, steam_name, good_id, rarity, source, in_watchlist, holding |
| market_index | 大盘指数历史 | date, value, change_7d, mood |
| price_history | 单品价格历史 | item_id, date, price_rmb, volume_day |
| snapshots | 分析报告存档 | item_id, date, grade, total_score, report_html, report_md |
| positions | 持仓记录 | item_id, buy_price, quantity, closed, close_price |
| settings | 配置键值对 | key, value |
| backtest_results | 回测结果 | strategy, sharpe_ratio, max_drawdown_pct |

## 常见问题

- **模板中文乱码**: 模板文件必须保存为 UTF-8 编码，不要用 PowerShell 编辑含中文的模板。使用 Python \uXXXX 转义序列生成。
- **成交量为0**: 检查 bar.date 是否正确设置（必须是 YYYY-MM-DD 格式），steamdt merge 依赖日期匹配。
- **分析结果不匹配**: 检查 StatTrak/纪念品过滤是否生效，_verify_item_name 是否正确。
- **分析耗时长**: 单次分析约 30-50 秒（csQAQ 浏览器 + steamdt 合并），正常现象。
- **庄盘识别偏低**: 算法侧重价格异常和供给控盘，存世量权重较低（大存世量也可能是庄盘）。
