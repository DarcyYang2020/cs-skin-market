# W7-2 steamdt 蓄水池采集 · 调度接入契约（2026-08-27，④运维 → 研发）

> 依据：decision-log EZ（PM 拍板）+ EY（预研）。落库代码归**研发**交付，调度接入归**④运维**。
> 本契约 = 运维侧挂接规格，研发按此交付脚本后，④直接接入 18:00 链，无需再协商接口。

## 一、脚本接口契约（研发交付物）

- **脚本名（建议）**：`collect_steamdt_reserve.py`（放项目根目录，与 `collect_data_reserve_p0.py` 同级；同款风格）
- **运行方式**：独立 CLI，`python collect_steamdt_reserve.py`（无参数；如需 dry-run 可加 `--dry-run`）
- **退出码**：0=成功 / 非 0=失败（④侧 subprocess 记录 returncode，失败不中断主采集）
- **数据源**：steamdt.com 站内 GET API（零鉴权，urllib 即可，无需 playwright）
  - `https://www.steamdt.com/api/index/statistics/v1/summary`
  - `https://www.steamdt.com/api/index/players/v1/statistics`
  - `https://www.steamdt.com/api/index/item-block/v1/summary`
- **幂等**：以 `(date)` 为唯一键，重复运行同日期不重复插（INSERT OR IGNORE / date 唯一约束）
- **append-only**：只 INSERT，无 UPDATE/DELETE（对齐 D7 raw.db 源码级断言）
- **超时**：GET 三个端点，单次 <10s，脚本总耗时预期 <30s（④侧 subprocess timeout=2400s 兜底）
- **stdout**：最后一行输出结果摘要（如 `RESULT mode=APPLY market=1 blocks=32`），④侧会取末行记 log

## 二、落库表（raw.db，研发建表，字段对齐 EY 存证）

### raw_steamdt_market（每日 1 行）
```sql
CREATE TABLE IF NOT EXISTS raw_steamdt_market (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    date TEXT NOT NULL UNIQUE,
    broad_market_index REAL,
    diff_yesterday REAL,
    diff_yesterday_ratio REAL,
    add_num INTEGER,
    add_valuation REAL,
    trade_num INTEGER,
    turnover REAL,
    add_num_ratio REAL,
    add_amount_ratio REAL,
    trade_volume_ratio REAL,
    trade_amount_ratio REAL,
    survive_num INTEGER,
    holders_num INTEGER,
    online_count INTEGER,
    month_avg_online INTEGER,
    update_time TEXT,
    source TEXT DEFAULT 'steamdt'
)
```

### raw_steamdt_blocks（每日多行，板块指数）
```sql
CREATE TABLE IF NOT EXISTS raw_steamdt_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    date TEXT NOT NULL,
    level TEXT NOT NULL,           -- hot / level1 / level2 / level3
    block_name TEXT NOT NULL,
    index_value REAL,
    rise_fall_rate REAL,
    rise_fall_diff REAL,
    source TEXT DEFAULT 'steamdt',
    UNIQUE(date, level, block_name)
)
```

> 字段与 `data/_exp_w7_2_steamdt_probe.json` 存证一一对应（研发可读该文件对照解析）。

## 三、调度接入（④运维执行，PM 拍板后即挂）

对齐 `_run_data_reserve()` 模式（run_daily_collect.py）：

```python
def _run_steamdt_reserve():
    """W7-2（2026-08-27，PM 拍板 EZ）：steamdt.com 市场级数据蓄水池，每日 1 次。
    append-only 入 raw.db（raw_steamdt_market/blocks）；失败仅 log 不中断主采集。"""
    import subprocess
    root = os.path.dirname(os.path.abspath(__file__))
    py = sys.executable
    try:
        r = subprocess.run([py, os.path.join(root, "collect_steamdt_reserve.py")],
                           capture_output=True, text=True, timeout=2400, cwd=root)
        _tail = ((r.stdout or "").strip().splitlines() or [""])[-1]
        log(f"W7-2 steamdt 储备 {r.returncode} | {_tail}")
    except Exception as e:
        log(f"W7-2 steamdt 储备异常（不中断采集）: {type(e).__name__}: {str(e)[:100]}")
```

- **挂接点**：`_run_data_reserve()` 之后（D7 储备收尾后立即执行，均在健康检查之前）
- **触发**：每日 1 次（随 18:00 每日链无条件执行；GET 零鉴权负载 <10s，无频率顾虑）

## 四、验收（③审计复核点）

1. 表存在 + 建表 SQL 符合上述契约（UNIQUE(date) / UNIQUE(date,level,block_name) 幂等）；
2. append-only 断言：脚本内无 UPDATE/DELETE；
3. 冒烟：脚本 dry-run 或首跑成功，raw_steamdt_market=1 行 / blocks≥20 行（对齐 item-block 返回）；
4. 不 bump ENGINE_VERSION、不进引擎、不碰 market.db。

## 五、合规红线（决策依据 decision-log 2161）

- 仅采**公开市场级**数据（指数/成交/在线/板块），不涉账号、不涉交易明细、不涉登录态；
- **蓄水池积累 3-6 月后再评**（W7-1 v1c 届时复用），不即采即落主分析；
- 数据源 = **steamdt.com 独立站**（非悠悠有品）。
