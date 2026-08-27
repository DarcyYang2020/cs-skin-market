# W7-2 steamdt 成交额组件 · 采集可行性预研报告（2026-08-27，④运维窗口）

> 卡：roadmap W7-2「steamdt 成交额组件」（市场级活跃度，待 S1 可行性预研 + 历史深度）。
> 前置（PM 指令 2026-08-27）：S1 账号已可用、D2 盘口采集已激活，具备起采条件。
> 红线（decision-log 2161）：解锁后走合规累积口径（积累 3-6 月再评），不得即采即落主分析；本次仅预研/起采蓄水池。
> 方法：Playwright headless（py311，playwright 1.61）实测 + 开放平台文档核验 + Web 检索交叉验证。
> 探针：`references/steamdt_probe1~17.py`；字段存证：`data/_exp_w7_2_steamdt_probe.json`。

## 〇、关键澄清：steamdt ≠ 悠悠有品（重要）

**steamdt 不是悠悠有品（youpin898.com）的站内页面，而是独立第三方 CS 饰品数据站 `steamdt.com`**（金华新果科技运营）：
- `www.youpin898.com/steamdt` 实测 →「啊哦，暂无该页面哟～」（404，SPA 兜底页）——悠悠站内无此组件。
- `steamdt.com` 独立运营，公开提供大盘指数/成交额/成交量/新增额/在线人数/板块指数，与 PM 任务描述字段**完全吻合**（搜索结果与实测交叉验证）。
- 建议：PM/研发后续表述统一为「steamdt.com 市场数据组件」，数据源为第三方站，非悠悠有品。

## 一、预研三项结论

### ① 页面/API 连通性与字段核实 —— ✅ 核心可采（匿名）

**站点连通**：`https://www.steamdt.com` 可达（HTTPS 200，Nuxt SPA，中文），headless Chromium 可渲染，**无需登录**。

**站内 API（GET，直接 fetch 即返回数据，零鉴权）**：

| 端点 | 功能 | 关键字段（实测） |
|---|---|---|
| `/api/index/statistics/v1/summary` | 大盘统计 | `broadMarketIndex`（大盘指数 830.77）、`diffYesterdayRatio`（环比）、`todayStatistics`（`addNum` 新增量 / `addValuation` 新增额 / `tradeNum` 成交量 / `turnover` 成交额 + 四项环比 Ratio）、`yesterdayStatistics`、`surviveNum` 存世量、`holdersNum` 持有者数、`historyMarketIndexList`（当日逐小时指数 25 点）、`transPerformanceTrend` |
| `/api/index/players/v1/statistics` | 在线人数 | `count`（当前 113万）、`yesterdayHour`/`lastWeekHour` + 环比、`monthAvg`/`todayMax`/`weekMax`/`monthMax`、`history`（逐小时 24 点）、`allHistory` |
| `/api/index/item-block/v1/summary` | 板块指数 | `hot`（热门板块：一代手套/千战/武库挂件等 5 项，各含 index/riseFallRate）、`itemTypeLevel1/2/3`（三级板块指数全量） |
| `/api/index/skin-folder/v1/hot` | 收藏夹板块 | folderName/folderCount/hotCount + trend（含 trendList 历史序列） |
| `/api/user/ranking/v1/page` | 榜单（POST） | 在售价涨跌榜/成交榜/热度榜（页面展示，POST 405 需带参数） |
| `/api/user/skin/v1/recent-add` | 新增品 | 新上架饰品 |

**单品页（`/cs2/{marketHashName}`，页面标注「**10分钟级更新**」）**：
- 页面实测渲染：当前价 ¥136.28、今日推算成交 26、存世量 59813、挂刀/搬砖 0.69/0.74、五平台对比（C5GAME/BUFF/悠悠/Steam/HaloSkins 在售+求购）、武器箱归属、磨损分布、K线图。
- 单品 API（POST，`{appId:730, marketHashName}` 或 `{itemId, typeDay, dateType}`）：
  - `/api/user/skin/v1/item` — 单品主数据
  - `/api/user/skin/v2/sale-wear-detail` — 成交/磨损详情
  - `/api/user/skin/v2/asset/wear-rank` — 磨损排行
  - `/api/user/steam/type-trend/v2/item/details` — 走势 K 线（dateType 可切日/时粒度）
  - `/api/index/item/change/v1/list` — 单品异动

**⚠️ 单品 POST 风控（errorCode=108）**：从首页或单品页上下文直接 fetch 复现 POST 单品 API 均返回 `108 当前环境异常`（STEAM_STOCK_COMMON_ERROR_108），仅页面原生交互（加载/点击 tab）成功。判定：**单品级 API 有环境校验（可能依赖页面会话/指纹/WS jwt），直接 HTTP 复现不可行**；但**大盘/板块/在线/新增 GET 类接口零鉴权直采**。单品路径建议走页面自动化（Playwright 页面内交互）或后续深挖 WS jwt（`/api/common/v1/ws/jwt/anonymous`）通道。

