# CS-Market 单品分析引擎文档

> 最后更新: 2026-07-31 | 版本: v4.2

---

## 一、数据输入
| 输入 | 来源 | 说明 |
|---|---|---|
| 90日K线 (prices) | csQAQ Playwright 拦截 info/chart API (period=90, platform=2) | 每日收盘价数组，约80个数据点 |
| 日成交量 (volumes) | steamdt Playwright 拦截 K线API → 聚合日线 tx_count | 与 prices 等长 |
| 在售数量 (supply_hist) | csQAQ K线 num_data 字段 | 与 daily_bars 等长 |
| 总存世量 (volume_total) | csQAQ 详情页 goods_info.in_sale_count | 单品当前在售总量 |
| 订单簿 (order_book) | csQAQ 详情页 | spread_pct, bid_depth, ask_depth |
| 大盘指数 | DB market_index 表 + 实时采集 | index_value, change_7d, market_history |
| 物品元数据 | DB items 表 | rarity, source, discontinued_years, steam_name, good_id |

### 数据采集流程

`
用户点击分析
  → csQAQ search_good_id(name)       # 搜索物品 good_id
  → csQAQ fetch_item_detail(good_id)  # 获取详情+K线+在售数(platform=2 悠悠有品)
  → steamdt fetch_steamdt_volume(steam_name)  # 获取Steam真实成交量
  → merge_daily_volume(daily_bars, steamdt_vol) # 合并成交量到K线
  → run_item_analysis()              # 执行分析管线
`

注意事项:
- bar.date 必须为 YYYY-MM-DD 格式，否则 steamdt 成交量合并失效
- steam_name 从 csQAQ goods_info.market_hash_name 获取
- StatTrak™/纪念品自动过滤

---

## 二、十大分析模块
### 1. 估值定位 _analyze_position

判断当前价格在90日历史中的位置。
| 指标 | 说明 |
|---|---|
| 90日百分位 | price 高于历史价格的百分比 |
| Z-score | (price - mean) / std |
| 时间衰减百分位 | near 7d 3x weight, 7-30d 2x, 30d+ 1x |
| 估值斜率 | 14日百分位变化率 |
| MAD-Z-score | 基于中位数绝对偏差的稳健Z-score |

分档: <=15% 低估 / <=80% 合理 / <=95% 高估 / >95% 泡沫

### 2. 周期判定 _analyze_cycle

四阶段独立打分 + softmax 归一化：

| 阶段 | 触发条件 |
|---|---|
| 吸筹期 | 百分位低 + Z负 + MA金叉 + 供给收缩 |
| 拉升期 | MA7>MA30 + 百分位15-70% + 量价确认（放量上涨）|
| 出货期 | 百分位高 + Z正 + MA死叉 + 高位放量 |
| 洗盘期 | 百分位40-80% + Z-1~1 + MA乖离<5% |

每阶段输出: phase / 持续天数 / 下一阶段触发条件 / 建议操作

### 3. 流动性评分 score_liquidity

四维 0-100 评分:

| 维度 | 权重 | 计分规则 |
|---|---|---|
| 日成交量 | 40% | >=20->40, >=10->32, >=5->24, >=3->16, >=1->8 |
| 在售深度 | 25% | >=500->25, >=200->20, >=100->16, >=50->12, >=10->6 |
| 价格稳定性 | 25% | volat<1%->20, <2%->16, <4%->12, <7%->7 |
| 订单簿价差 | 10% | <1%->10, <3%->5, <7%->2, >=7%->-3 |

### 4. 涨跌概率预测 analyze_probability

基于均值回归 + 多特征修正：

- base_up = 50 - z*10, 限制15-85
- TH修正: TH_bias * 0.20
- 庄盘修正: whale_prob>30 减 (wp-30)*0.15
- 周期修正: 出货*0.90, 吸筹*1.10
- 大盘修正: >80*0.95, <20*1.05
- TH<30 再 -10%收敛

输出: 3/7/14日 上涨/震荡/下跌概率 + 波动率分类

### 5. 投资价值评分 compute_value_score

1-10评分: 百分位(40%) + Z-score(30%) + 流动性(15%) + 周期(15%)

修正: TH +-2.0, 融合决策修正, 庄盘上限2.0, 事件风险折价

S(>=8) / A(>=6.5) / B(>=4.5) / C(<4.5)

### 6. 庄盘识别 analyze_whale

