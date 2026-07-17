# CS-Market 大盘分析引擎

> 版本: v4.0 | 更新: 2026-07-17

---

## 数据源

| 数据 | 来源 | 说明 |
|---|---|---|
| 大盘K线 (prices) | csQAQ API `GET /api/v1/sub/kline?id=1&type=90day` | 90 日每日收盘价，约 90 根日线 |
| 当前指数值 | csQAQ API `GET /api/v1/current_data?type=init` | 从 `sub_index_data` 提取当前指数 |
| 板块资金流向 | csQAQ API `GET /api/v1/current_data?type=init` | `chg_type_data` 各板块涨跌幅及趋势 |
| 宏观数据 | csQAQ API 多接口聚合 | K线成交额 + 在线人数 + 充值卡溢价 |

大盘引擎完全基于 csQAQ HTTP API，不需要 Playwright。

---

## 模块架构总览

| 序号 | 模块 | 函数 | 所在文件 | 版本 |
|---|---|---|---|---|
| 1 | 点位智能判断 | `analyze_index()` | `index_analysis.py` | v3 |
| 2 | 涨跌概率预测 | `analyze_probability()` | `index_analysis.py` | v3 |
| 3 | 周期阶段判定 | `analyze_cycle()` | `index_analysis.py` | v3 |
| 4 | 投资性价比评分 | `analyze_value_score()` | `index_analysis.py` | v3 |
| 5 | 大盘趋势健康度 | `compute_market_trend_health()` | `market_th.py` | v3 |
| 6 | 大盘融合决策 | `compute_market_fusion_decision()` | `market_th.py` | v3 |
| 7 | **周期概率分布** | `analyze_cycle_probability()` | `index_analysis.py` | v4 新增 |
| 8 | **涨跌概率(多因子)** | `analyze_probability_integrated()` | `index_analysis.py` | v4 新增 |
| 9 | **抄底就绪度** | `compute_bottom_signal()` | `market_macro.py` | v4 新增 |
| 10 | **宏观环境** | `market_macro.py` 系列函数 | `market_macro.py` | v4 新增 |
| 11 | 大盘-板块联动 | `market_context.py` | `market_context.py` | v3 |

---

## 各模块详细说明

### 1. 点位智能判断 `analyze_index`

**功能**: 基于 90 日 K 线数据计算当前百分位 + Z-score + 支撑/压力位

| 输出字段 | 含义 |
|---|---|
| `position.percentile_90d` | 90 日价格百分位 (0-100%) |
| `position.zscore_90d` | Z-score，偏离均值标准差倍数 |
| `position.position_label` | 低估/合理/高估/泡沫标签 |
| `position.strategy_zone` | entry/exit/hold 三区 |
| `position.zone_label` | 入场区/持有区/离场区 |
| `position.support_levels` | 支撑位列表 (近期低点+均线) |
| `position.resistance_levels` | 压力位列表 (近期高点+均线) |

**百分位策略阈值** (来自 trading-strategies.md):
- 入场: <=30% 分位 (低估区)
- 止盈: >=65% 分位 (分批落袋)
- 泡沫: >=90% 分位 (极度泡沫)

---

### 2. 涨跌概率预测 `analyze_probability`

**功能**: 基于 Z-score 均值回归模型 + 概率展期

| 输出字段 | 含义 |
|---|---|
| `probability.prob_up_3d` | 3 日上涨概率 (0-100%) |
| `probability.prob_up_7d` | 7 日上涨概率 |
| `probability.prob_up_30d` | 30 日上涨概率 |
| `probability.volatility_regime` | 波动率状态 (calm/normal/volatile) |

**计算逻辑**:
1. 计算 90 日 Z-score，归一化至 0-1 上涨概率
2. 按时间窗口展期: Z 值偏离越大，回归概率越高
3. 波动率修正: 高波动环境下调置信度

---

### 3. 周期阶段判定 `analyze_cycle`

**功能**: 基于 MA7/MA30/MA90 均线系统 + 量价判断市场所处周期

| 输出字段 | 含义 |
|---|---|
| `cycle.phase` | accumulation/consolidation/markup/distribution |
| `cycle.phase_label` | 吸筹期/洗盘期/拉升期/出货期 |
| `cycle.phase_strategy` | 对应操作策略描述 |
| `cycle.phase_confidence` | 周期判定置信度 (0-1) |

**判定规则**:
- 吸筹期: MA7 上穿 MA30 + 低位 + MA90 下方
- 洗盘期: 均线缠绕 + 中低位
- 拉升期: MA7>MA30>MA90 (多头排列) + 量能配合
- 出货期: MA7 下穿 MA30 + 高位 + 放量滞涨

---

### 4. 投资性价比评分 `analyze_value_score`

**功能**: 综合位置 + 风险 + 周期 + 情绪四维打分 (1-10 分)

