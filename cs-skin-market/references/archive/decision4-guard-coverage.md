# DECISION-4 守卫覆盖审计与对齐重放（2026-08-14）

只读研究，不改生产引擎，不覆盖 `data/item_backtest_full_2025.json`，不推翻 2026-08-10 四项审计。

## 产物

- `data/_exp_guard_coverage.json`：311 条可处理信号的逐条守卫覆盖与动作。
- `data/_exp_aligned_replay_v2T4.json`：对齐后仍为 buy 的 290 条信号。
- 生成器：`references/decision4_guard_coverage.py`。

## 关键结论

| 口径 | n | win14 | avg14 | net14 |
|---|---:|---:|---:|---:|
| 官方 317 产物（可处理 311） | 311 | 78.46% | +18.18% | +16.18% |
| 当前生产口径对齐 | 290 | 77.24% | +17.28% | +15.28% |
| 缺失守卫严格化 | 111 | 83.78% | +25.33% | +23.33% |

- 对齐后：`buy 311 -> buy 290 / watch 20 / avoid 1`，主要是新 `200/100` 地板与可用 `survive/bid` 守卫生效。
- `survive_history` 可覆盖 `210/311`，`bid_history` 可覆盖 `130/311`；严格化口径把缺失守卫视为 veto，因此只剩 111 条 buy，只应作为下界敏感性，不能当作可交易样本。

## 覆盖口径

- `survive_available`：信号日已存在 `survive_history`。
- `bid_available`：信号日已存在 `bid_history`，并由 `bid_history` 构造 `spread_pct / spread_avg / bid_7d_chg / bid_30d_chg` 代理。
- `liquidity_score`：311/311 全部可回放。

## 限制

- 官方 317 条中 6 条因历史名称不再匹配当前 `items` 表而未处理：`AWP | 无畏战神 (略有磨损)`、`指挥官 梅 “极寒” 贾米森 | 特警`。
- `bid_history` 没有现成 `spread_pct`，对齐重放使用 `bid_history_proxy`，不等于生产 `order_book`，结论需标注为代理口径。
- `strict` 是“缺失即拦”的最保守敏感性，不代表生产行为；后续 P-B/P-C 默认建议使用 `aligned` 口径，`strict` 只做边界对照。
## 关联探针结论（Phase 1，2026-08-14）

- `P-A`：supply_depth 最新一条 vs 近7日中位数仅 4 条分类翻转，且 123/311 条近7日有效在售不足 3 个；不落地，根因并入 `DECISION-6 / POOL-2`。
- `P-D`：LIQ-RATIO-1 前瞻 111 条，`listed_ratio≥5%` 桶 7 条 win14 57.14% / avg14 +6.86%，弱于低挂单桶；仅提示挂单率上界，不落地。
- `P-F`：后置族绕过 GUARD1/GUARD2；对恐慌族补 micro_th 会拦掉高收益信号（被拦 105 条 win 79.05% vs 恐慌族 100%）。market_weak 命中 135 条 win 81.48%/+22.68%，旁路保留为正优化。
- `P-B`：deep_value 0.15 落地（total 195.85→230.57、Calmar 36.42→40.04）；panic/supply_accum 变体均不落地。
- `P-C`：组合 stop/take 恶化 Calmar 36.42→16.72，不落地；hold21 为组合收益来源。
## 后置族旁路显式化（DECISION-2/3/8 事实源）

| 路径 | 绕过 GUARD1 | 绕过 GUARD2 | 仍生效的后续守卫 |
|---|---:|---:|---|
| 恐慌共振 `panic_resonance` | 是（守卫1后评估） | 否 | 守卫2 + supply_expansion |
| 深值企稳 `deep_value` | 是 | 是 | `supply_expansion`（族级 guards） |
| 恐慌退潮 `panic_easing` | 是 | 是 | 无族级 guards |
| 供给收缩吸筹 `supply_accum` | 是 | 是 | 无族级 guards |

- 定性：后置族旁路是设计意图，不是风控 bug；P-F 已证明补 micro_th/market_weak 会误伤高收益信号。
- 该表以 `pipeline/item_analysis.py:1569-1620` 为唯一事实源；`references/guard-chain-map.md` 是代码生成的守卫函数清单。