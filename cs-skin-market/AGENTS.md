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
4. **以完整引擎为准**：最终判定以当前完整引擎在统一窗口的胜率/收益为准，单层贡献数字仅作参考；结论与数字记入 `references/decision-log.md`（决策记录）。

配套：每次回测自动生成快照 `data/item_backtest_YYYYMMDD.json`（保留 365 天），用于因子衰减监控与回归对比。

### 参数冻结 + 基准对照 + 期望统计单一事实源（2026-08-07 定稿）

- **参数冻结**：`config.PARAM_FREEZE` 冻结去量引擎 v2（I-13）全参数、组合层 cap0.8、单票敞口提示 30%、
  `ITEM_EXPECTANCY_STATS` 展示口径；~260 天新数据（约 2027-04-25）后真 OOS 复验；复验触发（J-2 三通道，
  任一满足）= A 独立恐慌事件≥3（当前 2）/ B 260 天数据 / C buy 连续 2 月 14d<70% 或月度 14d<80%/30d<55%；
  监测 `python references/j2_channel_monitor.py` → `data/j2_channel_status.json`（dashboard 展示）。冻结期内禁止以回放数据为依据调参。
- **期望统计单一事实源**：`data/item_backtest_full_2025.json`（回放产物）→
  `python references/sync_expectancy_config.py` 自动同步 `config.ITEM_EXPECTANCY_STATS` +
  `data/signal_event_counts.json`；`t_expectancy_sync` 全字段硬校验防漂移（改回放不重跑同步即测试失败）。
- **基准对照**：`python references/benchmark_compare.py` → `data/benchmark_compare.json`
  （策略 cap0.8 vs 池内等权买入持有 vs 大盘指数，full/active 双窗口）。2026-08-07 结论：策略 +193.30%/-9.39%
  大幅跑赢大盘 -4.02%，但低于池内等权 +509.75%/-54.12% —— 引擎边际价值在风险控制（maxDD 9.4% vs 54~58%）。


## 数据来源与采集

数据层完整手册（数据源/采集链路/每日任务/表结构/维护/故障 SOP）见 `references/data-layer.md`；官方接口端点清单见 `references/cs-knowledge.md`。

- **量源**: csQAQ chart API 的 `in_sale_count`（在售量）为唯一量源；2026-08-07 起引擎去成交量，真实成交量采集器与 uu_headers 凭据已删除。
- **定价锚**: 悠悠有品 (platform=2) > Buff > C5GAME；Steam 价格不采用。
- **浏览器**: `_get_browser()` 全局单例，5 分钟超时重建；等待策略 `domcontentloaded`（SPA 长连接永不 idle）。
- **StatTrak/纪念品**: 自动排除，仅分析普通版；`（★）` 普通标记不过滤（StatTrak 刀显示 `（★ StatTrak™）`）。
- **快照 `_keep_wear`**: 枪皮/刀仅崭新出厂、手套仅略磨+久经、无磨损品类（印花/箱/胶囊）保留。
- **存世量**: 崭新出厂 <3000 → 不建仓（`survive_too_low`）；口径为 `info/good.statistic_list`（非 `buff_sell_num`）。
- **每日采集**: SQL 排除「存世量过低 / 活跃池淘汰」标记品（自选/持仓豁免）；大户集中度每周一采集。

## 单品分析引擎 (item_analysis.py)

run_item_analysis(name, prices, volumes, supply_hist, order_book, index_change_7d, market_history, market_pct_90d, market_zscore) 协调以下模块：

| 模块 | 函数 | 功能 |
|---|---|---|
| 估值定位 | _analyze_position | 90日百分位 + Z-score + 标签（低估/合理/高估/泡沫） |
| 周期判定 | _analyze_cycle | 四阶段：吸筹/拉升/出货/洗盘，含持仓时间计数 |
| 流动性评估 | score_liquidity | 二维 0-100：在售深度(50%) + 价格稳定(50%)（2026-08-07 去量重写，原成交量维度移除） |
| 涨跌概率 | analyze_probability | 均值回归 + 波动率分类 + 3/7/14日预测 |
| 投资价值 | compute_value_score | 1-10 分 + S/A/B/C 评级 |
| 庄盘识别 | analyze_whale | 四因子：价格异常 + 供给控盘 + 量价关系 + 波动率 |
| 趋势健康度 | compute_trend_health (trend_health.py) | 五维 0-100：持续性/陡度/均线结构/供给×价格配合/异常缺口（2026-08-07 去量） |
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