| 输出字段 | 含义 |
|---|---|
| `value_score.score` | 综合评分 (1-10) |
| `value_score.entry_proximity` | 入场接近度 (0-3) |
| `value_score.risk_score` | 风险评估 (0-3) |
| `value_score.cycle_score` | 周期阶段得分 (0-3) |
| `value_score.sentiment_score` | 情绪面得分 (0-3) |
| `value_score.position_advice` | 操作建议 (建仓/持有/观望等) |
| `value_score.recommendation` | 详细推荐说明 |

---

### 5. 大盘趋势健康度 `compute_market_trend_health`

**功能**: 多维度量化大盘趋势健康度 (0-100 分)，用于融合决策

| 维度 | 权重 | 衡量内容 |
|---|---|---|
| 趋势持续性 | 24% | 连续 N 日站稳/跌破 MA7 |
| 趋势陡度 | 24% | 7 日线性回归斜率归一化 |
| 均线结构 | 19% | MA7/MA30/MA90 排列 |
| 量价配合 | 18% | 涨放量/跌缩量 vs 背离 |
| 异常缺口 | 15% | MAD 修正标准差检测极端波动 |

**修正层**:
- 事件风险折价: 重大利空 x0.7~0.9
- 全市场量价背离折价: x0.8
- 泡沫广度折价: 超 50% 板块高估 x0.85

| 输出字段 | 含义 |
|---|---|
| `market_trend_health.raw_score` | 原始趋势健康分 |
| `market_trend_health.corrected_score` | 修正后趋势健康分 |
| `market_trend_health.direction` | up/down/sideways |
| `market_trend_health.ma_structure` | 均线结构描述 |
| `market_trend_health.ma_cross_type` | 金叉/死叉/无交叉 |
| `market_trend_health.deduction_sources` | 扣分来源列表 |

---

### 6. 大盘融合决策 `compute_market_fusion_decision`

**功能**: 百分位 + 趋势健康度 + Z-score 融合为标准化操作建议

**融合规则**:

| 区间 | 条件 | 输出 |
|---|---|---|
| 低估 0-30% | TH>=60 | 分批建仓 (仓位上限 30%) |
| 低估 0-30% | TH<40 | 下跌中继 (暂不参与) |
| 合理 30-70% | TH>=70 | 持有 (移动止盈) |
| 合理 30-70% | TH<50 | 震荡观望 |
| 高估 70-100% | TH>=70 | 强势趋势持有 (设止盈) |
| 高估 70-100% | TH<50 | 趋势反转清仓 |
| 极端泡沫 >95%+Z>2.5 | 强制 | 极端泡沫建议清仓 |

| 输出字段 | 含义 |
|---|---|
| `market_fusion_decision.action` | accumulate/hold/reduce/wait |
| `market_fusion_decision.action_label` | 操作标签 (中文) |
| `market_fusion_decision.action_detail` | 操作说明 |
| `market_fusion_decision.raw_th_score` | 原始 TH 分 |
| `market_fusion_decision.corrected_th_score` | 修正后 TH 分 |
| `market_fusion_decision.global_position_limit` | 全局仓位上限 (0-1) |

---

### 7. 周期概率分布 `analyze_cycle_probability` (v4 新增)

**功能**: 将周期判定概率化，输出四大周期概率分布

| 输出字段 | 含义 |
|---|---|
| `cycle_probability.accumulation` | 吸筹期概率 (%) |
| `cycle_probability.consolidation` | 洗盘期概率 (%) |
| `cycle_probability.markup` | 拉升期概率 (%) |
| `cycle_probability.distribution` | 出货期概率 (%) |

**判定方法**: 基于百分位 + Z-score + 均线结构综合打分

---

### 8. 涨跌概率(多因子) `analyze_probability_integrated` (v4 新增)

**功能**: 纳入趋势健康度 + 周期阶段 + 大盘环境的综合概率预测

相比 v3 纯 Z-score 模型，新增特征:
- 趋势健康分 (TH) 修正
- 周期阶段修正
- 大盘百分位约束
- 市场事件修正

| 输出字段 | 含义 |
|---|---|
| `probability_integrated.prob_up_3d` | 修正后 3 日上涨概率 |
| `probability_integrated.prob_up_7d` | 修正后 7 日上涨概率 |
| `probability_integrated.prob_up_30d` | 修正后 30 日上涨概率 |
| `probability_integrated.confidence` | 置信度标签 (high/medium/low) |
| `probability_integrated.modifiers_applied` | 应用过的修正因子列表 |

---

### 9. 抄底就绪度 `compute_bottom_signal` (v4 新增)

**功能**: 综合定价 + 广度 + 情绪 + 动能评分 (0-100)

| 维度 | 权重 | 说明 |
|---|---|---|
| 百分位贡献 | 25% | 价格位置越低分越高 |
| Z-score 贡献 | 20% | 偏离越极端分越高 |
| 广度恐慌 | 20% | 市场广度恐慌程度 |
| 情绪冰点 | 20% | 贪婪指数恐慌程度 |
| 跌速衰竭 | 15% | 下跌速度衰减程度 |

**输出结论**:
- >=80: 非常适合抄底
- 60-79: 可轻仓试探
- 40-59: 下跌中继或正常调整勿抄底
- <40: 趋势强势不适合抄底

