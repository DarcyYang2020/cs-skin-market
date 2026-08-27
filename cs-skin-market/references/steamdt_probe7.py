# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 7：成交榜 API 取商品 → 详情页成交记录/10min（2026-08-27）。只读。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        apis = []
        async def on_resp(resp):
            u = resp.url
            if "/api/" in u:
                apis.append((resp.status, u.split("?")[0]))
        page.on("response", on_resp)
        await page.goto("https://www.steamdt.com/", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(5)

        # 成交榜
        j = await page.evaluate("""async () => {
            const r = await fetch('https://www.steamdt.com/api/user/ranking/v1/page?timestamp=' + Date.now() + '&type=DEAL&pageNum=1&pageSize=3', {headers:{'Accept':'application/json'}});
            return await r.json();
        }""")
        s = json.dumps(j, ensure_ascii=False)
        print("=== 成交榜返回（前 800）===")
        print(s[:800])
        # 找 item id / hash
        items = []
        def walk(o):
            if isinstance(o, dict):
                if any(k in o for k in ("itemId","commodityId","skinId","goodId","id")):
                    items.append(o)
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(j)
        if items:
            it = items[0]
            print("\n=== 首个商品字段 ===")
            for k, v in it.items():
                print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:80]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
