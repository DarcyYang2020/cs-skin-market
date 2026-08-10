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
- **K 线写库（2026-08-10 B-1 增量写）**: `save_price_history_batch` 默认 `incremental`——只写「date > 库内 max(date)」的新行 + 当日最新行更新，历史行不可被覆盖（单次坏 chart 只污染当日行，防 8/9 串品事故复发）；变更记 `data/price_history_write_log.jsonl`；审计回填/串品修复用 `mode="force"` 全量覆盖（须人工确认）。
- **活跃池淘汰（F-3.1）**: 非自选/非持仓且最近 7 天平均在售量 <10 → 标记「活跃池淘汰:在售量过低(<10)」，退出每日采集与 discover 捞回；数据保留，加回自选恢复采集。
- **池台账（F-3.2）**: `data/pool_maintenance_log.jsonl` 一行一条 JSON（daily/prune/discover 三类），追加不清理。
- **K线失败台账（G-4, 2026-08-10）**: `collect_kline_all` 返回失败品清单，每日台账写 `kline_fail_count` / `kline_fail_names[:10]`（品名+原因），便于告警排查；采集可疑重试/平台切换前退避 1.5s 降限流压力。
- **健康检查**: `run_health_monitor.py` 随每日采集收尾执行，写 `health_checks`；`notify_alert.py --monitor` 在 FAIL 时推送告警。
- **DB 备份**: `backup_db.py`（SQLite online backup → `data/backup/market_YYYYMMDD_HHMMSS.db`，保留 14 份）。
- **J-2 监测**: 每日刷新 `data/j2_channel_status.json`（B 通道天数）。
- **保留策略（2026-08-09 落地，`pipeline/db.py:run_retention_cleanup`）**: price_history / snapshots / market_index / monitor_events 365 天；scan_*.md 旧报告 90 天；进度文件（scan_progress_*/discover_progress_*）7 天；scan_history JSON 保留最近 30 份；monitor_rank_snapshot 为研究型积累不清理。清理由批量扫描收尾与每日任务自动执行（含 VACUUM）；台账与备份按各自规则。

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
| executions | 执行记录+复盘（F-1/F-2） | item_id, action, advice_date, exec_price, settle_14/30, pnl_14/30, source（D-3: manual / push:{push_id}） |
| signal_tracking | 生产 buy 信号跟踪（J-2 C 通道） | signal_date, entry_price, engine_version, fwd14/30, net14/30 |
| health_checks | 数据源健康检查 | date, status, checks_json |
| analysis_results | 分析报告缓存（单品/批量扫描共用，按 name 覆盖） | name, price_rmb, grade, trend_dir, trend_score, report_html |
| backtest_results | 回测结果 | strategy, sharpe_ratio, max_drawdown_pct |
| settings | 配置键值对 | key, value；monitor_push_* 幂等值升级 JSON（D-3 含 push_id/items，旧值 "1" 兼容） |
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

## 8. 数据审计方案（全库核查 SOP）

> 适用：怀疑价格/在售量历史段被污染（串品、脏段）时，对数据层做全量核查与修复。
> 首次执行：2026-08-09（188 品逐品实拉），结论与修复清单见 `decision-log.md`「全库数据审计 + 混合回放重跑」。

### 触发场景
- 分析报告/信号复盘收益与实盘明显不符（如「至今收益」与回放 `fwd_series` 末端价对不上）。
- 每日采集后部分品价格整段偏离（8/8 曾因 DOM 价选择器失效 → price_rmb=0 → 串品 chart 误入，8/9 起采集器已有锚兜底）。
- 回放产物中 entry 与 DB 同日价偏差 >15% 的条数增多。

### 审计步骤（逐品实拉）
1. **快照备份**：先备份 `data/market.db`（复制为 `market.db.bak-<日期>`），保证修复全程可回滚。
2. **逐品实拉**：对全部 items 逐个用纯悠悠 platform=2 锚（info/good 的 yyyp_sell_price + yyyp_sell_num）重取真实 chart90（91 天 close + in_sale），与 `price_history` 逐日对齐，计算整段 medP/medS 偏差。
   - 首轮抓取空（EMPTY）→ 重试一轮（复用浏览器会话）；仍空（低流动性/页面异常）保留 DB 原值待人工复核。
