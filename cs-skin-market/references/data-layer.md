# 数据层手册（Data Layer）

> 数据层唯一权威文档：数据源、采集链路、每日任务、更新维护、表结构、质量规则。
> 2026-08-08（F-3.3）从 AGENTS.md / PROJECT_STRUCTURE.md 收敛而来，分散描述一律以本手册为准。
> 关联：品池专项维护见 `pool-maintenance.md`；数据源健康检查见 `data-source-health.md`；接口端点清单见 `cs-knowledge.md`。

## 1. 数据源与定价锚

| 数据 | 来源 | 方式 |
|---|---|---|
| 大盘指数 + 品类排名 | csQAQ `/api/v1/current_data?type=init` | HTTP GET |
| 大盘 K 线 | csQAQ `/api/v1/current_data?type=kline` | HTTP GET |
| 单品搜索/详情/90日K线 | csQAQ Playwright 导航 `goods/{id}`，响应拦截 info/chart API | 浏览器自动化 |
| 全市场快照 | csQAQ `get_page_list` 翻页（悠悠锚价+在售数） | 每周一 |
| 大户集中度 | csQAQ `monitor/rank` Top50 | 每周一 |

- **定价锚**: 悠悠有品 (platform=2) > Buff > C5GAME；Steam 价格失真仅参考。
- **量源**: `in_sale_count`（在售量）为唯一量源。2026-08-07 起引擎去成交量，真实成交量采集器与凭据已删除。
- **直连前置**: 需 `POST /sys/bind_local_ip` 绑定公网 IP（每日采集自动重绑）；或访问对应页面拦截 `/proxies/api/v1/*` 响应。
- **浏览器复用**: `_get_browser()` 全局单例，5 分钟超时重建；批量扫描共享单一浏览器会话。

## 2. 采集链路（5 类数据）

```
每日 18:00  CS_Skin_DailyCollect → run_daily_collect.py
  ├ 大盘指数（HTTP）→ market_index
  ├ 宏观情绪（HTTP）→ macro_history
  ├ 单品 K 线全量刷新（Playwright，活跃池每品价格+在售量）→ price_history
  ├ 周度(周一)：全市场快照 → market_snapshot；大户集中度 → monitor_rank_snapshot
  ├ 活跃池淘汰评估 prune_inactive（F-3.1）→ items.notes 标记
  ├ 健康检查 run_health_monitor → health_checks
  ├ J-2 三通道监测刷新 → data/j2_channel_status.json
  └ 池台账写一行 → data/pool_maintenance_log.jsonl（F-3.2）
discover 扩池（手动）→ 候选入库（items + 90日K线，立即落库）
监控事件（12:00 / 21:30 推送前）→ monitor_events
```

## 3. 调度时间表（Windows 计划任务）

| 任务 | 时间 | 内容 |
|---|---|---|
| CS_Skin_DailyCollect | 每天 18:00 | 存量 K 线全量刷新 + 周度快照 + 淘汰评估 + 健康检查 + 台账 |
| CS_Skin_NoonMonitor | 每天 12:00 | 监控事件扫描 + 午间推送 |
| CS_Skin_NightPush | 每天 21:30 | 监控事件扫描 + 晚间推送 |
| CS_Health_Alert | 每天 22:00 | 数据健康告警（FAIL 时钉钉） |
| CS_DB_Backup | 每天 23:30 | SQLite 备份（保留 14 份） |
| discover 扩池 | 手动 | 不做自动增量，按 `pool-maintenance.md` 评估决策点人工触发 |

安装：`powershell -ExecutionPolicy Bypass -File install_tasks.ps1`（cs-skin-market 目录）。

## 4. 更新与维护

