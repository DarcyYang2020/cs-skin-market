# 现有族切口审计 预注册判据（2026-08-20，②研究）

> 状态：预注册草案，交③审计判据本身后跑。仅研究不落地（落地须 PM 立项 → 研发）。
> 承接：CN 侦查证伪后，用户追问「现有 11 族（5 开 6 关）切口是否最优」——此前「已是最优」为过度声称，本审计补上。

## 一、目标

用**引擎独立全量数据**（不分引擎发没发）复核现有 11 族的切口是否最优，回答两个子问题：
1. **6 个关族该不该开**（开关决策复核）
2. **5 个开族的阈值/切口是否最优**（阈值审计）

## 二、字段映射核对（预注册前提，已只读核实）

全量扫描特征 12 个：`pct/z/chg7/chg30/chg90/sc7/sc30/vol7/vol30/mchg7/mchg21/mchg30`。

11 族 trigger 依赖的引擎字段 F，分三类：

| 类别 | 字段 | 说明 |
|---|---|---|
| ✅ 直接映射 | pct / z / chg7 / chg30 / mchg30 | 同名同口径 |
| ✅ 可换算 | drop21 = −mchg21；supply_change_30d = sc30 | 涨跌 vs 跌幅取反 |
| ⚠️ 需重算 | s7/s30（在售量均值）、chg5/chg8（5/8日涨跌）、vol7（引擎原始std非年化）、mkt180、dd20/dd20_age、current | 全量没存，需从原始库重算 |
| ❌ 无法审计 | sent（情绪）、th/market_th（技术面）、micro_th、stopped、survive、bid_now/bid_peak | 引擎内部复杂特征，全量没算，重算成本高 |

**按族可审计性：**

| 族 | 状态 | 可审计性 |
|---|---|---|
| rs_accum | 关 | ✅ **完全可审计**（仅 chg30/mchg30/pct/supply_change_30d）|
| ct_accum | 关 | ✅ **完全可审计**（mchg30/chg30/pct/supply_change_30d）|
| supply_accum / rise_accum / rise_contract / xishou_mid | 开/关 | ⚠️ 部分（供缩 s7/s30 需重算；market_th 不可）|
| volatile_accum | 关 | ⚠️ 部分（vol7 单位需换算）|
| panic_resonance / deep_value / panic_easing | 开 | ❌ 依赖 sent/TH/micro_th/stopped，暂无法审计 |
| second_wave | 关 | ❌ 依赖 dd20/bid/mkt180 |

## 三、审计范围（分阶段）

**第一阶段（本预注册锁定）**：复核 **rs_accum / ct_accum 两个关族的开关决策**——这是唯一两个"完全可映射"的关族，能立即用引擎独立全量数据回答「该不该开」。

**后续阶段（另立预注册，需重算引擎特征）**：supply/rise/xishou/volatile 等族的供缩条件、5 开族阈值、sent/TH 依赖族——需先在全量 item-day 上重算 s7/s30/TH/sent 等特征，工作量另估。

## 四、第一阶段判据（rs_accum / ct_accum 开关复核）

### 候选 trigger 复现（去掉发射口径 _dedup_gate/_cooldown，仅触发条件）

- **rs_accum**：`RS30 = chg30 − mchg30 > 10 且 pct > 40 且 supply_change_30d ≤ 5`（长持族，hold 180）
- **ct_accum**：`mchg30 < 0 且 chg30 > 5 且 pct > 40 且 supply_change_30d ≤ 5`（长持族，hold 180）

### 方法（引擎独立，无偏）

1. 用全量特征复现上述 trigger 条件的 item-day 集合（不分引擎发没发）。
2. **重算 fwd60 / fwd180**（全量扫描只有 fwd14/fwd30，而 rs/ct 是长持族，正期望在 60d/180d；从 replay_cycle_win.db 价格数据重算前向收益，扣 2% 成本）。
3. 统计每个 trigger 的 win/avg（60d/180d）+ 时间分布 + walk-forward（切点 2025-08-10）。

### 正期望判据（锁定）

一族算「该开」须**同时**满足（60d 或 180d 任一期限全套）：
1. `n ≥ 200`
2. `win ≥ 55%`（对应期限）
3. `avg ≥ +5.0%`（对应期限，净，长持族门槛高于摆动族）
4. walk-forward 两段方向一致（切点 2025-08-10，两段对应期限 avg>0 且 win≥50%）
5. 剔除前 5% 极值后 avg 仍 ≥ +2.0%
6. **单月占比 ≤ 50%**（沿用 A2 否决线，防单事件簇）

一族算「关得对」：不满足上述任一条件（尤其单月占比>50% 或 walk-forward 方向不一致）。

### 反过拟合声明

- 只做「开关复核」，不改任何阈值；threshold 值（RS30>10、chg30>5 等）来自引擎现有 trigger，非本次样本内调出。
- 结果正负一律登记；「该开」仅是候选，落地仍须 PM 立项 + 研发 + 样本外/live pilot。

## 五、不做的事

- 不改 pipeline/webapp 代码；只产出 `data/_exp_*.json` + 本预注册 + decision-log。
- 不重算 sent/TH/stopped 等引擎特征（归后续阶段）。
- 不做 5 开族的阈值优化（归后续阶段）。

## 六、产物

- `data/_exp_family_audit_rs_ct_2026-08-20.json`（rs/ct 开关复核原始统计）
- decision-log 条目（正负结果均登记）
