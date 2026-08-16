# cs-skin-market

CS 饰品市场投资分析工具。FastAPI Web 应用，从 csQAQ 采集大盘/单品数据（价格 + 在售量 in_sale_count），跑六维度评分 + 趋势健康度 + 融合决策模型，输出买卖建议。数据存 SQLite（`cs-skin-market/data/market.db`）。

> **2026-08-07 去成交量（v2）**：引擎彻底放弃真实成交量方向，改为「在售量 + 价格」双核心（决策见 `references/decision-log.md` 2026-08-07 条目，回测见下文）。悠悠有品成交量采集器（collector_youpin.py）与登录凭据（uu_headers.json）已于 2026-08-07 删除。

## 唯一入口

`cd cs-skin-market && python run_server.py`，访问 http://127.0.0.1:8000/

所有功能通过 Web 界面操作，无 CLI。

## 数据采集

数据层完整手册见 `cs-skin-market/references/data-layer.md`（数据源/采集链路/每日任务/表结构/维护/故障 SOP）。

- **量源**: csQAQ chart API 的 `in_sale_count`（在售量）为引擎唯一量源；2026-08-07 起去成交量，真实成交量采集器已删除。
- **定价锚**: 悠悠有品 (csQAQ platform=2) > Buff > C5GAME，Steam 价格失真仅参考。
- **StatTrak/纪念品**: 自动排除，仅分析普通版；采集函数共享单一浏览器会话。
- **每日任务**: 18:00 `run_daily_collect.py`（Windows 计划任务 `CS_Skin_DailyCollect`）全量刷新活跃池 K 线 + 淘汰评估 + 健康检查。

## 命名规则

- `FN57` = Five-SeveN（武器型号），勿与磨损 `FN`（Factory New）混淆
- 注意区分 `( )` 半角括号与 `（ ）` 全角括号

## 评分模型

### 基础评分（`compute_value_score`，item_analysis.py）

| 因子 | 权重 | 说明 |
|---|---|---|
| 位置 | 40% | 90日分位越低越有价值 |
| 周期 | 25% | 洗盘 > 吸筹 > 拉升 > 出货（2026-08-10 反转，365d 回放洗盘期最优） |
| 流动性 | 15% | 在售深度 50% + 价格稳定 50%（2026-08-07 去量重写，原「成交量40%+价差30%+在售30%」废弃） |
| 概率 | 20% | 涨跌概率修正（波动率 regime 主导：低波延续高、高波中性偏弱；2026-08-10 去 z 化消除与位置双计权） |

大盘/情绪不进入基础分，通过融合决策层进入（见下）。

### 融合决策（`decide_fusion_signal`）

- 入口：`compute_fusion_decision`（trend_health）产生初始 buy/watch/avoid
- 升级族1：恐慌共振（守卫1 后评估）
- 后置族（固定优先级）：深值·大盘企稳 > 恐慌退潮 > 供给收缩吸筹
- 闸门链：守卫1（大盘走弱/存世量/半山腰/7天去重/飞刀）→ 守卫2（微型TH/求购/Z门/大盘出货/连买抑制）→ 供给扩张过滤（`_g_supply_expansion`：在售量30日扩张>5% 禁买）→ 族级闸门
- I-13（2026-08-07 去量回测验证）：深值族仅在大盘 30 日涨跌 `mchg30<=-3`（企稳/修复环境）触发；`mchg30>=3` 上涨段 93 信号 14d 仅 44% 胜率/+2.2（跨10月40品，基线与去量版同款）→ 剔除
- 深度回调低吸例外（P0-7b）：周期吸筹 + 大盘21日跌幅>-18% 时，需 dd30<=-22% + chg14<=-6% 才豁免

评级（10 分制，2026-08-10 同步）：S>=8 / A 6.5-7.9 / B 4.5-6.4 / C<4.5

### 趋势分析（`trend_health.py`）

7/30/90日价格动量、MA7/MA30 均线交叉、7日波动率、供给×价格信号（`_dim_supply_price`：涨+供缩=吸筹配合 / 涨+供扩=派发嫌疑 / 跌+供扩=抛压）。五维权重：持续性22% / 陡度22% / 均线结构22% / 供给×价格16% / 异常缺口18%。趋势得分 -1.0 ~ +1.0。

### 供给分析（`supply.py`）

在售数量 7/30日变化率、供给趋势、吸筹检测（供给收缩+价格稳定/上涨）、派发检测（供给扩张+价格持平/下跌）。供给得分 -0.3 ~ +0.3。

### 估值分位（`valuation.py`）

30日/90日百分位排名、Z-score、估值标签（低估/合理/高估/泡沫）。

### 超跌买入例外 (P0)

当标准融合决策无法触发 buy 时，额外检查超跌反弹：
- pct<=15% + Z<=-2.0 + 跌速衰减(no_new_low2 + chg3d>0%) → 超跌反弹·分批建仓
- 回测: 早期预研 2025-11~2026-07 buy 16次 / 14d 88% / +9.65%（见 `references/engine-unified.md`）
- 数据见 `cs-skin-market/data/item_backtest_full_2025.json`（2026-08-10 去量 v2 引擎 365d 窗口 317 信号回放）；对比文件 `baseline450`（96品池原引擎）/ `devol_v1`（去量 v1）保留在 data/ 下（devol_v2 与 item_backtest_full_2025.json 内容一致，已删除）

### 参数拟合建议