```bash
cd cs-skin-market && python run_server.py
# 或 python -m uvicorn webapp.main:app --host 127.0.0.1 --port 8000
```

| 页面 | 路由 | 说明 |
|---|---|---|
| 大盘仪表盘 | / | 大盘指数 + 市场宏观 + 融合决策 + 数据积累进度 |
| 单品分析 | /search | 搜索 + 分析，结果持久化 |
| 持仓管理 | /watchlist | 自选 + 持仓 + 批量扫描 + 执行记录 + 组合仓位仪表 |
| 发现高分品 | /discover | 扫描全武器类型崭新出厂品，筛选 Top 10 |
| 监控 | /monitor | M1 每日自选品异动事件（买点接近/止损/决策翻转/供给突变/价格异动/大盘切换/持仓到期/新买信号） |

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
| GET  | /api/watchlist/batch-scan-latest | 最近一次批量扫描缓存（结果+HTML） |
| POST | /api/watchlist/batch-scan-latest/clear | 清除批量扫描缓存 |
| GET  | /api/watchlist/scan-history | 扫描历史归档列表 + 最近信号摘要 |
| GET  | /api/watchlist/scan-history/{scan_id} | 历史归档详情 HTML |
| GET  | /api/watchlist/executions | 执行记录列表（自动结算到期记录） |
| POST | /api/watchlist/executions | 新增执行记录（按建议执行/手动录入） |
| DELETE | /api/watchlist/executions/{eid} | 删除执行记录 |
| GET  | /api/data/progress | 数据积累进度（大盘/K线/在售量覆盖） |
| GET  | /api/portfolio/dashboard | 组合仓位仪表（持仓分布+并发仓位占用） |
| POST | /api/discover/scan-all | 扫描全武器类型，异步分析 |
| GET  | /api/items/discover-progress/{task_id} | 发现高分品进度轮询 |
| GET  | /api/discover/latest | 获取上次扫描缓存结果 |

**模板结构**:
```
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
    dashboard_refresh.html -- 仪表盘刷新区域
```

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
- **TH 三区语义（2026-08-06 TH 矫正后）**：TH<35 恐慌黄金坑（14d 95%/+41）｜35-54 摩擦带（deep_value 族加 chg30 闸门防阴跌横盘）｜≥55 趋势确认；详见 `references/th_calibration.md`

### 发现高分品（discover，F-3/F-3.4/F-3.5 定稿）
新页面 /discover：默认**池内扫描**（纯 DB 重排序，DB 新鲜 K 线秒过，过期品才网络补齐）；`mode=search` 保留全网搜索扩池路径（手动触发，受验证码/限流影响）。
- **范围**：13 武器类型（AK-47 / AWP / 沙漠之鹰 / M4A4 / USP / MP7 / SSG 08 / 法玛斯 / M4A1 消音版 / 格洛克 18 型 / MP9 / Tec-9 / 加利尔 AR）崭新出厂，排除 StatTrak/纪念品/匕首
- **过滤**：近 7 天平均在售量 <15 预筛跳过；非崭新出厂/存世量过低/活跃池淘汰品排除
- **排序**：综合分（评分 + 融合决策 + 趋势TH + 估值折价 + 数据质量系数）降序取 Top 10
- **缓存**：结果存 data/discover_latest.json；完成产物含 top10 历史 + 台账（F-3.2）
- **异步**：扫描在后台执行，点击立即返回进度条

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
- **期望值标签**：buy 信号区间旁显示历史回测胜率/均收益（`config.ITEM_EXPECTANCY_STATS`），恐慌共振 vs 周期吸筹两层分类。

### 样本扩展与恐慌共振过滤 (P0-7, 2026-08-02, 181天数据验证)

