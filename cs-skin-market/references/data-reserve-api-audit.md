# 直连 API 数据储备：可行性核验与立项清单

日期：2026-08-13
状态：只读核验完成；P0/P1 首批已落库（研究层），未改引擎参数
用途：交给产品侧做数据储备立项/排期

## 一、结论摘要

直连 API 确实可以稳定拿到一批系统当前未持续储备的数据，且优先级清晰：

- **最高优先**：`info/good` 基本面快照、`info/chart` 的求购价/求购量 90 日历史、`info/good/statistic` 存世量 180 日历史。
- **次高优先**：`monitor/rank` 大户集中度、`info/get_series_list` 系列/板块资金与动量。
- **全市场储备**：`info/get_page_list`、`info/get_rank_list` 可用于 discover/估值分布，但先做活跃池即可。
- **不可用/暂缓**：`get_all_goods_*`、`get_popular_goods`、`get_goods_template`、`container/containers` 实测 401，暂不立项。

这些数据都不直接改引擎权重、阈值或信号族，只作为研究样本与未来特征储备。

## 二、实测接口口径核验

| 端点 | 方法 | 实测 | 有效字段 | 口径结论 |
|---|---|---|---|---|
| `/info/good?id=` | GET | 200 | `goods_info` 96 字段、`statistic_list`、`container`、`is_collection` | 可用。`buff_sell_num` 是 Buff 挂单数，不是存世量；存世量看 `statistic`。 |
| `/info/good/statistic?id=` | GET | 200 | 180 条 `{statistic, created_at}` | 可用。示例 good_id=67：2026-02-14 至 2026-08-13，82704→85410，趋势合理。 |
| `/info/chart` + `key=buy_price` | POST | 200 | 546 个 10 分钟点 | `platform=2` 返回悠悠求购价，不是 Buff。示例 last≈104，与 `yyyp_buy_price≈102` 一致，与 `buff_buy_price≈106` 接近但平台口径不同。 |
| `/info/chart` + `key=buy_num` | POST | 200 | 546 个 10 分钟点 | `platform=2` 返回悠悠求购量。示例 last≈49，匹配 `yyyp_buy_num≈46`，明显不同于 `buff_buy_num=109`。 |
| `/info/chart` + `key=sell_price/sell_num` | POST | 200 | 546 个 10 分钟点 | 与当前引擎一致；last 在售价/在售量匹配 `yyyp_sell_price/yyyp_sell_num`。 |
| `/info/get_series_list` | POST | 200 | 64 个系列，含 1/7/15/30/90/180 涨跌、`amount`、`total_value`、`recently_data` | 可用。是“皮肤系列/赛事贴纸/手套系列”面板，不是五板块资金指数；做系列轮动与市场宽度储备。 |
| `/monitor/rank` | POST | 200 | 单品持有量 Top 榜，`steam_name/steam_id/num` | 可用。`num` 为持有件数；good_id=67 返回 393 条。适合集中度/庄盘研究，注意隐私与存储。 |
| `/info/get_rank_list` | POST | 200 | 需 `page_index/page_size`；含多平台 buy/sell/租赁价、涨跌 | 可用。适合全市场排名与跨平台估值分布储备。 |
| `/info/get_page_list` | POST | 200 | 需 `page_index/page_size`；含悠悠价/在售数 | 可用。现有快照已用浏览器实现，可迁移直连。 |
| `/info/chart` + `key=turnover_number` | POST | 404 | 无 | 成交件数不能从 chart 拿，应从 `info/good.turnover_number`。 |
| `/goods/get_all_goods_info`、`/goods/get_all_goods_rank`、`/info/get_popular_goods`、`/goods/get_goods_template`、`/container/containers` | POST | 401 | 无 | 当前 token/权限不可用，不立项。 |

## 三、量化/引擎视角的价值矩阵

