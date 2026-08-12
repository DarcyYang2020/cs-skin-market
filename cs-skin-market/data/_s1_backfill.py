# -*- coding: utf-8 -*-
"""S-1: 160 品贴纸深历史全量回填（断点续跑）。
每品成功即 append 一行到 data/_exp_sticker_deep_full.jsonl；
进度写 data/_sticker_deep_full_progress.json；可随时中断，重跑自动续。
不进 price_history、不动引擎基线；只读网络采集。"""
import asyncio, io, json, sys, time
from datetime import datetime
sys.path.insert(0, ".")
from pipeline import collector_csqaq, db

BASE = "data"
OUT = f"{BASE}/_exp_sticker_deep_full.jsonl"
SEED = f"{BASE}/_exp_sticker_deep_seed.json"
PROG = f"{BASE}/_sticker_deep_full_progress.json"
LOG = io.open(f"{BASE}/_sticker_deep_full.log", "a", encoding="utf-8")

def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()

def done_ids():
    seen = set()
    try:
        with io.open(OUT, encoding="utf-8") as f:
            for ln in f:
                try:
                    seen.add(json.loads(ln)["good_id"])
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return seen

async def main():
    # 1) 全部目标
    conn = db.get_conn()
    rows = conn.execute("SELECT good_id, name FROM items WHERE source='sticker' AND good_id>0 ORDER BY id").fetchall()
    conn.close()
    targets = [{"good_id": r["good_id"], "name": r["name"]} for r in rows]
    log(f"S-1 目标 {len(targets)} 品")

    # 2) seed 12 品直转（避免重复拉取）
    done = done_ids()
    try:
        seed = json.load(io.open(SEED, encoding="utf-8"))
        for it in seed["items"]:
            if it["good_id"] not in done:
                with io.open(OUT, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"good_id": it["good_id"], "name": it["name"],
                                        "points": it["points"]}, ensure_ascii=False) + "\n")
                done.add(it["good_id"])
                log(f"  seed 直转 {it['good_id']} {it['name']} points={len(it['points'])}")
    except Exception as e:
        log(f"seed 转换跳过: {e}")

    # 3) 拉剩余
    todo = [t for t in targets if t["good_id"] not in done]
    log(f"待拉 {len(todo)} 品（已完成 {len(done)}）")
    ok = fail = 0
    empty_run = 0
    prog = {"started": datetime.now().isoformat(timespec="seconds"), "total": len(targets),
            "done": len(done), "ok": 0, "fail": 0, "current": "", "ts": datetime.now().isoformat(timespec="seconds")}
    for i, t in enumerate(todo, 1):
        gid, name = t["good_id"], t["name"]
        got = False
        for attempt in (1, 2):
            try:
                pts = await collector_csqaq.fetch_history_deep(gid, min_date="2025-01-01")
            except Exception as e:
                log(f"  [{i}/{len(todo)}] {gid} {name[:30]} ERR {str(e)[:50]} (try{attempt})")
                await asyncio.sleep(8)
                continue
            if pts:
                with io.open(OUT, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"good_id": gid, "name": name, "points": [[d, c] for d, c in pts]},
                                       ensure_ascii=False) + "\n")
                ok += 1; empty_run = 0
                log(f"  [{i}/{len(todo)}] OK {gid} {name[:34]} points={len(pts)} {pts[0][0]}~{pts[-1][0]} (try{attempt})")
                got = True
                break
            log(f"  [{i}/{len(todo)}] {gid} {name[:30]} EMPTY (try{attempt})")
            empty_run += 1
            await asyncio.sleep(8)
        if not got:
            fail += 1
            log(f"  [{i}/{len(todo)}] FAIL {gid} {name[:30]}")
        prog.update({"done": len(done) + ok, "ok": ok, "fail": fail, "current": name[:30],
                     "ts": datetime.now().isoformat(timespec="seconds")})
        with io.open(PROG, "w", encoding="utf-8") as f:
            json.dump(prog, f, ensure_ascii=False)
        # 限流退避：连续 EMPTY 增长
        if empty_run >= 3:
            await asyncio.sleep(30)
        elif empty_run >= 6:
            await asyncio.sleep(120)
        await asyncio.sleep(2)
    prog["done_ts"] = datetime.now().isoformat(timespec="seconds")
    with io.open(PROG, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False)
    log(f"S-1 DONE ok={ok} fail={fail} total_done={len(done)+ok}")

asyncio.run(main())
LOG.close()
