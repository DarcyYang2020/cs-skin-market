# R2 factor_registry 因子注册表 · 预注册判据（②算法研究窗口交付）

- **卡**：roadmap v82 R2（状态：待②预注册 → 本稿交付后待 PM 冻结）
- **登记依据**：decision-log DC；架构文档 §2.2（因子挖掘）；R1 评估卡（data/_exp_factor_eval_2026-08-27.json，quality 字段数据源）
- **状态**：**预注册判据草案（②交付，PM 冻结后生效）**
- **定位**：因子层"账本"——一处集中回答每个因子的定义/口径/数据依赖/版本/出处/质量/状态；解决"因子混乱"（用户原话）

---

## 0. 目标（R2 卡原文）

因子注册表 `data/factor_registry.json`（机器事实源）+ md 视图；13 字段；生命周期 = 入库即登记 → 评估 → 状态流转（候选/生产/证伪，证伪保留防重复挖）。落 §2.2。

## 1. Schema 终稿（13 字段，dtype/必填/枚举）

| # | 字段 | dtype | 必填 | 枚举/格式 | 说明 |
|---|---|---|---|---|---|
| 1 | id | str | 是 | `[a-z0-9_]+` | 唯一标识（pct_90d/chg30/sc30…） |
| 2 | name | str | 是 | 自由文本 | 中文名 |
| 3 | category | str | 是 | 8 类：价值/动量/趋势/供给/波动/量价/情绪/市场环境 | 修订版分类 |
| 4 | role | str | 是 | 打分/触发/条件/过滤 | 功能角色（分类的意义） |
| 5 | definition | str | 是 | 公式+窗口 | 计算口径（可复现） |
| 6 | data_dependency | list[str] | 是 | 表.列 或 派生名 | 数据依赖（指向数据层） |
| 7 | version | str | 是 | `v1`/`v2`… | 口径版本（改口径=版本+1 留痕，C1 教训） |
| 8 | source | str | 是 | decision-log 条目 / 代码位置 | 出处 |
| 9 | quality | dict | 否 | R1 评估卡字段子集 | IC14/IC30/时期分段/滚动/覆盖率/增量IC/分层/条件IC |
| 10 | status | str | 是 | **生产/候选/证伪/存档/待数据** | 状态（证伪保留防重复挖） |
| 11 | in_engine | str | 否 | 打分权重/决策维度/守卫/无 | 进引擎方式（status=生产 才有资格） |
| 12 | cs_note | str | 否 | 自由文本 | CS 特殊性备注（在售量≠成交量等） |
| 13 | tested_at | str | 否 | YYYY-MM-DD | 最近评估时间（R1=2026-08-27） |

**校验规则**（schema 校验脚本强制）：
- id/name/definition/data_dependency/source 必填非空；
- category/role/status 必须落在枚举内；
- status=生产 ⇒ in_engine 非空且 config 有权重镜像（衔接 config）；
- quality 存在 ⇒ tested_at 存在。

## 2. 生命周期状态机

```
入库即登记（候选，含预注册假设）
  ├─ 评估（R1 流程/未来挖掘流程）→
  │    ├─ 通过四关+③审计 → 生产（in_engine 落 config 权重）
  │    ├─ 筛查层通过但未走准入 → 候选（停留）
  │    ├─ 证伪/无增量/不稳定 → 证伪（保留，防重复挖）
  │    └─ 数据不足 → 待数据（覆盖率<30%，等 D2/D7 积累）
  └─ 口径变更 → version+1，旧版本留痕（不改旧条目，新增版本行）
```

**流转规则**：
- 候选 → 生产：**必须走完整管线**（预注册→回放→四关→③审计→PM 立卡→研发落地），筛查层结论（R1 的"候选"）**不自动升级**；
- 生产 → 证伪：监测破阈（J-2 C 通道/生命周期台账）→ 触发调整闭环（§3.5）；
- **证伪/存档永不删除**，仅状态流转（防重复挖，08-21 sentiment 教训）。

## 3. 衔接接口

1. **↔ config**：registry 管"因子本体"（定义/质量/状态）；`config.PARAM_REGIME` 管"参数值"；**status=生产 才有资格进 config 权重表**（R2 落地时校验现有 config 因子全部有 registry 条目）；
2. **↔ 数据层**：data_dependency 指向加工层表/派生层；评估按"版本冻结"口径取数（103 漂移教训）；D7 raw.db 供应新因子时先登记后评估；
3. **↔ ③审计**：registry 是审计核对清单——③复核因子口径/质量指标/状态流转依据（§7.1 待审计项）；
4. **↔ R1**：R1 21 因子评估卡 quality 字段直接入库（首批）。

## 4. 存储落法

- **机器事实源**：`data/factor_registry.json`（研究脚本/评估直接读；git 跟踪——因子账本是资产非派生数据）；
- **人工视图**：`references/factor-registry.md`（生成脚本 `references/gen_factor_registry_view.py`：读 JSON → 渲染 md 表格，可重复生成）；
- **版本**：文件头 `{"schema_version": 1, "generated": ...}`；条目级 version 字段独立。

## 5. 首批入库（R1 21 因子 → registry）

- 数据源：`data/_exp_factor_eval_2026-08-27.json`（21 卡：verdict/IC/时期分段/滚动/覆盖率/增量IC/分层/条件IC/冗余）；
- 状态映射：`候选（条件IC）`→候选（供给类，标注条件IC口径）；`候选·无增量`→证伪（无增量=信息冗余，按 §3 增量IC<0.02 登记）；`弱/无效`/`不稳定`→证伪；`待数据`→待数据；`条件因子`→存档（市场环境，条件因子状态）；
- 入库脚本：`references/init_factor_registry.py`（读 R1 JSON → 写 registry JSON，确定性、可重跑幂等）。

## 6. 验收标准（PM 据②判据冻结后定）

1. `data/factor_registry.json` 存在且 schema 校验通过（脚本 `references/validate_factor_registry.py`）；
2. R1 21 因子全部入库（id 不重复、状态映射正确）；
3. md 视图可生成且与 JSON 一致；
4. 现有 config 因子（引擎在用）能通过 name/id 匹配到 registry 条目（缺口清单登记）；
5. 冒烟 0 failed（无生产逻辑改动，registry 是数据文件）。

## 7. 前置依赖

- R1 评估卡（已交付 ✅）；D6 oos_guard（评估口径已守院 ✅）；无新采集。
