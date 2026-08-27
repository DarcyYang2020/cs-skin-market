# ③独立审计 · R2 factor_registry 因子注册表口径复核（2026-08-27）

**审计对象**：②R2 落地（decision-log DP + `data/factor_registry.json` + `references/init_factor_registry.py` + `references/factor-registry.md`）
**审计员**：窗口③（独立审计 / 刹车）
**红线执行**：只认 R2 预注册判据（`references/r2-factor-registry-prereg-2026-08-27.md` §1 schema/§2 状态机/§5 状态映射/§6 验收）+ 产物/代码事实；DP 自述仅对照。**独立重算核验**（python 直读 registry + R1 评估卡交叉验证）。

---

## 一、核验结果

### 结构层（通过）
| 项 | 核验 |
|---|---|
| 21 因子、id 无重复、schema_version=1 | ✅ |
| 13 字段结构（id/name/category/role/definition/data_dependency/version/source/quality/status/in_engine/cs_note/tested_at） | ✅ 完整 |
| 必填 9 字段无缺失；status/role/category 枚举全合法（5 态/4 角色/8 类） | ✅ |
| quality 存在 ⇒ tested_at 存在（全部 tested=2026-08-27） | ✅ |
| 状态分布 证伪 15 / 候选 3 / 存档 3 | ✅ 与 DP 一致 |

### 状态映射层（通过，独立抽验）
预注册 §5 映射 vs R1 评估卡 verdict，逐条抽验全部正确：
| R1 verdict | registry status | 抽验因子 | 判定 |
|---|---|---|---|
| 候选（条件IC）| 候选（供给类）| sc7/sc30/s7_ratio（cond_ic 均正：0.052/0.072/0.082）| ✅ |
| 候选·无增量 | 证伪 | sentiment（IC14 0.142 强但增量 IC −0.0008<0.02，verdict_note 已解释）| ✅ |
| 不稳定 / 弱·无效 | 证伪 | spread（IC −0.097 不稳）/ bid（IC −0.011 弱）| ✅ |
| 条件因子 | 存档 | mchg7/21/30（截面 IC 无定义 n=0 为正确结果）| ✅ |

### 关键口径层（通过，防误读设计到位）
- **引擎在用因子 status=证伪/候选/存档 但 in_engine 保留现状标注**：pct（打分·位置40%核心）/ z（展示口径·去z化后）/ chg30（打分+触发·动量）/ vol30（风险调节·概率因子）/ sc30（打分·供给维度）/ mchg30（条件·regime 路由）——「registry 状态=新管线准入状态，证伪/存档 ≠ 引擎立即移除」在数据层成立（in_engine 承担现状标注）✅
- role 归一化：R1 口语化（打分+触发/决策触发/风险调节/加分/过滤/条件因子）→ 4 角色枚举，cs_note 逐个留痕 ✅；category 8 类归一化 ✅
- md 视图存在（22 行 = 表头 + 21 因子）✅；init 脚本确定性/幂等（覆盖式输出 + 内嵌 validate）✅；config 引擎在用因子全部有 registry 条目（验收④）✅

## 二、缺口/建议（非阻断，登记）

1. **`references/validate_factor_registry.py` 独立脚本缺失**（预注册 §6 验收①承诺的独立校验脚本）——校验逻辑内嵌于 `init_factor_registry.py::validate()`（功能覆盖），但独立脚本未建。建议补建或修订预注册文档说明。
2. **证伪/候选 + in_engine 非空的 6 条缺统一「引擎遗留待 R3」防误读标注**：pct/z/chg30/vol30/sc30/mchg30——in_engine 已标现状，但建议在 registry 头部 meta 或各条 cs_note 统一注明「引擎现状遗留（v2-T13 历史累积），取舍待 R3 策略隔离评估裁决」，防下游把「证伪」误读为「应移除」（DP 口径已声明，数据文件自带更稳）。
3. 量价 category 在枚举内但首批无该类因子（可接受，注明）。

## 三、裁定

- **R2 factor_registry 口径复核通过**：schema 结构、21 因子状态映射（与 R1 卡独立交叉验证）、引擎在用因子「证伪≠移除」口径、role/category 归一化全部正确；R3 判据交付待 PM 冻结、R4 挖掘清单、R5 情绪 v0 判据——非本次复核范围，按各自卡走后续流程。
- 附 2 项非阻断收尾（独立 validate 脚本 / 统一 R3 防误读标注），由②补或登记待办即可，不阻断 R2 生效。
- 无生产逻辑改动（registry 为数据文件），不 bump ENGINE_VERSION ✅。

---

**一句话**：R2 factor_registry 口径复核通过——13 字段 schema 合法、21 因子状态映射与 R1 卡独立交叉验证全部正确（候选3/证伪15/存档3）、引擎在用因子「证伪≠引擎移除」（in_engine 标现状）防误读口径成立；仅 2 项非阻断收尾（独立 validate 脚本缺失、6 条引擎遗留因子建议加统一 R3 标注）。
