# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 11：单品详情页（/cs2/路由）成交记录 + summary 历史深度（2026-08-27）。只读。"""
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

        # 单品详情页（从首页链接抓到的真实路由）
        await page.goto("https://www.steamdt.com/cs2/M4A1-S%20%7C%20Blood%20Tiger%20(Factory%20New)",
                        wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(8)
        print(f"=== 单品页 title={await page.title()} url={page.url}")
        txt = await page.evaluate("() => document.body.innerText")
        print("文本片段:", txt[:700].replace("\n", " | "))
        print("\n=== 单品页 API ===")
        seen = set()
        for st, u in apis:
            if u not in seen:
                seen.add(u)
                print(f"  [{st}] {u[len('https://www.steamdt.com'):]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
