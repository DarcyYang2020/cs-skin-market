# DOC-COMPACT-1 长文档归档压缩清单（2026-08-18，预注册）

> 本清单 = 立项卡（iteration-roadmap.md「DOC-COMPACT-1」）的预注册产物。处置与清单逐项一致，清单外零改动。
> 红线：不删仍被活跃引用/审计依赖/决策编号依赖的内容；不碰代码/测试/引擎/基线；不改变文档语义；不整体归档活跃手册。

## 一、归档卷路径

- 统一放 `references/archive/doc-compact-2026-08-18/`，文件名 = 原文件名 + `-archive` + 日期。
- 原文件头部加「归档卷链接」；主文件保留压缩后索引（决策编号/条目标题/日期，可定位到归档卷锚点）。

## 二、候选处置表（13 文件）

| # | 文件 | 现行数 | 压缩方式 | 保留范围（主文件） | 归档范围 | 目标行数 |
|---|---|---|---|---|---|---|
| 1 | `references/decision-log.md` | 4757 | 整体归档 | 头部+归档索引+最新战役（AM~AZ：拿历史均值收尾/治理收敛/CLEANUP-1/DISPLAY-1/单品短期期望 AQ~AY/③审计#1#2/DISPLAY-2）+归档链接 | 数据与口径四表 + 2026-08-03~08-17 全部历史条目（326~4512 行） | ≤1500 |
| 2 | `references/iteration-roadmap.md` | 823 | 拆分归档 | 头部+版本摘要表(v1~v71 各一行)+当前基线+未收口台账+活跃立项卡(CLEANUP-1/DISPLAY-1/DISPLAY-2/DOC-COMPACT-1)+归档链接 | 版本历史细节(v1~v70)+新思路映射+批次+状态追踪+立项排期+各技术方案(BUY-1/cycle-refit/v3-enhance 等 8~696 行) | ≤500 |
| 3 | `references/cs-knowledge.md` | 429 | 评估后轻量压缩 | 当前接口清单 + 定价锚 + 采集要点 | 已废弃旧端点历史说明 | 报告实际 |
| 4 | `AGENTS.md` | 340 | 评估后轻量压缩 | 总纲/纪律/活跃配置/活跃模块表 | 历史结论区（超跌例外/建仓过滤/样本扩展等已归档到 decision-log 的重复段落） | 报告实际 |
| 5 | `references/data-source-health.md` | 295 | 评估后轻量压缩 | 当前检查 SOP | 历史检查口径/旧基线 | 报告实际 |
| 6 | `references/first-principles-market-fit.md` | 298 | 评估后压缩为结论摘要 | 结论摘要 + 指针 | 过程稿 | 报告实际 |
| 7 | `references/engine-unified.md` | 266 | 评估后压缩 | 当前架构 + 基准对照现状 | 历史设计过程 | 报告实际 |
| 8 | `references/first-principles-modules-fit.md` | 229 | 评估后压缩为结论摘要 | 结论摘要 + 指针 | 过程稿 | 报告实际 |
| 9 | `references/data-layer.md` | 188 | 活跃手册，仅压缩冗余历史 | 全文（活跃手册） | 冗余历史说明（如旧 370 信号口径） | 报告实际 |
| 10 | `PROJECT_STRUCTURE.md` | 184 | 仅清理过时条目 | 主体全文 | 过时条目（如 archive 卷旧清单） | 报告实际 |
| 11 | `references/trading-strategies.md` | 182 | 评估后压缩 | 当前策略表 | 历史研究段落 | 报告实际 |
| 12 | `references/trend_leg_research.md` | 159 | 评估后压缩为结论摘要 | 结论摘要 | 过程稿 | 报告实际 |
| 13 | `references/current-state-expectancy-design.md` | 152 | 评估后压缩为设计定稿摘要 | 定稿摘要 | 过程稿 | 报告实际 |

## 三、引用检查证据（压缩前全仓 rg）

- 活跃代码/测试对候选 .md 的引用：测试仅 `test_smoke.py:2078` 注释提及 decision-log（AK-47 | ??? 1337 脏名），无内容断言依赖。
- 活跃文档间引用：压缩后凡指向被归档段落的引用，一律改为指向归档卷；TOC/锚点经 `rg` 校验无悬空（指向归档卷除外）。

## 四、执行顺序

1. 建归档目录 + 落本清单。
2. decision-log → 归档卷 + 主文件瘦身。
3. iteration-roadmap → 归档卷 + 主文件瘦身。
4. 其余 11 文件逐项评估压缩（仅动冗余/过时，不动活跃手册主体）。
5. 同步 PROJECT_STRUCTURE/AGENTS 归档卷指针。
6. `python tests/test_smoke.py`（131 passed / 0 failed，不得因文档压缩改变测试数）+ `python tests/check_encoding.py` PASS。
7. decision-log 条目 + commit。

## 五、验收对照

1. 主文件行数：decision-log ≤1500、iteration-roadmap ≤500；其余报告实际。
2. 归档卷完整保留被移出内容，索引可定位到原编号/章节。
3. 冒烟 131/0/0 + 编码 PASS。
4. PROJECT_STRUCTURE/AGENTS 归档卷指针同步。
5. 交付物：本清单 + 归档卷 + decision-log 条目 + commit。