四维 0-100, 阈值: strong>=25, extreme>=60:

| 维度 | 权重 | 说明 |
|---|---|---|
| 量价背离 | 40% | 价涨量缩 / 价跌量放 |
| 波动异常 | 25% | 30日波动率 > 2x历史均值 |
| 持仓锁定 | 20% | 供给持续收缩 + 价格稳定/上涨 |
| 价格异动 | 15% | 短期暴涨暴跌 + 价格虚高检测 |

庄盘类型: 低位吸筹锁仓 / 无量拉升诱多 / 高位放量出货

### 7. 趋势健康度 compute_trend_health (trend_health.py)

六维 0-100:

| 维度 | 权重 | 衡量内容 |
|---|---|---|
| 多头排列 | 19% | MA7/MA30/MA90 排列结构 |
| 持续性 | 24% | 连续N日站稳/跌破 MA7 |
| 陡度 | 24% | 7日线性回归斜率归一化 |
| 量价配合 | 18% | 涨放量/跌缩量 vs 背离 |
| 缺口 | 13% | MAD修正标准差检测极端波动 |
| 关键位 | 2% | 近期高低点突破/跌破检测 |

修正: 庄盘 + 周期 + 波动率, 最大单个修正-15

### 8. 融合决策 compute_fusion_decision (trend_health.py)

百分位三档(低估<=30% / 中性30-70% / 高估>70%) x 趋势健康三档 x 方向三档 → 操作指令

结构:
`
if 百分位 <= 30%:     # 低估区
    TH>=55 → 分批建仓
    TH>=35 → 筑底观察
    else   → 下跌中继观望
elif 百分位 <= 70%:   # 中性区
    TH>=55 → 短线持有
    TH>=35 → 震荡观望
    else   → 回调关注
    # 周期感知: 出货期降级, 吸筹期升级
else:                 # 高估区
    TH>=55 → 强势趋势持有 / 抱团风险分批止盈
    TH>=35 → 方向感知: 高位强势整理 / 横盘减仓 / 回调减仓
    else   → 方向感知: 趋势反转清仓 / 高位震荡减仓
`

| 保护 | 触发条件 |
|---|---|
| 极端保护 | pct>95% + z>2.5 → 强制清仓 |
| 大盘过滤 | 大盘出货期 → buy/hold 降级为 watch |

### 9. 估值宫格 compute_valuation_grid (valuation.py)

3行(百分位: 低估/合理/高估) x 4列(趋势强度: 强上涨TH>=75 / 弱反弹60-74 / 横盘40-59 / 下跌<40)

每个宫格: 操作建议 + 仓位建议


### 超跌买入例外 (P0)
当标准融合决策无法触发 buy 时，额外检查超跌反弹条件:
`
if pct <= 15% AND zscore <= -2.0:
    no_new_low2 = min(prices[-2:]) > min(prices[-3:])  # 最后2日不创新低
    chg3d = (prices[-1] - prices[-4]) / prices[-4] * 100
    if no_new_low2 AND chg3d > 0%:
        action = buy  # 超跌反弹-分批建仓
`
此规则位于 zone/action 矩阵之后、流动性/事件过滤器之前。

### 单品买入硬过滤 (P0, 2026-08-01)

融合决策输出 buy 后，`run_item_analysis` 追加三层数据验证过滤器（顺序：大盘环境 → 半山腰 → 7日聚类）：

| 过滤器 | 条件 | 输出 | 数据依据 |
|---|---|---|---|
| 大盘环境硬过滤 | 大盘TH<45 且 大盘30日跌幅<0 | 🟡 大盘走弱·观望 | 2026-07 单品信号 0/3 全负 |
| 情绪贪婪禁买 | sentiment≤30（贪婪） | 🟡 情绪贪婪·禁止追买 | 回测 30d 胜率 0% |
| 半山腰降级 | pct 25~40 且 sent<85（无恐慌共振） | 🟡 半山腰·观望 | 回测 14d 胜率仅 28% |
| 7日信号聚类 | 7 日内同品已触发 buy（snapshots.action） | 🟡 已在买点区·等待回调 | 格洛克拉美西斯 6/11~6/19 连续 9 天重复 |

触发均记录到 `deduction_sources`（market_weak_filter / greedy_no_buy / halfway_downgrade / buy_cluster_dedup），前端可追溯降级原因。

