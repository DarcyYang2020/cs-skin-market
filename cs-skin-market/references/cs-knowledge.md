# CS Market Deep Knowledge

> 项目相关的 CS 饰品市场深度知识，供评分模型/投资策略/分析报告参考。
> 新窗口工作时，请先阅读本文件获取上下文。

---

## 一、热门板块体系

### 数据入口
- **板块列表 API**: /api/user/item/block/v1/relation (GET)
- **板块摘要 API**: /api/user/item/block/v1/summary?type=HOT&typeVal=<snowflake_id> (GET)
- **板块趋势 API**: /api/user/item/block/v1/trend?type=HOT&typeVal=<snowflake_id> (GET, 10分钟级)
- **子板块 API**: /api/user/item/block/v1/next-level (GET, 下级按武器类型分类)

### 五个重点热门板块

| 板块 | typeVal (snowflake ID) | 当前指数(参考) | 含义 |
|---|---|---|---|
| 一代手套指数 | 1496347463977287680 | ~558,968 | 第一代手套皮肤（手套武器箱系列） |
| 探员指数 | 1368076160637956096 | ~9,795 | 探员皮肤 |
| 收藏品指数 | 1496371022874832896 | ~960,568 | 收藏品（非箱子掉落，如地图收藏品） |
| 千战指数 | 1496347526866681856 | ~251,480 | 千战系列（1000击杀/战痕？） |
| 百战指数 | 1496347256370708480 | ~118,342 | 百战系列 |

> 指数大小 = 板块容纳资金规模。收藏品 ≈ 96万 > 一代手套 ≈ 56万 > 千战 ≈ 25万 > 百战 ≈ 12万 > 探员 ≈ 1万。

### 板块数据字段
- index / yesterdayIndex / highIndex / lowIndex — 价格数据
- 
iseFallDiff / 
iseFallRate — 涨跌值/涨跌幅
- 	ransactionAmount / 	ransactionCount — 成交额/成交量
- upNum / latNum / downNum — 涨跌家数
- platforms — 各平台分项（ALL / BUFF / 悠悠 / C5GAME）
- 	rendList — 历史趋势点（25个时间点）

---

## 二、炼金机制变革（2025-10-24）

### 核心变化

| 项目 | 旧机制 | 新机制 |
|---|---|---|
| 金色获取 | 几乎只能开箱 | 5红 → 1刀/手套（5合1配方） |
| 红色材料 | 普通消耗品 | 金色炼金唯一消耗品，需求暴增 |
| 10合1 | 不变 | 不变，但红色材料变贵导致成本上升 |

### 市场影响

- **金色（刀/手套）贬值**：获取途径增多，供应增加，低端刀/手套价格下跌
- **红色（隐秘级/covert）升值**：成为刚需材料，尤其适合卡金的磨损
- **玩家行为分化**：攒红炼金 vs 开箱，中低端炼金被挤压
- **控盘逻辑改变**：控制红色材料供给→推高炼金成本→影响金色价格

### 对评分模型的启示

- 红色（covert）皮肤新增「炼金消耗」属性 → 稀缺度应上调
- 刀/手套新增「可稳定合成」属性 → 稀缺度应下调
- 事件修正因子应包含炼金机制带来的结构性变化

---

## 三、上游控盘策略（供应链投资框架）

### 核心逻辑

`
箱子 → 红色材料（同箱隐秘级皮肤）
         ↓ 5合1炼金
       刀/手套（目标产物）
`

**不直接买刀/手套，而是囤积同箱红色材料**，控制供给端瓶颈：
1. 红色材料被扫货 → 炼金成本飙升
2. 手套/刀供给受限 → 价格被动拉升
3. 材料是杠杆：少量资金即可撬动整个板块定价权

### 实战案例：一代手套

手套武器箱包含的红色材料（影响一代手套价格的关键下级素材）：
- M4A4 | 喧嚣杀戮
- 法玛斯 | 机械工业
- USP | 次时代
- （及其他同箱隐秘级皮肤）

### 对单品分析的启发

分析 **刀/手套/任何可合成的金色饰品** 时，必须：

1. **溯源到箱子** → 确认来源武器箱
2. **列出同箱红色材料** → 找到控盘关键标的
3. **监测材料异动** → 供给收缩 + 价格上涨 = 控盘信号
4. **计算炼金成本价差** → 产物被低估 = 买入窗口；材料爆拉而产物滞涨 = 补涨预期
5. **识别团队进场模式** → 同箱多材料同步吸筹

