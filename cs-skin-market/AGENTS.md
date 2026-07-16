# cs-skin-market Skill

## 数据采集

- **大盘数据**: csQAQ API (`https://api.csqaq.com/api/v1`) — HTTP GET（同步）
- **单品搜索+K线**: csQAQ Playwright 采集（异步，浏览器自动化）
- **定价锚**: 悠悠有品 > Buff > C5GAME，Steam 价格失真仅作参考
- **StatTrak 过滤**: 自动排除 StatTrak 和纪念品版本，仅分析普通版

### 数据采集路径

| 数据 | 数据源 | 方式 |
|---|---|---|
| 大盘指数、品类排名、市场情绪 | csQAQ `GET /api/v1/current_data?type=init` | HTTP GET（同步） |
| 大盘日线 K 线 | csQAQ `GET /api/v1/current_data?type=kline` | HTTP GET（同步） |
| 单品搜索 | csQAQ Playwright 搜索页 | 浏览器自动化 |
| 单品详情 + 90日K线 | csQAQ Playwright 详情页 | 浏览器自动化（响应拦截） |

## 单品分析引擎

详见 `references/analysis-engine.md`，核心模块：

| 模块 | 位置 | 功能 |
|---|---|---|
| 估值定位 | item_analysis._analyze_position | 90日百分位 + Z-score |
| 周期判定 | item_analysis._analyze_cycle | 吸筹/拉升/出货/洗盘 四阶段 |
| 流动性评估 | item_analysis.score_liquidity | 三维 0-100 评分 |
| 涨跌概率 | item_analysis.analyze_probability | 均值回归 + 多特征预测 |
| 投资价值 | item_analysis.compute_value_score | 1-10 分 + S/A/B/C 评级 |
| 庄盘识别 | item_analysis.analyze_whale | 四因子 + 订单簿检测 |
| 趋势健康度 | trend_health.compute_trend_health | 六维度 0-100 评分 |
| 融合决策 | trend_health.compute_fusion_decision | 百分位×TH → 操作指令 |
| 估值宫格 | valuation.compute_valuation_grid | 3×4 宫格 + 仓位建议 |
| 信号冲突 | item_analysis.detect_signal_conflicts | 跨模块矛盾检测 |

## 文件结构

```
SKILL.md               -- 核心工作流指令
AGENTS.md              -- 本文件（项目完整说明）
references/
  cs-knowledge.md      -- CS市场深度知识库 + csQAQ API 参考
  trading-strategies.md-- 标准化交易策略
  analysis-engine.md   -- 单品分析引擎文档
pipeline/
  config.py            -- TOKEN/BASE_URL/权重/评分表/CATEGORY_PARAMS
  collector.py         -- csQAQ 大盘数据（同步 HTTP）
  collector_csqaq.py   -- csQAQ 单品数据（Playwright 异步）
  db.py                -- SQLite 存储（items/价格/快照/持仓/回测 + watchlist CRUD）
  item_analysis.py     -- 单品分析主流程（10大模块协调）
  trend_health.py      -- 趋势健康度 + 融合决策
  valuation.py         -- 估值宫格
  scorer.py            -- 六维度评分引擎（旧版，部分功能已迁移）
  trends.py            -- 多时间框架趋势分析
  supply.py            -- 供给端追踪（吸筹/派发）
  regime.py            -- 市场状态识别（牛/熊/震荡/高波）
  reporter.py          -- Markdown 单品报告生成
  backtest.py          -- 策略回测（夏普/回撤/胜率）
  portfolio.py         -- 持仓管理 + 投资组合优化
  watchlist.py         -- 批量扫描引擎 + 汇总报告
  cli.py               -- 命令行入口
  index_analysis.py    -- 大盘指数分析
  market_context.py    -- 大盘锚定（保留，暂未接入）
webapp/
  main.py              -- FastAPI Web 应用
  templates/           -- Jinja2 模板（base/search/watchlist/dashboard + partials）
  static/              -- CSS + JS
```

## CLI 命令

```bash
python -m pipeline.cli index       # 大盘指数 (csQAQ API)
python -m pipeline.cli sector      # 板块排名 (csQAQ API)
python -m pipeline.cli regime      # 市场状态 (csQAQ API)
python -m pipeline.cli analyze "物品名" --rarity <等级> --source <来源>
python -m pipeline.cli list / history / watchlist / portfolio / backtest
```

## Web 应用

```bash
cd cs-skin-market && python -m uvicorn webapp.main:app --host 127.0.0.1 --port 8000
```

- 大盘仪表盘: `http://127.0.0.1:8000/`
- 单品搜索: `http://127.0.0.1:8000/search`
- 自选管理: `http://127.0.0.1:8000/watchlist`
- 分析结果 + 报告均以弹窗模态框展示

## 常见坑

- csQAQ 免费 Token 仅支持 `current_data` 接口，goods/info 接口需企业 Token
- 单品搜索和K线走 Playwright 浏览器自动化，单次分析约 20-30 秒
- Windows 终端 GBK 编码，cli 已设置 stdout UTF-8
- 收藏品/纪念品受 2026.5 炼金解禁影响，持续利空
- 模板文件编码必须为 UTF-8，避免使用 PowerShell 编辑含中文的模板
