# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 13：单品页真实 POST 请求捕获（含 body）（2026-08-27）。只读。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

URL = "https://www.steamdt.com/cs2/M4A1-S%20%7C%20Blood%20Tiger%20(Factory%20New)"

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        posts = []
        async def on_req(req):
            if "/api/" in req.url and req.method == "POST":
                try:
                    body = req.post_data or ""
                    posts.append((req.url.split("?")[0], body[:400]))
                except Exception:
                    pass
        page.on("request", on_req)
        await page.goto(URL, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(8)
        # 触发更多加载：滚动 + 点 tab
        for _ in range(2):
            await page.mouse.wheel(0, 1200); await asyncio.sleep(1.5)
        await asyncio.sleep(3)
        print(f"=== 捕获 {len(posts)} 个 POST 请求 ===")
        seen = set()
        for u, b in posts:
            key = (u, b[:60])
            if key in seen: continue
            seen.add(key)
            print(f"  POST {u}")
            print(f"      body: {b[:250]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
