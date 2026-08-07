# CS-Market 大盘分析引擎文档

> 版本: v5.2 | 更新: 2026-08-02
> ⚠️ **本文档已过时**：大盘决策已并入统一大脑 K-2，TH 阈值语义已三区化（恐慌<35 黄金坑 / 35-54 摩擦带 / ≥55 趋势确认），
> 当前口径以 `engine-unified.md` + `th_calibration.md` 为准，本文保留作 v5.2 历史参考。

---

## 数据源
| 数据 | 来源 | 说明 |
|---|---|---|
| 2026-08-02 | v5.2 | P1-2 牛熊动态 TH 阈值：牛市/震荡 TH_NEUTRAL 35→30 + 新增牛市深调买点(bull+TH>=30+drop21<=-12%)；2025牛市段 cluster=1 3→6 信号 14d/30d 全胜，熊市段无回归 |
| 大盘K线 (prices) | csQAQ API GET /api/v1/sub/kline?id=1&type=90day | 90日每日收盘价 |
| 当前指数值 | csQAQ API GET /api/v1/current_data?type=init | 从 main_index.market_index 提取 |
| 市场情绪(数值) | csQAQ /current_data?type=volume → greedy[] | 60日贪婪指数时间序列(65~150连续值) |
| 市场情绪(标签) | csQAQ同上 → greedy_status | level=low/medium/high 三档(当前代码不使用) |
| 板块资金流向 | csQAQ API GET /api/v1/current_data?type=init | chg_type_data 各板块涨跌幅及趋势 |
| 宏观数据 | csQAQ API 多接口聚合 | K线成交额 + 在线人数 + 充值卡溢价 |

大盘引擎完全基于 csQAQ HTTP API，不需要 Playwright。

**注意**: 情绪数据源为 greedy[] 数值序列(65-150连续值)，非 greedy_status.level 三档标签。compute_sentiment_score() 将其映射为0-100连续逆向分数。

---

## 模块架构总览

| 序号 | 模块 | 函数 | 所在文件 |
|---|---|---|---|
| 1 | 点位智能判断 | analyze_index() | index_analysis.py |
| 2 | 大盘涨跌概率 | analyze_probability() | index_analysis.py |
| 3 | 大盘周期概率 | analyze_cycle_probability() | index_analysis.py |
| 4 | 投资性价比评分 | analyze_value_score() | index_analysis.py |
| 5 | 多因子涨跌概率 | analyze_probability_integrated() | index_analysis.py |
| 6 | 大盘趋势健康度 | compute_market_trend_health() | market_th.py |
| 7 | 大盘融合决策 | compute_market_fusion_decision() | market_th.py |
| 8 | 抄底就绪度 | compute_bottom_signal() | market_macro.py |
| 9 | 宏观环境 | market_macro.py 系列函数 | market_macro.py |
| 10 | 大盘-板块联动 | build_market_context() | market_context.py |

---

## 情绪因子全链路传导 (v4.4 新增)

### compute_sentiment_score() → 0-100 连续逆向分数
将 csQAQ greedy 数值序列(65~150)映射为连续情绪分数，**恐惧=高分，贪婪=低分**。

| greedy值 | sentiment_score | 标签 |
|---|---|---|
| <60 | 95 | 极度恐惧 |
| 60-70 | 90 | 极度恐惧 |
| 70-80 | 80 | 恐惧 |
| 80-90 | 70 | 恐惧 |
| 90-100 | 60 | 恐惧偏多 |
| 100-110 | 50 | 中性 |
| 110-120 | 35 | 贪婪 |
| 120-130 | 20 | 贪婪 |
| 130-150 | 10 | 高度贪婪 |
| >=150 | 5 | 极度贪婪 |

### compute_sentiment_factor() → -0.6 ~ +0.6 连续修正因子
| sentiment_score | factor | 含义 |
|---|---|---|
| >=85 | +0.6 | 极度恐惧→强逆向买入信号 |
| 70-85 | +0.3 | 恐惧→轻度逆向买入 |
| 50-70 | 0.0 | 中性→无修正 |
| 30-50 | -0.3 | 贪婪→轻度逆向卖出 |
| <=15 | -0.6 | 极度贪婪→强逆向卖出 |

### 六层传导链路

| 层级 | 模块 | 修正方式 | 最大影响 |
|---|---|---|---|
| ① 大盘涨跌概率 | index_analysis: analyze_probability | s_mod 乘数: 恐惧×1.15 / 贪婪×0.85 | ±15% |
| ② 大盘周期概率 | index_analysis: analyze_cycle_probability | 间接传导(通过 breadth+sentiment 共同影响) | 中等 |
| ③ 抄底就绪度 | market_macro: compute_bottom_signal | sentiment_contrib 占20分/总分100 | ±20分 |
| ④ 单品涨跌概率 | item_analysis: analyze_probability | base_up += factor × 8 | ±4.8% |
| ⑤ 单品周期置信度 | item_analysis: _analyze_cycle | phase_confidence += factor × (10/5) | ±6分 |
| ⑥ 融合仓位决策 | trend_health: compute_fusion_decision | ts += (sentiment-50)/50 × 3 | ±2.4分 |

