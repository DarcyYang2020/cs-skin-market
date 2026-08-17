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

## 三、批准后的两段式重构设计（待探针裁决后细化）

- 报告"距买点"改为：`触发条件：已满足（达 X 族）` + `剩余闸门：大盘走弱（TH 45<、30日 −10%）、供给扩张…` —— 100% 的含义从"马上能买"改为"触发已就绪，被 N 道闸门拦着"；
- 或反之：proximity 不满足时显示"还差：…"，满足时直接显示闸门清单。