回测（2025-11-02 起, warmup=30）: 67 信号（含重复）→ 18 独立信号；14d 胜率 61%→72%（均+14.9%），30d 77%→65%（均+26.6%，剔除半山腰等负期望区）。


| 因子 | 说明 |
|---|---|
| 90日均价 | 历史均价 |
| 近7日均量 | 近期日均成交量 |
| 换手率 | 日成交量 / 总在售数 |
| MA30偏离率 | (price - ma30) / ma30 |
| 资金流斜率 | 价量趋势方向强度 |

---

## 三、买卖区间参考 price_zones

基于当前价格、波动率、趋势健康度动态计算：

- **买入区间**: 当前价 - 波动率×N倍, 叠加支撑位和趋势健康度修正
- **卖出区间**: 当前价 + 波动率×N倍, 叠加压力位和趋势健康度修正
- **止损参考**: 低于买入区间的极端下沿

波动率计算取 7日/30日/90日三周期加权, 趋势弱时扩大安全边际。

---

## 四、前端展示
| 页面 | 路径 | 说明 |
|---|---|---|
| 单品搜索 | /search | 输入名称直接分析，结果持久化 |
| 自选管理 | /watchlist | 自选列表+持仓管理，点击分析/报告 |
| 分析部分 | partials/analysis.html | 单品分析结果渲染，含分析时间戳 |
| 报告存档 | DB snapshots 表 | 历史分析结果，最新报告覆盖旧报告 |

---

## 五、v3.5 更新日志

1. **百分位阈值调整**: 20/70/90 → 15/80/95, 更符合CS饰品市场波动特性
2. **融合决策bug修复**: cycle-aware 代码缩进到中性区内部, else 正确绑定区域链
3. **新增分析时间戳**: 报告头部显示分析生成时间
4. **批量扫描持久化**: 批量扫描结果保存到 snapshots 表, 报告按钮可查看
5. **持仓建议模块**: _portfolio_advice() 根据成本/数量/现价生成个性化加仓减仓建议


---

## 六、v3.6 更新（品类差异化）

### 1. 交易摩擦
悠悠有品手续费 1%（config.FEE_RATE = 0.01），推荐语自动附带扣费提示。

### 2. 品类差异化阈值
config.CATEGORY_THRESHOLDS 配置独立阈值：
- 高波动品类（收藏品/胶囊）：入场更严格（百分位<=20%，Z<=-2.0）
- 低波动品类（手套/匕首）：可容忍稍高分位（百分位<=35%，Z<=-1.2）
- 未配置品类使用全局默认（百分位<=30%，Z<=-1.5）

## 十、实盘修正（v3.7）

### 1. 交易摩擦扣费
悠悠有品手续费 1%（config.FEE_RATE = 0.01），分析引擎推荐语已自动附带扣费提示。

### 2. 品类差异化阈值
不同品类波动率不同，config.CATEGORY_THRESHOLDS 配置独立阈值：
- 高波动品类（收藏品/胶囊）：入场更严格（百分位<=20%，Z<=-2.0）
- 低波动品类（手套/匕首）：可容忍稍高分位（百分位<=35%，Z<=-1.2）
- 未配置品类使用全局默认（百分位<=30%，Z<=-1.5）

### 3. MAD-Z 统一
全系统 Z-score 统一为 MAD-Z（中位数绝对偏差），替代传统标准差：
- 公式: (current - median) / (MAD * 1.4826)
- 优势: 对异常值更鲁棒，单日暴涨暴跌不会导致 Z 值剧烈失真
- 已统一: index_analysis.py（大盘）、item_analysis.py（单品）、trend_health.py（缺口检测）
- 移除: 独立的 mad_zscore_90d 字段（现主 zscore_90d 直接使用 MAD-Z）

### 4. 事件风险过滤（融合决策新增）
重大 V 社规则更新（炼金改版、纪念品可合成等）自动约束融合决策：
- 事件风险系数 < 0.85 时，buy/hold 信号自动降级为 watch
- 大盘和单品融合决策均已接入 event_risk_coefficient()
- 事件列表在 market_macro._SYSTEMIC_EVENTS 配置

### 5. 周期概率优化（cycle_probability 新增信号）
analyze_cycle_probability() 新增三个补充信号：