- **窗口扩展（历史）**: `backfill_youpin_price.py` 曾用悠悠 day=180 回填历史价（重叠期校准系数 k=median(csqaq/youpin)），单品历史 104天→181天（2026-02-03）；该归档脚本与悠悠采集器已于 2026-08-07 删除（数据已积累至 500+ 天，无需再回填）
- **过拟合实证**: 窗口扩展后 49 信号 14d 66.7%/30d 48.8%（原37信号88.9%/76.5% 是窗口偏差——warmup=30 恰好过滤掉 4-23/5-11 半山腰次）
- **P0-7 恐慌共振过滤**: 共振升级需满足 ①非印花/贴纸 ②价格≥15 ③ z≥-2.2（深超卖冷门品反而继续阴跌） ④ 大盘 21日跌幅≤-18%（区分 4-23 半山腰 -13% vs 5-22 黄金坑 -19.6%）
- **P0-7b 周期吸筹过滤**: 吸筹 buy 也需大盘 21日跌幅≤-18%（新样本4信号30d均-20%，全非深跌场景）
- **效果（49→14 信号）**: 14d 100%/avg+57.1，30d 85.7%/avg+50.5（全部为 5/22-5/26 黄金坑，提示未来再次触发需等下一次恐慌深跌）
- 大盘 drop21 参数已全链路传递（backtest_common / run_item_backtest / webapp.analysis_service.market_snapshot / item_analysis）

### 因子衰减监控 (factor_monitor.py, 2026-08-01)

- `run_item_backtest.py` 每次回测自动存档快照至 `data/backtest_snapshots/item_backtest_YYYYMMDD.json`（大盘对应 `backtest_YYYYMMDD.json`）
- `python pipeline/factor_monitor.py item_backtest_` 自动监控信号胜率，14d 胜率 <70% 或 30d <55% 时输出 DECAY / WATCH 警告
- 当前基线: item_backtest_20260802.json 37 信号, 净14d 86%/30d 74%（含供给扩张过滤后, 扣 2% 双边成本）

### 供给扩张过滤器 (2026-08-02, 数据验证)

- 回测 in_sale_count（csQAQ chart 在售数历史，`backfill_in_sale.py` 回填）：42 个 buy 信号中，供给扩张(supply_change_30d>5%)的 5 个信号30d 胜率0%，均为负期望
- 规则：buy/超卖买入信号且 in_sale 30日扩张 >5% → 降级 🟡 供给扩张·观望，position_limit=0
- 效果：42→37 信号，14d 86.8%→88.9%，30d 74.3%→76.5%，打掉 4 个 30d 负收益（合纵 -16.24% 等）；回测口径已统一扣 2% 双边成本（--cost 0.02），净胜率14d 86.1%/30d 73.5%
- 回测切片：`run_item_9grid_backtest.py` 情绪×估值九宫格，恐惧带≥75+深低估 pct<10 为核心格子（14d 95%/30d 83%），贪婪带样本少且非负期望，暂无需新增降级规则

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

### 单品回测工具 (run_item_backtest.py, 2026-07-31；2026-08-08 归档)

> 已归档至 `references/scripts-archive/`（2026-08-08：与 refit_pipeline.py 功能重叠且零引用）。
> 历史结论保留如下，当前回测/重拟合统一走 `references/refit_pipeline.py`。

离线回放单品引擎（不采集、不联网），验证买入信号历史胜率：

```
python references/scripts-archive/run_item_backtest.py --all --warmup 30 --stratify
python references/scripts-archive/run_item_backtest.py --items "AWP | 冥界之河 (崭新出厂);AK-47 | 抽象派 1337 (崭新出厂)" --warmup 60
```

- 数据源: `price_history`（2026-04-21 起，按日期取最新采集去重）+ `market_index`（2025-11-02 起）
- 情绪: 离线回测优先用持久化贪婪指数（macro_history 表，P1-1），无历史时回退大盘价格近似；实时引擎仍用贪婪指数
- 缺失成交量/在售/盘口历史 → 回测用中性默认值，信号带 data_quality 标注
- warmup=30 结果（2026-05-21~07-31, P0 过滤后 33 信号）: 14d胜率94%/均+45.5%, 30d胜率82%/均+53.7%（旧版 67 信号含重复: 14d 61%/30d 77%）
- 分层结论（支撑补仓阈值）: pct≤25&th≥40 → 14d胜率75%; pct 25~40(半山腰) → 14d胜率28%; 市场贪婪(sent≤30) → 30d胜率0%
- 输出: 控制台明细 + data/backtest_snapshots/item_backtest_YYYYMMDD.json（标准回放基准 = data/item_backtest_full_2025.json，旧 88 基准已删）

