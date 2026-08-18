# CLEANUP-1 工程卫生清理清单（2026-08-18，预注册）

> 本清单 = 立项卡（iteration-roadmap.md「CLEANUP-1」）的预注册产物。实际处置与本清单逐项一致，清单外文件一律不动。
> 处置方式只有两种：**归档**（`git mv` 至 `references/archive/`，git history 可逆）与 **登记**（仅记录交运维，不物理删除）。
> 红线遵守：不碰活跃引擎/测试/基线数字/信号逻辑；不物理删除 `.db`/`.bak`/`.log`；不做目录大重构。

## 一、归档候选（文档，处置 = `git mv` 至 `references/archive/`）

字段：`路径 / 分类 / 处置 / 引用检查证据 / git 跟踪状态`

| # | 文件 | 分类 | 处置 | 引用检查证据 | 跟踪 |
|---|---|---|---|---|---|
| 1 | `references/handoff-2026-08-18.md` | a（过时交接，与 decision-log AM 矛盾） | 归档 | rg 全仓 0 引用；内容停在 AM 前（「对齐口径前不动」已被 AM 闭环取代） | tracked |
| 2 | `references/optimization-initiation-2026-08-15.md` | a（自标「历史立项基线，建议归档」） | 归档 | 4 引用均为历史/派生：`data/_exp_buy1_gate.json`（产物）、`backfill_buy1_buy_price.py`（一次性脚本 docstring）、`iteration-roadmap.md` v68（历史存证）、`scripts-archive/probes/probe_buy1_gate.py`（已归档） | tracked |
| 3 | `references/family-boundary-arbitration-v1.md` | a（自标「已被 v2 取代」） | 归档 | 2 引用：`batch2-family-boundaries-design.md`（同批归档）、`family-boundary-arbitration-v2.md`（历史依据，归档后改注） | tracked |
| 4 | `references/batch2-family-boundaries-design.md` | a（自标「历史设计，被 v1/v2 承接」） | 归档 | rg 全仓 0 引用 | tracked |
| 5 | `references/alignment-and-fix-plan.md` | a（AM 战役签收单，战役已闭环） | 归档 | rg 全仓 0 引用；「待用户批准执行」已由 decision-log AM 三处落地取代 | tracked |
| 6 | `references/conclusion-audit-2026-08-15.md` | b（外审一次性审计，历史存证） | 归档 | rg 全仓 0 引用 | tracked |
| 7 | `references/core-sat-1-2026-08-15.md` | b（外审立项基线；sleeve 已证伪关闭 AJ） | 归档 | rg 全仓 0 引用 | tracked |
| 8 | `references/trap-key-plan-2026-08-15.md` | b（外审立项基线，一次性方案） | 归档 | rg 全仓 0 引用 | tracked |
| 9 | `references/system-evaluation-2026-08-17.md` | b（两天战役收官评估，历史存证） | 归档 | rg 全仓 0 引用 | tracked |
| 10 | `references/exception-pass-ledger.md` | b（异常吞噬收口登记，一次性记录） | 归档 | rg 全仓 0 引用 | tracked |
| 11 | `references/cycle-refit-2026-08-15.md` | b（外审立项基线，L0 已落地折入 v69） | 归档 | 4 引用均历史/派生：`data/_exp_cycle_refit_2026.json`（产物）、`backfill_cycle_window.py`（一次性脚本 docstring）、`decision-log`（历史账本）、`iteration-roadmap.md` v69（历史存证） | tracked |
| 12 | `references/v3-engine-enhance-2026-08-15.md` | b（外审方案基线，收益增强器已收口证伪） | 归档 | 2 引用：`iteration-roadmap.md` v70（历史存证）、`scripts-archive/probes/probe_trend1_greedy.py`（已归档） | tracked |
| 13 | `references/engine-refoundation-audit-2026-08-15.md` | b（引擎重建审计，历史存证） | 归档 | 1 引用：`decision-log`（历史账本） | tracked |
| 14 | `references/decision4-guard-coverage.md` | b（DECISION-4 守卫覆盖审计，历史存证） | 归档 | 2 引用：`archive/optimization-roadmap-2026-08-14.md`（已归档）、`decision-log`（历史账本） | tracked |
| 15 | `references/execution-flywheel-audit.md` | b（执行飞轮诊断，历史存证） | 归档 | 1 引用：`decision-log`（历史账本） | tracked |
| 16 | `references/product-pm-initiation.md` | b（产品立项转化版，A/B 线已落地） | 归档 | 1 引用：`decision-log`（历史账本） | tracked |
| 17 | `references/product-pm-review.md` | b（PM 评估，一次性历史） | 归档 | 1 引用：`product-pm-initiation.md`（同批归档） | tracked |

## 二、登记候选（不物理删除，交运维窗口处理）

| # | 文件 | 分类 | 处置 | 说明 |
|---|---|---|---|---|
| E1 | `data/market.db.bak-*`（7 份，2026-08-08~08-13） | e（运行时备份） | 登记，运维清理 | `.db`/`.bak` 属运维域，研发不删 |
| E2 | `data/market.bak-*`（3 份）、`data/replay_v2t6_win.bak-*`（2 份） | e（运行时备份） | 登记，运维清理 | 同上 |
| E3 | `data/item_backtest_full_2025.json.bak-preaudit-20260809` | e（文本备份） | 登记，运维清理 | 同上 |

## 三、明确不处置（评估后保留，避免误删/超出本轮范围）

- `references/guard-chain-map.md`：`generate_guard_chain_map.py` 的生成产物（v2-T5 已过时但可再生成），非冗余文档，本轮不动。
- `references/system-evaluation-2026-08-10.md` / `p2_backtest_plan.md` / `position-building-strategy.md` / `bid-data-accumulation.md` / `data-reserve-api-audit.md` / `deployment.md`：被活跃白名单文档（`first-principles-*.md` / `trading-strategies.md` / PROJECT_STRUCTURE / `collect_data_reserve_*`）引用或属用户侧部署方案，保留。
- `data/_exp_v2t7_win_replay_deprecated_20260814.json` / `_exp_v2t8_win_replay_deprecated_20260815.json`：已按项目口径「_deprecated_ 后缀 + BASELINE_LEDGER 登记」在库内存证，非冗余裸留，保留。
- 所有 `.py` 研究脚本：本轮不做脚本迁移（立项卡红线「不做大规模迁移」），后续单独一轮做 import graph + 断言映射验证再议。

## 四、执行后验证

1. `python tests/test_smoke.py` 0 failed
2. `python tests/check_encoding.py` PASS
3. 全仓 rg 归档文件名（除 archive/ 与 decision-log/iteration-roadmap 历史存证外）无活跃引用
4. 归档后更新 `family-boundary-arbitration-v2.md` 对 v1 的引用（标注已归档）+ `PROJECT_STRUCTURE.md` archive/ 条目