### ② 历史深度评估 —— 部分可回溯，回测能力有限

| 层级 | 深度 | 说明 |
|---|---|---|
| 大盘指数 | **当日逐小时**（25 点）+ 页面 K 线图（时/日/周多周期，前端聚合） | `historyMarketIndexList` 为当日序列；长周期 K 线数据在页面内（需页面交互/深挖请求参数） |
| 在线人数 | 当日逐小时（24 点）+ `allHistory` 字段 | `allHistory` 疑似更长历史（未全量验证） |
| 板块指数 | 当前快照 + 板块 trendList（收藏夹板块约 1 月） | item-block summary 为当前值；历史走势在板块详情页 |
| 单品 | 页面 K 线（10min 级更新，多周期） | 需页面上下文调用 |

**结论**：**历史深度 = 有限（当日小时级 + 页面内多周期 K 线），无公开的全历史数据批量接口**。与 S1 报告「悠悠求购/成交历史深度 = 当前快照」类似——**回测能力弱，价值在"从现在开始积累"**。这与 W7-2 合规累积口径（积累 3-6 月再评）天然契合：**蓄水池从今日起逐日累积，3-6 月后可评估回测**。

### ③ 采集频率与落库表设计

**建议方案（蓄水池，不接引擎）**：
- **数据源**：`steamdt.com` 站内 GET API（summary / players / item-block / skin-folder），零鉴权，urllib 即可（无需 playwright 主链路）。
- **频率**：每日 1 次（18:00 每日链收尾挂接，对齐现有节奏；成本 <10 秒/次，负载可忽略）。可选加频：大盘/在线每 30 分钟（蓄水池积累更密粒度，成本仍低）——首期建议每日 1 次起步，观察稳定性后再议。
- **落库**：`data/raw.db`（append-only 蓄水池，符合 D7 治理「高价值数据独立 append-only」）：
  - 新表 `raw_steamdt_market`（date, ts, broad_market_index, diff_yesterday_ratio, add_num, add_valuation, trade_num, turnover, add_num_ratio, add_amount_ratio, trade_volume_ratio, trade_amount_ratio, survive_num, holders_num, online_count, month_avg_online, update_time）
  - 新表 `raw_steamdt_blocks`（date, ts, level, block_name, index, rise_fall_rate, rise_fall_diff）
  - 单品级（10min/走势）**暂缓**：受 108 风控限制，首期不采，待 WS/页面方案验证后再评估（不阻塞市场级蓄水池）。
- **合规**：仅采公开市场级数据（指数/成交/在线/板块），不涉账号/交易明细；不即采即落主分析，蓄水池 3-6 月后再评（W7-1 内生情绪 v1 届时复用）。

## 二、风险与红线对照

| 项 | 结论 |
|---|---|
| 合规 | ✅ 公开市场级数据，无登录墙，不涉账号；符合 DU 红线（积累 3-6 月再评、不即采即落主分析） |
| 反爬 | ⚠️ 单品 POST 有 108 环境风控（fetch 复现被拦）；市场级 GET 接口实测无拦截。频率控制：每日 1 次低频，风险低 |
| ToS | ⚠️ 第三方站数据采集，低频只读，风险低-中；开放平台（open.steamdt.com）仅公开 wear 接口，市场数据接口未开放，只能走站内 API |
| 落库 | 蓄水池表写入 raw.db，不碰 market.db 生产库、不接引擎、不 bump ENGINE_VERSION |

## 三、结论与建议

1. **可行性：市场级 ✅ 可采**（大盘指数/成交额/成交量/新增额/新增量/在线人数/板块指数，GET 零鉴权）；**单品级 ⚠️ 有条件**（10min 数据存在但受 108 风控，需页面自动化或 WS 通道，建议二期）。
2. **历史深度有限**（当日小时级 + 页面内 K 线），无批量全历史接口 → **回测能力弱，价值在积累**，与 W7-2 3-6 月合规累积口径契合。
3. **建议动作**：PM 立项「W7-2 蓄水池采集」（raw.db 两表，每日 1 次挂 18:00 链，纯 GET 低风险）→ 落地后积累 3-6 月 → 再评估进 W7-1 内生情绪 v1。**本窗口不落地代码**（归属研发），仅出结论。
4. **需 PM 拍板**：①确认数据源=steamdt.com（非悠悠有品）；②是否立项蓄水池采集；③单品级是否二期深挖（WS 通道）。

## 状态

**预研完成（市场级可采，单品级有条件，历史深度有限）**。探针 17 个存证于 references/steamdt_probe*.py；字段快照 `data/_exp_w7_2_steamdt_probe.json`。待登记 decision-log / roadmap W7-2。
