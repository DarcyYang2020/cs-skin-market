# CS-Market 大盘分析引擎文档

> 版本: v4.2 | 更新: 2026-07-21

---

## 数据源
| 数据 | 来源 | 说明 |
|---|---|---|
| 大盘K线 (prices) | csQAQ API GET /api/v1/sub/kline?id=1&type=90day | 90日每日收盘价 |
| 当前指数值 | csQAQ API GET /api/v1/current_data?type=init | 从 main_index.market_index 提取 |
| 市场情绪 | csQAQ API greedy_status.level | low=恐惧, medium=中性, high=贪婪 |
| 板块资金流向 | csQAQ API GET /api/v1/current_data?type=init | chg_type_data 各板块涨跌幅及趋势 |
| 宏观数据 | csQAQ API 多接口聚合 | K线成交额 + 在线人数 + 充值卡溢价 |

大盘引擎完全基于 csQAQ HTTP API，不需要 Playwright。
---

## 模块架构总览

| 序号 | 模块 | 函数 | 所在文件 |
|---|---|---|---|
| 1 | 点位智能判断 | analyze_index() | index_analysis.py |
| 2 | 涨跌概率预测 | analyze_probability() | index_analysis.py |
| 3 | 周期阶段判定 | analyze_cycle_probability() | index_analysis.py |
| 4 | 投资性价比评分 | analyze_value_score() | index_analysis.py |
| 5 | 周期概率分布 | analyze_cycle_probability() | index_analysis.py |
| 6 | 多因子涨跌概率 | analyze_probability_integrated() | index_analysis.py |
| 7 | 大盘趋势健康度 | compute_market_trend_health() | market_th.py |
| 8 | 大盘融合决策 | compute_market_fusion_decision() | market_th.py |
| 9 | 抄底就绪度 | compute_bottom_signal() | market_macro.py |
| 10 | 宏观环境 | market_macro.py 系列函数 | market_macro.py |
| 11 | 大盘-板块联动 | market_context.py | market_context.py |

---

## 各模块详细说明
### 1. 点位智能判断 analyze_index

| 输出字段 | 含义 |
|---|---|
| position.percentile_90d | 90日价格百分位 (0-100%) |
| position.zscore_90d | MAD-Z-score，基于中位数绝对偏差的稳健Z-score |
| position.position_label | 低估/合理/高估/泡沫标签 |
| position.strategy_zone | entry/exit/hold 三区 |
| position.support_levels | 支撑位列表(近期低点+均线) |
| position.resistance_levels | 压力位列表(近期高点+均线) |

百分位策略阈值: 入场 <=30% / 止盈 >=65% / 泡沫 >=90%

### 2. 涨跌概率预测 analyze_probability

基于 Z-score 均值回归模型:
- Z值偏离越大，回归概率越高
- 波动率修正: 高波环境下调信心度
- 输出: 3/7/30日 上涨概率 + 波动率状态(calm/normal/volatile)

### 3. 周期阶段判定 analyze_cycle

基于 MA7/MA30/MA90 均线系统 + 量价判断:

| 阶段 | 判定规则 |
|---|---|
| 吸筹期 | MA7上穿MA30 + 低位 + MA90下方 |
| 洗盘期 | 均线缠绕 + 中低位 |
| 拉升期 | MA7>MA30>MA90 (多头排列) + 量能配合 |
| 出货期 | MA7下穿MA30 + 高位 + 放量滞涨 |

输出: 阶段标签 + 策略描述 + 置信度

### 4. 投资性价比评分 analyze_value_score

综合位置 + 风险 + 周期 + 情绪 四维打分 (1-10):

| 子项 | 分值范围 | 衡量内容 |
|---|---|---|
| entry_proximity | 0-3 | 入场接近度 |
| risk_score | 0-2.5 | 风险评估 (基于 Z-score和波动率) |
| cycle_score | 0-2.5 | 周期阶段得分 |
| sentiment_score | 0-2.5 | 情绪面得分(逆向: 恐惧=高分) |

### 5. 周期概率分布 analyze_cycle_probability

与单品周期判定类似的四阶段概率分布 + softmax，提供更细粒度的周期视图。

### 6. 多因子涨跌概率 analyze_probability_integrated

综合百分位 + 周期 + 市场广度 + 贪婪指数 的多因子概率预测。

### 7. 大盘趋势健康度 compute_market_trend_health (market_th.py)

多维量化大盘趋势健康度 (0-100):

| 维度 | 权重 | 衡量内容 |
|---|---|---|
| 趋势持续性 | 24% | 连续 N 日站稳/跌破 MA7 |
| 趋势陡度 | 24% | 7日线性回归斜率归一化 |
| 均线结构 | 19% | MA7/MA30/MA90 排列状态 |
| 量价配合 | 18% | 涨放量/跌缩量 vs 背离 |
| 异常缺口 | 15% | MAD修正标准差检测极端波动 |

### 8. 大盘融合决策 compute_market_fusion_decision (market_th.py)

百分位 + TH + 周期 + 方向 → 综合操作指令，含极端保护和周期方向感知。