| 信号 | 条件 | 解决什么问题 |
|---|---|---|
| 磨底吸筹 | pct<=25% + 14日波动<5%（窄幅横盘） | 深度阴跌无金叉的磨底机会 |
| 无量抱团拉升 | pct 15-60% + ma7>ma30 + 14日波动<6% | 庄盘锁仓控盘上涨不被误判 |
| 慢速派发 | pct>65% + 14日波动<5%（平顶）+ 0.5<=Z<=1.0 | 高位横盘无量出货不漏检 |

### 6. 涨跌概率多因子增强
analyze_probability_integrated() 新增修正因子：
- 周期修正: accumulation x1.05, markup x1.10, distribution x0.85
- 事件折价: event_risk_coefficient() 乘入最终概率
- 移除: 旧的 bearish_score 双重计数（广度已扣一次，又用广度再扣一次）

## 七、情绪因子传导（v4.0）

单品引擎复用大盘情绪分 compute_sentiment_factor()（-0.6 ~ +0.6，恐惧=正/贪婪=负）：
- 周期置信度：_analyze_cycle phase_confidence += factor × (10/5)，±6 分
- 涨跌概率：analyze_probability base_up += factor × 8，±4.8%
- 融合决策：compute_fusion_decision ts += (sentiment_score-50)/50 × 3，±2.4 分
- 分层仓位：sentiment>=75 仓位分 +2.0；<=30 仓位分 -1.5

## 八、求购承接信号（v4.1）

### compute_bid_support(order_book) → 0-100
真实买盘意愿快照，仅辅助修正不开仓：
| 维度 | 分值 | 说明 |
|---|---|---|
| 断层宽度 | 0-35 | <=3% 承接强；>15% 流动性断层 |
| 断层收窄/扩张 | 0-30 | vs 30日均值：收窄加分、扩张扣分 |
| 求购价 7/30 日趋势 | 0-35 | bid_7d_chg×0.6 + bid_30d_chg×0.4 映射 |

融合修正（保守）：
- score<=25 且原 buy → 降级 🟡 求购承接弱·观望
- score>=75 且 watch + 低估区 → 标签「底部观察·承接增强」，仓位上限提至 8%

数据链路：拦截 csQAQ 页面原生「求购价」图表请求（platform=2），order_book 含
spread_pct / highest_buy / bid_7d_chg / bid_30d_chg / spread_avg / bid_count / depth。

## 九、市场联动（v4.2）

- run_item_analysis 接收 market_cycle / market_th_score / market_zscore
- 大盘 distribution 周期：buy/hold 信号强制降级为观望
- 单品 Z-gate 按周期差异化：accumulation -0.5 / consolidation -1.0 / distribution -1.5 / markup 0
- 连续买入抑制：3 日价格变动 <1.5% 时不重复触发 buy（3 日冷却）
- 分层仓位梯度（综合 value.score + 情绪）：>=8.5→30% / 7.0~8.5→20% / 5.0~7.0→12% / 3.0~5.0→5% / <3.0→0%
- 风险等级 A/B/C/D：TH + Z-score + 流动性 + 庄盘四维累加

## 回测记录

- **P0 过滤后（2026-08-01）**: 18 独立信号, 14d 胜率 72% / 均+14.9%, 30d 胜率 65% / 均+26.6%
- 旧版（含重复）: 67 信号, 14d 61% / 均+15.7%, 30d 77% / 均+29.3%

| 文件 | 说明 |
|---|---|
| run_item_backtest.py | 单品离线回放, warmup=30: 67信号, 14d胜率60.9%/均+15.7%, 30d胜率77%/均+29.3% (2026-05-21~07-31) |
| data/item_backtest_latest.json | 单品回测最新明细（信号+分层字段） |

### 补仓建议阈值（2026-07-31, 数据验证）

浮亏持仓补仓/止损分层（`batch_scan._portfolio_advice`，sentiment_score 由大盘贪婪指数实时计算）：

- 市场贪婪 sent≤30 → 禁止补仓（回测 30d 胜率 0%）
- pct 25~40 半山腰 → 暂缓补仓（14d 胜率 28%）
- pct≤25 + 单品TH≥40 + z≤-0.5 + 大盘TH≥45 → 可分批补仓（14d 胜率 75%）
- pct≤25 但大盘TH<45 → 暂缓，等大盘共振
- 单品TH<30 → 止损优先
| references/backtest_results.json | 大盘 2025-11-02 ~ 2026-07-21, 232条 |
| pipeline/config.py THRESHOLDS | TH_STRONG=55, TH_NEUTRAL=35 |