**数据验证**: (2025-11-02 ~ 2026-07-23, 264点)
- 系数3策略 buy胜率 30%, 情绪改判胜率 100%
- 系数5策略(旧) buy胜率 28%, 情绪改判胜率 33%
- 结论: 系数3严格优于系数5, 保留 avoid→watch 升级, 消除 watch→buy 误升级

---


## V7 智能熊市过滤器 (2026-07-27 新增)
在熊市环境中分化不同性质的短期反弹，避免 V 型反弹假信号。

### microTH（微型趋势健康度）
在 compute_micro_th() 中计算，专用于短期拐点识别：
- **普通反弹**：7日跌幅 10-20% + 近2日止跌 + 价格接近低点
- **恐慌抛售**（capitulation）：30日跌幅 >20% + 价格接近90日低点 + 恐慌下跌，**得分额外 +15**

### 熊市覆盖规则
当 is_bear=True（大盘处于下跌/出货周期）时：
**熊市持久性判定（v4.7）**：`is_bear = ma30 < ma90 and 现价 < ma90`（原为 `ma30 < ma90*0.98`）。
V 型反弹后 MA30 不能立即翻牛，必须完全站上 MA90 才出熊，避免反弹末端假翻牛导致 rally_decay 失效。
数据验证（2025-11-02 起）：修复后 37→14 个 buy 信号，14d 胜率 76%→86%，均收益 8.7%→15.0%，
6 月密集假信号（06-03~06-07）全部过滤。
1. **恐慌抛售可买入**：只有 cap_triggered 的 microTH 才能触发 buy，普通 V 型反弹 microTH 被拦截
2. **反弹动能衰减**（rally_decay）：上涨波形出现降低高点、涨幅收窄时，watch/buy 强制降级为 reduce
3. **熊市安全网**：大盘下跌 + TH<65 + 趋势下降，基础引擎 buy 降级为 hold

### 阈值调整
熊市环境下阈值自动降低 5 分，加速信号响应：
| 原阈值 | 熊市阈值 | 作用 |
|---|---|---|
| avoid→watch: 55 | 50 | 超跌更容易触发观望 |
| watch→buy: 70 | 65 | 恐慌抛售更容易触发买入 |

### 执行流程
1. analyze_index_full() 判断 is_bear/cap_triggered/rally_decay
2. compute_market_fusion_decision() 接收这些状态
3. 在融合决策中依次执行 override 规则（均为 if 非 elif，可叠加）
4. 最终 action 由最严格的规则决定

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

### 2. 大盘涨跌概率 analyze_probability

基于 Z-score 均值回归模型:
- Z值偏离越大，回归概率越高
- 波动率修正: 高波环境下调信心度
- 情绪修正: 恐惧时上调概率(×1.15)，贪婪时下调(×0.85)
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
| risk_score | 0-2.5 | 风险评估 (基于Z-score和波动率) |
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
| 趋势持续性 | 24% | 连续N日站稳/跌破MA7 |
| 趋势陡度 | 24% | 7日线性回归斜率归一化 |
| 均线结构 | 19% | MA7/MA30/MA90 排列状态 |
| 量价配合 | 18% | 涨放量/跌缩量 vs 背离 |
| 异常缺口 | 15% | MAD修正标准差检测极端波动 |

### 8. 大盘融合决策 compute_market_fusion_decision (market_th.py)

百分位 + TH + 周期 + 方向 + 情绪 → 综合操作指令。

#### 情绪修正
融合决策接收 sentiment_score 参数, 在分区判定前对 TH 做微调:
```
sentiment_adjustment = (sentiment_score - 50) / 50 * 3
ts = ts + sentiment_adjustment
```
- 恐惧80分: ts +1.8 (帮助 avoid→watch)
- 恐惧90分: ts +2.4 (帮助 avoid→watch, 但不足以 watch→buy)
- 贪婪20分: ts -1.8 (谨慎压制)

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
在低估区(百分位≤30%)内, 若百分位已从底部回升但尚未脱离低估区, 判定为反弹末期, 自动降级买入信号:

| 原信号 | 反弹末期降级后 |
|---|---|
| TH_STRONG → 分批建仓 | TH_STRONG → 反弹末期·轻仓试探(仓位上限15%) |
| TH_NEUTRAL → 筑底观察 | TH_NEUTRAL → 反弹尾声·观望(仓位上限10%) |

