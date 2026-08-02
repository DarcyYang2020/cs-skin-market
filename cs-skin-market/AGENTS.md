# CS-Skin-Market — 项目说明

## 项目三大原则（总纲，所有改动以此为准）

1. **破除散户魔咒**：将恐惧和贪婪抽象为计算符号（止损/止盈/抄底等），避开散户凭感觉的弊端。
2. **数学模型代替主观直觉**：相信概率与期望值，寻求正期望值交易；所有算法方案必须先数据测试、后改代码。
3. **止损是概率成本**：不需要每次都看对，看错的时候少亏；止损不是割肉，是付费买一个正确的概率。

## 算法改动验证流程（强制，防分层覆盖）

多因子引擎中各因子共享同一决策边界，后续优化层可能覆盖前面已生效的规则。所有算法改动必须按以下四步执行：

1. **单层独立回测**：每层改动前先跑基线，改动后单独回测，记录单层增量（胜率/均收益/信号数）。
2. **叠加回归**：层与层合入前，重跑当前完整引擎的统一窗口回测（大盘 `python run_backtest.py`；单品 `python run_item_backtest.py --all --warmup 30`），确认叠加后整体 ≥ 最优单层，不满足则不准合入。
3. **消融定位**：叠加后整体变差时，临时关闭上一层规则再跑一次，区分「上一层被冗余化（删规则）」还是「本层引入副作用（调本层）」。
4. **以完整引擎为准**：最终判定以当前完整引擎在统一窗口的胜率/收益为准，单层贡献数字仅作参考；结论与数字记入 `references/backtest_layered.md` 或对应引擎文档。

配套：每次回测自动生成快照 `data/item_backtest_YYYYMMDD.json`（保留 365 天），用于因子衰减监控与回归对比。

## 数据来源与采集

| 数据 | 来源 | 方式 | 说明 |
|---|---|---|---|
| 大盘指数 + 品类排名 | csQAQ API | HTTP GET（同步） | /api/v1/current_data?type=init + ?type=kline |
| 单品搜索 + 详情 + K线 | csQAQ Playwright | 浏览器自动化（异步） | 导航 goods/{id}，拦截 info/chart API |

**定价锚**: 悠悠有品 (platform=2) > Buff > C5GAME，Steam 价格不采用。

**K线数据**: csQAQ chart API 提供 90日日线 OHLCV（price + in_sale_count），成交量由悠悠有品趋势接口采集后按日期聚合回填。

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

### 牛熊动态 TH 阈值 + 牛市深调买点 (P1-2, 2026-08-02)

- 牛市/震荡（regime=bull/sideways）：TH_NEUTRAL 35→30，fair 区「回调确认·分批介入」提前触发；熊市维持 35
- 新增「牛市深调·分批介入」：regime=bull + TH>=30 + z<=0.5 + 21日跌幅<=-12% → buy（仓位 20%），仅 bull 放行
- 数据验证（2026-08-02）：2025 牛市段 cluster=1 3→6 信号 14d/30d 均 100%（新增 10-24 V 型底 +79%）；
  熊市段 6 信号不变 14d 100% 无回归；组合回测结果与 P0 一致
### 建仓区域假底部过滤 (V5.1, 2026-08-01)
「建仓区域」buy（pct≤30 + TH≥55 + z≤0）需满足放行确认：**30日深跌≤-20% 或 14日急跌≤-10%，或 21日温和反弹 0~8%**，否则降级「🟡 假底部·观望」
- V5.1 (2026-08-01 熊市14d视角重验): 深跌确认 OR 低位温和反弹(21日涨幅0~8%)放行；放行 2月小牛六连发(14d全胜 +3.2~+6.7%), 仍拦截 6/15(+20.1%追高)/6/18(+9.8%)/6/30(-8.1%中继)
- 数据验证 (2025-11-02起, run_backtest.py): 过滤后 buy 6次, 14d 胜率 100% 均+11.6%（30d 胜率 50% 均+7.4%, 熊市以14d为准）
- 历史(V5): 曾以30d视角将2月六连发判为假底(30d -0.6%~-3.6%)误杀, 熊市应侧重14d胜率
- 不影响超跌例外路径（pct≤15 短期反转）与 11 月深跌后建仓（chg30=-26% 通过）

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

