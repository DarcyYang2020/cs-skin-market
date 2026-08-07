# cs-skin-market

CS 饰品市场投资分析工具。FastAPI Web 应用，从 csQAQ 采集大盘/单品数据（价格 + 在售量 in_sale_count），跑六维度评分 + 趋势健康度 + 融合决策模型，输出买卖建议。数据存 SQLite（`cs-skin-market/data/market.db`）。

> **2026-08-07 去成交量（v2）**：引擎彻底放弃真实成交量方向，改为「在售量 + 价格」双核心（方案见 `references/plan-supply-price-v1.md`，回测见下文）。悠悠有品成交量采集器（collector_youpin.py）与登录凭据（uu_headers.json）已于 2026-08-07 删除。

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
| ~~真实成交量~~（已删除） | 悠悠有品 `price/trend/data` API（登录态 headers） | 2026-08-07 起引擎不再消费；采集器与 uu_headers 凭据已删除 |

csQAQ chart API 提供 price + in_sale_count（在售量），为引擎唯一量源。历史 `volume_day` 字段与悠悠有品回填数据保留在库中（供数据进度卡展示历史覆盖），评分/决策不再读取。

## 命名规则

- `FN57` = Five-SeveN（武器型号），勿与磨损 `FN`（Factory New）混淆
- 注意区分 `( )` 半角括号与 `（ ）` 全角括号

## 评分模型

### 基础评分（`compute_value_score`，item_analysis.py）

| 因子 | 权重 | 说明 |
|---|---|---|
| 位置 | 40% | 90日分位越低越有价值 |
| 周期 | 25% | 吸筹 > 拉升 > 洗盘 > 出货 |
| 流动性 | 15% | 在售深度 50% + 价格稳定 50%（2026-08-07 去量重写，原「成交量40%+价差30%+在售30%」废弃） |
| 概率 | 20% | 涨跌概率修正（均值回归 + 波动率分类） |

大盘/情绪不进入基础分，通过融合决策层进入（见下）。

### 融合决策（`decide_fusion_signal`）

- 入口：`compute_fusion_decision`（trend_health）产生初始 buy/watch/avoid
- 升级族1：恐慌共振（守卫1 后评估）
- 后置族（固定优先级）：深值·大盘企稳 > 恐慌退潮 > 供给收缩吸筹
- 闸门链：守卫1（大盘走弱/存世量/半山腰/7天去重/飞刀）→ 守卫2（微型TH/求购/Z门/大盘出货/连买抑制）→ 供给扩张过滤（`_g_supply_expansion`：在售量30日扩张>5% 禁买）→ 族级闸门
- I-13（2026-08-07 去量回测验证）：深值族仅在大盘 30 日涨跌 `mchg30<=-3`（企稳/修复环境）触发；`mchg30>=3` 上涨段 93 信号 14d 仅 44% 胜率/+2.2（跨10月40品，基线与去量版同款）→ 剔除
- 深度回调低吸例外（P0-7b）：周期吸筹 + 大盘21日跌幅>-18% 时，需 dd30<=-22% + chg14<=-6% 才豁免

评级: S>=3.5 / A 2.5-3.4 / B 1.5-2.4 / C<1.5

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
- 数据见 `cs-skin-market/data/item_backtest_full_2025.json`（2026-08-07 去量 v2 引擎 370 信号回放）；对比文件 `baseline450`（96品池原引擎）/ `devol_v1`（去量 v1）/ `devol_v2`（去量 v2+I-13）保留在 data/ 下

### 参数拟合建议

不需要定期拟合。触发重新验证的场景：
1. 积累完整牛熊循环（~260天新数据）
2. buy信号连续2月14d胜率跌破70%
3. 每月检查: 14d>=80%、30d>=55%则不动

### 参数冻结条款（OOS 纪律，2026-08-07 定稿）

去量引擎 v2（I-13）、组合层 cap0.8、单票敞口提示 30% 与 `ITEM_EXPECTANCY_STATS` 展示口径已冻结
（见 `pipeline/config.py` 的 `PARAM_FREEZE`，测试 `t_param_freeze` 防删）。冻结期约 260 天
（至 2027-04-25 前后，覆盖完整牛熊循环样本）后做真 OOS 复验；复验触发 = 260 天数据 / buy 连续 2 月
14d 胜率 <70% / 月度检查 14d>=80%、30d>=55% 则不动。

**期望统计单一事实源**：`data/item_backtest_full_2025.json`（回放产物）→
`python references/sync_expectancy_config.py` 自动同步 `config.ITEM_EXPECTANCY_STATS` 与进度卡 J-3
（`data/signal_event_counts.json`），`t_expectancy_sync` 全字段硬校验防漂移。

**基准对照**：`python references/benchmark_compare.py` 产出 `data/benchmark_compare.json`
（策略 cap0.8 vs 池内等权买入持有 vs 大盘指数，full/active 双窗口）。2026-08-07 结论：策略 +193.30%/-9.39%
大幅跑赢大盘 -4.02%，但低于池内等权 +509.75%/-54.12%——引擎边际价值在风险控制（maxDD 9.4% vs 54~58%）。


## 文件结构

    cs-skin-market/
      run_server.py            -- Web 服务入口（uvicorn）
      SKILL.md / AGENTS.md     -- Skill 元数据 / 详细说明
      data/market.db           -- SQLite 数据库
      pipeline/
        config.py              -- 配置（API/权重/评分表/阈值）
        collector.py           -- 大盘指数采集（HTTP）
        collector_csqaq.py     -- 单品采集（Playwright）
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
        main.py                -- FastAPI 应用（1816行，路由 + 页面编排）
        analysis_service.py    -- 单品分析服务层（2026-08-07 重构）：kline兜底/脏价校验/锚价校正/大盘上下文/快照落库 + 统一分析核心 analyze_fresh
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
- 2026-08-07 起引擎去成交量：真实成交量（悠悠有品）不再参与评分/决策；`collector_youpin.py` 与 `data/uu_headers.json` 已删除（2026-08-07 终审）
- `bar.date` 必须为 YYYY-MM-DD 格式才能与在售量/回测日期对齐
- 批量扫描需在有网络的环境运行（宿主机直连）
- 详细模块说明见 `cs-skin-market/AGENTS.md`