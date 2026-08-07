# 回测方法学升级（A2 工作流）

> 背景：项目回测现用「全量日记录回放 + 14d/30d 胜率」口径，但信号高度集中在少数事件日（如 2026-05-22~05-26 单簇 42/88信号），按信号条数统计的胜率容易自证。本文档介绍三个可复用的方法学工具与当前 buy 信号的聚类/外推结论。

## 工具用法

### pipeline/backtest_methodology.py

- 信号时间聚类报告。±window 天内算同一事件簇；输出信号数/簇数/最大簇占比/去重后事件级数量；单簇占比>50% 或有效事件日<5 时返回 warning。
- 按时间序切 train/test（anchor_ratio=0.7），边界同日时自动后移切点，保证 test 段完全在 train 段之后；返回两段 win_rate/avg/n。
- 符号置换检验（每条收益 50% 概率翻号，保留幅度），估计“随机也能达到该胜率”的经验 p 值（单尾，(hits+1)/(n_perm+1)）。

三个函数均为纯函数，无引擎依赖，输入输出为 Python dict/list，可在回测脚本、报告与测试中直接复用。

### references/methodology_report.py

回测报告：加载 buy 信号明细，运行上述三个检验，生成 data/methodology_report.json 并打印摘要。

```bash
cd cs-skin-market
python references/methodology_report.py [--signals-file data/item_backtest_full_2025.json]
```

## 当前 buy 信号结论摘要（2026-08-05 生成）

- 口径（历史，2026-08-07 归档）：曾基于 data/item_backtest_latest.json（旧引擎 88 条 buy 信号，2025-11-15 ~ 2026-06-21）。该基准已删除；当前标准回放 = data/item_backtest_full_2025.json（去量 v2，370 信号）。
- 聚类集中度（window=3）：88 信号 / 25 唯一日期 / 11 事件簇。最大簇 2026-05-22~05-26 共 42 条（47.7%），次大簇 2026-06-12~06-21 共 34 条（38.6%）；前两大簇合计 86.4% 触发 warning（单簇未超 50%，但胜率仍集中于两段行情）。
- 事件级统计：按簇去重后 net14 事件胜率 8/11 = 72.7%（信号级 79.5%），下调约 7pp。
- Walk-forward（anchor=0.7，严格时序）：train 截至 2026-06-18（n=65），test 为 2026-06-19~06-21（n=23，即末尾 panic 簇）。net14：train 87.7% → test 56.5%（跌 31.2pp）；net30：train 70.8% → test 34.8%（跌 36pp，样本外仅略高于抛硬币）。收益同向衰减：net14 avg +34.08 → +17.88；net30 avg +27.85 → +8.07。
- 置换检验（sign-flip, n_perm=1000）：fwd14 p=0.0010、fwd30 p=0.0040、net14 p=0.0010、net30 p=0.0170，均 < 0.05，观察胜率显著优于随机符号；但 p 值不修正事件聚类，应配合聚类报告一起看。
- 结论：信号级胜率经置换检验显著，但事件集中度高（前两簇 86.4%）；14d 样本外胜率 56.5% 仍正值且收益正向，30d 样本外 34.8% 已与随机无异，建议后续以 14d 为主口径、对 30d 保持警惕；任何新信号类型上线前应先跑本报告检查其事件集中度。

完整明细（历史口径）原见 data/methodology_report.json（已随旧基准删除）；重跑 `python references/methodology_report.py` 可从 item_backtest_full_2025.json（370 信号）再生。

## 注意

- 严格只读：不改任何信号引擎/回测口径；
- 胜率口径为 net（fwd - 2% 双边成本），报告同时列出 fwd 毛收益供对照；
- walk-forward 的 test 段为末尾单一行情簇（06-19~06-21），代表“不同市场环境”下的小样本外推，不可视为平均样本外能力；
- 信号新增后重跑：python references/methodology_report.py 重生报告。
