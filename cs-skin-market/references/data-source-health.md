# 数据源健康检查（Data Source Health Check）

> 创建: 2026-08-04 | 用途: 不定期检查各数据源正确性，防止脏数据 / 错误数据使用
> 触发场景: 每日自动（run_daily_collect 收尾，2026-08-07 起）或 批量扫描结果异常 / 用户反馈数据不对时

---


## 自动化运行方式（2026-08-05 A1）

> 2026-08-05 起由 run_health_monitor.py 自动执行并把结果持久化，替代人工不定期跑。

### 1. 入口与退出码

```bash
cd cs-skin-market
python run_health_monitor.py            # 人类可读摘要，退出码 0/2（与 run_data_health 一致）
python run_health_monitor.py --json     # JSON 输出（供告警/日志系统）
```

退出码语义：
- 0 = 全部通过（无 FAIL）
- 2 = 存在 FAIL，需人工核查

### 2. 结果持久化（health_checks 表）

每次运行把结果 upsert 进 SQLite `health_checks` 表（pipeline/db.py `_init_schema` 建表，按 date 每天一条覆盖）：

| 列 | 说明 |
|---|---|
| id | 自增主键 |
| date | 检查日期（YYYY-MM-DD，唯一，同日重复运行覆盖）|
| status | pass / warn / fail（任一检查 FAIL → fail）|
| checks_json | 检查明细 JSON：[{name, level, detail}]（level ∈ PASS/FAIL）|
| created_at | 写入时间 |

### 3. 自动触发

- **每日采集收尾**：`run_daily_collect.py` 结尾自动调用 `run_health_monitor.run_monitor()`，失败仅记录日志、不中断采集主流程（现有 Windows 计划任务即覆盖本检查）。
- **独立调度**（可选告警）：另建计划任务运行 `python run_health_monitor.py`，以退出码 0/2 判定健康状态。

### 4. Web 展示

- `GET /api/health/status`：返回最新一条 health_checks（date/status/created_at/checks/fail_list/fail_count）。
- 大盘仪表盘 `/` 新增「数据健康」卡片：最新状态（PASS/WARN/FAIL 徽标）+ 最近检查时间 + FAIL 项摘要。

---

## 检查方式总览

| 数据源 | 检查方法 | 关键验收点 |
|---|---|---|
| 大盘指数 | 直连 csQAQ API 或对比库内最新值 | 值>0，change_7d 与当日行情一致，mood 三态 |
| 单品 K 线 | 库内 price_history 覆盖 | 每日历史有在售量品（动态，当前约 103 品）≥85%，最新日期为当日/前一日 |
| 在售量 | 库内 in_sale_count | 近7日每日 ≥90% 品有在售量（csQAQ chart 自带，无登录态依赖） |
| 贪婪/卡价 | macro_history | greedy 60 点 / card 179 点 |
| 全市场快照 | market_snapshot | 周度（周一）采集，最新日行数≈1468（磨损过滤后），无 StatTrak/纪念品残留 |
| 大户集中度 | monitor_rank_snapshot | 周度（周一）采集，最新日约 100 品 / 8234 行，抽查与已知大户一致 |
| items 元数据 | items 表 | 无 good_id=0 的采集品，无重复 good_id，存世量过低品已打标 |

---

## 一、库表完整性检查

### 1. 大盘指数（market_index）

```sql
SELECT date, value, change_7d, mood FROM market_index ORDER BY date DESC LIMIT 3;
```

验收：
- 最新 date = 当日（工作日）
- value > 1000（指数正常范围）
- mood ∈ {恐惧, 中性, 贪婪}
- 若 mood 出现乱码或 neutral（英文），说明写库编码问题

### 2. 单品 K 线（price_history）

```sql
SELECT date, COUNT(*) n, COUNT(DISTINCT item_id) items
FROM price_history WHERE date >= date('now','-7 day') GROUP BY date ORDER BY date;
```

验收：
- 历史有在售量的品应每天有 K 线（2026-08-07 Phase 1b: 基线从自选品改为动态"历史覆盖品"，阈值 85%，修复 08-03 起非自选品停更漏检；低于阈值提示当日抓取不完整）
- 2026-08-07 起每日全量刷新（价格+在售量，P3）；若大量品停在 2 天前，检查 `run_daily_collect.py` 的 `collect_kline_all` 是否被调用（回归防护测试 t_kline_daily）

### 3. 在售量覆盖（price_history.in_sale_count）

```sql
SELECT date, COUNT(*) n FROM price_history
WHERE in_sale_count>0 AND in_sale_count IS NOT NULL
  AND date>=date('now','-7 day') GROUP BY date ORDER BY date DESC LIMIT 1;
```