| 输出字段 | 含义 |
|---|---|
| `bottom_signal.total_score` | 抄底就绪度总分 (0-100) |
| `bottom_signal.conclusion` | 结论标签 |
| `bottom_signal.percentile_contrib` | 百分位维度得分 |
| `bottom_signal.zscore_contrib` | Z-score 维度得分 |
| `bottom_signal.breadth_contrib` | 广度恐慌得分 |
| `bottom_signal.sentiment_contrib` | 情绪冰点得分 |
| `bottom_signal.deceleration_contrib` | 跌速衰竭得分 |

---

### 10. 宏观环境 `market_macro.py` (v4 新增)

**功能**: 采集并分析市场宏观辅助指标

| 指标 | 函数 | 含义 |
|---|---|---|
| 市场广度 7d | `compute_breadth_score(7)` | 近 7 日板块涨跌占比 |
| 市场广度 90d | `compute_breadth_score(90)` | 近 90 日板块涨跌占比 |
| 情绪面 | `compute_sentiment_score()` | 贪婪/恐慌综合评分 |
| 贪婪指数 | `get_greedy_current()` | 当前贪婪指数值 |
| 在线人数 | `get_online_current()` | Steam 当前在线人数 |
| 在线趋势 | `compute_online_trend_score()` | 在线人数趋势评分 |
| 充值卡溢价 | `compute_card_trend_score()` | 充值卡价格趋势评分 |

---

### 11. 大盘-板块联动 `market_context.py`

**功能**: 计算大盘与板块、大盘与单品的相关性

| 输出字段 | 含义 |
|---|---|
| `market_corr.with_sectors` | 大盘 vs 各板块相关系数 |
| `market_corr.with_watchlist` | 大盘 vs 自选单品相关系数 |
| `market_corr.market_regime` | 大盘当前市场状态 |

---

## 数据流架构

```
csQAQ API (HTTP)
    |
    GET /sub/kline?id=1&type=90day -> 大盘K线数据
    GET /current_data?type=init    -> 当前指数 + 板块数据
    其他聚合接口                    -> 宏观数据
    |
    v
collector.py (HTTP 同步调用)
    |
    v
index_analysis.py
    +--- analyze_index()              -> 点位智能判断
    +--- analyze_probability()        -> 涨跌概率预测 (v3)
    +--- analyze_cycle()              -> 周期阶段判定
    +--- analyze_value_score()        -> 投资性价比评分
    +--- analyze_cycle_probability()  -> 周期概率分布 (v4)
    +--- analyze_probability_integrated() -> 多因子概率 (v4)
    +--- analyze_index_full()         -> 整合入口 (v4)
    |
    v
market_th.py
    +--- compute_market_trend_health()    -> 大盘趋势健康度
    +--- compute_market_fusion_decision() -> 大盘融合决策
    |
    v
market_macro.py (v4)
    +--- compute_bottom_signal() -> 抄底就绪度
    +--- 宏观辅助指标系列函数
    |
    v
webapp/main.py -> Jinja2 模板渲染
    +--- index_analysis.html (大盘仪表盘)
    +--- index_card.html (大盘卡片)
    +--- dashboard_refresh.html (刷新入口)
```

---

## 调用流程 (刷新链路)

```
用户点击"刷新数据"
    |
    v
POST /api/market/refresh
    |
    +-- 1. collector.fetch_market_index()   -> 当前指数值
    +-- 2. collector.fetch_index_kline()    -> 90日K线数据
    +-- 3. collector.fetch_sector_flow()    -> 板块资金流向
    +-- 4. db.save_market_index()           -> 保存当前指数
    +-- 5. db 批量保存K线数据
    +-- 6. db 缓存板块JSON
    +-- 7. index_analysis.analyze_index_full() -> 完整大盘分析
    |       +-- analyze_index()              -> 点位
    |       +-- analyze_probability()        -> 概率 (v3)
    |       +-- analyze_cycle()              -> 周期
    |       +-- analyze_value_score()        -> 评分
    |       +-- compute_market_trend_health  -> 趋势健康度
    |       +-- compute_market_fusion_decision -> 融合决策
    |       +-- analyze_cycle_probability    -> 周期概率 (v4)
    |       +-- analyze_probability_integrated -> 多因子概率 (v4)
    |       +-- compute_bottom_signal        -> 抄底就绪度 (v4)
    |       +-- macro_context 系列           -> 宏观环境 (v4)
    +-- 8. 缓存结果至 DB setting cached_index_analysis
    |
    v
返回 dashboard_refresh.html 模板片段
    +--- index_card.html     -> 大盘指数卡片
    +--- index_analysis.html -> 完整大盘分析仪表盘
```

---

## 版本变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-07-17 | v4.0 | 移除 sector_recommendation 板块推荐模块; 完善 v4 模块 (周期概率/多因子概率/抄底就绪度/宏观环境); 数据源全部迁移 csQAQ |
| 2026-07-14 | v3.5 | 新增市场趋势健康度 + 融合决策; 优化大盘引擎 |
| 2026-07-10 | v3.0 | 数据源从 SteamDT 迁移至 csQAQ |
