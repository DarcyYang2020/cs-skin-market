# cs-skin-market Skill

## 数据采集

- **代理**: 可选，`config.py` 中 `PROXY` 设为空即为直连（当前默认直连）
- **定价锚**: 悠悠有品 > Buff > C5GAME，Steam 价格失真仅作参考
- **等待策略**: `domcontentloaded`（非 networkidle，SPA 长连接永不 idle）
- **StatTrak 过滤**: 自动排除 StatTrak 和纪念品版本，仅分析普通版
- **浏览器复用**: 所有采集函数支持 `pw`/`browser` 参数，批量扫描时共享单一浏览器会话

### 数据采集路径

| 数据 | 来源 | 方式 |
|---|---|---|
| K 线历史数据 | `/api/user/steam/type-trend/v2/item/details` | Playwright 响应拦截（页面自动触发） |

### Nuxt 3 数据提取

- `_extract_from_nuxt()` 解析 Nuxt 引用链，提取：itemId、价格、成交量、存世量、涨跌幅
- Nuxt 包装器类型：Reactive / ShallowReactive / Ref / EmptyRef / Set

### K 线数据

- API: `POST /api/user/steam/type-trend/v2/item/details`，自动由页面触发
- 通过 `page.on("response")` 拦截，无需手动调用（可避免反爬 error 108）
- 数据粒度：10 分钟级，每次约 700+ 条
- 通过 `_daily_aggregate()` 聚合成日线 OHLCV（约 30 根日线）
- 每行格式：`[timestamp, price, in_sale, bid_price, volume, tx_amount, tx_count, survive_num]`

## 命名规则

- `FN57` = Five-SeveN（武器型号），勿与磨损 `FN`（Factory New）混淆
- 注意区分 `( )` 半角括号与 `（ ）` 全角括号

## 六维度评分模型 (v3)

### 四因子（基础评分）

| 因子 | 权重 | 说明 |
|---|---|---|
| 稀缺度（来源+等级+绝版） | 35% | rarity × source_multiplier |
| 成交量（在售数+流动性） | 25% | 日成交件数 → 评分 |
| 流动性（订单簿健康度） | 15% | 价差 + 求购深度 |

### 修正因子

| 修正层 | 范围 | 触发条件 |
|---|---|---|
| 动量信号 | ±0.05 ~ ±0.25 | 日成交 / 30日均量 >= 3x |
| 事件冲击 | ±0.03 ~ ±0.30 | Major/新箱/CS2更新/大促 |
| **趋势** | ±0.15 | 7/30/90日动量 + MA交叉 + 波动率 + 量价信号 |
| **供给** | ±0.09 | 在售数量变化率 + 吸筹/派发检测 |

评级: S>=3.5 / A 2.5-3.4 / B 1.5-2.4 / C<1.5

### 趋势分析（从 K 线 API 实时抓取）

- 7日/30日/90日 价格动量
- MA7 / MA30 均线交叉（金叉/死叉）
- 7日波动率
- 成交量趋势（rising/falling/stable/spike）
- 量价信号（accumulation/distribution）
- 趋势得分：-1.0 ~ +1.0

### 供给分析（从 K 线 API 实时抓取）

- 在售数量 7日/30日变化率
- 供给趋势（expanding/contracting/stable）
- 吸筹检测：供给收缩 + 价格稳定/上涨
- 派发检测：供给扩张 + 价格持平/下跌
- 供给得分：-0.3 ~ +0.3

### 估值分位（新增）

- 当前价格在 30日/90日 历史中的百分位排名
- Z-score（偏离均值标准差数）
- 估值标签：低估（<=20%分位）/ 合理 / 高估（>=80%分位）
- 数据来源：`price_history` 表

### 市场状态识别（新增）

- 基于大盘指数历史数据判断：上涨市 / 下跌市 / 震荡市 / 高波市
- 根据市场状态动态调整仓位建议（牛70% / 熊30% / 震荡50% / 高波30%）

### 投资组合优化（新增）

- 持仓间日收益率相关性矩阵
- 基于 Sharpe 比率的建议权重分配
- 组合预期年化收益 / 波动率 / 夏普比率

## 文件结构

