# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 1（2026-08-27，运维窗口）：
steamdt.com 页面结构 + API 盘点 + 字段核实。只读，不落库。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        apis = []
        async def on_resp(resp):
            if resp.status == 200 and "api" in resp.url.lower():
                apis.append(resp.url)
        page.on("response", on_resp)

        await page.goto("http://steamdt.com/", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(8)
        print(f"=== steamdt.com title={await page.title()} url={page.url}")
        txt = await page.evaluate("() => document.body.innerText")
        print("=== 页面文本（前 1500 字）===")
        print(txt[:1500].replace("\n", " | "))

        print("\n=== 捕获 API 清单 ===")
        seen = set()
        for u in apis:
            key = u.split("?")[0]
            if key not in seen:
                seen.add(key)
                print(f"  {u[:160]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
