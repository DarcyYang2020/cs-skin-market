# cs-skin-market

CS 饰品市场投资分析工具。FastAPI Web 应用，从 csQAQ 采集大盘/单品数据、SteamDT 补成交量，跑六维度评分 + 趋势健康度 + 融合决策模型，输出买卖建议。数据存 SQLite（`cs-skin-market/data/market.db`）。

## 唯一入口

`cd cs-skin-market && python run_server.py`，访问 http://127.0.0.1:8000/

所有功能通过 Web 界面操作，无 CLI。

## 数据采集

- **定价锚**: 悠悠有品 (csQAQ platform=2) > Buff > C5GAME，Steam 价格失真仅作参考
- **等待策略**: `domcontentloaded`（非 networkidle，SPA 长连接永不 idle）
- **StatTrak 过滤**: 自动排除 StatTrak 和纪念品版本，仅分析普通版
- **浏览器复用**: 采集函数支持 `pw`/`browser` 参数，批量扫描时共享单一浏览器会话

### 数据采集路径

| 数据 | 来源 | 方式 |
|---|---|---|
| 大盘指数 + 品类排名 | csQAQ `/api/v1/current_data?type=init` | HTTP GET |
| 大盘 K 线 | csQAQ `/api/v1/current_data?type=kline` | HTTP GET |
| 单品搜索/详情/90日K线 | csQAQ Playwright 导航 `goods/{id}` | 响应拦截 info/chart API |
| 真实成交量 | SteamDT Playwright 导航 `/cs2/{name}` | 响应拦截 K线 API |

csQAQ chart API 提供 price + in_sale_count（不含真实成交量）。成交量由 SteamDT 单独采集，通过 `merge_daily_volume()` 按日期 (YYYY-MM-DD) 合并到 K线数据。

## 命名规则

- `FN57` = Five-SeveN（武器型号），勿与磨损 `FN`（Factory New）混淆
- 注意区分 `( )` 半角括号与 `（ ）` 全角括号

## 评分模型

### 四因子基础评分（权重见 `pipeline/config.py`）

| 因子 | 权重 | 说明 |
|---|---|---|
| 稀缺度 | 35% | rarity × source_multiplier |
| 成交量 | 15% | 日成交件数 → 评分 |
| 流动性 | 15% | 价差 + 求购深度 |
| 大盘 | 25% | 大盘 7 日涨跌 → 评分 |
| 概率 | 10% | 涨跌概率修正 |

### 修正因子

| 修正层 | 范围 | 触发条件 |
|---|---|---|
| 动量信号 | ±0.05 ~ ±0.25 | 日成交 / 30日均量 >= 3x |
| 事件冲击 | ±0.03 ~ ±0.30 | Major/新箱/CS2更新/大促 |
| 趋势 | ±0.15 | 7/30/90日动量 + MA交叉 + 波动率 + 量价信号 |
| 供给 | ±0.09 | 在售数量变化率 + 吸筹/派发检测 |

评级: S>=3.5 / A 2.5-3.4 / B 1.5-2.4 / C<1.5

### 趋势分析（`trend_health.py`）

7/30/90日价格动量、MA7/MA30 均线交叉、7日波动率、成交量趋势、量价信号（accumulation/distribution）。趋势得分 -1.0 ~ +1.0。

### 供给分析（`supply.py`）

在售数量 7/30日变化率、供给趋势、吸筹检测（供给收缩+价格稳定/上涨）、派发检测（供给扩张+价格持平/下跌）。供给得分 -0.3 ~ +0.3。

### 估值分位（`valuation.py`）

30日/90日百分位排名、Z-score、估值标签（低估/合理/高估/泡沫）。

### 超跌买入例外 (P0)

当标准融合决策无法触发 buy 时，额外检查超跌反弹：
- pct<=15% + Z<=-2.0 + 跌速衰减(no_new_low2 + chg3d>0%) → 超跌反弹·分批建仓
- 回测: 2025-11~2026-07, buy信号16次, 14d胜率88%, 均收益+9.65%
- 数据见 `cs-skin-market/references/backtest_results.json`

### 参数拟合建议

不需要定期拟合。触发重新验证的场景：
1. 积累完整牛熊循环（~260天新数据）
2. buy信号连续2月14d胜率跌破70%
3. 每月检查: 14d>=80%、30d>=55%则不动

## 文件结构

    cs-skin-market/
      run_server.py            -- Web 服务入口（uvicorn）
      SKILL.md / AGENTS.md     -- Skill 元数据 / 详细说明
      data/market.db           -- SQLite 数据库
      pipeline/
        config.py              -- 配置（API/权重/评分表/阈值）
        collector.py           -- 大盘指数采集（HTTP）
        collector_csqaq.py     -- 单品采集（Playwright）
        collector_steamdt.py   -- 成交量采集（Playwright）
        db.py                  -- SQLite 存储
        item_analysis.py       -- 单品分析引擎（1051行）
        index_analysis.py      -- 大盘分析引擎（903行）
        trend_health.py        -- 趋势健康度 + 融合决策（802行）
        valuation.py           -- 估值分位 + 估值宫格
        supply.py              -- 供给分析
        market_th.py           -- 大盘趋势健康度
        market_macro.py        -- 市场宏观情绪
        market_context.py      -- 大盘上下文
        batch_scan.py          -- 自选批量扫描
      webapp/
        main.py                -- FastAPI 应用（1108行，全部路由）
        templates/             -- Jinja2 模板
        static/                -- CSS/JS
      references/              -- 估值模型 + 策略手册
      tests/test_smoke.py      -- 冒烟测试

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

批量扫描生成 Markdown 汇总报告（`data/scan_*.md`），含市场状态、总览表、每物品详情、持仓个性化建议。

## 数据保留策略

- price_history、snapshots、market_index：保留 365 天（延长前为 90 天，解锁更长回测）
- scan_*.md 报告：保留 90 天
- debug 文件（_debug_*）：保留 7 天
- 批量扫描自动执行清理 + VACUUM

## 常见坑

- 英文搜索名可能返回不同皮肤，优先用中文名
- 文件名不能包含 `|` 等特殊字符，已自动消毒
- Windows 终端 GBK 编码问题，已设置 stdout UTF-8
- csQAQ chart API 不含真实成交量，需 SteamDT 单独采集合并
- `bar.date` 必须为 YYYY-MM-DD 格式才能与 SteamDT 合并
- 批量扫描需在有网络的环境运行（宿主机直连）
- 详细模块说明见 `cs-skin-market/AGENTS.md`