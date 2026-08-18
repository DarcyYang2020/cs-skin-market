# 异常吞噬归档（Exception Pass Ledger）

> 工程卫生收口登记：`narrowed` = 吞真错误，已收窄为 logger.warning(..., exc_info=True)；`keep-best-effort` = 意图性 best-effort，保持 pass；`deferred-batch-2` = 研究/测试/数据脚本，本轮不动。
>
> 覆盖范围：当前只登记了第一批生产代码中的异常吞噬；`deferred-batch-2` 的 24 处研究/测试/数据脚本吞异常尚未处理，不得视为已完成。

## 已收窄（本轮）

| 文件 | 行 | 处置 |
|---|---:|---|
| cs-skin-market/pipeline/collector_csqaq.py | 524 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 561 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 573 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 579 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 595 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 623 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 633 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 651 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 665 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 727 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 749 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 829 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 867 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 877 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 908 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 970 | narrowed |
| cs-skin-market/pipeline/collector_csqaq.py | 1024 | narrowed |
| cs-skin-market/pipeline/collector_monitor.py | 50 | narrowed |
| cs-skin-market/pipeline/collector_snapshot.py | 53 | narrowed |
| cs-skin-market/pipeline/discover_tasks.py | 35 | narrowed |
| cs-skin-market/pipeline/discover_tasks.py | 59 | narrowed |
| cs-skin-market/pipeline/discover_tasks.py | 189 | narrowed |
| cs-skin-market/pipeline/discover_tasks.py | 479 | narrowed |
| cs-skin-market/pipeline/scan_tasks.py | 49 | narrowed |
| cs-skin-market/pipeline/scan_tasks.py | 304 | narrowed |
| cs-skin-market/webapp/main.py | 1324 | narrowed |
| cs-skin-market/webapp/main.py | 1461 | narrowed |
| cs-skin-market/webapp/analysis_service.py | 586 | narrowed |

## 当前仍为 pass

| 文件 | 行 | except | 处置 |
|---|---:|---|---|
| cs-skin-market/collect_data_reserve_p0.py | 51 | `Exception:` | deferred-batch-2 |
| cs-skin-market/collect_data_reserve_p1.py | 70 | `Exception:` | deferred-batch-2 |
| cs-skin-market/data/_s1_backfill.py | 30 | `Exception:` | deferred-batch-2 |
| cs-skin-market/data/_s1_backfill.py | 32 | `FileNotFoundError:` | deferred-batch-2 |
| cs-skin-market/pipeline/collector.py | 134 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/collector_csqaq.py | 46 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/collector_csqaq.py | 346 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/collector_csqaq.py | 381 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/collector_csqaq.py | 411 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/collector_csqaq.py | 688 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/config.py | 34 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/dashboards.py | 174 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/db.py | 499 | `sqlite3.OperationalError:` | keep-best-effort |
| cs-skin-market/pipeline/db.py | 544 | `sqlite3.OperationalError:` | keep-best-effort |
| cs-skin-market/pipeline/db.py | 836 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/db.py | 1404 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/db.py | 1417 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/db.py | 1425 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/db.py | 1434 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/db.py | 1444 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/discover_tasks.py | 318 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/discover_tasks.py | 443 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/discover_tasks.py | 445 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/discover_tasks.py | 488 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/index_analysis.py | 1185 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/monitor.py | 222 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/pool_log.py | 27 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/scan_tasks.py | 29 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/scan_tasks.py | 65 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/scan_tasks.py | 220 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/scan_tasks.py | 322 | `Exception:` | keep-best-effort |
| cs-skin-market/pipeline/scan_tasks.py | 324 | `Exception:` | keep-best-effort |
| cs-skin-market/references/collect_bid_observations.py | 170 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/collect_bid_observations.py | 175 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/data_quality_review.py | 113 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/pool_expand_p2.py | 48 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/sale_caliber_compare.py | 39 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/scripts-archive/backfill_csqaq_365.py | 53 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/scripts-archive/backfill_csqaq_365.py | 75 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/scripts-archive/backfill_csqaq_365.py | 198 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/scripts-archive/backfill_yyyp.py | 30 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/scripts-archive/backfill_yyyp.py | 35 | `Exception:` | deferred-batch-2 |
| cs-skin-market/references/scripts-archive/run_backfill_history.py | 30 | `Exception:` | deferred-batch-2 |
| cs-skin-market/run_daily_collect.py | 28 | `Exception:` | keep-best-effort |
| cs-skin-market/run_daily_collect.py | 148 | `Exception:` | keep-best-effort |
| cs-skin-market/run_daily_collect.py | 422 | `Exception:` | keep-best-effort |
| cs-skin-market/run_daily_monitor.py | 27 | `Exception:` | keep-best-effort |
| cs-skin-market/run_data_health.py | 231 | `Exception:` | keep-best-effort |
| cs-skin-market/run_night_push.py | 27 | `Exception:` | keep-best-effort |
| cs-skin-market/tests/test_smoke.py | 874 | `Exception:` | deferred-batch-2 |
| cs-skin-market/tests/test_smoke.py | 930 | `Exception:` | deferred-batch-2 |
| cs-skin-market/tests/test_smoke.py | 1760 | `Exception:` | deferred-batch-2 |
| cs-skin-market/tests/test_smoke.py | 2364 | `Exception:` | deferred-batch-2 |
| cs-skin-market/tests/test_smoke.py | 2410 | `Exception:` | deferred-batch-2 |
| cs-skin-market/tests/test_smoke.py | 2455 | `Exception:` | deferred-batch-2 |
| cs-skin-market/tests/test_smoke.py | 2506 | `Exception:` | deferred-batch-2 |
| cs-skin-market/tests/test_smoke.py | 2562 | `Exception:` | deferred-batch-2 |
| cs-skin-market/tests/test_smoke.py | 3080 | `Exception:` | deferred-batch-2 |
| cs-skin-market/webapp/analysis_service.py | 210 | `Exception:` | keep-best-effort |
| cs-skin-market/webapp/analysis_service.py | 247 | `Exception:` | keep-best-effort |
| cs-skin-market/webapp/analysis_service.py | 1170 | `Exception:` | keep-best-effort |
| cs-skin-market/webapp/main.py | 58 | `(StopIteration, KeyError):` | keep-best-effort |
| cs-skin-market/webapp/main.py | 743 | `Exception:` | keep-best-effort |
| cs-skin-market/webapp/main.py | 859 | `Exception:` | keep-best-effort |
| cs-skin-market/webapp/main.py | 1023 | `Exception:` | keep-best-effort |
| cs-skin-market/webapp/main.py | 1056 | `Exception:` | keep-best-effort |
| cs-skin-market/webapp/main.py | 1755 | `Exception:` | keep-best-effort |
| cs-skin-market/webapp/render_html.py | 167 | `Exception:` | keep-best-effort |
## 处理标准

- 吞真错误（数据/计算异常）→ 收窄为 `logger.warning(..., exc_info=True)`。
- 意图性 best-effort（清理/可选特性/降级兜底）→ 保留 pass 或加 `# best-effort` 注释。
- `deferred-batch-2` 必须逐项按同一标准复核后，才能改为 `narrowed` 或 `keep-best-effort`。

