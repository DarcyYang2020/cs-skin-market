# 260 品池维护手册（F-3.2, 2026-08-08）

目标：把 discover 扩池收敛后的库内品数据维护好（**存量更新**），定期刷新、可追溯、可评估。
当前不做增量扩池；数据积累到一定程度后按本手册「增量更新评估」决定是否需要扩池。

## 1. 口径与收敛基线

- 候选上限 260 = 13 武器 × 每类 20（`webapp/main.py` DISCOVER_WEAPONS）；实际入库数 < 260
  （排除已库 3 天新鲜品、淘汰品、预筛失败品），第三轮收敛后约 190 品。
- 库内品分类：
  - **活跃池**（每日采集）：自选/持仓（豁免必采集）+ notes 为空品，排除「存世量过低」「活跃池淘汰」标记品。
  - **淘汰池**（退出采集，数据保留）：非自选/非持仓且最近 7 天平均在售量 <10 的品（F-3.1）。
- 基线快照在台账首条 type=daily 记录（pool_size/active_pool/pruned），收敛后以当天行为准。

## 2. 完整链路

```
discover 扩池（手动触发，13 武器全量）
  → 排除已库 3 天新鲜品 + 淘汰品 + 存世量过低品 → 候选入库
  → 网络采集立即落库（items + price_history 90 日 K 线，INSERT OR REPLACE 幂等）
  → 每日 18:00 计划任务 CS_Skin_DailyCollect
      ├ 大盘指数 + 宏观情绪（HTTP）
      ├ K 线全量刷新（活跃池每品价格 + 在售量，引擎唯一量源）
      ├ 周度（周一）：全市场快照 + 大户集中度（数据积累用，不消费）
      ├ 活跃池淘汰评估 prune_inactive（<10 退出采集，数据保留）
      ├ 健康检查 run_health_monitor（写 health_checks）
      ├ J-2 三通道监测刷新
      └ 池台账写一行（data/pool_maintenance_log.jsonl）
  → 评分/决策/回测消费 price_history（引擎参数不触碰）
```

## 3. 调度时间表（Windows 计划任务）

| 任务 | 时间 | 内容 |
|---|---|---|
| CS_Skin_DailyCollect | 每天 18:00 | 存量 K 线全量刷新 + 淘汰评估 + 健康检查 + 台账 |
| CS_Skin_NoonMonitor | 每天 12:00 | 监控事件扫描 + 午间推送 |
| CS_Skin_NightPush | 每天 21:30 | 监控事件扫描 + 晚间推送 |
| CS_Health_Alert | 每天 22:00 | 数据健康告警 |
| discover 扩池 | 手动 | 收敛后不再自动触发；评估通过才跑 |

## 4. 台账（data/pool_maintenance_log.jsonl）

一行一条 JSON，追加写、不清理（历史可追溯）。字段：

- type=daily（每日采集收尾）：date、pool_size（库内品数）、active_pool（活跃池）、pruned（淘汰数）、
  kline_ok（K 线刷新成功数）、new_items_today（当日新增）、health / health_fail（健康检查结果）。
- type=prune（淘汰执行）：marked（本次标记数）、min_avg_sale、days。
- type=discover（扩池扫描完成）：task_id、candidates（候选数）、ok/error/skipped、market_th、pool_size_now。

## 5. 淘汰与恢复

- 淘汰条件：非自选/非持仓 + 最近 7 天平均在售量 <10（F-3.1，阈值依据 190 品分布，保守线）。
- 淘汰后：退出每日采集与 discover 捞回；price_history 数据保留。
- 恢复：手动加回自选即恢复采集（无自动复活——淘汰品数据不再更新，自动评估无意义）。

## 6. 增量更新评估（数据积累后决策，不做自动增量）

触发评估的条件（任一面板，人工检查台账即可）：

1. **活跃池萎缩**：pruned 占比 >20%（当前 7/173≈4%），说明池子老化，该考虑补充新候选。
2. **高分品产出骤降**：连续 3 次 discover 扫描 ok 新品数显著下降或 top10 高分品占比下降，
   说明现有池覆盖不足。
3. **K 线新鲜度恶化**：active_pool 中近 4 天有 K 线的品占比 <95%（当前 176/177≈99.4%）。
4. **市场结构变化**：新武器/新收藏品上线（csQAQ 搜索源变化）或重大更新后，评估是否补对应武器。

评估通过才手动触发 discover 扩池（按第 2 节链路，自动排除已库新鲜品与淘汰品）。

## 7. 故障 SOP

- **csQAQ 限流**：采集函数自动等待（API_RATE_LIMIT）；大批量失败时中止当日采集，次日计划任务重跑。
- **串品**：discover 消费前用悠悠锚（DOM 价 + info/good 在售量）双重校验，不合格重取一次，再不行跳过。
- **服务器重启中断扫描**：重启会杀死 in-process 后台任务；discover 支持进度落盘（data/discover_progress_*.json），
  重新触发会因「已库 3 天新鲜品」规则自动跳过已采集品。
- **计划任务失败**：每日采集落 data/daily_collect.log；健康检查写 health_checks 表并由 CS_Health_Alert 告警。
- **排查入口**：台账 JSONL（做了什么）→ daily_collect.log（采集详情）→ health_checks 表（数据体检）。
