# 距买点（proximity）误导性研究方案（2026-08-18，预注册，研究版）

> 用户指认：距买点指标大量 100% 但实际不买，有误导性——先研究。
> 本文只做方案 + 探针；改动须批准后落地。

## 一、代码根因（已查明，三条）

1. **proximity 不含守卫链**：`compute_buy_proximity` 度量"距族触发条件"（几何平均，7 天去重是唯一守卫类条件），**不含**大盘走弱/贪婪禁买/供给扩张/流动性地板/半山腰/飞刀/存世量/时期路由禁发等守卫——触发条件全满足即 100%，但守卫照样把 buy 降级 → "100% 但不买"是结构性常态。
2. **只覆盖 6 条路径**（base/panic/deep/easing/supply/oversold），rise/rs/ct/C/D/xishou 等后置族不参与。
3. **过渡区间宽**（th 35-55、pct 30-45 线性过渡），多条件同时到 1.0 很容易。

## 二、预注册探针（先写判据后跑）

- **采集**：回放器加 env 钩子 `CS_ENGINE_PROXIMITY_MISS=1`——对每个 item-day，当 `action != buy 且 proximity.score == 100` 时记录一条 miss：
  {date, name, nearest, deduction_sources（守卫位）, state_bucket, pct, z, th}。
  重放 180 品 3 年（~31 分钟），miss 记录进入产物 `proximity_misses` 键。
- **判据**：
  1. 若 miss 中 ≥80% 的 `deduction_sources` 含守卫类（market_weak/greedy/supply_expansion/liquidity/route 等）→ **两段式重构立项**（第一阶段=距触发，第二阶段=触发后剩余闸门清单显式化）；
  2. 若 miss 主要来自触发条件边界（proximity 实际 <100 但显示 100 的 bug）或数据不足 → 修显示 bug；
  3. 若 miss 稀少（<30 条）→ 误导性证据不足，维持现状并登记。
- **产物**：`data/_exp_proximity_miss_*.json` + 守卫分布表。

## 三、探针结果（2026-08-18，已跑，裁决见下）

重放 180 品 3 年 → `data/_exp_cycle_proximity_miss.json`，`proximity_misses` 共 **15836** 条（同期真实 buy 信号仅 189 条，**噪声比 84:1**）。归因脚本 `references/proximity_miss_analyze.py` → `data/_exp_proximity_miss_analysis.json`。

### 3.1 nearest 路径分布

| 路径 | miss 数 | 占比 |
|---|---|---|
| 低估区建仓（base） | 15207 | 96.0% |
| 供给收缩吸筹（supply） | 328 | 2.1% |
| 深值企稳（deep） | 263 | 1.7% |
| 超跌反弹（oversold） | 37 | 0.2% |
| 恐慌退潮（easing） | 1 | ~0 |

### 3.2 归因分类（primary，每条 miss 取最高优先级类）

| 类 | 条数 | 占比 | 语义 |
|---|---|---|---|
| **th_scoring（TH 周期扣分）** | **14847** | **93.8%** | TH 被洗盘期×0.90 等乘子压低，th 落入 ≤35 带 |
| cycle_coord（周期协调降级） | 558 | 3.5% | buy 已产生后被洗盘/出货周期降级 |
| guard（守卫链拦截） | 188 | **1.2%** | market_weak/supply_expansion 等真守卫 |
| liquidity | 101 | 0.6% | 在售量缺失/地板 |
| route（时期路由禁发） | 39 | 0.2% | period_route 禁发 |
| empty | 103 | 0.7% | proximity=100 但零 deduction 痕迹 |

### 3.3 base 路径专项（96% 的病灶）

- 15207 条 base miss 的 **th 全部落在 [2, 35]**，均值 24.7 —— 正是「th≤35 = 黄金坑」带；
- 其中 **95.7%（14551 条）deduction 只有 TH 扣分类**（consolidation_phase/steepness_bottom_cap 等），**无 cycle_coord、无族源、无守卫**——说明引擎对它们从未产生 buy，也从未降级，而是从根上就是 avoid。

## 四、裁决（预注册判据核对）

- **判据 1（≥80% 守卫类 → 两段式重构）→ 证伪**：guard 仅 188 条 = 1.2%，远低于 80%。提案 §三「触发已就绪 + 剩余闸门清单」的前提不成立，**不按两段式方案走**。
- **判据 3（<30 条 → 维持现状）→ 不适用**：15836 条，误导性证据充分。
- **判据 2（触发条件边界/误导重建 → 修显示 bug）→ 成立**，且根因比提案假设更具体、更严重：

  1. **base 路径 th 语义倒置（96% 病灶）**：`compute_buy_proximity` 的 base「深跌确认」用 `_prog_low(th, 35, 55)`——把 **th≤35 当「黄金坑=100% ready」**；但引擎 `compute_fusion_decision` 在低估区（pct≤30）**只在 th≥55（TH_STRONG）才 buy**，th<35 是 `avoid/下跌中继·观望`。proximity 度量的是一个**引擎根本不会发射的买点**（th≤35 黄金坑是 TH 三区语义的研究结论，从未接成触发）。这是「拿历史均值当引擎买点」的又一处系统性问题。
  2. **supply 路径漏 T4 动量门**：proximity 的 supply 路径没建模 `chg8≤3`（T4 泵后横盘禁买门），导致 95 条 empty miss（proximity=100 但族不发射、零 deduction）。
  3. **真守卫拦截只占 1.2%**：deep（263）与 oversold（37）miss 里确实存在「族发射→supply_expansion/route/cycle 降级」，但这只是边角，不是主导。

## 五、修复方向（待批，改动须批准后落地）

1. **base 路径 th 反置修正**：`_prog_low(th, 35, 55)` → `_prog_high(th, 55, 35)`（th≥55 = 趋势确认 = ready），对齐 fusion 决策低估区 buy 的真实门槛；缺口文案同步改「≥55 趋势确认」。
2. **supply 路径补 chg8 门**：加入 `chg8≤3` 条件（与 T4 门一致），消除 95 条 empty miss。
3. **（可选小修）显式化剩余闸门**：仅对真正「族触发→守卫拦截」的 1.2% 样本，把 guard 源展示为「触发已就绪，被 N 道闸门拦」——非主导，可后置。

> 说明：判据 1 证伪后，原「两段式重构」标题保留为历史假设，不再执行；正确修法为判据 2 的显示层修正（1+2 为必做，3 为可选）。