```
SKILL.md               -- 核心工作流指令
AGENTS.md              -- 本文件（项目完整说明）
references/            -- 估值模型 + 策略手册 + 行情方法论
pipeline/              -- 统一数据管线（采集-存储-评分-报告-回测-持仓）
  config.py            -- 代理/权重/评分表/止盈止损
  collector.py         -- Playwright 采集（大盘/板块/搜索/详情/订单簿/K线）
  db.py                -- SQLite 存储（items/价格/快照/持仓/回测 + watchlist CRUD）
  scorer.py            -- 六维度评分引擎 + 修正层
  trends.py            -- 多时间框架趋势分析
  supply.py            -- 供给端追踪（吸筹/派发）
  valuation.py         -- 历史估值分位（百分位 + Z-score）
  regime.py            -- 市场状态识别（牛/熊/震荡/高波）
  reporter.py          -- Markdown 单品报告生成
  backtest.py          -- 策略回测（夏普/回撤/胜率）
  portfolio.py         -- 持仓管理 + 投资组合优化（P&L/集中度/相关性/有效前沿）
  watchlist.py         -- 批量扫描引擎（复用浏览器 + 汇总报告 + 90天清理）
  cli.py               -- 命令行入口
scripts/               -- 旧版脚本（备用）
assets/                -- 截图、JSON 数据
data/                  -- 运行时数据（DB、报告 scan_*.md）
```

## CLI 命令

```bash
# 大盘指数
python -m pipeline.cli index

# 板块资金流向
python -m pipeline.cli sector

# 市场状态识别
python -m pipeline.cli regime

# 搜索饰品
python -m pipeline.cli search "关键词" --detail

# 完整分析（采集-存储-评分-单品报告）
python -m pipeline.cli analyze "物品名" --rarity <等级> --source <来源> [--discontinued <年数>]

# 查看历史
python -m pipeline.cli list
python -m pipeline.cli history "物品名"

# ---- Watchlist 批量自选管理 ----

# 添加自选
python -m pipeline.cli watchlist add --name "物品全名" --rarity restricted --source case

# 编辑参数
python -m pipeline.cli watchlist edit --name "物品全名" --source discontinued_case --notes "备注"

# 删除
python -m pipeline.cli watchlist remove --name "物品全名"

# 查看列表
python -m pipeline.cli watchlist list

# 一键批量扫描（复用浏览器 + 汇总报告 + 90天清理）
python -m pipeline.cli watchlist scan

# ---- 持仓管理 ----

python -m pipeline.cli portfolio add --name "物品名" --price <价格> --qty <数量>
python -m pipeline.cli portfolio check
python -m pipeline.cli portfolio close --id <ID> --price <价格>

# 投资组合优化（相关性矩阵 + 建议权重）
python -m pipeline.cli portfolio optimize

# ---- 策略回测 ----

python -m pipeline.cli backtest "物品名" --entry A --capital 10000
```

## Watchlist 定时扫描

Windows 任务计划程序，每天 12:00 自动扫描（管理员 PowerShell 运行）：

```powershell
$taskName = "CS-Model Watchlist Scan"
$pythonPath = "C:\Users\81572\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$workDir = "C:\Users\81572\Desktop\codex\cs-model\cs-skin-market"

$trigger = New-ScheduledTaskTrigger -Daily -At "12:00"
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "-m pipeline.cli watchlist scan" -WorkingDirectory $workDir
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Trigger $trigger -Action $action -Settings $settings -RunLevel Highest -Force
```

## 汇总报告结构（scan_*.md）

每次 `watchlist scan` 生成一份 Markdown 报告，包含：

1. **市场状态** -- 大盘指数 + 市场状态标签（牛/熊/震荡/高波）+ 建议仓位
2. **总览表** -- 所有物品价格/成交量/评级/趋势/估值/建议
3. **每物品详情**：
   - 基本指标（价格/成交量/在售/评级）
   - 估值分位（30d/90d 百分位 + Z-score + 最高/最低/中位价）
   - 四因子评分（稀缺度/成交量/流动性/大盘）
   - 趋势信号（7d/30d 动量 + MA 交叉 + 波动率 + 量价）
   - 供给信号（供给趋势 + 吸筹/派发检测）
4. **投资组合优化** -- 相关性矩阵 + 建议权重 + 预期收益

## 数据保留策略

- price_history、snapshots、market_index：保留 **90 天**
- scan_*.md 报告文件：保留 **90 天**
- debug 文件（_debug_*）：保留 **7 天**
- 每次 `watchlist scan` 自动执行清理 + VACUUM

## 常见坑

- 代理可选：`config.py` 中 `PROXY = ""` 为直连，设为代理地址走 Clash
- 英文搜索名可能返回不同皮肤，优先用中文名
- 文件名不能包含 `|` 等特殊字符，`_save_debug` 已自动消毒
- 详情页可能覆盖搜索页的正确数据，collector 已加保护逻辑
- Windows 终端 GBK 编码问题，cli 已设置 stdout UTF-8
- Nuxt 3 数据中字段值可能是引用索引（整数 → 需 unwrap 解析）
- K 线 API 手动 fetch 会触发 error 108 反爬，必须用响应拦截
- `page.request` 不走浏览器代理，不能用它调 API
- watchlist scan 需要在有网络的环境运行（沙箱内需代理，宿主机可直连）
