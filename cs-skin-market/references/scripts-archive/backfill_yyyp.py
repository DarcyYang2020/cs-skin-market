# -*- coding: utf-8 -*-
"""一次性回填 items.yyyp_id：对每个 good_id 打开 csqaq 商品页，拦截 info/good 响应拿悠悠 template id。"""
import sys, io, asyncio, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import collector_csqaq, db

async def backfill(start=0, end=10**9):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, good_id, name FROM items WHERE good_id > 0 AND (yyyp_id IS NULL OR yyyp_id = '') ORDER BY id"
    ).fetchall()
    conn.close()
    rows = rows[start:end]
    print(f"待回填: {len(rows)} (slice {start}~{end})", flush=True)
    pw, browser = await collector_csqaq._get_browser()
    ok = 0
    for i, r in enumerate(rows, 1):
        gid = r["good_id"]
        yyyp = ""
        page = await browser.new_page()
        try:
            async def on_response(response):
                nonlocal yyyp
                if "info/good" in response.url and response.ok:
                    try:
                        body = await response.text()
                        d = json.loads(body)
                        yyyp = str((d.get("data") or {}).get("goods_info", {}).get("yyyp_id", "") or "")
                    except Exception:
                        pass
            page.on("response", on_response)
            try:
                await page.goto(f"https://csqaq.com/goods/{gid}", wait_until="domcontentloaded", timeout=25000)
            except Exception:
                pass
            for _ in range(20):
                if yyyp:
                    break
                await asyncio.sleep(0.5)
        except Exception as e:
            print(f"  ERR item={r['id']} gid={gid}: {e}", flush=True)
        finally:
            await page.close()
        if yyyp:
            conn = db.get_conn()
            conn.execute("UPDATE items SET yyyp_id=?, updated_at=datetime('now','localtime') WHERE id=?", (yyyp, r["id"]))
            conn.commit()
            conn.close()
            ok += 1
        print(f"[{i}/{len(rows)}] item={r['id']} gid={gid} yyyp={yyyp or 'N/A'} | {r['name'][:34]}", flush=True)
    print(f"完成: {ok}/{len(rows)}", flush=True)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=10**9)
    a = ap.parse_args()
    asyncio.run(backfill(a.start, a.end))