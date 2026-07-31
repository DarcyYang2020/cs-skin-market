---
name: cs-skin-market
description: "CS 饰品市场投资策略全流程辅助。覆盖行情趋势分析、饰品估值评分与筛选、买卖时机判断及持仓管理。当用户需要：(1) 查询或分析 CS 饰品价格走势时；(2) 筛选高潜力投资标的时；(3) 制定买入/卖出策略时；(4) 了解市场动态与事件驱动因素时；(5) 需要持仓风险评估时，自动启用此技能。"
---

# CS Skin Market

## 核心规则

1. **只分析用户指定的磨损等级**，不对比其他磨损
2. **大盘先行**，单品分析前必先获取大盘指数
3. **数据源优先级**: 悠悠有品 (platform=2) > Buff > C5GAME，Steam 仅参考
4. **自动过滤** StatTrak™ 和纪念品

## 数据来源

### 大盘数据
- csQAQ API: GET /api/v1/current_data?type=init → 指数/品类排名/市场情绪
- csQAQ API: GET /api/v1/current_data?type=kline → 大盘 K 线
- **抛压衰竭**：compute_selling_pressure_exhaustion() 三维打分（跌速衰减/无新低/止跌企稳），20日跌幅门控防下跌中继误报，≥70 进入底部观察

### 单品数据
- csQAQ Playwright: 导航 goods/{id} → 拦截 info/chart API (90日日线)
- csQAQ Playwright: 拦截 info/good?id= API → 详情 (steam_name, 价格)
- csQAQ Playwright: **求购价图表**（出售价下拉→求购价）→ buy_price 90日序列 → order_book 价差/趋势
- steamdt Playwright: 导航 /cs2/{market_hash_name} → 拦截 K线 API → 真实成交量

### 成交量合并
csQAQ chart API 提供 price + in_sale_count (不含真实成交量)。成交量由 steamdt 单独采集，通过 merge_daily_volume() 按日期 (YYYY-MM-DD) 合并到 K线数据。

## 工作流程

### Step 1: 获取大盘温度
- Web: 访问 http://127.0.0.1:8000/ 查看大盘仪表盘
- 输出: 指数数值 + 7日涨跌 + 市场情绪 + 融合决策

### Step 2: 单品分析
- Web: 访问 http://127.0.0.1:8000/search，输入名称直接分析
- 分析结果包含: 估值定位 + 周期判定 + 流动性 + 涨跌概率 + 投资价值 + 庄盘识别 + 趋势健康度 + 融合决策
- 结果自动保存到 localStorage，刷新不丢失

### Step 3: 自选管理
- Web: http://127.0.0.1:8000/watchlist
- 添加/编辑/删除自选物品
- 点击“分析”按钮重新分析单品
- 点击“报告”查看历史分析报告

## 单品分析模块说明

| 模块 | 功能 | 关键指标 |
|---|---|---|
| 估值定位 | 90日百分位 + Z-score | 低估/合理/高估/泡沫 |
| 周期判定 | 四阶段识别 | 吸筹/拉升/出货/洗盘 |
| 流动性 | 三维 0-100 | 成交量/价差/在售深度 |
| 涨跌概率 | 均值回归预测 | 3/7/14日 涨/平/跌 |
| 庄盘识别 | 四因子检测 | 价格异常/供给控盘/量价/波动 |
| 趋势健康度 | 六维 0-100 | 短期/长期/均线/波动/量价/回撤 |
| 融合决策 | 百分位+TH+周期 | 操作指令 |
| 求购承接 (v4.6) | 断层+价差趋势 0-100 | spread_pct / bid7d_chg / bid30d_chg / spread_avg |

## 新增信号 (v4.6)

### 大盘抛压衰竭
- 熊市 V 侧底部先行信号，不依赖均线金叉
- 三维打分（跌速衰减 0-40 + 无新低 0-30 + 止跌企稳 0-30），回测 30d 胜率 100%
- 20 日跌幅硬门控（< -7%）杜绝下跌中继反弹误报

### 单品求购承接
- 实时买盘意愿快照，从页面「求购价」图表抓取完整历史
- 断层宽度/收窄扩张/求购价趋势三维，承接弱（≤25）强制降级 buy→观望
- order_book 价差深度已修复（原 401 导致恒为 0）

## 常见问题

- **模板编辑**: 不要用 PowerShell 编辑含中文的 HTML 模板，使用 Python \uXXXX 转义序列生成
- **成交量正确性**: ar.date 必须为 YYYY-MM-DD 格式才能与 steamdt 合并
- **StatTrak 误匹配**: 检查 _verify_item_name 和 search_good_id 过滤逻辑
- **分析耗时**: 单次约 30-50 秒，正常范围

## 启动服务

`ash
cd cs-skin-market && python run_server.py
# 访问 http://127.0.0.1:8000/
`
