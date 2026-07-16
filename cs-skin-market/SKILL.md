---
name: cs-skin-market
description: "CS 饰品市场投资策略全流程辅助。覆盖行情趋势分析、饰品估值评分与筛选、买卖时机判断及持仓管理。当用户需要：(1) 查询或分析 CS 饰品价格走势时；(2) 筛选高潜力投资标的时；(3) 制定买入/卖出策略时；(4) 了解市场动态与事件驱动因素时；(5) 需要持仓风险评估时，自动启用此技能。"
---
# CS Skin Market Strategy

## Overview

## 核心规则

1. **只分析用户指定的磨损等级**，不对比其他磨损
3. **始终先获取大盘指数**，再分析单品

---

## Workflow：统一分析流程

### Step 1：获取大盘温度

- CS 饰品综合指数数值 + 7 日涨跌
- 整体市场情绪（热/温/冷）

### Step 2：搜索目标饰品

- 当前价格
- 今日 / 近期成交量
- K 线图走势（观察趋势方向、均线形态）

### Step 3：三因子评分

参照 `references/skin-valuation.md` 逐项打分：

**稀缺度 (40%)**：
- 来源：哪个箱子/收藏品？
- 等级：违禁品/隐秘/机密/受限/军规/工业/消费级？
- 绝版状态：是否已停产？停产多久？
- 计算公式：来源加成 × 稀有度系数

**成交量 (35%)**：
- 对照系数表换算得分

**大盘 (25%)**：
- 从 Step 1 的大盘指数 7 日涨跌对照系数

### Step 4：综合评分

```
综合评分 = 稀缺度得分 × 0.40 + 成交量得分 × 0.35 + 大盘得分 × 0.25
```

评级：S (≥3.5) | A (2.5–3.4) | B (1.5–2.4) | C (<1.5)

### Step 5：输出建议

```
【ITEM_NAME | WEAR】

大盘温度: 综合指数 XXX | 7日 XX% | [热/温/冷]
实时数据: 当前价 RMB XXX | 日成交 X 件
走势判断: [上升/下降/横盘] | [描述K线形态]

稀缺度分析:
  来源: [箱子/收藏品名] | 等级: [稀有度] | [绝版/在售]
  得分: X.X

综合评分: X.X (X级)
建议操作: [买入/持有/卖出/观望]
参考入手价: RMB XXX ~ XXX
止损线: RMB XXX (-XX%)
止盈线: RMB XXX (+XX%) | RMB XXX (+XX%)
建议仓位: 总仓位 X%

核心逻辑: 2-3句...
主要风险: ...

> 请以悠悠有品/Buff163 实时挂单价确认后操作
```

---

## 特有场景处理

### 持仓审查
用户提供持仓清单 → 逐项走 Step 2-5 → 汇总总市值、浮盈/浮亏 → 给出调仓建议

### 选品推荐

### 止损触发
大盘 7 日跌 >8% → 提示整体减仓 30% | 单品跌 15% → 提示卖出 50% | 单品跌 25% → 提示清仓

---

## Unified Pipeline (pipeline/)

One-command analysis: collect -> store -> score -> report.

```
# Quick commands
python -m pipeline.cli index
python -m pipeline.cli search "????"
python -m pipeline.cli search "item name" --detail
python -m pipeline.cli list
python -m pipeline.cli history "item name"

# Full analysis
python -m pipeline.cli analyze "FN57 | ???? (????)"     --rarity restricted --source collection --discontinued 10
```

### Pipeline Modules

| Module | Role |
|---|---|
| pipeline/config.py | Proxy, paths, factor weights, score tables |
| pipeline/db.py | SQLite storage (items, prices, snapshots, index) |
| pipeline/scorer.py | Three-factor scoring engine |
| pipeline/reporter.py | Markdown report generator |
| pipeline/cli.py | Unified CLI entry point |

### Data Flow

         |                                      |
    MarketIndex + ItemData              items / price_history
         |                                      |
    scorer <- index_change_7d          scorer <- rarity, volume
         |
    ScoreResult -> reporter -> Markdown report -> data/report_*.md
                -> db.snapshots

---

## Resources

### references/
- `skin-valuation.md` — 三因子估值模型 + 止盈止损规则
- `market-analysis.md` — 市场周期框架 + 事件日历（参考用）
- `trading-strategies.md` — 策略手册（参考用）

### scripts/（备用，非主要）
- `fetch_prices.py` — Steam API 价格查询（仅供参考）
- `analyze.py` — 数据技术分析

---

## 关键原则

2. **只分析用户指定的磨损**，不展开对比
3. **大盘先行**，单品分析前必先看指数
5. **非投资建议**，所有分析仅供参考