验收：
- 最新日期为当日/前一日，n ≥ 90% 品数（约 101 品）
- 若骤降为 0，说明每日 K 线/在售量刷新未跑（2026-08-07 起每日全量刷新，不再依赖悠悠登录态）

### 4. 贪婪/卡价（macro_history）

```sql
SELECT COUNT(*) FROM macro_history WHERE greedy_index IS NOT NULL;
SELECT COUNT(*) FROM macro_history WHERE card_price IS NOT NULL;
```

验收：greedy ≈ 60 点、card ≈ 179 点（写穿透全量 upsert）。数量大幅减少说明采集失败。

---

## 二、全市场快照检查（2026-08-04 起）

### 1. 覆盖与行数

```sql
SELECT MAX(date) d, COUNT(*) n FROM market_snapshot;
```

验收：当日行数 ≈ **1468**（5000 品 → StatTrak/纪念品过滤 + 磨损过滤后）。波动 ±50 属正常。

### 2. 残留检查（不允许出现）

```sql
SELECT COUNT(*) FROM market_snapshot
WHERE name LIKE '%StatTrak%' OR name LIKE '%纪念品%';
```

验收：= 0（StatTrak/纪念品已被采集器过滤）

### 3. 磨损口径抽查

```sql
SELECT exterior_localized_name, COUNT(*) n FROM market_snapshot
WHERE name NOT LIKE '%StatTrak%' AND name NOT LIKE '%纪念品%'
GROUP BY exterior_localized_name ORDER BY n DESC;
```

验收（2026-08-04 基线）：
- 无磨损（印花/箱/胶囊）≈1011
- 崭新出厂（枪皮 FN）≈455
- 略有磨损（手套保留）少量
- 久经沙场（手套保留）少量
- 其他磨损（略磨枪皮/破损/战痕等）应为 0

### 4. 存世量口径提醒

`info/get_page_list`（快照接口）**不含存世量**。存世量在单品详情 `info/good` 的 `statistic_list`，按 good_id 匹配当前磨损档的 `statistic`。快照层无法按存世量过滤，属已知限制。

---

## 三、大户集中度检查（monitor_rank_snapshot）

```sql
SELECT date, COUNT(DISTINCT item_id) items, COUNT(*) rows
FROM monitor_rank_snapshot GROUP BY date;
```

验收：100 品 / 每品 Top50 → 4960 行/天（部分品无大户会少几行）。

抽查已知大户（决策日志记录，2026-08-04）：
- AK-47 | 抽象派 1337：顶头 **koyouki** x149
- USP 消音版 | 守护者：顶头 **HWLH** x241

大户排行实时波动（买卖变化会变名次），同一天不同时点 top1 不同属正常；若某品 top1 稳定但数值异常大（>10x 历史），需复查是否 route 改写 good_id 串品。

---

## 四、items 元数据检查

### 1. 无 good_id 的采集品（不应存在）

```sql
SELECT id, name, good_id FROM items WHERE good_id <= 0 AND in_watchlist=1;
```

验收：持仓品必须有 good_id（否则每日采集跳过、K 线不更新）。历史残留：
- ~~id=7 FN57 神祇~~ → 已补 good_id=863（2026-08-04）
- ~~id=39 法玛斯 对比涂装~~ → 已补 good_id=744 + notes「存世量过低不采集」

### 2. 重复 good_id（不应存在）

```sql
SELECT good_id, COUNT(*) n FROM items WHERE good_id > 0 GROUP BY good_id HAVING n > 1;
```

验收：= 0（2026-08-04 已清理 id=26/42 重复品）

### 3. 存世量过低标记

```sql
SELECT id, name, good_id, notes FROM items WHERE notes LIKE '%存世量过低%';
```

验收：法玛斯 对比涂装（id=39）应有标记。每日采集 SQL 已排除 `notes LIKE '%存世量过低%'`。

---

## 五、过滤规则汇总（2026-08-04 定稿）

| 层级 | 规则 | 位置 |
|---|---|---|
| 快照采集 | 排除 StatTrak / 纪念品（`★` 是普通标记不过滤）| `collector_snapshot.py` |
| 快照采集 | 磨损过滤：枪皮/刀仅崭新出厂、手套仅略磨+久经、无磨损保留 | `collector_snapshot._keep_wear` |
| 单品分析 | 崭新出厂存世量 <3000 → 存世量过低·不建仓 | `item_analysis.run_item_analysis` |
| 每日采集 | 排除 notes 含「存世量过低」的品 | `run_daily_collect.py` 三处 SQL |

