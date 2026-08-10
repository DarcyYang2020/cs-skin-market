# -*- coding: utf-8 -*-
"""数据质量定期复核（2026-08-10）：抽样联网实拉 chart vs DB price_history 逐日对齐。

三层数据质量机制（data-layer.md §8 前置）：
  日常层（每日）  run_data_health.py + run_health_monitor.py —— SQLite 只读基线体检 + FAIL 告警
  周期层（每周）  本脚本抽样复核 —— 持仓品全量 + 自选/活跃池随机（默认 15 品），
                  用 fetch_kline_90d（悠悠锚 + 串品防护）重采当日真实 chart，
                  与 DB price_history 逐日对比价格/在售量偏差，产出 data_review_*.json
  深度层（触发/每月）data-layer.md §8 全库逐品实拉 SOP（8/9 已执行，修复+回放联动）

用法:
    python references/data_quality_review.py [--sample N] [--fix]
        --sample N   抽样品数上限（默认 15；含全部持仓品）
        --fix        对 ISSUE 品按 §8 回填（仅改偏差>20% 行的 price_rmb/in_sale_count，
                     原值备份 data/_data_review_backup_<date>.json；默认只读不修）
        --skip-net   跳过联网（测试/CI），仅做抽样清单与上次复核时间检查

退出码: 0 = 全部 OK / 2 = 存在 ISSUE（建议人工核查，或 --fix 后重跑）
产物: data/data_review_<YYYYMMDD>.json（证据留存）+ data/data_review_latest.json（最新指针）
      settings: data_review_last=YYYY-MM-DD（供每日任务判频率）
"""
import asyncio, io, json, os, random, sqlite3, statistics, sys
from datetime import date, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market.db")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

DEV_TH = 20.0   # 单日偏差>20% 记敏感段（与锚校验口径一致）
MED_TH = 10.0   # 整段价格偏差中位数>10% 判 ISSUE


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sample_items(conn, limit=15):
    """持仓品全量 + 自选 + 活跃池随机，去重，上限 limit。"""
    held = conn.execute("SELECT id, name, good_id FROM items WHERE holding=1 AND good_id>0").fetchall()
    wl = conn.execute("SELECT id, name, good_id FROM items WHERE in_watchlist=1 AND good_id>0").fetchall()
    pool = conn.execute(
        "SELECT id, name, good_id FROM items WHERE good_id>0 AND holding=0 AND in_watchlist=0 "
        "AND (notes IS NULL OR (notes NOT LIKE '%存世量过低%' AND notes NOT LIKE '%活跃池淘汰%'))").fetchall()
    pool = list(pool)
    random.shuffle(pool)
    chosen, seen = [], set()
    for r in list(held) + list(wl) + pool:
        if len(chosen) >= limit:
            break
        gid = r["good_id"]
        if gid in seen:
            continue
        seen.add(gid)
        chosen.append({"id": r["id"], "name": r["name"], "good_id": gid})
    return chosen


def db_rows(conn, item_id):
    rows = conn.execute("SELECT date, price_rmb, in_sale_count FROM price_history WHERE item_id=?", (item_id,)).fetchall()
    return {r["date"]: {"price": r["price_rmb"] or 0, "sale": r["in_sale_count"] or 0} for r in rows}


def compare(bars, dmap):
    """bars（fetch_kline_90d 输出，含 date/close/in_sale_count）与 DB 逐日对比。

    返回 dict: n_days / dev_pct 中位数 / n_dev_gt20（价格敏感段）/ sale 中位偏差 / 分类 OK|ISSUE
    """
    devs_p, devs_s, n20 = [], [], 0
    dev_days = []
    for b in bars:
        d = getattr(b, "date", "")
        if not d or d not in dmap:
            continue
        live_p = float(getattr(b, "close", 0) or 0)
        live_s = float(getattr(b, "in_sale_count", 0) or 0)
        db_p = dmap[d]["price"]; db_s = dmap[d]["sale"]
        if live_p > 0 and db_p > 0:
            dev = abs(live_p / db_p - 1) * 100
            devs_p.append(round(dev, 1))
            if dev > DEV_TH:
                n20 = n20 + 1
                if len(dev_days) < 30:
                    dev_days.append({"date": d, "db_price": db_p, "live_price": live_p,
                                     "db_sale": db_s, "live_sale": live_s, "dev_pct": round(dev, 1)})
        if live_s > 0 and db_s > 0:
            devs_s.append(round(abs(live_s / db_s - 1) * 100, 1))
    med_p = round(statistics.median(devs_p), 1) if devs_p else None
    med_s = round(statistics.median(devs_s), 1) if devs_s else None
    status = "OK" if (med_p is not None and med_p < MED_TH and n20 == 0) else "ISSUE"
    return {"n_days": len(devs_p), "med_dev_pct": med_p, "n_dev_gt20": n20, "dev_days": dev_days,
            "med_sale_dev_pct": med_s, "status": status}