触发条件: 百分位≤30 + 百分位趋势上升 + Z-score > -1.2 且 < 0.0

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
| 情绪面 | compute_sentiment_score() | 贪婪/恐惧 0-100 连续逆向分 |
| 情绪因子 | compute_sentiment_factor() | -0.6~+0.6 连续修正系数(恐惧正、贪婪负) |
| 贪婪指数 | get_greedy_current() | 当前原始贪婪指数值(65~150) |
| 在线人数 | get_online_current() | Steam当前在线人数 |
| 在线趋势 | compute_online_trend_score() | 在线人数趋势评分 |
| 充值卡溢价 | compute_card_trend_score() | 充值卡价格趋势评分 |

### 11. 大盘-板块联动 market_context.py

计算大盘与板块、大盘与单品的相关性，为融合决策提供上下文。

---

## 数据流架构 (刷新链路)

```
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
```

---

### 大盘回测记录
| 文件 | 说明 |
|---|---|
| run_backtest.py | 回测脚本：低层引擎函数逐日回放，`python run_backtest.py [--start 2025-11-02]`，含熊市持久性 is_bear 直接计算 + rally_decay 与真实引擎对齐 |
| data/item_backtest_full_2025.json | K-2 引擎 458 信号回放（2026-08-06；backtest_results.json 已移除） |

**最新回测（v4.9，2025-11-02 ~ 2026-07-31）**：6 个 buy 信号，14d 胜率 100%（均 +11.6%），30d 胜率 50%（均 +7.4%）；捕捉 2月小牛买点（2/21、2/24、2/27），拦截 6 月假底。
主要盈利波段：2025-10 V底（+20~79%）、2025-11 修复反弹（+13~17%）、2026-05 V底（+22~30%）。

## 参数拟合与更新频率

当前参数 (2026-07-23 通过回测确定):
- TH_STRONG = 55
- TH_NEUTRAL = 35
- 情绪修正系数 = 3 (数据验证: 优于系数5, buy胜率30% vs 28%)
- 超跌买入: pct<=15% + Z<=-2.0 + 跌速衰减(no_new_low2 + chg3d>0%)

### 拟合建议
不需要定期拟合。触发时重新验证:
1. **积累完整牛熊循环** (~260天新数据)
2. **buy信号连续2月14d胜率跌破70%**
3. **每月**: 快速验证, 14d>=80%、30d>=55%则不动

## 抛压衰竭信号 (v4.6 新增)

### compute_selling_pressure_exhaustion() (index_analysis.py)
熊市 V 型底部的先行信号：**卖方力量枯竭 + 止跌企稳**，用数据验证筛出下跌中继误报。

三个子信号（0-100 累加）：
| 子信号 | 分值 | 说明 |
|---|---|---|
| 3日跌速衰减 | 0-40 | 近3日跌幅 < 前段3日跌幅一半 / 转涨 |
| 3日无新低 | 0-30 | 恐慌抛售枯竭 |
| 高点抬高/企稳 | 0-30 | 止跌结构 |

**硬性上下文门控（关键，防下跌中继误报）**：20 日跌幅 < -7% 才允许触发观察级信号（≥70）；
20 日跌幅 < -12% 为深度恐慌（不限分）。跌幅不足直接封顶 55 分，杜绝「下跌中继反弹」假信号。

回测（2025-11-02 起，中性情绪=50，数据窗口 market_index 表）：
- 触发 8 天 / 4 个独立波段：2026-01-26、05-17、05-28、06-02
- 14d 胜率 50%（均 +2.48%），**30d 胜率 100%（均 +6.13%）**
- 有效滤除 4/26、5/01、6/23 等中继误报（30d 收益 -18%~-26%）

### 融合决策接入 (market_th.py compute_market_fusion_decision)
新增参数 `selling_pressure_score=50`：
- score ≥ 70 且 90d 百分位 ≤ 20：avoid/sell/reduce → **🟡 抛压衰竭·底部观察**（仓位上限 10%）
- score ≥ 85 且 百分位 ≤ 15 且 microTH ≥ 55：→ **🟢 抛压衰竭·分批建仓**（仓位上限 15%）

前端：大盘页「📉 抛压衰竭」卡片。

## 单品求购承接信号 (v4.6 新增)

### 数据链路修复 (collector_csqaq.py)
原 `page.request.post(info/chart)` 直连被 ApiToken IP 白名单拦截（401），导致 order_book 恒为空、
价差深度 0/20。改为**拦截页面原生「求购价」图表请求**（出售价下拉 → 求购价，走浏览器会话 cookie）：
- 路由强制 period=90、platform=2（悠悠有品，与卖价同平台），保留 key
- 抓取完整 buy_price 序列 → 聚合日频求购价

order_book 字段扩展：`spread_pct / highest_buy / bid_7d_chg / bid_30d_chg / spread_avg / spread_7d_avg / bid_count / depth`

