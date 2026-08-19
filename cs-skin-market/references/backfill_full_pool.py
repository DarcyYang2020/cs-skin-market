# -*- coding: utf-8 -*-
"""DATA-1 全池 3 年历史补全：非印花非角色全池 3 年价格+在售量回填到回放库 replay_cycle_win.db。

对齐键 = good_id（回放库 items.id 与生产库 items.id 错位，good_id 唯一对齐）。
范围 = 生产库 market.db items 排除印花（name LIKE '印花 |%'）与角色（5 关键词）。

去重不覆盖：按 (item_id, date) 只 INSERT 缺失日期，绝不 UPDATE 已有值。

用法:
  python references/backfill_full_pool.py --dry-run              # 全量清单（只读不写库）
  python references/backfill_full_pool.py --dry-run --limit 5    # 试跑前 5 品
  python references/backfill_full_pool.py --apply                # 实际回填（去重不覆盖 + 二次审计）
"""
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.collector import _api_call  # noqa: E402
from pipeline.config import TZ_BJ  # noqa: E402

PROD_DB = ROOT / "data" / "market.db"
REPLAY_DB = ROOT / "data" / "replay_cycle_win.db"
PLAN_OUT = ROOT / "data" / "_exp_data1_plan.json"

# 角色关键词（5 个，立项卡清单；指挥官梅为弯引号变体，按关键词识别更稳）
ROLE_KEYWORDS = ("特警", "游击队", "军刀勇士", "海豹部队", "巴西第一营")
STICKER_PREFIX = "印花 |"


def log(msg: str):
    print(msg, flush=True)


def is_role(name: str) -> bool:
    return any(k in name for k in ROLE_KEYWORDS)


def is_sticker(name: str) -> bool:
    return name.startswith(STICKER_PREFIX)


def fetch_sell(good_id: int):
    resp = _api_call("POST", "/info/chart", {
        "good_id": str(good_id), "key": "sell_price", "platform": 2,
        "period": "1095", "style": "all_style",
    })
    if resp.get("code") != 200 or not isinstance(resp.get("data"), dict):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def parse_daily(data: dict) -> dict:
    """sell_price period=1095 → {date: (price, in_sale)}（日线，每日单值）。"""
    out = {}
    ts = data.get("timestamp") or []
    price = data.get("main_data") or []
    num = data.get("num_data") or []
    n = min(len(ts), len(price), len(num))
    for i in range(n):
        try:
            t = int(ts[i])
            if t < 10 ** 11:
                t *= 1000
            p = float(price[i])
            s = float(num[i])
        except (TypeError, ValueError):
            continue
        if t <= 0 or p <= 0:
            continue
        day = datetime.fromtimestamp(t / 1000, tz=TZ_BJ).strftime("%Y-%m-%d")
        out[day] = (round(p, 2), int(s) if s >= 0 else None)
    return out