### 重要口径备忘
- `（★）` 是**普通标记**（如 运动手套（★）），不是 StatTrak；StatTrak 刀显示为 `（★ StatTrak™）`
- 存世量 = `statistic_list` 中当前 good_id 磨损档的 `statistic`，**不是** `buff_sell_num`（在售挂单数）
- `in_sale_count` 采集自 `gi.get('in_sale_count', ...)` 实际 fallback 到 `buff_sell_num`，是挂单数不是存世量

---

## 六、快速体检命令（一条跑完）

```bash
cd cs-skin-market && python - <<'EOF'
# -*- coding: utf-8 -*-
import sys, io, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
db = sqlite3.connect('data/market.db')
c = db.cursor()
print('index latest:', c.execute("SELECT date,value,mood FROM market_index ORDER BY date DESC LIMIT 1").fetchone())
print('kline last 3d:', c.execute("SELECT date,COUNT(DISTINCT item_id) FROM price_history GROUP BY date ORDER BY date DESC LIMIT 3").fetchall())
print('snapshot latest:', c.execute("SELECT MAX(date),COUNT(*) FROM market_snapshot").fetchone())
print('snapshot stattrak残留:', c.execute("SELECT COUNT(*) FROM market_snapshot WHERE name LIKE '%StatTrak%' OR name LIKE '%纪念品%'").fetchone()[0])
print('monitor:', c.execute("SELECT date,COUNT(*) FROM monitor_rank_snapshot GROUP BY date").fetchall())
print('dupe good_id:', c.execute("SELECT COUNT(*) FROM (SELECT good_id FROM items WHERE good_id>0 GROUP BY good_id HAVING COUNT(*)>1)").fetchone()[0])
db.close()
EOF
```

验收输出参考（2026-08-04 基线）：
- index latest: 2026-08-04, 1551.82, 恐惧
- kline last 3d: 8/2=101、8/3=36、8/4=25（周末/批量扫描影响，正常）
- snapshot latest: 2026-08-04, 1468
- snapshot stattrak残留: 0
- monitor: 2026-08-04, 4960
- dupe good_id: 0

---

## 七、异常处置

| 现象 | 处置 |
|---|---|
| 快照含 StatTrak/纪念品 | 重跑 `collect_market_snapshot`，确认采集器过滤代码未回退 |
| 快照出现非预期磨损（如破损枪皮）| 检查 `_keep_wear` 是否被改动 |
| 单品报告出现存世量过低却仍 buy | 检查 `survive_count` 是否传入（5 处调用点）|
| 大盘 mood 乱码 | 检查 `collector.fetch_market_index` 编码 |
| 在售量骤降/为 0 | 检查每日 K 线全量刷新是否运行（`run_daily_collect.py` `collect_kline_all`，2026-08-07 起每日执行）|
| 大户快照 0/100 | 浏览器 loop 问题（回归防护：单 loop 跑全部品）|

---

## 八、BUFF 数据源验证记录（2026-08-05，**已停止使用**）

**结论：BUFF 无法提供历史成交量，已于 2026-08-05 停止使用**（cookie 登录态验证过，记录封存以防重复尝试）：

| 端点 | 结果 | 说明 |
|---|---|---|
| `/api/market/goods/bill_order` | 不可用于历史量 | 每品固定 ~10-20 条，page_num/page_size 无效，多页返回同一批 |
| `/api/market/goods/price_history` | 无成交量 | days=90/180/365 均仅稀疏价格点 [ts, price] |
| 搜索/详情 | 仅当前快照 | sell_num/buy_num/transacted_num=0，无历史 |
| detail/trend/volume 等候选路径 | 404 | 模拟源不存在 |


---

## 九、审计历史

| 日期 | 结果 | 处理 |
|---|---|---|
| 2026-08-04 | 发现 is_sunday 回归 bug（周日 K 线刷新失效）| 修复 + 回归测试 t_is_sunday_order |
| 2026-08-04 | 发现 items 重复品/Test Item/乱码记录 | 清理 6 条，合并 K 线 |
| 2026-08-04 | 快照含 1883 StatTrak/纪念品 | 采集器过滤 + 磨损过滤，5000→1468 |
| 2026-08-04 | 存世量口径错误（误用挂单数）| 改从 statistic_list 解析，<3000 不建仓 
| 2026-08-04 | items 重复 good_id=863（FN57 神祇 id=7 / 神祗 id=30）| 删除脏行 id=7（名称误匹配脏价），持仓以 id=30 为准 |
| 2026-08-05 | BUFF cookie 验证历史成交量 | bill_order 上限 20 条/无分页、price_history 无成交量字段 → 不可用；历史成交量仍靠悠悠有品逐日积累 |
| 2026-08-07 | 去量落地：成交量检查 → 在售量检查；K 线每周日刷新 → 每日全量刷新（P3）| run_data_health.py / run_daily_collect.py / 进度卡同步（t_kline_daily 回归） |