### compute_bid_support() (item_analysis.py)
求购承接信号 0-100（真实买盘意愿快照，仅辅助修正不开仓）：
- 断层宽度（0-35）：≤3% 承接强；>15% 流动性断层
- 断层收窄/扩张 vs 30日均值（0-30）
- 求购价 7/30 日趋势（0-35）

融合修正（保守）：
- score ≤ 25 且原 buy → 降级 **🟡 求购承接弱·观望**
- score ≥ 75 且 watch + 低估区 → 标签「底部观察·承接增强」，仓位上限提至 8%

前端：单品报告「🛒 求购承接」卡片；价差深度恢复正常取值。


## 牛熊动态 TH 阈值 + 牛市深调买点 (P1-2, 2026-08-02)

### 背景
固定 TH_STRONG=55 / TH_NEUTRAL=35 在牛市回调时门槛过高：2025 牛市段（01~10）仅 3 个买点，
漏掉 10-24 五合一 V 型底（th=38、drop21=-58%、14d +79%）。

### 规则
1. 牛市/震荡（regime=bull/sideways）：TH_NEUTRAL 35→30，fair 区「回调确认·分批介入」门槛降低，
   牛市回调买点提前触发；熊市维持 35（保守防假信号）。
2. 新增「牛市深调·分批介入」路径：regime=bull + TH>=30 + z<=0.5 + 21日跌幅<=-12% → buy（仓位 20%）。
   仅 bull 放行（sideways 曾误放行 2026-01-24 熊市横盘反抽，14d -1.95%，已收紧排除）。

### 数据验证（2026-08-02）
- 牛市段 2025-01-01~10-31（cluster=1）：3→6 信号，14d/30d 均 100%（14d 均 +20.4%，30d 均 +25.5%）
  - 新增：2025-05-15 回调确认 +10.0%、2025-10-24 牛市深调 +79.0%（14d）
- 熊市段 2025-11-02 起（cluster=3）：6 信号不变，14d 胜率 100%，无回归
- 组合回测（熊市窗口，SL-20/TP20/30d）：+7.52% / 年化 14.06%，与 P0 完全一致

### 实现
- `compute_market_fusion_decision()`：新增 th_neutral_eff（bull/sideways 时 30）
- `run_backtest.py`：回测传入 market_regime（与线上 analyze_index_full 口径一致）
## 版本变更记录


| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-07-31 | v4.7 | 熊市持久性修复：is_bear 需 MA30 完全站上 MA90 才出熊；回测 37→14 信号、14d 胜率 86%；回测脚本与真实引擎对齐（rally_decay/is_bear/cap_triggered/selling_pressure） |
| 2026-07-30 | v4.6 | 新增抛压衰竭信号 compute_selling_pressure_exhaustion（3日跌速衰减+3日无新低+高点抬高，20日跌幅门控）；融合决策接入 selling_pressure_score（≥70 底部观察 / ≥85 分批建仓）；新增市场状态判定 compute_market_regime（MA30/MA90 比率+MA90 趋势确认）；microTH 阈值表按波动率自适应 |
| 2026-08-01 | v4.9 | V5.1温和反弹放行: 建仓区域放行条件扩展为 30日深跌≤-20% OR 14日急跌≤-10% OR 21日涨幅0~8%; 数据验证(熊市14d视角): buy 6次 14d胜率100% 均+11.6%, 放行2月小牛六连发(14d全胜), 仍拦截6/15/6/18/6/30假底 |
| 2026-08-01 | v4.8 | 建仓区域假底部过滤(V5): 「建仓区域」buy需30日深跌≤-20%或14日急跌≤-10%放行, 否则降级假底部·观望; 回测buy 6次全胜(14d/30d 100%, 均+29.7%), 拦截2月六连发+6月假底 |
| 2026-07-28 | v4.5 | 新增 V7 智能熊市过滤器（microTH + 恐慌抛售识别 + 反弹衰减拦截 + 熊市安全网）；移除非必要武器类型；新增发现高分品缓存 |
| 2026-07-23 | v4.4 | 新增情绪因子全链路六层传导(compute_sentiment_factor); 情绪修正系数5→3(数据验证); 更新情绪数据源说明(greedy数值序列替代greedy_status三档) |
| 2026-07-21 | v4.3 | 新增迟滞带防抖(方向A)+反弹末期买入降级(方向B)；更新大盘融合决策文档 |
| 2026-07-19 | v4.1 | 修复市场情绪检测; greedy_status.label(韩文) → level(low/medium/high); mood改为中文显示(恐惧/中性/贪婪) |
| 2026-07-17 | v4.0 | 完善v4模块; 数据源全部迁移csQAQ |
| 2026-07-14 | v3.5 | 新增市场趋势健康度+融合决策 |
| 2026-07-10 | v3.0 | 数据源从 SteamDT 迁移至 csQAQ |
