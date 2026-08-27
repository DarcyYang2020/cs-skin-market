# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 4：完整 API 盘点（页面所有 /api/ 请求）+ API 文档（2026-08-27）。只读。"""
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
        await asyncio.sleep(10)
        # 滚动触发懒加载
        for _ in range(3):
            await page.mouse.wheel(0, 1500); await asyncio.sleep(1.5)
        await asyncio.sleep(3)

        print("=== 页面全部 /api/ 请求（去重）===")
        seen = set()
        for st, u in apis:
            if u not in seen:
                seen.add(u)
                print(f"  [{st}] {u[len('https://www.steamdt.com'):]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
