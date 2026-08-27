# -*- coding: utf-8 -*-
"""数据源健康监控：复用 run_data_health 检查逻辑 → 结果 upsert 进 health_checks 表。

用法:
    python run_health_monitor.py            # 人类可读摘要
    python run_health_monitor.py --json     # JSON 输出（供告警/日志）
    python run_health_monitor.py --db PATH  # 指定数据库路径（测试/排查用）

退出码（与 run_data_health 一致）:
    0 = 全部通过
    2 = 存在 FAIL（数据异常，需人工核查）

定时接入说明:
    每日采集 run_daily_collect.py 收尾自动调用本监控（Windows 计划任务已挂该脚本）；
    如需独立告警调度，可另建计划任务运行 `python run_health_monitor.py`，
    以退出码 0/2 判定健康状态（0 正常 / 2 异常需人工核查）。
"""
import sys, io, os, json, argparse, sqlite3
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
DEFAULT_DB = os.path.join(BASE, "data", "market.db")


def run_monitor(db_path=None, check_date=None):
    """执行健康检查并把结果写入 health_checks 表，返回摘要 dict。

    - 复用 run_data_health.run_checks（纯 SQLite 只读，不触发任何采集）
    - 每天按 date upsert 一条；任一检查 FAIL → status=fail，否则 pass
    - 读库/写库异常由调用方捕获（run_daily_collect 收尾调用处 try/except 只记录不中断）
    返回: {"status": "pass|fail", "date": YYYY-MM-DD, "checks": [...], "fail_count": int}
    """
    db_path = db_path or DEFAULT_DB
    check_date = check_date or date.today().isoformat()

    from run_data_health import run_checks
    rows = run_checks(db_path)
    checks = [{"name": n, "level": lv, "detail": dt} for n, lv, dt in rows]
    # D3（2026-08-27）：清洗台账当日触警计数进健康检查（纯统计，不判 FAIL）
    try:
        from pipeline.cleaning_ledger import count_since
        _cl_today = count_since(check_date)
        checks.append({"name": "清洗触警台账(当日)", "level": "PASS",
                       "detail": f"cleaning_ledger 当日 {_cl_today} 条"})
    except Exception:
        pass
    n_fail = sum(1 for _, lv, _ in rows if lv == "FAIL")
    status = "fail" if n_fail else "pass"

    conn = sqlite3.connect(db_path, timeout=10)
    try:
        from pipeline import db
        db._init_schema(conn)  # 幂等建表，兼容任意库
        db.save_health_check(conn, check_date, status, json.dumps(checks, ensure_ascii=False))
    finally:
        conn.close()
    return {"status": status, "date": check_date, "checks": checks, "fail_count": n_fail}


def main():
    if sys.stdout is sys.__stdout__:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="数据源健康监控（写 health_checks 表）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--db", default=None, help="数据库路径（默认 data/market.db）")
    args = ap.parse_args()

    res = run_monitor(db_path=args.db)
    if args.json:
        print(json.dumps({"ok": res["fail_count"] == 0, "status": res["status"],
                          "date": res["date"], "fail_count": res["fail_count"],
                          "checks": res["checks"]}, ensure_ascii=False, indent=2))
    else:
        for c in res["checks"]:
            mark = "[PASS]" if c["level"] == "PASS" else "[FAIL]"
            print(f"{mark} {c['name']}: {c['detail']}")
        n_pass = len(res["checks"]) - res["fail_count"]
        print(f"\n== {n_pass}/{len(res['checks'])} 通过, FAIL={res['fail_count']}, 状态={res['status']}（已写入 health_checks）==")
    return 2 if res["fail_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
