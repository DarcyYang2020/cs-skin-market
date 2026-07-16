# CS-Market 大盘分析引擎文档

> 版本: v1.0 | 更新: 2026-07-16

---

## 一、数据输入

| 输入 | 来源 | 说明 |
|---|---|---|
| 大盘指数K线 (prices) | csQAQ API `/api/v1/sub/kline?id=1&type=1day` | 日线收盘价数组，约900+数据点（2023年起） |
| 大盘当前值 | csQAQ API `/api/v1/current_data?type=init` | 从 `sub_index_data` 提取饰品综合指数 |
| 板块资金流向 | csQAQ API `/api/v1/current_data?type=init` | `chg_type_data` 各板块涨跌幅和资金净额 |

当前无大盘成交量数据（csQAQ指数K线仅返回日期+收盘价），量价配合维度暂不可用。

---

## 二、分析模块

### 1. 大盘点位智能判断 `analyze_index`

**文件**: `pipeline/index_analysis.py`

基于 `analyze_index()`（和单品共用算法），输出：

| 模块 | 功能 |
|---|---|
| PositionIntel | 90日百分位 + Z-score + 估值档位 + 策略区域 |
| ProbPrediction | 3/7/30日涨跌概率 + 预期收益 |
| CycleAnalysis | 四阶段周期判定（吸筹/洗盘/拉升/出货） |
| ValueScore | 1-10投资性价比评分 |

**核心算法**：
- 百分位 = 低于当前价格的样本数 / 总样本数 × 100
- Z-score = (当前值 - 均值) / 标准差
- 策略区域：entry(≤30%分位 + Z≤-1.5) / exit(≥65%分位 或 Z≥+2.0)
- 周期判定：低分位+负Z→吸筹 / 高分位+高Z→出货 / 中间→洗盘/拉升

---

### 2. 大盘趋势健康度 `compute_market_trend_health`

**文件**: `pipeline/market_th.py`

**与单品的差异**：
- 复用 `trend_health.compute_trend_health()` 六维度评分核心
- 移除单品专属修正（庄盘概率、单品流动性折价）——大盘不需要
- 新增三大宏观修正：

| 修正因子 | 触发条件 | 折价 |
|---|---|---|
| 事件风险折价 | 全市场重大利空（炼金改版等） | ×0.7~0.9 |
| 量价背离折价 | 无量拉升 | ×0.8 |
| 泡沫广度折价 | 超50%板块处于高估区间 | ×0.85 |

**输出**: `MarketTrendHealth` 数据类

| 字段 | 类型 | 说明 |
|---|---|---|
| raw_score | int | 原始六维度加权分 (0-100) |
| score | int | 修正后分数 (0-100) |
| level | str | 强势/中性偏强/中性无序/弱势 |
| direction | str | up/flat/down |
| persistence_score | int | 趋势持续性 (0-24) |
| steepness_score | int | 趋势陡度 (0-24) |
| structure_score | int | 均线结构 MA7/MA30/MA90 (0-19) |
| volume_score | int | 量价配合 (0-18) |
| anomaly_score | int | 异常缺口 (0-15) |
| key_level_score | int | 支撑压力验证 (0-10) |
| deduction_sources | list | 扣分来源列表 |
| volume_divergence | bool | 是否存在量价背离 |

**方向封顶规则**：
- 下跌趋势(down)：上限 45 分
- 走平(flat)：上限 65 分

---

### 3. 大盘融合决策 `compute_market_fusion_decision`

**文件**: `pipeline/market_th.py`

**核心公式**: 百分位(在哪) × 趋势健康度(往哪走) = 操作决策

#### 三区决策矩阵

##### 低估区（百分位 0-30%）

| 趋势健康分 | 操作 | 全局仓位上限 |
|---|---|---|
| ≥ 60 | 🟢 建仓区域 | 30% |
| 40-59 | 🟡 筑底观察 | 15% |
| < 40 | 🔴 下跌中继·暂不参与 | 5% |

##### 合理区间（30-70%）

| 趋势健康分 | 操作 | 全局仓位上限 |
|---|---|---|
| ≥ 70 | 🟢 健康持有 | 25% |
| 50-69 | 🟡 震荡观望 | 15% |
| < 50 | 🟡 回调关注 | 10% |

##### 高估区（70-100%）

| 趋势健康分 | 操作 | 全局仓位上限 |
|---|---|---|
| 极端泡沫(≥95% + Z≥2.5) | 🔴 极端泡沫·清仓 | 0% |
| ≥ 70 | 🟠 抱团行情·分批止盈 | 10% |
| 40-69 | 🟠 高位横盘·减仓 | 5% |
| < 40 | 🔴 趋势反转·清仓 | 0% |

**输出**: `MarketFusionDecision` 数据类

| 字段 | 说明 |
|---|---|
| percentile_90d | 90日百分位 |
| raw_th_score | 原始趋势健康分 |
| corrected_th_score | 修正后趋势健康分 |
| zone / zone_label | 估值区间 |
| action / action_label | 融合决策操作标签 |
| action_detail | 操作详细描述 |
| global_position_limit | 全局仓位上限 (0.0-1.0) |

---

### 4. 全局宏观拦截机制

**功能**: 大盘融合决策结果作为全局参数传递给单品分析引擎

| 大盘决策 | 对单品的影响 |
|---|---|
| 减仓/观望 | 所有单品「分批建仓」信号降级为观望，价值评分 -1.5 |
| 建仓/持有 | 不做折价，正常输出单品策略 |

此机制确保单品分析不会在大盘出货期给出激进建仓建议。

---

## 三、数据流

```
csQAQ API
  ├── GET /current_data?type=init ──→ 大盘当前值 + 板块资金
  ├── GET /sub/kline?id=1&type=1day ──→ 大盘日线K线
  │
  ▼
analyze_index_full()
  ├── analyze_index() ──→ PositionIntel + ProbPrediction + CycleAnalysis + ValueScore
  ├── compute_market_trend_health() ──→ MarketTrendHealth
  └── compute_market_fusion_decision() ──→ MarketFusionDecision
      │
      ▼
  JSON 序列化 → DB settings (cached_index_analysis)
      │
      ▼
  webapp 模板渲染
    ├── index_analysis.html (点位判断/概率/周期/价值评分)
    ├── Market Trend Health 卡片 (六维度 + 扣分来源)
    └── Market Fusion Decision 卡片 (操作标签 + 仓位上限)
```

---

## 四、前端展示

| 页面 | 内容 |
|---|---|
| 大盘仪表盘 | 指数卡片 → 大盘趋势健康度 → 大盘融合决策 → 点位智能判断 → 涨跌概率预测 → 周期阶段 → 投资性价比评分 |
| 刷新数据 | POST `/api/market/refresh` 重新拉取 csQAQ 数据 + 重跑分析 + 更新缓存 |

---

## 五、与单品引擎的联动

| 联动点 | 机制 |
|---|---|
| 大盘周期 | 传入 `run_item_analysis(market_cycle=...)` → 出货期触发单品信号降级 |
| 大盘百分位 | 传入涨跌概率预测作为宏观环境修正 |
| 全局仓位上限 | 大盘融合决策的 `global_position_limit` 约束单品建仓建议 |
| 趋势健康度 | 大盘和单品分别独立计算，不互相污染 |