def write_review(report):
    _d = date.today().strftime("%Y%m%d")
    _path = os.path.join(BASE, "data", f"data_review_{_d}.json")
    with io.open(_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    with io.open(os.path.join(BASE, "data", "data_review_latest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return _path


def set_last_review(date_str):
    try:
        from pipeline import db
        conn = db.get_conn()
        try:
            db.set_setting(conn, "data_review_last", date_str)
        finally:
            conn.close()
    except Exception:
        pass


def get_last_review():
    try:
        from pipeline import db
        conn = db.get_conn()
        try:
            v = db.get_setting(conn, "data_review_last", "") or ""
        finally:
            conn.close()
        return v
    except Exception:
        return ""


def _apply_fix(item, dev_days):
    """--fix 回填（按 §8 SOP）：仅改偏差>20% 行的 price_rmb/in_sale_count，原值备份。"""
    _d = date.today().strftime("%Y%m%d")
    _bk = os.path.join(BASE, "data", f"_data_review_backup_{_d}.json")
    backup = []
    if os.path.exists(_bk):
        try:
            with io.open(_bk, encoding="utf-8") as f:
                backup = json.load(f)
        except Exception:
            backup = []
    fixed = 0
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        for dd in dev_days:
            row = conn.execute("SELECT price_rmb, in_sale_count, created_at FROM price_history "
                               "WHERE item_id=? AND date=?", (item["id"], dd["date"])).fetchone()
            if not row:
                continue
            backup.append({"item_id": item["id"], "name": item["name"], "date": dd["date"],
                           "old_price": row["price_rmb"], "new_price": dd["live_price"],
                           "old_sale": row["in_sale_count"], "new_sale": dd.get("live_sale") or row["in_sale_count"]})
            conn.execute("UPDATE price_history SET price_rmb=?, in_sale_count=? WHERE item_id=? AND date=?",
                         (dd["live_price"], dd.get("live_sale") or row["in_sale_count"], item["id"], dd["date"]))
            fixed += 1
        conn.commit()
    finally:
        conn.close()
    with io.open(_bk, "w", encoding="utf-8", newline="\n") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1)
    print(f"  --fix {item['name']}: 回填 {fixed} 行（备份 {_bk}）", flush=True)
    return fixed


async def run_review(sample_limit=15, fix=False):
    from pipeline import collector_csqaq as cc
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        items = sample_items(conn, limit=sample_limit)
    finally:
        conn.close()
    report = {"generated": _now(), "mode": "fix" if fix else "readonly",
              "sample_limit": sample_limit, "items": []}
    issues = []
    for i, it in enumerate(items, 1):
        print(f"[{i}/{len(items)}] 复核 {it['name'][:34]}", flush=True)
        try:
            bars, _raw = await cc.fetch_kline_90d(it["good_id"])
        except Exception as e:
            report["items"].append({**it, "error": str(e)[:120], "status": "FETCH_ERR"})
            issues.append(it["name"])
            await asyncio.sleep(1.5)
            continue
        if not bars:
            report["items"].append({**it, "error": "chart 空/串品防护返回空（保留 DB 值）", "status": "FETCH_ERR"})
            issues.append(it["name"])
            await asyncio.sleep(1.5)
            continue
        conn2 = sqlite3.connect(DB_PATH, timeout=10)
        conn2.row_factory = sqlite3.Row
        try:
            dmap = db_rows(conn2, it["id"])
        finally:
            conn2.close()
        cmp = compare(bars, dmap)
        if fix and cmp["status"] == "ISSUE" and cmp.get("dev_days"):
            _fixed = _apply_fix(it, cmp["dev_days"])
            cmp["fixed_rows"] = _fixed
        entry = {**it, **cmp}
        report["items"].append(entry)
        if cmp["status"] != "OK":
            issues.append(it["name"])
        await asyncio.sleep(1.5)  # G-4 限流退避
    n_issue = sum(1 for x in report["items"] if x.get("status") != "OK")
    report["summary"] = {"total": len(items), "issue": n_issue,
                         "issue_names": issues, "date": date.today().isoformat()}
    saved = write_review(report)
    set_last_review(date.today().isoformat())
    print("written:", saved)
    print("summary:", report["summary"])
    return report


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=15)
    ap.add_argument("--fix", action="store_true", default=False)
    ap.add_argument("--skip-net", action="store_true", default=False)
    args = ap.parse_args()
    if args.skip_net:
        last = get_last_review()
        print(f"[skip-net] 上次复核: {last or '从未'}；本次仅检查频率逻辑（联网复核需正常网络）")
        return 0
    report = asyncio.run(run_review(sample_limit=args.sample, fix=args.fix))
    return 2 if report["summary"]["issue"] else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