---

## 四、投资策略备忘

### 估值锚
- 悠悠有品 > Buff > C5GAME
- Steam 美元价失真，仅作参考

### 定价参考
- 当前价格在 30日/90日 历史中的百分位排名
- Z-score（偏离均值标准差数）
- 估值标签：低估（<=20%分位）/ 合理 / 高估（>=80%分位）

---

## 五、CS2 饰品市场核心特征（宏观框架）

### 一、资产属性：非金融、纯稀缺驱动的虚拟实物资产

- **零基本面、纯供需定价**：无利息、无分红、无财报，价格完全由稀缺度+市场情绪+资金热度+版本规则决定。
- **永久保值基底**（规则不变前提下）：饰品永久存续、不销毁、不贬值清零，只要V社不修改规则，存量永久锁定。
- **独一无二非标属性**：每款有专属磨损值、贴纸搭配、暗金计数，无完全相同标的，溢价分层极其复杂。

### 二、行情波动：强周期、强事件驱动，波动极不规律

- **周期性极强**：严格跟随「箱子上新→热度拉升→存量消耗→下架稀缺→长期慢涨」闭环，贴合Major赛事、版本更新、寒暑假流量周期。
- **事件暴击性波动**：最大涨跌来自V社规则更新、合成机制调整、箱子下架、赛事活动、Steam政策变动，纯技术指标无法单独预判，必须叠加事件修正。
- **短期情绪化严重**：散户追高踩踏频发，超涨超跌是常态，适配Z-score偏离度做反转判断。

### 三、价格结构：分层明显、溢价复杂

- **低端通货**：高流通、低波动
- **中端热门皮**：稳波动、适合套利
- **高端刀/手套**：高溢价、高风险、资金盘属性
- 不同品类走势完全独立，无统一大盘走势。

### 四、交易流动性：两极分化

- **多平台价差常态化**：Steam/BUFF/悠悠/IGXE 长期存在差价，搬砖套利机会长期存在。
- **兼具消费与投资属性**：自用消费 + 理财套利双重需求，价格同时受审美热度+资金热度影响。

### 五、风险特征：规则风险 > 市场风险

- 最大亏损来源不是价格波动，而是V社机制改动（合成、掉率、箱子规则调整）引发的系统性崩盘。

### 六、对产品算法的指导意义

CS2饰品市场**不是随机波动市场，而是「周期规律+事件驱动+情绪超跌超涨+流动性分层」的可量化市场**。

算法核心路径：
- **百分位看位置** → 估值分位（valuation.py）
- **Z-score看偏离** → 反转信号
- **周期雷达看阶段** → 趋势+供给（trends.py + supply.py）
- **事件贝叶斯做修正** → 事件冲击修正层
- **流动性评分做风控** → 流动性因子

无需复杂深度学习，上述因子组合即可实现远超普通行情工具的精准预判。

---

## 附录：与交易策略的对应关系

详见 [trading-strategies.md](trading-strategies.md)，策略框架摘要：

| 产品模块 | 策略对应 |
|---|---|
| 买点 | 90日百分位 ≤ 30% + Z-score ≤ -1.5 |
| 选品 | 流动性评分过滤冷门死货 |
| 持仓 | 分批建仓 + 15-45天中线持有 |
| 止盈 | 百分位 ≥ 65% 或 Z-score ≥ +2.0 |
| 止损 | 90日新低 / V社利空事件 |
| 轮动 | 吸筹→洗盘→拉升→出货四个阶段 |

---

## 六、2026年5月纪念品炼金开放事件

### 核心一句话

> 收藏品板块的全部溢价，建立在「不可再生产、纯绝版存量」的收藏品逻辑上；炼金解禁直接让收藏品变成「可量产工业品」，底层估值逻辑彻底崩塌。

### 四层核心影响逻辑

#### 1. 稀缺性底层逻辑彻底失效（最根本原因）

**旧规则**：仅赛事掉落、永不新增、无法炼金、无法再生产 → 纯存量收藏品，越消耗越少。

**2026.5 更新**：纪念品支持炼金汰换，普通皮肤可批量合成纪念品 → 从绝版存量变为**无限增量供给**，收藏品属性直接被剥夺。

#### 2. 高端收藏品溢价全面崩盘

过去高端纪念刀/纪念手套/纪念暗金溢价 = 稀缺收藏价值 + 赛事纪念属性。更新后稀缺归零，纪念属性无法支撑天价泡沫，大量人工炼金新品冲击市场。