### 持仓补仓/止损（F-3.7 定稿，2026-08-09）
浮亏持仓走**五状态止损矩阵 + V 型底补仓**（完整理论/回测/矩阵见 `references/stop-loss-strategy.md`）：
- 触发线：浮亏≥-15% 评估（非直接止损）；供给扩张（单品在售量 30日+5%）→ 全止损；恐慌深跌（mchg30≤-15%）→ 不止损转补仓评估；阴跌中继（-15%~-5%）→ 减半止损；大盘上涨段/中性 → 不止损
- 补仓：仅「恐慌深跌 + 单品供给收缩」（V 型底指纹 win87%/+43.7%），倒金字塔 3:2:1、单批≤15%、总敞口≤30%；禁补=阴跌中继/供给扩张/贪婪区（sent≤30）
- 旧规则（sent≤30 禁补 / pct≤25+TH≥40 可补）已并入矩阵，不再单列

## 发现高分品模块优化（2026-08-01，历史记录；扫描范围/路径 2026-08-08 起由 F-3/F-3.4/F-3.5 更新，见上节「发现高分品」）

- P0-1 综合分重排: composite = (评分 + 融合决策加权 + 趋势TH加权) x 估值折价 x 数据质量系数
  - 数据质量: good=1.0 / medium=0.85 / low=0.6 / insufficient=0.2（杜绝"没数据排第一"）
  - 融合决策: buy +1.0 / watch +0.5 / hold 0 / reduce -0.5 / avoid -1.0 / sell -1.0
  - 趋势TH: (TH-50)/50 归一化 ±1.0 加权
- P0-2 覆盖提升（2026-08-08 扩至 13 武器/240 候选，见 F-3）: 每类武器扫 6 个(原3), 总量上限 40(原24); K线<14天轻量预筛直接跳过(省采集+分析耗时)
- P1-1 结构化持久化: discover_latest.json 保存 results 明细 + market_th, 前端显示上次扫描时间与成功数
- P1-2 联动单品报告: Top 表名称点击跳 /search?q=名称 自动触发分析; search 页支持 q 参数预填+自动提交

## 产品层迭代 (2026-08-04)

2026-08-04 引擎冻结期（当时等真实成交量积累）的产品/展示层增强批次，不改任何信号引擎（2026-08-07 去量后已解冻）：

- **P0-1 批量扫描历史归档**：批量扫描提取信号（可分批补仓 > 建议止损 > 已到买点），存 data/scan_history/scan_*.json（保留 30 份）；watchlist 页历史下拉回看（信号中心卡 2026-08-09 移除）
- **P0-2 执行记录 + 自动复盘**：executions 表；批量扫描「按建议执行」/手动录入；14/30 天到期按最近收盘价自动结算（净收益扣 2% 双边成本，与回测口径一致）
- **P0-3 数据积累进度**：大盘/K线覆盖度 + 90 天目标进度条（2026-08-07 改为在售量覆盖，见 dashboards.data_progress）
- **P0-4 组合仓位仪表**：持仓市值/仓位比例/集中度 + 最近扫描时间（并发建议仓位占用 2026-08-09 移除）
- **体验优化**：执行记录手动录入、待结算预计日期、平均净收益汇总、物品名自动补全

## 文档编码规范（防乱码，2026-08-04）

所有文本文件统一 **UTF-8 无 BOM**（.md/.py/.html/.css/.js/.json/.txt），`.gitattributes` 已声明文本属性，换行符由 git 规范化（提交入库为 LF）。

**乱码三大根源与规避**：
1. **PowerShell 管道传中文**：`@'...'@ | python -` 会把中文变 `?`（控制台 GBK 代码页）。禁止用管道直接传中文给脚本；改用 node_repl（JSON 通道，UTF-8 无损）或先落盘 UTF-8 脚本再执行，或代码内用 `\uXXXX` 转义。
2. **终端显示误判**：GBK 控制台直接 `Get-Content` UTF-8 文件会显示乱码，但文件本身没坏。用 Python/node_repl 以 UTF-8 读取验证后再判断。
3. **编辑器保存编码**：统一 UTF-8 无 BOM；不要用 GBK/ANSI 保存中文文件。

**提交前检查**：`python tests/check_encoding.py`（已并入冒烟测试 t_encoding）。hard 问题（非法 UTF-8/BOM/U+FFFD）必须修复；`?` 长串警告需人工确认——如 decision-log 中 `AK-47 | ??? 1337` 是刻意记录脏名，非损坏。