| 数据 | 对系统的直接用途 | 量化优先级 | 工程风险 |
|---|---|---|---|
| 悠悠求购价/求购量 90 日历史 | BID-1、F-2、SUPPLY-CONF-1、A1-4 滑点校准、盘口深度 | 高 | 需要新表；当前 `order_book` 只在单品分析时采集，discover 多为 NULL。 |
| `info/good` 全量基本面 | 跨平台价差、涨跌率、炼金/收藏/磨损元数据、热度排名 | 高 | 字段多，需控制落库口径，避免污染现有 `items`/`price_history`。 |
| 存世量 180 日序列 | 存世量闸门、供给冲击、稀缺度研究 | 高 | 当前 `survive_count` 只存单值，需新增序列表。 |
| 大户持有量 Top 榜 | 庄盘/集中度、吸筹异动 | 中高 | 单请求返回几百条；按活跃池每日采会加大请求量，建议周度或抽样。 |
| 系列资金/动量面板 | 板块轮动、市场背景、赛事贴纸/手套/收藏品宽基 | 中 | 单请求 64 系列，成本低；但需要明确与五板块指数的口径边界。 |
| 全市场排名/列表 | discover 扩展、估值分布、跨平台排序 | 中 | 全量分页成本较高；先做 Top N/活跃池过滤。 |

## 四、建议立项优先级

### P0：活跃池基本面 + 求购历史（第一批）

**采集对象**：当前活跃池 202 品。

**每日新增**：

1. `GET /info/good?id=`，存 `item_fundamental_snapshot`。
2. `POST /info/chart`，`key=buy_price`，`platform=2`，存 `bid_history`（悠悠求购价）。
3. `POST /info/chart`，`key=buy_num`，`platform=2`，存 `bid_history`（悠悠求购量）。

**成本**：约 `202 × 3 = 606` 次请求；按 1.5s 节流约 15 分钟，可并入现有每日采集或拆成独立低峰任务。

**工程要求**：新表、独立回填脚本、失败台账、可回滚；不写回 `price_history`，不改引擎消费。

### P1：存世量 + 集中度 + 系列面板（第二批）

**采集对象**：活跃池 + 自选/持仓。

1. `info/good/statistic` 周度或每日，存 `survive_history`。
2. `monitor/rank` 周度，只存 Top20/Top50，存 `holder_rank_snapshot`。
3. `info/get_series_list` 每日一次，存 `series_snapshot`。

**成本**：显著低于 P0；优先接自选/持仓，再扩展到活跃池。

### P2：全市场储备（第三批）

1. 把 `collector_snapshot.py` 从浏览器迁移到 `info/get_page_list` 直连。
2. 每日或每周用 `info/get_rank_list` 采集 Top N 排名，存 `market_rank_snapshot`。
3. 未来若要扩大 discover 池，再按分页逐步扩充。

**前置条件**：确认产品是否接受全市场表规模、保留策略与请求预算。

## 五、口径偏差与风险

- **平台口径**：`info/chart` 的 `buy_price/buy_num` 在 `platform=2` 下是悠悠口径；不能与 Buff 求购字段混用。落库必须带 `platform` 字段。
- **存世量与挂单数**：`statistic`/`statistic_list` 是存世量；`buff_sell_num`、`yyyp_sell_num` 是在售挂单数。不得复用 2026-08-04 的旧错误。
- **成交字段**：`info/good.turnover_number/turnover_avg_price` 更接近 Steam 成交口径（示例价格约 16.3，按美元约合 117 RMB，与悠悠/Buff 人民币价接近）。在未与官方确认前，只做研究观察，不进入引擎。
- **求购量波动**：`buy_num` 是快照级盘口深度，单点可能跳变；做因子前必须聚合/去噪，且样本不足前不接 buy。
- **隐私与存储**：`monitor/rank` 含 Steam 名/ID/头像，立项需确认存储最小化与保留策略。
- **限流**：直连稳定但仍有 429；所有批量采集必须沿用 1.5s 节流、指数退避、失败台账与“先备份、可回滚”纪律。

## 六、建议产品排期

1. 第一周：立项 P0，定义三张新表 schema 与保留策略；写采集脚本，先跑 1 天 dry-run，不写引擎。
2. 第二周：P0 每日任务灰度 3 天，核对与 `info/good`/`info/chart` 锚的一致性；同步 `data-layer.md`。
3. 第三周：启动 P1 的存世量与系列面板；`monitor/rank` 先只对自选/持仓周度采集。
4. P2 等 P0/P1 稳定、产品确认全市场预算后再启动。