### 单品买入硬过滤 (P0, 2026-08-01)
在融合决策输出 buy 后追加三层数据验证过滤器（`run_item_analysis`）：
- 大盘环境硬过滤: 大盘TH<45 且 大盘30日跌幅<0 → 🟡 大盘走弱·观望（2026-07 单品信号全灭的根因修复）
- 情绪贪婪禁买: sentiment≤30（贪婪）→ 🟡 情绪贪婪·禁止追买（回测 30d 胜率 0%）
- 半山腰降级: pct 25~40 且无恐慌共振(sent<85) → 🟡 半山腰·观望（回测 14d 胜率仅 28%）
- 7日信号聚类: 7 日内已触发 buy 的同品 → 🟡 已在买点区·等待回调（消除重复信号，依赖 snapshots.action 列）
- 飞刀确认: z<-2 且仍在创新低且3日续跌 → 🟡 飞刀未止跌·观望（回测 z<-2 信号 0/2 全亏）
- 恐慌共振升级: microTH≥60 + pct≤15 + z≤-1.5 + sent≥75 且近7日无 buy → 🟢 恐慌共振·分批建仓（捕捉 5/22-5/27 黄金坑，回测升级 18 信号 14d 100%）
- 微型TH确认: buy 但 microTH<45 → 🟡 短期动能弱·观望（回测该类信号均亏）
- 回测（2025-11-02 起, warmup=30）: 67信号 → 33 独立信号, 14d 胜率 94%（均+45.5%）, 30d 胜率 82%（均+53.7%）

### 买卖区间·退出规则数据拟合 (2026-08-02, P1)

`price_zones` 的 stop_loss / take_profit 按情绪档位配置化（`config.ITEM_EXIT_RULES`），参数来源 `run_item_exit_backtest.py` 网格拟合（ 42 buy 信号, 2026-04-21~08-01 ）：

- **恐慌 sent≥75**：stop_loss = 当前价×0.70 (-30%)，take_profit = 当前价×1.40 (+40%)（深洗盘宽止损 + 利润奔跑，回测 25 信号 76% 胜率 / 单笔期望 +9.70%）
- **中性**：stop_loss = 2.5×ATR（保留），take_profit = 当前价×1.15 (+15%)（回测 17 信号 76.5% 胜率 / 单笔期望 +2.68%）
- **贪婪 sent≤30**：take_profit = 1.5×atr_pct，stop_loss = 当前价×0.92 (-8%)（样本少，维持风控规则）
- **建议持仓 21 天**：buy/hold 信号策略文本展示；前端新增止盈参考卡片。

### ?????? (factor_monitor.py, 2026-08-01)

- `run_item_backtest.py` ????????????? `data/backtest_snapshots/item_backtest_YYYYMMDD.json`?????? `run_backtest.py` ?? `backtest_YYYYMMDD.json`?
- `python pipeline/factor_monitor.py item_backtest_` ???????????14d ?? <70% ? 30d <55% ?????? DECAY ???????? WATCH
- ????????: item_backtest_20260801.json?33 ??, 14d 94%, 30d 82%?

### ??????????? (2026-08-01, ????)

`price_zones` ? stop_loss / take_profit ??????????????????????

- **????**?33 ? buy ?? 30 ????????? avg +53.7% ???????/????"??????"?SL-8 avg +32%?TP+10 avg +19.6%??????(sent?75)??? 3-5 ??? -21%~-28% ????????????????
- **?? sent?75**?stop_loss ??? -30%?current?0.70??take_profit +30%???"????"
- **?? sent?30**?take_profit ??? +1.5?atr_pct?stop_loss ??? -8%???"????"
- **??**??????????

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
- 情绪: 离线回测优先用持久化贪婪指数（macro_history 表，P1-1），无历史时回退大盘价格近似；实时引擎仍用贪婪指数
- 缺失成交量/在售/盘口历史 → 回测用中性默认值，信号带 data_quality 标注
- warmup=30 结果（2026-05-21~07-31, P0 过滤后 33 信号）: 14d胜率94%/均+45.5%, 30d胜率82%/均+53.7%（旧版 67 信号含重复: 14d 61%/30d 77%）
- 分层结论（支撑补仓阈值）: pct≤25&th≥40 → 14d胜率75%; pct 25~40(半山腰) → 14d胜率28%; 市场贪婪(sent≤30) → 30d胜率0%
- 输出: 控制台明细 + data/item_backtest_latest.json