3. **判定分类**：
   - OK：与实时 chart 一致（2026-08-09：147/188）。
   - FIXED：DB 整段明显偏离实拉值 → 判定脏段，回填。
   - 串品：价格整段高 27-43% + 在售量错 92-22900%（8/8 火卫一事件特征），需同时查采集器根因。
   - SALE 偏差：sale 端差 30-80% 属平台流动/表达差异，**非数据错误**，不修复。
4. **回填**：`UPDATE price_history` 仅改 price_rmb + in_sale_count，保留 volume/created_at；原值备份 `data/_batch_repair_backup.json`。
5. **根因修复**：补齐采集器兜底（8/9：DOM 价失效时回退 info/good `yyyp_sell_price`，见 `collector_csqaq.py`），防再次串品。
6. **重新分析**：修复品重跑 `/api/items/analyze` 刷新 `analysis_results`，持仓/自选页面即时生效。

### 回放联动（数据修复后必做）
数据层变更会改变回放产物，必须按序重跑（「回放同源，改产物必须重跑同步」纪律）：
1. **构建混合回放库**：`data/replay_hybrid.db` = 修复后现库 + 历史备份（`market.db.bak-p0-*`）补 2025-01-01 起 price_history 与 market_index（2026-08-09：插入 21292 + 631 行，共 65106 行）。
2. **重跑回放**：`$env:CS_MODEL_DB=<混合库绝对路径>; python references/run_item_backtest_full.py`（约 10 分钟，96 品，runner 已归档至 `references/scripts-archive/`，加载路径脚本内已兼容）。
3. **校验**：信号数应接近 370；受影响信号 entry ≈ DB 同日价；偏差 >15% 条数（2026-08-09：24 → 0）。
4. **同步**：`python references/sync_expectancy_config.py`（config.ITEM_EXPECTANCY_STATS + signal_event_counts + J-3）→ `python references/sync_replay_snapshot.py`（回放快照）。
5. **验证**：冒烟测试全绿（2026-08-09：84 passed / 6 skipped）。

### 审计证据留存
| 文件 | 内容 |
|---|---|
| `data/_audit_repair_sweep.jsonl` | 188 品主扫（OK/EMPTY/FIXED 状态 + 偏差段数） |
| `data/_audit_repair_retry.jsonl` | 首轮空品重试结果 |
| `data/_audit_chart_sweep.jsonl` | 逐品 chart 抓取明细 |
| `data/_audit_anchor_sweep.jsonl` / `_audit_anchor_issues.json` | 锚点校验明细 / 问题清单 |
| `data/_batch_repair_backup.json` / `_awp_ph_backup.json` | 8/8 批量回填原值备份 |
| `data/item_backtest_full_2025.json.bak-preaudit-20260809` | 审计前回放产物备份（对比用） |

### 2026-08-09 实例结果（速览）
- 188 品：147 OK / 34 重试后 OK2 / 1 仍空（法玛斯 对比涂装，低流动性淘汰品）。
- 7 品实修复：MP9 气密(86 段)、加利尔 蓝钛(87 段)、MP7 地下水(66 段)、USP 守护者(4 段)、USP 地狱门票(17 段)、沙漠之鹰 青铜装饰(14 段)、AK 精英之作崭新出厂(1 段)。
- 无 SAP/整体性错误；气密 5-6 月脏段（350-385）回真实 200-300 档。
- 回放联动后：369 信号 entry 与 DB 同日价偏差 >15% 由 24 条 → 0 条。

### 约束
- 只动数据层/展示层/文档；评分与决策参数改动须回测先行 + 三件套记录 + 文档同步（2026-08-10 起无冻结禁令）。
- 回放产物变更后必须重跑 sync（`t_expectancy_sync` / `t_replay_snapshot` 硬校验防漂移）。