#### 3. 资金抱团集体解散（直接导致持续阴跌）

收藏品是**全市场最大抱团板块**（低流通、存量锁定、大户长期囤货核心赛道）。利空落地后抱团资金集体出逃、不计成本出货 → 高分位持续塌陷、Z值长期负偏离、无量阴跌、流动性崩坏。

#### 4. 市场信仰崩塌

从前共识：大盘跌收藏品稳、大盘涨收藏品领涨（避险属性）。现在共识：**收藏品是最大利空板块，无底部、无支撑、越囤越亏**。

### 对评分模型的直接影响

| 模块 | 调整方向 |
|---|---|
| 稀缺度因子（收藏品/纪念品） | 来源 multiplier 应大幅下调 |
| 事件修正层 | 收藏品板块应持续标记为利空 |
| 趋势分析 | 收藏品 Z 值长期负偏离不视为超跌机会 |
| 投资建议 | 收藏品/纪念品应标注"高风险、无底部支撑" |
| 板块热度 | 收藏品指数应视为持续利空板块 |

---

## 七、csQAQ API 参考（数据源）

### 基本信息

| 项目 | 值 |
|---|---|
| Base URL | https://api.csqaq.com/api/v1 |
| 认证方式 | HTTP Header ApiToken: YOUR_TOKEN + IP 白名单 |
| 频率限制 | 1次/秒（通用），部分接口有特殊限制 |
| 响应格式 | {\"code\": 200, \"msg\": \"Success\", \"data\": ...} |
| IP 绑定 | POST /api/v1/sys/bind_local_ip（30秒/次）|

> **IP 绑定方案已生效（2026-08-06 实测）**：直连接口需先 `POST /sys/bind_local_ip`（body `{}`）把当前公网 IP 加入白名单；动态运营商 IP 可能变化，`run_daily_collect.py` 每日采集开头自动重绑。**旧版直连接口（goods/search_good_id、goods/get_good_id、info/good_detail）绑定 IP 后仍返回 401，属永久废弃**，已迁移到新版接口（见下方对照表）。

### 新旧接口对照

|---|---|---|
| 大盘指数 | Playwright 抓首页 | GET /api/v1/current_data?type=init |
| 大盘K线 | 响应拦截 API | GET /api/v1/current_data?type=kline |
| 板块/分类 | document.body.innerText 解析 | current_data 的 sub_index_data(23项) + chg_type_data(75项) |
| 饰品搜索 | 联想接口 | GET /api/v1/search/suggest?text=（旧 search_good_id 已废弃 401） |
| 饰品ID查询 | 无(用MarketHashName) | POST /api/v1/goods/getPriceByMarketHashName（旧 get_good_id 已废弃 401） |
| 饰品详情 | JSON | GET /api/v1/info/good?id=（data.goods_info；旧 good_detail 已废弃 401） |
| K线数据 | 响应拦截 API | POST /api/v1/info/kline |
| 存世量走势 | K线API提取 | GET /api/v1/info/survive?good_id= |
| 批量价格 | 逐个抓取 | POST /api/v1/goods/get_multi_sell_info |
| 图表数据(售价/在售/求购/成交) | 多个来源拼接 | POST /api/v1/info/chart |
| 排行榜 | 无 | POST /api/v1/rank/rank_list |
| 收藏品/箱子列表 | 无 | POST /api/v1/container/containers |

### 核心接口详情

#### 1. 大盘指数 GET /api/v1/current_data?type=init

无需 ApiToken。返回字段：

- sub_index_data[] — 23个子指数(id, name, market_index, chg_num, chg_rate, open/close/high/low)
- chg_type_data[] — 75个品类(name, total_price, price_diff_1/7/15/30/90/180, type)
- chg_price_data[] — 按价格分层的涨跌(小/中/大件)
- 
ate_data — 涨平跌家数统计
- online_number — 在线人数(current/today_peak/month_peak)
- online_chart[] — 在线人数历史
- greedy[] — 恐惧贪婪指数历史(daily)
- greedy_status — 当前贪婪状态(level/label)
- lteration[] — 异动监控
- iew_count[] — 浏览热度排行

#### 2. 饰品搜索 GET /api/v1/search/suggest?text=（新版，2026-08-06 迁移）

旧 `goods/search_good_id` 已废弃（绑定 IP 后仍 401）。返回 `data: [{id: 字符串, value: 中文全名}]`，id 即 good_id；名称/价格等详情由 `info/good` 补齐。

#### 3. 饰品详情 GET /api/v1/info/good?id=（新版，2026-08-06 迁移）

旧 `info/good_detail` 已废弃（绑定 IP 后仍 401）。返回 `data.goods_info`：name / market_hash_name / buff_sell_price / buff_sell_num / buff_buy_price / buff_buy_num / yyyp_sell_price / yyyp_sell_num / steam_sell_price / turnover_number（日成交件数）等；盘口与日成交量可直接取 goods_info，不再依赖 info/chart。

#### 3.1 MarketHashName → good_id：POST /api/v1/goods/getPriceByMarketHashName（新版，2026-08-06 迁移）

旧 `goods/get_good_id` 已废弃（绑定 IP 后仍 401）。Body: `{"marketHashNameList": ["AK-47 | Elite Build (Battle-Scarred)"]}` → `data.success[hash].goodId`；未命中项进 `data.error`。可批量。

#### 4. K线 POST /api/v1/info/kline

Body: {\"good_id\": int, \"day\": int(7/30/90/180/360), \"platform\": int(1=BUFF)}

#### 5. 均价/在售/求购/成交量 POST /api/v1/info/chart

Body: {\"good_id\": int, \"key\": \"sell_price|sell_num|buy_price|buy_num|turnover_number\", \"platform\": int}

#### 6. 存世量 GET /api/v1/info/survive?good_id=

返回近180天存世量走势。


---

### 官方接口文档 (docs.csqaq.com) 端点清单

> 学习日期: 2026-08-04；接口实测更新 2026-08-06。官方文档托管于 Apifox（docs.csqaq.com，项目 ID 4711104），共收录 37 个端点。
> 直连 API 需 IP 白名单：先 `POST /sys/bind_local_ip` 绑定当前公网 IP（每日采集自动重绑，见 run_daily_collect.collect_bind_ip）；**旧版直连端点（search_good_id / get_good_id / good_detail）绑定后仍 401 属永久废弃**。浏览器绕过路径仍可用：Playwright 访问对应页面、拦截 /proxies/api/v1/* 响应（复用 collector_csqaq._capture_proxies_api 机制，无需 ApiToken）。

#### 页面 → 端点映射（2026-08-04 实测）

| 页面 | 触发端点 | 用途 |
|---|---|---|
| /detail | info/get_page_list | 分页饰品列表（筛选类别/磨损/类型），返回悠悠锚价+在售数 |
| /rank | info/get_rank_list | 排行榜单 |
| /monitor | monitor/rank、monitor/get_task_trends、monitor/get_task_stat | 库存监控（大户持仓持有量排行/最新动态） |
| /exchange | info/exchange_detail | 挂刀行情（Steam 汇率） |
| /series | info/get_series_list | 热门系列（资金规模+1/7/15/30/90/180 涨跌+15点趋势） |
| /stat/case | info/roi | 开箱回报率列表 |
| /goods/{id} | info/good、info/chart | 单品详情+K线（项目已在用） |

#### 官方端点总表（37 个）

| 端点 | 方法 | 说明 | 项目状态 |
|---|---|---|---|
| /api/v1/sub_data | GET | 获取指数详情数据（大盘 sub_index_data 同源） | 新 |
| /api/v1/sub/kline | GET | 获取指数K线图 | 已用 collector.fetch_index_kline |
| /api/v1/goods/get_all_goods_id | - | 获取全量站内饰品ID | 新·触发方式待确认 |
| /api/v1/goods/get_all_goods_info | POST | 获取全量饰品价格数据（多平台 sell/buy/num + 悠悠/IGXE 租赁价） | 新·触发方式待确认 |
| /api/v1/goods/get_all_goods_rank | POST | 获取全量饰品排行榜（1/7/15/30/90/180/365 涨跌 + buff/yyyp 价格趋势） | 新·触发方式待确认 |
| /api/v1/info/simple/chartAll | POST | 简化日线 [{t,o,c,h,l,v}]（body good_id/plat/periods/max_time，max_time 向前翻页每窗口150天，实测可回补至 2023-08；plat=2 为悠悠价；v 口径未确认） | 新·已实测(历史回填) |
| /api/v1/info/get_popular_goods | POST | 获取全量饰品热度排名（rank_num + change + turnover_number） | 新·触发方式待确认 |
| /api/v1/goods/get_goods_template | POST | 获取饰品模板（含 container/income/roi、buff_id/yyyp_id/steam_id/c5_id 跨平台映射） | 新 |
| /api/v1/info/get_good_id | - | 获取饰品的ID信息（分页目录；实测需翻页定位 hash，未采用） | 新·未采用 |
| /api/v1/search/suggest | GET | 联想查询饰品（搜索框自动补全 ?text=） | 已用(2026-08-06) |
| /api/v1/info/good | GET | 获取单件饰品详情（Playwright 拦截 info/good?id=；同步直连已迁移至此） | 已用 |
| /api/v1/info/good/statistic | GET | 获取单件饰品存世量走势（?id=，[{statistic,created_at}] 日序列） | 新 |
| /api/v1/goods/getPriceByMarketHashName | POST | 批量获取出售价格（body marketHashNameList[] → success{goodId, buff/yyyp/steam 价} + error[]） | 已用(2026-08-06, hash→goodId) |
| /api/v1/info/chart | POST | 获取单件饰品图表数据（sell_price/sell_num/buy_price/buy_num/turnover_number） | 已用 |
| /api/v1/info/chartAll | - | 获取单件饰品全量图表数据 | 暂停使用 |
| /api/v1/info/get_rank_list | POST | 获取排行榜单信息 | 新 |
| /api/v1/info/get_page_list | POST | 饰品列表（body page_index/page_size/search/filter{类别,磨损,类型}；返回 yyyp_sell_price/yyyp_sell_num；200/页，全市场 2 万+ 品） | 新·已实测(全市场快照) |
| /api/v1/info/get_series_list | POST | 获取热门系列饰品列表（sell_price_1..180 + amount + total_value + recently_data[15]） | 新·已实测 |
| /api/v1/info/get_series_detail | - | 获取单件热门系列饰品详情 | 新 |
| /api/v1/info/exchange_detail | POST | 获取挂刀行情详情 | 新·已实测 |
| /api/v1/monitor/get_task_trends | - | 获取库存监控最新动态 | 新·已实测 |
| /api/v1/monitor/get_task_list | POST | 获取库存监控任务列表（body page_index/page_size/order/search → res[{steam_name,steam_id,amount,active_time,state}]） | 新 |
| /api/v1/monitor/rank | POST | 获取库存监控持有量排行榜（body good_id → [{steam_name,steam_id,avatar,num}]） | 新·已实测 |
| /api/v1/task/get_task_info | - | 获取监控单个用户信息 | 新 |
| /api/v1/task/get_task_business | - | 获取监控单个用户库存动态 | 新 |
| /api/v1/task/get_task_all | - | 获取监控单个用户全部库存 | 新 |
| /api/v1/task/get_task_recent | - | 获取监控单个用户库存快照列表 | 新 |
| /api/v1/stat/case | POST | 获取武器箱开箱数量统计（daily/weekly/monthly/total + cn_name/good_id/ground_at） | 新 |
| /api/v1/info/roi | POST | 获取武器箱开箱回报率列表（roi/income/price/num + comment 掉落状态） | 新·已实测 |
| /api/v1/info/roi_detail | GET | 获取单个武器箱开箱回报率走势（?id=，小时级 {income,roi,date}） | 新 |
| /api/v1/stat/case/chart | POST | 获取单个武器箱历史开箱量（body case_id → [{daily,date}] 日序列） | 新 |
| /api/v1/info/container_data_info | POST | 获取所有收藏品列表 | 新 |
| /api/v1/info/good/container_detail | - | 获取单个收藏品的包含物 | 新 |
| /api/v1/info/vol_data_info | POST | 获取成交量数据信息（**武器箱维度**，statistic/avg_price/sum_price；非单品真实成交量） | 新 |
| /api/v1/info/vol_data_detail | - | 获取成交量图表/磨损信息 | 新 |
| /api/v1/info/get_banana_data | - | 获取所有Banana列表数据 | 新·无关 |
| /api/v1/info/get_banana_chart | - | 获取单件Banana图表数据 | 新·无关 |

> 补充：/monitor 页面还触发了文档未收录的 monitor/get_task_stat（监控任务统计）。

#### 对项目的价值判断与落地（2026-08-04）

- **真实成交量主线不变**：官方文档无「单品每日真实成交历史」接口（simple/chartAll 的 v 为 csQAQ 内部成交量口径，实测与悠悠逐日量不一致，**未确认、勿用于成交量因子**），悠悠有品仍是唯一真实量来源，等成交量积累继续。
- **历史深度（已落地）**：simple/chartAll(plat=2 悠悠价) 多窗口向前翻页可回补至 2023-08。经研判 **2024 及更早市场逻辑已过时，回填起点定为 2025-01-01**（覆盖 2025-02 反弹、2025-05 深底、2026-02 小牛，全部关键样本点）。`run_backfill_history.py` 给现有品补 2025-01-01~2025-08-03 缺失价格（仅补缺失、不覆盖已有 volume_day）。
- **全市场快照（已落地）**：`collector_snapshot.py` 用 get_page_list 翻页（200/页，按热度取前 5000 品 ≈ 25 页 ≈ 2 分钟/天）每日采集悠悠锚价+在售数，存 market_snapshot 表，为未来全市场选品/估值分布/异动扫描积累面板，与成交量积累并行。
- **P1 已落地（2026-08-04）**：monitor/rank 大户集中度每日快照（collector_monitor.py，每品 Top50 大户持有量，存 monitor_rank_snapshot，挂 run_daily_collect 每日任务）；复验期回测「集中度变化」能否提升吸筹信号（等数据积累 2~3 个月）。
- **P2 待办**：stat/case 开箱量 + info/roi 回报率 → 事件/热度因子量化；get_all_goods_* 权限确认后做全市场估值分布。

## 八、csQAQ API 数据字典

### 采集方式
- Playwright 浏览器自动化访问 csqaq.com/goods/{good_id}
- 拦截 info/good?id= 和 info/chart 两个 API 响应
- HTTP API 直接调用需要 IP 白名单（当前用 Playwright 绕过）

### goods_info 字段（通过 info/good?id= 拦截获取）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | csQAQ good_id |
| name | str | 中文全名 |
| market_hash_name | str | Steam 市场名 |
| type_localized_name | str | 武器类型：步枪/手枪/刀/手套/贴纸/探员等 |
| rarity_localized_name | str | 品质等级：隐秘/保密/受限/军规/工业级/消费级 |
| exterior_localized_name | str | 磨损：崭新出厂/略有磨损/久经沙场/破损不堪/战痕累累 |
| quality_localized_name | str | 类型：普通/StatTrak/纪念品 |
| group_hash_name | str | 同皮肤聚合名（跨磨损共用） |
| buff_sell_price | float | Buff 在售价 |
| buff_sell_num | int | Buff 在售数量（存世量） |
| buff_buy_price/buy_num | float/int | Buff 求购价/求购数 |
| turnover_number | int | 日成交件数 |
| turnover_avg_price | float | 日均成交价 |
| sell_price_rate_1/7/15/30/90/180/365 | float | 各周期涨跌幅(%) |
| min_float / max_float | float | 磨损值范围 |
| rank_num | int | 热度排名 |
| def_index / paint_index | int | 武器定义索引 / 皮肤索引 |
| statistic | int | 统计数 |
| period_at | str | 上架时间 |

### container 字段

| 字段 | 说明 |
|---|---|
| id | 箱子 ID |
| name | 箱子中文名（如"激流大行动"武器箱） |
| price | 箱子当前价格 |
| comment | 箱子状态："绝版"=已下架, ""=在售 |
| created_at | 箱子发布时间 |
| roi | 开箱回报率(%) |

### statistic_list

同皮肤的**所有磨损版本**列表，每项含：
- id, name, exterior_localized_name, rarity_localized_name
- 可用于跨磨损比价

### chart 数据（通过 info/chart POST 拦截，period=90）

| 字段 | 说明 |
|---|---|
| timestamp | 毫秒时间戳数组 |
| main_data | 价格数组（sell_price） |
| num_data | 在售数量数组 |

通过 _chart_to_daily_ohlc() 聚合成日线 OHLCV。

### 多平台价格

csQAQ 同时提供 Buff / YYYP(悠悠有品) / C5 / IGXE / ECO / Steam 六个平台的价格和存量。
当前默认使用 Buff 价格作为定价锚。

### 可用的关键衍生数据

| 需求 | 数据来源 |
|---|---|
| 存世量 | buff_sell_num |
| 存世量变化率 | sell_price_rate_30/90 或 chart.num_data 趋势 |
| 是否炼金材料 | rarity_localized_name == "隐秘" |
| 箱子是否绝版 | container[0].comment == "绝版" |
| 品类分类 | type_localized_name |
| 是否收藏品 | quality_localized_name == "纪念品" |
| 同皮肤其他磨损 | statistic_list |
| 排名/热度 | rank_num, rank_num_change |
| 磨损区间 | min_float, max_float |