### 持仓补仓建议 (batch_scan._portfolio_advice, 2026-07-31)

浮亏持仓按数据验证阈值分层（sentiment_score 由大盘贪婪指数计算，批量扫描时传入）：

- 市场贪婪 sent≤30 → 禁止补仓（30d 期望为负）
- pct 25~40 半山腰 → 暂缓补仓，等 pct≤25
- pct≤25 + 单品TH≥40 + z≤-0.5 + 大盘TH≥45 → 可分批补仓（14d 胜率 75%）
- pct≤25 但大盘TH<45 → 暂缓，等大盘共振
- 单品TH<30 → 止损优先（风险预算原则）

## 发现高分品模块优化 (2026-08-01)

- P0-1 综合分重排: composite = (评分 + 融合决策加权 + 趋势TH加权) x 估值折价 x 数据质量系数
  - 数据质量: good=1.0 / medium=0.85 / low=0.6 / insufficient=0.2（杜绝"没数据排第一"）
  - 融合决策: buy +1.0 / watch +0.5 / hold 0 / reduce -0.5 / avoid -1.0 / sell -1.0
  - 趋势TH: (TH-50)/50 归一化 ±1.0 加权
- P0-2 覆盖提升: 每类武器扫 6 个(原3), 总量上限 40(原24); K线<14天轻量预筛直接跳过(省采集+分析耗时)
- P1-1 结构化持久化: discover_latest.json 保存 results 明细 + market_th, 前端显示上次扫描时间与成功数
- P1-2 联动单品报告: Top 表名称点击跳 /search?q=名称 自动触发分析; search 页支持 q 参数预填+自动提交

## 文件结构

`
cs-skin-market/
  AGENTS.md              -- 本文件
  SKILL.md               -- Codex Skill 元数据
  run_server.py          -- Web 服务启动脚本
  run_backtest.py        -- 大盘回测脚本（python run_backtest.py [--start 2025-11-02]）
  run_item_backtest.py   -- 单品回测脚本（--all/--items/--warmup/--stratify）
  data/market.db         -- SQLite 数据库
  data/discover_latest.json -- 发现高分品缓存
  pipeline/
    config.py            -- 配置（TOKEN/BASE_URL/权重/参数）
    collector.py         -- csQAQ HTTP 采集（大盘指数/品类/搜索）
    collector_csqaq.py   -- csQAQ Playwright 采集（单品搜索/详情/90日K线）
    collector_youpin.py -- 悠悠有品成交量采集（HTTP，登录态）
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
    backtest_common.py   -- 回测公共模块（approx_sentiment/patch_sentiment/build_market_context）
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
| snapshots | 分析报告存档 | item_id, date, grade, total_score, report_html, report_md, action |
| positions | 持仓记录 | item_id, buy_price, quantity, closed, close_price |
| settings | 配置键值对 | key, value |
| macro_history | 每日宏观快照（贪婪指数/点卡价，P1-1） | date, greedy_index, card_price |
| backtest_results | 回测结果 | strategy, sharpe_ratio, max_drawdown_pct |

## 常见问题

- **模板中文乱码**: 模板文件必须保存为 UTF-8 编码，不要用 PowerShell 编辑含中文的模板。使用 Python \uXXXX 转义序列生成。
- **成交量为0**: 检查 bar.date 是否正确设置（必须是 YYYY-MM-DD 格式），悠悠逐日成交量依赖日期匹配。
- **分析结果不匹配**: 检查 StatTrak/纪念品过滤是否生效，_verify_item_name 是否正确。
- **分析耗时长**: 单次分析约 30-60 秒（csQAQ 浏览器采集为主，悠悠成交量 0.1s），正常现象。
- **庄盘识别偏低**: 算法侧重价格异常和供给控盘，存世量权重较低（大存世量也可能是庄盘）。
