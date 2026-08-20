# 引擎独立全量扫描 — 研究档案索引

> 用途：为后续研究（尤其是「牛市上行段高选择性解法」）提供完整入口，避免重新扫盲区/重复造轮子。
> 生成：2026-08-20（②算法研究窗口）；决策链路 decision-log BZ→CA→CB→CC→CD→CE→CF。

## 一、背景（为什么做）

- 原「族划分重构」基于 374 信号聚类 = 有偏样本（只含旧引擎开火的时刻），对子题②（引擎盲区）无效。
- 战略转向（decision-log BZ，commit `b8eecb0`）：**引擎独立全量扫描**——不经过旧引擎，从 3 年原始行情（价格+在售量+大盘）扫所有 item-day 的「特征→前向收益」，反推市场真实结构。
- ③审计预注册复核（CA，commit `a38d820`）：双期限修订（fwd14+fwd30 双树 + gate 任一期限全套达标即过 + 记录自然期限）+ 稀有结构探针（pct 20 桶 / 低 pct 子空间 min_leaf≈50 细树）。

## 二、判据（先判据后跑的锁定值，改它需过③）

- 文档：`references/family-refactor-prereg-2026-08-20.md`
- 关键锁定：特征集 12 项（pct/z/chg7/30/90/sc7/30/vol7/30/mchg7/21/30）、决策树 min_leaf≥200 depth≤4、正期望 gate（n≥200 且 任一期限 win≥55% 且 avg≥+2% 且 walk-forward 两段方向一致 且 trim 前 5% 极值后 avg≥+1%）、walk-forward 切点 2025-08-10、盲区定义 = 正期望区域 − 引擎 5 活跃族覆盖。

## 三、脚本

| 脚本 | 功能 | 复跑方式 |
|---|---|---|
| `references/fullscan_features.py` | 特征构建器（231 品 239,826 item-day） | `fullscan_venv_python references/fullscan_features.py` |
| `references/fullscan_regions.py` | 决策树结构发现 + 双期限 gate + 引擎覆盖对照 | 同上 |

- 环境：独立 venv `C:\Users\81572\.workbuddy\binaries\python\envs\fullscan\Scripts\python.exe`（numpy 2.5.2 / sklearn 1.9.0）。系统 Python 3.11 无 sklearn，勿混用。

## 四、产物（data/_exp_fullscan_*.json）

| 产物 | 大小 | 内容 |
|---|---|---|
| `_exp_fullscan_features_2026-08-20.json` | 33MB | 全量特征矩阵 + fwd14/fwd30（原始数据源） |
| `_exp_fullscan_regions_2026-08-20.json` | 55KB | 63 区域特征边界 + 统计（21 过 gate） |
| `_exp_fullscan_blindspots_2026-08-20.json` | 1KB | 2 盲区清单 |

## 五、核心结论（已定格，勿改口径）

扫描收敛 **4 类自然结构**：

| 结构 | 特征中心 | 自然期限 | 引擎覆盖 | 结论 |
|---|---|---|---|---|
| 恐慌深跌 | pct<20 · 深跌 · 大盘深跌 | 14d/30d | 已覆盖（恐慌共振/退潮） | 不新增族 |
| 深值慢修复 | pct 14–30 · 供给收缩 | **30d** | 已覆盖（深值/供给收缩） | 不新增族；**实证③期限错配判断** |
| **牛市/强势上行** | pct 48–69 · 上涨 · 大盘涨 | 30d | **覆盖薄弱区**（0.14%，非零覆盖） | **子题②盲区实锤**；候选族 |
| **深跌反弹右侧** | pct≈55 · chg7+12.5 · mchg21−36 | 14d/30d | 零覆盖（真盲区） | 单事件簇（91.6% 挤 2025-10），弱候选 |

**盲区验证（族开回放 + 完整四关，CE/CF）**：两候选全拒，无落地项——
- crash_vol：221 条 100% 挤 2025-10 单月 → 触③预注册 A2 否决线（单月>50% 自动驳回）。
- bull_steady：added 13,279 条，val win14 49.1% vs 买书 78.9%，p_avg=1.0 → 宽触发稀释高质量买书，五门 FAILED。
- **结论：盲区真实存在，但「加宽触发族」的朴素修补被证伪；真解法须「高选择性」（正期望区域内叠加更强过滤，使信号量级与买书可比）。**

## 六、决策日志链路

- BZ（战略转向）→ CA（③审双期限修订）→ CB（扫描结果）→ CC（③放行 + 盲区→覆盖薄弱区措辞更正 + A2 否决线预注册）→ CD（族开回放口径=研究脚本变体）→ CE（族开回放 + delta + 四关全拒）→ CF（③确认，证伪闭环）。

## 七、相关提交

- `b8eecb0` 战略转向 + 预注册 BZ
- `a38d820` 预注册双期限修订 + CA
- `1dcc58c` 扫描（features/regions/blindspots）+ CB
- `cc83e69` 措辞更正（blindspot→weak-coverage）+ CC 落盘
- `bb5f2df` 族开回放 + delta + A2 四关 + CE

## 八、后续研究接入口

1. **牛市上行段「高选择性」解法**（未来立项）：以 `_exp_fullscan_regions_2026-08-20.json` 的牛市上行区域为种子，叠加更强过滤（信号量级压到百条级）→ 预注册 trigger → 族开回放 → 完整四关 → ③审。基线 = `data/_exp_cycle_replay_fullpool_2026.json`（374 信号，C1 后八键分类）。
2. **rise_accum 改造**（H3 候选：chg7 下限 3→10，chg7>10 段 win 50%/avg +24）：引擎参数修正候选，同样走预注册→回放→四关。
3. **池子再扩/特征扩展**：改 `fullscan_features.py` 重跑，判据文档同步修订（过③）。

## 九、口径红线（勿忘）

- 研究池 = **240 品 − 贴纸/印花 − 角色 − 2 污染品（流金王朝/丁烷拍档）**；扫描实际加载 231 品（文档写 232，以文档为准）。
- 374 信号是**基线引擎回放**（引擎现状），不是扫描产物；扫描产物是区域清单。
- C1-UNIFY（commit `dd8c47c`）落地后基线信号分类为 8 键：panic 149 / accumulate 82 / deep_value 48 / base 64 / rise 29 / weak_market 2。
