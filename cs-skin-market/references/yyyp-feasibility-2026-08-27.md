# S1 悠悠有品采集可行性预研报告（2026-08-27，研发窗口）

> 卡：roadmap v82 Wave3 S1「悠悠有品采集可行性预研」（§4.4/§4.7）。仅预研结论，不落库、不动生产。
> 方法：Playwright headless（项目已有基建，`pipeline/collector_snapshot.py` 同款 `page.on("response")` 拦截模式），对 https://www.youpin898.com 实测 4 轮。
> 探针：`references/yyyp_probe_feasibility.py`（首页 API 盘点）/ `yyyp_probe_detail.py`（详情路由）/ `yyyp_probe_detail2.py`（交互懒加载）/ `yyyp_probe_route.py`（路由挖掘）。

## 一、结论速览

| 数据 | 可采性 | 证据 | 风险 |
|---|---|---|---|
| **在售列表**（市场底价/在售量） | ✅ **可采**（无登录） | `/api/homepage/pc/commodity/page` 200，分页 `totalElements≈11354/500`，字段 `id/commodityName/commodityHashName/iconUrl/…` | 低-中（见反爬） |
| **求购列表** | ⚠️ **未实证**（登录墙 + 路由未定位） | 用户级 API 全返 `84101 登录信息已失效`；`/goods/{id}` 详情路由 404「暂无该页面」 | 高（需登录账号） |
| **成交记录** | ⚠️ **未实证**（同上） | 同上；详情页初始加载未捕获任何成交/历史 API | 高（需登录账号） |

## 二、已实证发现（可复核）

### 1. 站点与渲染
- `https://www.youpin898.com` 可达（HTTP 200, Byte-nginx），JS SPA，**headless Chromium 可渲染**（首页 title「悠悠有品饰品交易平台｜CS2饰品交易｜CS2饰品租赁」，DOM 含「在售」条目）。
- 内部 API 主机：**`pc-api.youpin898.com`**（JSON `{code,msg,timestamp,data}`）+ `bdapi.youpin898.com`（埋点）。

### 2. 在售列表 API（可采，S2 数据源）
- 端点：`GET https://pc-api.youpin898.com/api/homepage/pc/commodity/page`
- 返回：`{Code,Msg,Data:{pageSize,pageNum,totalPages,totalElements,contents:[{id,commodityName,commodityHashName,iconUrl,iconUrlLarge,…}]}}`
- 实测：`pageSize=20, totalPages=568, totalElements=11354`（另一请求口径 500 件）；**无需登录**。
- 首品样例：`id=100354, commodityName="蝴蝶刀（★ StatTrak™） | 传说 (久经沙场)", commodityHashName="★ StatTrak™ Butterfly Knife | Lore (Field-Tested)"`。
- 历史深度：**当前快照，无历史**（页面只翻当前在售）。

### 3. 求购/成交（未实证，登录墙）
- 用户级 API（`bff/user/Account/getUserInfoForApp`、`mailbox/unReadMsgCount`）均返 `code=84101 登录信息已失效`。
- 商品详情路由 `/goods/{commodity_id}` → 页面渲染「啊哦，暂无该页面哟～」（404 语义）；SPA 未在初始加载/滚动/交互后触发任何求购/成交专用 API。
- 正确详情路由（如 `/market/goods/{hash}` 类）本轮未定位；需登录账号 + 浏览器登录态方可继续验证。

### 4. 反爬 / 风控信号
- `/api/deviceW2` 返回**加密设备指纹串**（每次请求携带，疑似风控 token）。
- 登录墙（84101）+ SPA 懒加载；高频直连可能触发限频/风控。

## 三、风险与建议

1. **在售列表采集**：可行。建议**低频**（对齐现有 daily collect 节奏，18:00 每日 1 次全量分页 或 按活跃池筛选），请求头模拟浏览器（Referer/Accept/UA），**验证 deviceW2 是否为必需参数**（若必需，需采集其生成逻辑，风险上升）。
2. **求购/成交**：**需用户决策是否提供悠悠有品登录账号**给采集器（Steam 风控红线不涉及——采集≠交易，但平台账号风控仍需评估）。若提供 → 可继续验证详情路由与求购/成交 API；若不提供 → **挂账**，S2 核心数据（底价在售）不受影响。
3. **不触碰生产**：本次仅预研，未落库（探针只读）。

## 四、S2 采集方案草稿（可采部分）

- **端点**：`GET https://pc-api.youpin898.com/api/homepage/pc/commodity/page?pageNum={N}&pageSize=20`（分页遍历；或按需过滤活跃池商品）。
- **落库**：进 `data/raw.db`（D7 已建 `raw_order_book`）——在售底价/在售量为 S2 模拟成交规则（§4.3 买=底价在售 0 费）提供实时价源；可选增强 `market_snapshot`。
- **频率**：每日 1 次（18:00 窗口，复用 daily collect 链路）。
- **反爬**：浏览器环境 + 低频 + 随机间隔；deviceW2 指纹是否必需待采集实现时实证。
- **求购/成交**：挂账，待用户拍板登录账号后补采（非 S2 硬前置，架构 §4.4「非主口径」）。

## 五、验收对照

- ①预研报告（可采/不可采/风险）：✅ 本文档（在售可采 / 求购成交待登录验证 / 反爬风险已列）。
- ②若可行给 S2 采集方案草稿：✅ 第四节。
- ③不动生产：✅ 探针只读，未落库、未改采集链路。

## 状态

**S1 预研完成（部分可采）**：在售列表可采 → S2 底价在售数据源成立；求购/成交挂「待登录账号决策」。移交③审计复核（复核点：探针证据可复跑、deviceW2 风控影响评估）。
