# cs-skin-market Skill

## 数据源

| 数据 | 数据源 | 方式 |
|---|---|---|
| 大盘指数、品类排名、贪婪指数、市场情绪 | csQAQ API (`https://api.csqaq.com/api/v1`) | HTTP GET（同步） |
| 大盘日线 K 线 | csQAQ `GET /api/v1/current_data?type=kline` | HTTP GET（同步） |

## 文件结构

```
pipeline/
  config.py            -- TOKEN/BASE_URL/权重/评分表
  collector.py         -- csQAQ 市场数据（同步 HTTP）
  db.py                -- SQLite 存储
  scorer.py            -- 六维度评分引擎
  trends.py / supply.py / valuation.py / regime.py
  reporter.py          -- Markdown 报告生成
  backtest.py / portfolio.py / watchlist.py
  cli.py               -- 命令行入口（市场命令同步、单品命令异步）
references/
  cs-knowledge.md      -- CS市场深度知识库 + csQAQ API 参考
  trading-strategies.md-- 标准化交易策略
```

## CLI 命令

```bash
python -m pipeline.cli index       # 大盘指数 (csQAQ)
python -m pipeline.cli sector      # 板块排名 (csQAQ)
python -m pipeline.cli regime      # 市场状态 (csQAQ)
python -m pipeline.cli analyze "物品名" --rarity <等级> --source <来源>
python -m pipeline.cli list / history / watchlist / portfolio / backtest
```

## 常见坑

- csQAQ 免费 Token 仅支持 `current_data` 接口，goods/info 接口返回 401
- Windows 终端 GBK 编码，cli 已设置 stdout UTF-8
- 收藏品/纪念品受 2026.5 炼金解禁影响，持续利空