**已知历史损坏**：`references/portfolio_cap_fit.py` 头部中文注释已丢失（PowerShell 管道写入所致，2026-08-04 发现），代码可用，未恢复。

## 文件结构

> 文件结构唯一事实源：`PROJECT_STRUCTURE.md`；本清单仅保留运行要点，改动时两处同步。


cs-skin-market/
  AGENTS.md              -- 本文件
  SKILL.md               -- Codex Skill 元数据
  run_server.py          -- Web 服务启动脚本（uvicorn）
  run_daily_collect.py   -- 每日自动采集总调度（大盘/宏观/K线全量每日 + 全市场快照/大户每周一 + 健康 + J-2 刷新 + 信号回填 + DB 备份）
  run_data_health.py     -- 数据源健康检查（全量可采集品动态基线）
  run_health_monitor.py  -- 健康监控入口（run_monitor，退出码 0/2）
  backup_db.py           -- 每日 SQLite 备份（保留 14 份）
  notify_alert.py        -- 告警/监控推送（钉钉，.env NOTIFY_WEBHOOK_URL；M2 监控日报复用）
  references/scripts-archive/ -- 历史回测/回填脚本归档（run_backtest/run_item_backtest/run_item_9grid/run_item_exit/run_portfolio/run_backfill_history，2026-08-08 归档；当前回测统一走 references/refit_pipeline.py）
  data/market.db         -- SQLite 数据库
  data/item_backtest_full_2025.json -- 标准回放基准（去量 v2，370 信号）
  pipeline/
    config.py            -- 配置（TOKEN/BASE_URL/权重/PARAM_FREEZE/J2_THRESHOLDS/ENGINE_VERSION）
    collector.py         -- csQAQ HTTP 采集（大盘指数/品类/搜索）
    collector_csqaq.py   -- csQAQ Playwright 采集（单品搜索/详情/K线/fetch_history_deep 深历史）
    collector_snapshot.py -- 全市场快照采集（get_page_list 翻页，存 market_snapshot，每周一）
    collector_monitor.py -- 大户集中度快照采集（monitor/rank 每周 Top50，存 monitor_rank_snapshot）
    db.py                -- SQLite 存储（schema 版本化 + 全表 CRUD）
    item_analysis.py     -- 单品分析主流程（信号族注册制 + 12 闸门融合决策）
    trend_health.py      -- 趋势健康度 + 融合决策
    valuation.py         -- 估值分位（百分位 + Z-score + 标签）
    index_analysis.py    -- 大盘指数分析引擎
    market_macro.py      -- 市场宏观（涨跌比/贪婪/在线/活跃卡/抄底信号）
    market_th.py         -- 大盘趋势健康度 + 大盘融合决策
    market_context.py    -- 大盘上下文构建 + state_bucket 状态桶
    portfolio_risk.py    -- B1 风险预算层（组合回撤熔断 + 单票敞口提示）
    supply.py            -- 供给端追踪（在售量唯一量源）
    buy_distance.py      -- 买点参考位（批量扫描排序/信号提取用；展示卡片 F-3.8 移除）
    signal_tracking.py   -- 生产实盘信号跟踪（J-2 C 通道）
    monitor.py           -- M1/M2 监控模式（每日自选品异动事件生成 + 日报 + 钉钉推送，纯提醒层）
    backtest_common.py   -- 回测公共模块（build_market_context 等）
    backtest_methodology.py -- A2 三件套（walk-forward/聚类/置换检验）
    batch_scan.py        -- 自选批量扫描（信号提取/按建议执行按钮）
    dashboards.py        -- 仪表盘数据（数据积累进度/J-2 三通道/组合仓位）
    factor_monitor.py    -- 因子衰减监控
  webapp/
    main.py              -- FastAPI 应用（含批量扫描进度落盘持久化）
    analysis_service.py  -- 公共分析服务层（analyze_fresh 统一核心 + 锚价/兜底助手）
    templates/           -- Jinja2 模板
    static/css/style.css -- 样式
    static/js/app.js     -- 公共 JS（Modal/导航）
  references/            -- 文档 + 研究脚本（j2_channel_monitor.py / refit_pipeline.py / portfolio_backtest.py 等）
  tests/
    test_smoke.py        -- 冒烟测试（86 用例，支持 CS_MODEL_SKIP_NET；P1.2 起含 Web 只读 API 冒烟）
    check_encoding.py    -- 编码健康检查
    snapshots/replay_v2.json -- 回放口径快照


