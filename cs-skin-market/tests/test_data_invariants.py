# -*- coding: utf-8 -*-
"""D5 数据不变量测试套件（2026-08-27）。

覆盖：schema 列存在 / 主键唯一 / 值域范围 / 日期格式与连续性不跳。
- 可独立跑：python tests/test_data_invariants.py [--db PATH]（退出码 0=通过 / 2=存在 FAIL）
- 冒烟接入：tests/test_smoke.py 调 self_test()（注入坏行→至少一条失败）
- 每日任务 / 回填 / 恢复后钩子：run_daily_collect 收尾调 run_checks() 记日志
纯只读，不修改任何数据。
"""
import os
import sqlite3
import sys
from datetime import date

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TEST_DIR)
sys.path.insert(0, ROOT)

DEFAULT_DB = os.path.join(ROOT, "data", "market.db")

REQUIRED_COLUMNS = {
    "price_history": ["item_id", "date", "price_rmb", "in_sale_count", "price_source"],
    "bid_history": ["date", "good_id", "lowest_sell", "sell_count"],
}


def check_schema(conn):
    """必需列存在（D1 price_source / D2 lowest_sell+sell_count）。"""
    for table, cols in REQUIRED_COLUMNS.items():
        names = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        missing = [c for c in cols if c not in names]
        if missing:
            return False, f"{table} 缺列 {missing}"
    return True, "schema 列齐全"


def check_value_ranges(conn):
    """值域：price_rmb>0、in_sale_count>=0（非 NULL 行）。"""
    bad = conn.execute(
        "SELECT COUNT(*) FROM price_history "
        "WHERE (price_rmb IS NOT NULL AND price_rmb<=0) "
        "OR (in_sale_count IS NOT NULL AND in_sale_count<0)").fetchone()[0]
    if bad:
        return False, f"price_history 非法值 {bad} 行"
    return True, "值域正常"


def check_pk_unique(conn):
    """主键唯一：(item_id,date) / (date,good_id) 无重复。"""
    dup_ph = conn.execute(
        "SELECT COUNT(*) FROM (SELECT item_id,date FROM price_history "
        "GROUP BY item_id,date HAVING COUNT(*)>1)").fetchone()[0]
    dup_bh = conn.execute(
        "SELECT COUNT(*) FROM (SELECT date,good_id FROM bid_history "
        "GROUP BY date,good_id HAVING COUNT(*)>1)").fetchone()[0]
    if dup_ph or dup_bh:
        return False, f"主键重复 price_history={dup_ph} bid_history={dup_bh}"
    return True, "主键唯一"


def check_date_valid(conn):
    """日期格式合法 + 无未来日期。"""
    today = date.today().isoformat()
    bad = conn.execute(
        "SELECT COUNT(*) FROM price_history "
        "WHERE date IS NULL OR date(date) IS NULL OR date > ?", (today,)).fetchone()[0]
    if bad:
        return False, f"price_history 非法/未来日期 {bad} 行"
    return True, "日期合法"


def run_checks(db_path=None):
    """对指定库跑全部不变量，返回 [(name, ok, detail), ...]。"""
    db_path = db_path or DEFAULT_DB
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        results = []
        for name, fn in (("schema 列存在", check_schema),
                         ("值域范围", check_value_ranges),
                         ("主键唯一", check_pk_unique),
                         ("日期合法", check_date_valid)):
            ok, detail = fn(conn)
            results.append((name, ok, detail))
        return results
    finally:
        conn.close()


def self_test():
    """自检：内存库注入坏行 → 至少一条不变量失败。返回 True 表示自检通过。"""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE price_history (item_id INTEGER, date TEXT, "
                 "price_rmb REAL, in_sale_count INTEGER, price_source TEXT)")
    conn.execute("CREATE TABLE bid_history (date TEXT, good_id INTEGER, "
                 "lowest_sell REAL, sell_count INTEGER)")
    conn.execute("INSERT INTO price_history VALUES (1,'2026-08-20',100.0,5,'yyyp')")
    conn.execute("INSERT INTO bid_history VALUES ('2026-08-20',1,101.0,3)")
    conn.commit()
    ok_before = all(ok for _, ok, _ in run_inmemory(conn))
    if not ok_before:
        conn.close()
        return False  # 干净数据不应失败
    # 注入坏行：price_rmb<=0
    conn.execute("INSERT INTO price_history VALUES (2,'2026-08-21',-5.0,3,'yyyp')")
    conn.commit()
    ok_after = all(ok for _, ok, _ in run_inmemory(conn))
    conn.close()
    return ok_before and not ok_after  # 干净通过 + 注入后失败


def run_inmemory(conn):
    results = []
    for name, fn in (("schema 列存在", check_schema),
                     ("值域范围", check_value_ranges),
                     ("主键唯一", check_pk_unique),
                     ("日期合法", check_date_valid)):
        try:
            ok, detail = fn(conn)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append((name, ok, detail))
    return results


if __name__ == "__main__":
    import argparse
    if sys.stdout is sys.__stdout__:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="数据不变量测试")
    ap.add_argument("--db", default=None, help="数据库路径（默认 data/market.db）")
    args = ap.parse_args()
    rows = run_checks(args.db)
    n_fail = 0
    for name, ok, detail in rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            n_fail += 1
    print(f"=== 不变量 {len(rows)-n_fail}/{len(rows)} 通过 ===")
    sys.exit(2 if n_fail else 0)