- **K 线全量刷新（每日）**: 活跃池（自选/持仓豁免 + notes 空品）每品刷新 90 日 K 线；排除「存世量过低」「活跃池淘汰」标记品。
- **活跃池淘汰（F-3.1）**: 非自选/非持仓且最近 7 天平均在售量 <10 → 标记「活跃池淘汰:在售量过低(<10)」，退出每日采集与 discover 捞回；数据保留，加回自选恢复采集。
- **池台账（F-3.2）**: `data/pool_maintenance_log.jsonl` 一行一条 JSON（daily/prune/discover 三类），追加不清理。
- **健康检查**: `run_health_monitor.py` 随每日采集收尾执行，写 `health_checks`；`notify_alert.py --monitor` 在 FAIL 时推送告警。
- **DB 备份**: `backup_db.py`（SQLite online backup → `data/backup/market_YYYYMMDD_HHMMSS.db`，保留 14 份）。
- **J-2 监测**: 每日刷新 `data/j2_channel_status.json`（B 通道天数）。
- **保留策略**: price_history / snapshots / market_index 365 天；scan_*.md 90 天；debug 7 天；台账与备份按各自规则。

## 5. 数据库表（market.db）

| 表名 | 用途 | 关键字段 |
|---|---|---|
| items | 品池（自选/持仓/活跃池/淘汰池） | name, good_id, weapon, skin, wear, source, notes, in_watchlist, holding |
| price_history | 单品价格历史（唯一量源） | item_id, date, price_rmb, in_sale_count |
| market_index | 大盘指数历史 | date, value, change_7d, mood |
| macro_history | 每日宏观快照（贪婪指数/点卡价） | date, greedy_index, card_price |
| snapshots | 分析报告存档 | item_id, date, grade, total_score, report_html, action |
| market_snapshot | 全市场周度快照 | date, good_id, yyyp_sell_price, yyyp_sell_num |
| monitor_rank_snapshot | 大户集中度每周 Top50 | date, item_id, rank, num |
| monitor_events | M1 监控事件归档（近 7 天） | date, item_id, event_type, level, detail |
| positions | 持仓记录 | item_id, buy_price, quantity, closed, close_price |
| executions | 执行记录+复盘（F-1/F-2） | item_id, action, advice_date, exec_price, settle_14/30, pnl_14/30 |
| signal_tracking | 生产 buy 信号跟踪（J-2 C 通道） | signal_date, entry_price, engine_version, fwd14/30, net14/30 |
| health_checks | 数据源健康检查 | date, status, checks_json |
| backtest_results | 回测结果 | strategy, sharpe_ratio, max_drawdown_pct |
| settings | 配置键值对 | key, value |
| schema_version | schema 版本记录 | version, applied_at |

## 6. 数据质量与过滤规则（不动信号算法）

- **StatTrak/纪念品排除**: 自动排除 `StatTrak™` 和纪念品版本；`（★）` 普通标记不过滤。
- **快照 `_keep_wear`**: 枪皮/刀仅崭新出厂，手套仅略磨+久经，无磨损品类（印花/箱/胶囊）保留。
- **存世量过低**: 崭新出厂存世量 <3000 → 不建仓（`survive_too_low`）；口径为 `info/good` 的 `statistic_list`（非 `buff_sell_num`）。
- **串品防护**: discover 消费前用悠悠锚（DOM 价 + info/good 在售量）双重校验，不合格重取一次，再不行跳过。

## 7. 故障 SOP

- **csQAQ 限流**: 采集自动等待（API_RATE_LIMIT 1.1s）；大批量失败中止当日，次日 18:00 重跑。
- **服务器重启中断扫描**: discover 进度落盘（data/discover_progress_*.json），重触发按「已库 3 天新鲜品」自动跳过已完成。
- **计划任务失败**: 排查顺序 —— 台账 JSONL（做了什么）→ data/daily_collect.log（采集详情）→ health_checks 表（数据体检）。
- **数据不一致**: 以本手册为准；发现 AGENTS.md / PROJECT_STRUCTURE.md 与新口径冲突时修正对应文档并在此追加记录。