def load_prod_targets():
    """读生产库，分类印花/角色/目标，返回 (stickers, roles, targets)。"""
    conn = sqlite3.connect(PROD_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, good_id, weapon, skin, wear FROM items").fetchall()
    conn.close()
    stickers, roles, targets = [], [], []
    for r in rows:
        if is_sticker(r["name"]):
            stickers.append(r)
        elif is_role(r["name"]):
            roles.append(r)
        else:
            targets.append(r)
    return stickers, roles, targets


def load_replay_map():
    """回放库 items 的 good_id → (replay_id, name) 映射，以及已有 date 集合。"""
    conn = sqlite3.connect(REPLAY_DB)
    conn.row_factory = sqlite3.Row
    gid_map = {}
    for r in conn.execute("SELECT id, name, good_id FROM items"):
        if r["good_id"] and r["good_id"] > 0:
            gid_map[r["good_id"]] = (r["id"], r["name"])
    existing_dates = {}
    for r in conn.execute("SELECT item_id, date FROM price_history"):
        existing_dates.setdefault(r["item_id"], set()).add(r["date"])
    conn.close()
    return gid_map, existing_dates


def build_plan(limit: int = 0):
    """dry-run：构造精确目标清单（调接口拿天数，不写库）。"""
    stickers, roles, targets = load_prod_targets()
    gid_map, existing_dates = load_replay_map()

    no_gid = [t for t in targets if not t["good_id"] or t["good_id"] <= 0]
    with_gid = [t for t in targets if t["good_id"] and t["good_id"] > 0]
    already = [t for t in with_gid if t["good_id"] in gid_map]
    need_new = [t for t in with_gid if t["good_id"] not in gid_map]

    pool = with_gid
    if limit:
        pool = pool[:limit]

    plan = []
    failed = []
    for i, t in enumerate(pool, 1):
        gid = t["good_id"]
        rid = gid_map.get(gid, (None, None))[0]
        exist = existing_dates.get(rid, set()) if rid else set()
        data, err = fetch_sell(gid)
        if data is None:
            failed.append({"name": t["name"], "good_id": gid, "err": err})
            plan.append({
                "name": t["name"], "prod_id": t["id"], "good_id": gid,
                "action": "fetch_failed",
                "already_in_replay": rid is not None, "replay_item_id": rid,
                "existing_first_date": min(exist) if exist else None,
                "existing_days": len(exist), "api_days": None, "need_days": None,
                "reason": err,
            })
            log(f"[{i}/{len(pool)}] good={gid} FETCH-FAIL {err} {t['name'][:24]}")
            continue
        series = parse_daily(data)
        need = set(series) - exist
        entry = {
            "name": t["name"], "prod_id": t["id"], "good_id": gid,
            "action": "backfill" if rid else "new_item_backfill",
            "already_in_replay": rid is not None, "replay_item_id": rid,
            "existing_first_date": min(exist) if exist else None,
            "existing_days": len(exist), "api_days": len(series),
            "need_days": len(need),
            "reason": None,
        }
        plan.append(entry)
        if i <= 3 or i % 25 == 0:
            log(f"[{i}/{len(pool)}] good={gid} api_days={len(series)} "
                f"exist={len(exist)} need={len(need)} {t['name'][:22]}")

    summary = {
        "prod_total": len(stickers) + len(roles) + len(targets),
        "sticker_excluded": len(stickers),
        "sticker_rule": "name.startswith('印花 |')（印花集枪皮 name 为 M4A1消音版 | 印花集，天然不含前缀，不会误排）",
        "role_excluded": len(roles),
        "role_list": [r["name"] for r in roles],
        "target_total": len(targets),
        "target_no_good_id": len(no_gid),
        "no_good_id_names": [r["name"] for r in no_gid],
        "target_with_good_id": len(with_gid),
        "already_in_replay": len(already),
        "need_new_item": len(need_new),
        "fetch_failed_in_plan": len(failed),
        "note": "角色 5 个（立项卡用户口径 4、实际核查 5），故目标=405-160-5=240 而非 241；good_id<=0 品登记「数据源无 good_id」跳过",
    }
    return {
        "meta": {
            "task": "DATA-1", "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "engine_version": "v2-T13", "prod_db": str(PROD_DB.name),
            "replay_db": str(REPLAY_DB.name), "limit": limit or None,
        },
        "summary": summary,
        "plan": plan,
        "excluded_roles_detail": [{"name": r["name"], "good_id": r["good_id"]} for r in roles],
    }


def apply_backfill():
    """实际回填：备份 → 新增缺失 items 行 → 去重 INSERT → 二次审计。"""
    # 1. 备份回放库（研究域 .bak 自清规则）
    bak = REPLAY_DB.with_suffix(".db.bak-data1")
    shutil.copy2(REPLAY_DB, bak)
    log(f"backup: {bak.name}")

    stickers, roles, targets = load_prod_targets()
    no_gid = [t for t in targets if not t["good_id"] or t["good_id"] <= 0]
    with_gid = [t for t in targets if t["good_id"] and t["good_id"] > 0]
    log(f"targets: {len(targets)} | no_good_id: {len(no_gid)} | with_good_id: {len(with_gid)}")

    conn = sqlite3.connect(REPLAY_DB)
    conn.row_factory = sqlite3.Row

    # 2. 现有 good_id → replay_id 映射 + 已有 date 集合（回填前快照）
    gid_map = {}
    for r in conn.execute("SELECT id, name, good_id FROM items"):
        if r["good_id"] and r["good_id"] > 0:
            gid_map[r["good_id"]] = (r["id"], r["name"])
    existing_dates = {}
    for r in conn.execute("SELECT item_id, date, price_rmb, in_sale_count FROM price_history"):
        existing_dates.setdefault(r["item_id"], {})[r["date"]] = (r["price_rmb"], r["in_sale_count"])

    # 3. 新增缺失 items 行（good_id 不在回放库的目标品）
    inserted_items = 0
    for t in with_gid:
        if t["good_id"] not in gid_map:
            cur = conn.execute(
                "INSERT INTO items (name, good_id) VALUES (?, ?)",
                (t["name"], t["good_id"]))
            rid = cur.lastrowid
            gid_map[t["good_id"]] = (rid, t["name"])
            inserted_items += 1
    conn.commit()
    log(f"inserted new items rows: {inserted_items}")

    # 4. 逐品回填（去重：只 INSERT 缺失日期，绝不 UPDATE）
    inserted = skipped = failed = 0
    total = len(with_gid)
    before_rows = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    for i, t in enumerate(with_gid, 1):
        gid = t["good_id"]
        rid = gid_map[gid][0]
        exist = existing_dates.get(rid, {})
        data, err = fetch_sell(gid)
        if data is None:
            failed += 1
            log(f"[{i}/{total}] good={gid} FAIL {err}")
            continue
        series = parse_daily(data)
        for day, (price, insale) in series.items():
            if day in exist:
                skipped += 1  # 已存在日期，跳过（不覆盖）
                continue
            conn.execute(
                "INSERT INTO price_history (item_id, date, price_rmb, volume_day, volume_total, in_sale_count) "
                "VALUES (?,?,?,?,?,?)", (rid, day, price, None, None, insale))
            inserted += 1
        if i <= 3 or i % 25 == 0:
            log(f"[{i}/{total}] good={gid} new={len(set(series)-set(exist))} "
                f"skip={len(set(series)&set(exist))} {t['name'][:22]}")
    conn.commit()
    after_rows = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]

    # 5. 二次审计
    # 5a. 已存在日期零覆盖：回填前快照 (item_id,date)→(price,insale) 回填后必须一致
    overwritten = 0
    checked = 0
    for rid, dates in existing_dates.items():
        for day, (p, s) in dates.items():
            row = conn.execute(
                "SELECT price_rmb, in_sale_count FROM price_history WHERE item_id=? AND date=?",
                (rid, day)).fetchone()
            if row is None:
                continue
            checked += 1
            if (row["price_rmb"], row["in_sale_count"]) != (p, s):
                overwritten += 1
    # 5b. first_date < 2025-08-01 覆盖率
    target_ids = [gid_map[t["good_id"]][0] for t in with_gid]
    q = "SELECT item_id, MIN(date) fd FROM price_history WHERE item_id IN (%s) GROUP BY item_id" % ",".join("?" * len(target_ids))
    fd_map = {r["item_id"]: r["fd"] for r in conn.execute(q, target_ids)}
    covered = sum(1 for rid in target_ids if fd_map.get(rid) and fd_map[rid] < "2025-08-01")
    not_covered = [gid_map[t["good_id"]][1] for t in with_gid
                   if not fd_map.get(gid_map[t["good_id"]][0]) or fd_map[gid_map[t["good_id"]][0]] >= "2025-08-01"]
    conn.close()

    audit = {
        "backup": str(bak),
        "target_total": len(targets),
        "no_good_id_skipped": len(no_gid),
        "with_good_id": total,
        "inserted_items_rows": inserted_items,
        "inserted_dates": inserted,
        "skipped_existing_dates": skipped,
        "failed_goods": failed,
        "before_price_rows": before_rows,
        "after_price_rows": after_rows,
        "overwritten_existing": overwritten,
        "overwrite_check_count": checked,
        "first_date_covered": covered,
        "first_date_not_covered": not_covered,
        "cover_rate": round(covered / total, 4) if total else None,
    }
    log(f"APPLY done: inserted_dates={inserted} skipped={skipped} failed={failed} "
        f"new_items={inserted_items} overwritten={overwritten}")
    log(f"  rows {before_rows} -> {after_rows}")
    log(f"  first_date<2025-08-01 covered {covered}/{total}")
    if not_covered:
        log(f"  NOT COVERED: {not_covered}")
    return audit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if args.dry_run:
        result = build_plan(args.limit)
        with open(PLAN_OUT, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        s = result["summary"]
        log(f"DRY-RUN done: target={s['target_total']} (sticker={s['sticker_excluded']} "
            f"role={s['role_excluded']}) no_gid={s['target_no_good_id']} "
            f"already={s['already_in_replay']} need_new={s['need_new_item']}")
        log(f"  plan saved: {PLAN_OUT.name}")

    if args.apply:
        audit = apply_backfill()
        out = ROOT / "data" / "_exp_data1_audit.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(audit, f, ensure_ascii=False, indent=1)
        log(f"  audit saved: {out.name}")


if __name__ == "__main__":
    main()
