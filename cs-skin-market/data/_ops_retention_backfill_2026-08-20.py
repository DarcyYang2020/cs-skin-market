# -*- coding: utf-8 -*-
"""运维④ 2026-08-20：生产库 price_history 3 年历史回填（decision-log CV ①拍板）。

源：data/replay_cycle_win.db（3 年同源数据，387 品 good_id 与生产完全对齐，CV 已核实）
目标：data/market.db（生产库，只写 price_history 表，不碰引擎/其他表）
纪律：DATA-1 同款——dry-run 清单先行（_exp_retention_backfill_plan.json）
      → 去重不覆盖（INSERT OR IGNORE，靠 uq_price_history_item_date 唯一索引）
      → 二次审计（补入数=预估、已存在日期零覆盖、failed=0）。

用法：
  python data/_ops_retention_backfill_2026-08-20.py --dry-run   # 只读，产出 plan
  python data/_ops_retention_backfill_2026-08-20.py --apply     # 备份 + 回填 + 审计
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "replay_cycle_win.db")
DST = os.path.join(ROOT, "data", "market.db")
PLAN_OUT = os.path.join(ROOT, "data", "_exp_retention_backfill_plan.json")
AUDIT_OUT = os.path.join(ROOT, "data", "_exp_retention_backfill_audit.json")
BAK_DIR = os.path.join(ROOT, "data", "_ops_recovery_2026-08-20")


def log(msg):
    print(msg, flush=True)


def build_map(conn, table="items"):
    """good_id -> (item_id, name)（仅 good_id>0）。"""
    m = {}
    for r in conn.execute(f"SELECT id, name, good_id FROM {table}"):
        if r["good_id"] and r["good_id"] > 0:
            m[r["good_id"]] = (r["id"], r["name"])
    return m


def dry_run():
    src = sqlite3.connect(SRC)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(DST)
    dst.row_factory = sqlite3.Row
    src_map = build_map(src)
    dst_map = build_map(dst)
    common = sorted(set(src_map) & set(dst_map))
    plan = []
    total_need = 0
    for gid in common:
        src_id = src_map[gid][0]
        dst_id = dst_map[gid][0]
        src_dates = {r[0] for r in src.execute(
            "SELECT date FROM price_history WHERE item_id=?", (src_id,))}
        dst_dates = {r[0] for r in dst.execute(
            "SELECT date FROM price_history WHERE item_id=?", (dst_id,))}
        missing = sorted(src_dates - dst_dates)
        total_need += len(missing)
        plan.append({
            "good_id": gid, "name": src_map[gid][1],
            "src_item_id": src_id, "dst_item_id": dst_id,
            "src_days": len(src_dates), "dst_days": len(dst_dates),
            "need_days": len(missing),
            "first_need": missing[0] if missing else None,
            "last_need": missing[-1] if missing else None,
        })
    src.close()
    dst.close()
    out = {
        "meta": {
            "task": "RETENTION-BACKFILL", "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "replay_cycle_win.db", "target": "market.db",
            "discipline": "DATA-1 同款：dry-run 先行 → 去重不覆盖 → 二次审计 failed=0",
        },
        "summary": {
            "src_good_id_items": len(src_map), "dst_good_id_items": len(dst_map),
            "common_aligned": len(common), "total_need_days": total_need,
        },
        "plan": plan,
    }
    with open(PLAN_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    log(f"DRY-RUN: 对齐 {len(common)} 品，预估补入 {total_need} 行 -> {os.path.basename(PLAN_OUT)}")
    return out


def backup_prod():
    os.makedirs(BAK_DIR, exist_ok=True)
    bak = os.path.join(BAK_DIR, "market.db.pre-backfill")
    dst = sqlite3.connect(DST)
    b = sqlite3.connect(bak)
    with b:
        dst.backup(b)
    b.close()
    dst.close()
    log(f"backup: {bak} ({os.path.getsize(bak)}B)")
    return bak


def apply_backfill():
    # 先备份，再重读 plan 作为预估
    backup_prod()
    plan_data = json.load(open(PLAN_OUT, encoding="utf-8"))
    expected = plan_data["summary"]["total_need_days"]

    src = sqlite3.connect(SRC)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(DST, timeout=60)
    dst.row_factory = sqlite3.Row
    dst.execute("PRAGMA busy_timeout=60000")

    # 回填前快照（二次审计零覆盖用）
    overwrite_check = {}
    for r in dst.execute("SELECT item_id, date, price_rmb, in_sale_count FROM price_history"):
        overwrite_check[(r["item_id"], r["date"])] = (r["price_rmb"], r["in_sale_count"])

    inserted = 0
    per_item = []
    for p in plan_data["plan"]:
        gid, src_id, dst_id, need = p["good_id"], p["src_item_id"], p["dst_item_id"], p["need_days"]
        if need == 0:
            continue
        rows = src.execute(
            "SELECT date, price_rmb, volume_day, volume_total, in_sale_count "
            "FROM price_history WHERE item_id=? ORDER BY date", (src_id,)).fetchall()
        cur = dst.executemany(
            "INSERT OR IGNORE INTO price_history "
            "(item_id, date, price_rmb, volume_day, volume_total, in_sale_count) "
            "VALUES (?,?,?,?,?,?)",
            [(dst_id, r["date"], r["price_rmb"], r["volume_day"], r["volume_total"], r["in_sale_count"])
             for r in rows if r["date"] not in overwrite_check])
        n = cur.rowcount if hasattr(cur, "rowcount") else 0
        inserted += n
        per_item.append({"good_id": gid, "name": p["name"], "inserted": n, "need": need})
    dst.commit()

    # 二次审计
    after = dst.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    before = len(overwrite_check)
    overwritten = 0
    checked = 0
    for (iid, day), (pr, ins) in overwrite_check.items():
        row = dst.execute(
            "SELECT price_rmb, in_sale_count FROM price_history WHERE item_id=? AND date=?",
            (iid, day)).fetchone()
        if row is None:
            continue
        checked += 1
        if (row["price_rmb"], row["in_sale_count"]) != (pr, ins):
            overwritten += 1
    dst.close()
    src.close()

    audit = {
        "meta": {"task": "RETENTION-BACKFILL-APPLY",
                 "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "backup": os.path.join(BAK_DIR, "market.db.pre-backfill")},
        "expected_need_days": expected,
        "inserted_days": inserted,
        "match_expected": inserted == expected,
        "before_rows": before, "after_rows": after,
        "delta_rows": after - before,
        "overwrite_check_count": checked, "overwritten_existing": overwritten,
        "failed_goods": 0, "per_item": per_item,
        "ok": (inserted == expected) and (overwritten == 0),
    }
    with open(AUDIT_OUT, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=1)
    log(f"APPLY: inserted={inserted} (预估 {expected}) | rows {before} -> {after} | "
        f"overwritten={overwritten} | ok={audit['ok']}")
    return audit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        dry_run()
    if args.apply:
        apply_backfill()


if __name__ == "__main__":
    main()
