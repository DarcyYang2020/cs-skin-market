# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 8：/market 饰品市场页 → 商品列表 + 详情路由（2026-08-27）。只读。"""
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
        await page.goto("https://www.steamdt.com/market", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(8)
        print(f"=== /market title={await page.title()} url={page.url}")
        txt = await page.evaluate("() => document.body.innerText")
        print("文本片段:", txt[:600].replace("\n", " | "))
        # 商品链接
        links = await page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('a').forEach(a => {
                const h = a.getAttribute('href')||'';
                if (h.includes('/') && !h.startsWith('http') && out.length < 8) out.push(h);
            });
            return out;
        }""")
        print("链接:", links)
        print("\n=== 新增 API ===")
        seen = set()
        for st, u in apis:
            if u not in seen:
                seen.add(u)
                print(f"  [{st}] {u[len('https://www.steamdt.com'):]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