所有新增数据先进入研究层，不进评分/决策层；是否接引擎由后续 A2 或专项验证决定。
## 七、产品侧排期（PM 定稿，2026-08-13）

> 采用“研究层优先、不接引擎、先小后大”的排期；与 `iteration-roadmap.md` v58 联动。任何因子/特征接引擎必须另行 A2 + 三件套。

### 排期结论
1. **立即启动 P0（D0-D7）**：只做 schema + dry-run，不写生产表。优先级高于 P1/P2。
2. **P0 灰度（D8-D14）**：独立低峰任务跑 3-5 天，验证与现有锚一致性；通过后再进每日任务。
3. **P1（D15-D30）**：存世量 180d 与系列面板先接自选/持仓，`monitor/rank` 周度 Top20；隐私最小化。
4. **P2（暂缓）**：等 P0/P1 稳定 30 天 + 产品确认全市场表预算，再单独立项。
5. **引擎接入（无排期）**：BID-1 / F-2 / SUPPLY-CONF-1 / A1-4 是否用这些数据，由既有 2026-11-09~13 判定窗口或专项 A2 决定。

### 关键产品决策
- **P0 落库口径**：`item_fundamental_snapshot` 只存活跃池 + 自选/持仓，字段只保留与现有 `items`/`price_history` 不冲突的子集；不写回引擎表。
- **`bid_history` 存储口径**：10 分钟原始点默认不落主库；只落 `date + good_id + platform=2` 的日聚合（last/min/max/mean/count + buy_price/buy_num）。若未来需要盘口深度，再开 7 天滚动原始区。
- **平台标记**：所有新表强制 `platform=2` 与 `source='csqaq_direct'`，与 Buff 口径隔离；防 2026-08-04 旧错误。
- **限流**：P0 与每日 18:00 K 线错峰；先跑 dry-run 与低峰独立任务，429 时指数退避 + 台账。

### 上线门禁
- P0 入每日：连续 3 天覆盖 active pool ≥95%，`bid_history` 日聚合完整率 ≥95%，平台标记 100%，无引擎表写。
- P1 入每日/周度：`survive_history` 自选/持仓覆盖 100%，`monitor/rank` 周度成功，存储增长在 `data-layer.md` 增长预算内。
- 任一失败：只告警不接引擎，先回滚/修复；不触发回放/引擎变更。

### 与现有项目关系
- P0 直接缩短 BID-1 / SUPPLY-CONF-1 / LIQ-1 的求购与 spread 样本等待，但数据门禁不变。
- P1 为存世量闸门、庄盘/集中度、系列轮动研究供数，不改变当前 201 品主引擎口径。
- P2 暂不占用 csQAQ 预算，避免与主引擎采集竞争。

## 八、落地进度（2026-08-13）

> 研究层优先，不接引擎。数据仅进新表，不写 items/price_history；所有改动均未 commit/未分支/未 push。

- **P0 完成**：`collect_data_reserve_p0.py`；`item_fundamental_snapshot` 202 品（date=2026-08-13），`bid_history` 18,381 行（2026-05-15~至 2026-08-13，日聚合）。
- **P1 完成**：`collect_data_reserve_p1.py`；`survive_history` 195 个有效品×180天=35,100 行（7 个武器箱/角色/挂件/印花类型 API 返回空序列）；`series_snapshot` 64 行；`monitor_rank_snapshot` 自选/持仓 43 品 Top20=860 行（date=2026-08-13）。
- **schema**：`SCHEMA_VERSION` 3→4；备份 `data/backup/market_20260813_231242.db`（P1）、`data/backup/market_20260813_222205.db`（P0）。
- **验证**：`python tests/test_smoke.py` 104 passed / 0 failed / 0 skipped；`pyflakes pipeline/db.py collect_data_reserve_p0.py collect_data_reserve_p1.py` 0 新告警。