## 数据库表

完整表结构与用途见 `references/data-layer.md` 第 5 节：
items / price_history / market_index / macro_history / snapshots / market_snapshot / monitor_rank_snapshot /
monitor_events / positions / executions / signal_tracking / analysis_results / health_checks / backtest_results / settings / schema_version。

## 风控/信号职责分工（三层闸门，2026-08-06 定稿）

- **组合闸门（portfolio_risk.py）**：组合回撤熔断（10%，收复峰值解除）+ 单票敞口提示（30%，只提示不拒绝）——管「组合层面是否开新仓」。
- **信号族闸门（未来路由层）**：按市场状态（贪婪禁入/恐慌+深跌=V型底区/恐慌+中跌=阴跌中继区/恐慌浅跌/中性企稳/弱市观望）决定哪些信号族开火——当前由各族门控隐含实现，界面标注见 batch_scan.market_regime。
- **单品买点（item_analysis 融合决策）**：管「具体品是否到买点」。

## 运维（2026-08-06）

- **数据库自动备份**：`python backup_db.py`（SQLite online backup API → `data/backup/market_YYYYMMDD_HHMMSS.db`，默认保留 14 份）；计划任务 `CS_DB_Backup` 每日 23:30。
- **健康告警**：`python notify_alert.py --monitor`（健康检查 FAIL 时推送）；`.env` 配 `NOTIFY_WEBHOOK_URL`（钉钉机器人）后生效，未配置则静默；计划任务 `CS_Health_Alert` 每日 22:00（采集落库后告警）。
- **计划任务安装**：`powershell -ExecutionPolicy Bypass -File install_tasks.ps1`（在 cs-skin-market 目录）。任务清单：`CS_Skin_DailyCollect` 每日 18:00 全量采集（2026-08-08 由 21:30 提前；收尾仅生成监控事件+日报不推送）、`CS_Skin_NightPush` 每日 21:30 晚间推送（事件幂等去重，保持 12:00 午间 + 21:30 晚间两时段）、`CS_Skin_NoonMonitor` 每日 12:00 午间轻量、`CS_Health_Alert` 每日 22:00 健康告警。
- **调度与数据维护总览**：见 `references/data-layer.md`（第 3 节调度表 + 第 4 节更新维护）。
- **本地 CI（pre-commit hook）**：`powershell -ExecutionPolicy Bypass -File install_hooks.ps1` → 每次 `git commit` 自动跑 `tests/test_smoke.py`，失败则拦截提交。
- **执行记录滑点统计**：`executions.advice_price`（建议价，批量扫描「按建议执行」自动带入）；复盘页显示单笔滑点与平均滑点，用于校准 2% 双边成本假设。

## 常见问题

- **模板中文乱码**: 模板文件必须保存为 UTF-8 编码，不要用 PowerShell 编辑含中文的模板。使用 Python \uXXXX 转义序列生成。
- **在售量缺失**: 检查 bar.date 是否正确设置（必须是 YYYY-MM-DD 格式）；在售量（in_sale_count）为当前唯一量源（悠悠成交量采集器 2026-08-07 已删除）。
- **分析结果不匹配**: 检查 StatTrak/纪念品过滤是否生效，_verify_item_name 是否正确。
- **分析耗时长**: 单次分析约 30-60 秒（csQAQ 浏览器采集为主），正常现象。
- **庄盘识别偏低**: 算法侧重价格异常和供给控盘，存世量权重较低（大存世量也可能是庄盘）。

<!-- PROJECT-MEMORY -->
## 会话分工约定（重要）

- 策略研究（大盘/单品引擎 + 回测验证）是唯一长期会话，其余短任务应提醒用户新开会话执行。
- 短任务类型：修 bug、改前端/报告、采集数据、样本扩展、工程清理、文档更新等。
- 短任务开工前读 AGENTS.md + references/decision-log.md，干完把涉及口径的改动补记进 decision-log.md。
- 避免并行改同一文件：webapp/main.py 归前端短任务会话，pipeline/item_analysis.py 归策略会话。

<!-- PROJECT-MEMORY -->