不需要定期拟合。触发重新验证的场景（J-2 三通道，任一满足）:
1. A 通道: 独立恐慌市场事件 ≥3（当前 2 个，自然积累）
2. B 通道: 积累完整牛熊循环（~260天新数据，约 2027-04-25）
3. C 通道: 胜率+期望监测——buy 连续2月14d胜率<70%（胜率下限）或月度期望转负；月度 14d<80%/30d<55% 为附加下限

### 参数治理（2026-08-10 解除冻结期）

引擎参数不再有冻结禁令：`pipeline/config.py` 的 `PARAM_REGIME` 维护参数台账（去量引擎 v2（I-13）全参数、组合层 cap0.8、
单票敞口提示 30%、`ITEM_EXPECTANCY_STATS` 展示口径、proximity 深跌确认、守卫1 大盘走弱拦截、四项审计落地（周期反转/panic 分级修复/概率去 z，2026-08-10）、north_star 主指标（期望+Calmar/maxDD，胜率为下限，2026-08-14））。参数迭代纪律 =
回测先行 + 三件套记录（信号数/期望/风险调整后收益增量，胜率作下限）+ 文档同步；新信号族须过 A2 三件套（walk-forward + 聚类 + 置换检验）。
A2 第五件套（2026-08-16 起，候选族准入硬门槛）：发射分布复算（`cs-skin-market/references/a2_emission.py`，对「族开」vs「基线」回放产物做实际发射信号的 walk-forward + 对现存买书的置换检验）；数据层 A2 数字仅作初筛。
J-2 三通道监测数据照常收集：A 独立恐慌事件≥3 / B v2 样本积累 260 天（约 2027-04-25）/ C 胜率+期望监测（buy 连续 2 月 14d<70% 或月度期望转负；
月度 14d<80%、30d<55% 为附加下限），作为样本完整性与胜率/期望健康度提示项；监测见 data/j2_channel_status.json。

**期望统计单一事实源**：`data/item_backtest_full_2025.json`（回放产物）→
`python references/sync_expectancy_config.py` 自动同步 `config.ITEM_EXPECTANCY_STATS` 与进度卡 J-3
（`data/signal_event_counts.json`），`t_expectancy_sync` 全字段硬校验防漂移。

**基准对照**：`python references/benchmark_compare.py` 产出 `data/benchmark_compare.json`
（策略 cap0.8 vs 池内等权买入持有 vs 大盘指数，full/active 双窗口）。2026-08-10 结论（365d 窗口，317 信号，组合模拟口径 hold21——2026-08-10 对齐单品 hold_guidance，见 decision-log）：策略 +200.55%/-9.13%
大幅跑赢大盘 -24.20%/-58.21%，但低于池内等权 +252.32%/-55.59%——引擎边际价值在风险控制（maxDD 9.13% vs 55~58%）。


## 文件结构

> 文件结构唯一事实源：`cs-skin-market/PROJECT_STRUCTURE.md`。本文不再复制文件树，也不再标注代码行数；仅保留启动入口与关键口径。

## Web API 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | / | 大盘仪表盘 |
| GET | /search | 单品搜索分析 |
| GET | /watchlist | 持仓管理 |
| POST | /api/market/refresh | 刷新大盘数据 |
| POST | /api/items/search | 搜索并分析单品 |
| GET | /api/items/analyze | 单品分析 |
| POST | /api/watchlist/add | 添加自选 |
| GET | /api/watchlist/{id}/analyze | 自选单品分析 |
| GET | /api/watchlist/{id}/report | 查看分析报告 |
| POST | /api/watchlist/assets | 设置资产规模 |
| POST | /api/watchlist/batch-scan/selected | 批量扫描（异步） |
| GET | /api/watchlist/batch-scan-progress/{id} | 批量扫描进度 |

批量扫描结果展示为 HTML 汇总面板（`data/batch_scan_latest.json`）+ 历史归档（`data/scan_history/scan_*.json`，保留最近 30 份），含总览表、每物品详情（名称行显示采集时间、评分列显示综合评分）；2026-08-11 起：结果按综合评分降序（与发现高分品 Top10 同口径）；移除“建议”列与“市场环境”卡片（用户点击物品名查看完整报告）；每条记录右侧提供行级“⚡ 刷新”（`POST /api/watchlist/batch-scan-item-refresh`，单品强制联网重采+重算后重排）；不再生成 scan_*.md 报告。

## 数据保留策略

- price_history、snapshots、market_index、monitor_events：保留 365 天；scan_*.md 旧报告 90 天；进度文件（scan_progress_*/discover_progress_*）7 天；scan_history JSON 保留最近 30 份；monitor_rank_snapshot 为研究型数据积累不清理；池台账 `pool_maintenance_log.jsonl` 不清理。
- 清理由批量扫描收尾与每日任务（run_daily_collect.py）自动执行（`pipeline/db.py:run_retention_cleanup`，含 VACUUM）；完整口径见 `cs-skin-market/references/data-layer.md`。

## 常见坑

- 英文搜索名可能返回不同皮肤，优先用中文名
- 文件名不能包含 `|` 等特殊字符，已自动消毒
- Windows 终端 GBK 编码问题，已设置 stdout UTF-8
- 2026-08-07 起引擎去成交量：真实成交量（悠悠有品）不再参与评分/决策；`collector_youpin.py` 与 `data/uu_headers.json` 已删除（2026-08-07 终审）
- `bar.date` 必须为 YYYY-MM-DD 格式才能与在售量/回测日期对齐
- 批量扫描需在有网络的环境运行（宿主机直连）
- 详细模块说明见 `cs-skin-market/AGENTS.md`