与单品融合决策逻辑一致，但参数适配大盘特性:
- 百分位三档: <=30% 低估 / 30-70% 中性 / >70% 高估
- 趋势健康三档: strong(>=55) / neutral(>=35) / weak
- 方向三档: up / flat / down

#### 方向A: 迟滞带防抖 (Hysteresis Band)
在百分位阈值边界附近引入缓冲区，防止信号频繁翻转:

| 边界 | 正常阈值 | 迟滞区域 | 判定规则 |
|---|---|---|---|
| 低估→合理(上行) | 30% | 28-35% | 趋势下降时保持低估区 |
| 合理→低估(下行) | 30% | 25-32% | 趋势上升时保持在合理区 |
| 合理→高估(上行) | 70% | 65-72% | 趋势上升时提前进入高估区 |
| 高估→合理(下行) | 70% | 68-75% | 趋势下降时提前回到合理区 |

百分位趋势由近7日百分位变动判断: 变动>+3%为rising, >-3%为falling, 否则flat。
hysteresis_applied 标记本次判定是否触发了迟滞修正。

#### 方向B: 反弹末期买入降级
在低估区(百分位≤30%)内，若百分位已从底部回升但尚未脱离低估区，判定为反弹末期，自动降级买入信号:

| 原信号 | 反弹末期降级后 |
|---|---|
| TH_STRONG → 分批建仓 | TH_STRONG → 反弹末期·轻仓试探(仓位上限15%) |
| TH_NEUTRAL → 筑底观察 | TH_NEUTRAL → 反弹尾声·观望(仓位上限10%) |

触发条件: 百分位≤30 + 百分位趋势上升 + Z-score > -1.2 且 < 0.0 (已从深度超跌恢复但尚未过热)

### 9. 抄底就绪度 compute_bottom_signal (market_macro.py)

五维 0-100, 评估当前是否具备抄底条件:

| 维度 | 权重 | 说明 |
|---|---|---|
| 价格百分位 | 25% | 位置越低分越高 |
| Z-score | 20% | 偏离越极端分越高 |
| 市场广度 | 20% | 广度恐惧程度 |
| 情绪冰点 | 20% | 贪婪指数恐惧程度 |
| 跌速衰减 | 15% | 下跌速度衰减程度 |

分级: >=80 强烈抄底 / 60-79 可轻仓试探 / 40-59 中性偏多 / <40 不适合抄底

### 10. 宏观环境 market_macro.py

| 指标 | 函数 | 含义 |
|---|---|---|
| 市场广度 | compute_breadth_score(7/90) | 近N日板块涨跌占比 |
| 情绪面 | compute_sentiment_score() | 贪婪/恐惧综合评分 |
| 贪婪指数 | get_greedy_current() | 当前贪婪指数值(基于 greedy_status.level) |
| 在线人数 | get_online_current() | Steam当前在线人数 |
| 在线趋势 | compute_online_trend_score() | 在线人数趋势评分 |
| 充值卡溢价 | compute_card_trend_score() | 充值卡价格趋势评分 |

### 11. 大盘-板块联动 market_context.py

计算大盘与板块、大盘与单品的相关性，为融合决策提供上下文。

---

## 数据流架构 (刷新链路)

`
用户点击刷新 / 自动刷新
    |
    +-- 1. collector.fetch_market_index()   -> 当前指数值 + 市场情绪
    +-- 2. collector.fetch_index_kline()    -> 90日K线数据
    +-- 3. collector.fetch_sector_flow()    -> 板块资金流向
    +-- 4. db.save_market_index()           -> 保存当前指数到DB
    +-- 5. db 批量保存K线数据
    +-- 6. db 缓存板块JSON
    +-- 7. index_analysis.analyze_index_full() -> 完整大盘分析
    +-- 8. 缓存结果到 cached_index_analysis
    |
    v
返回 dashboard_refresh.html 模板片段
`

---


### 大盘回测记录
| 文件 | 说明 |
|---|---|
| references/backtest_results.json | 2025-11-02 ~ 2026-07-21 逐日信号记录 (232条) |

## 参数拟合与更新频率

当前参数 (2026-07-21 通过回测确定):
- TH_STRONG = 55 (原60)
- TH_NEUTRAL = 35 (原40)
- 超跌买入: pct<=15% + Z<=-2.0 + 跌速衰减(no_new_low2 + chg3d>0%)

### 拟合建议
不需要定期拟合。触发时重新验证:
1. **积累完整牛熊循环** (~260天新数据)
2. **buy信号连续2月14d胜率跌破70%**
3. **每月**: 快速验证, 14d>=80%、30d>=55%则不动

## 版本变更记录

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-07-21 | v4.3 | 新增迟滞带防抖(方向A)+反弹末期买入降级(方向B)；更新大盘融合决策文档 |
| 2026-07-19 | v4.1 | 修复市场情绪检测; greedy_status.label(韩文) → level(low/medium/high); mood改为中文显示(恐惧/中性/贪婪) |
| 2026-07-17 | v4.0 | 完善v4模块; 数据源全部迁移csQAQ |
| 2026-07-14 | v3.5 | 新增市场趋势健康度+融合决策 |
| 2026-07-10 | v3.0 | 数据源从 SteamDT 迁移至 csQAQ |
