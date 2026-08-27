# -*- coding: utf-8 -*-
"""W7-2 steamdt 预研探针 2：深入 /steamdt 页面内容与 API（2026-08-27）。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        apis = []
        async def on_resp(resp):
            if resp.status == 200:
                apis.append(resp.url)
        page.on("response", on_resp)

        # steamdt 页面 + 等待渲染
        await page.goto("https://www.youpin898.com/steamdt", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(8)
        print(f"=== /steamdt title={await page.title()} url={page.url}")
        # dump 页面文本（前 1500 字符）
        txt = await page.evaluate("() => document.body.innerText")
        print("=== 页面文本（前 1200 字）===")
        print(txt[:1200].replace("\n", " | "))

        # 全部捕获 API
        print("\n=== 捕获 API 清单 ===")
        seen = set()
        for u in apis:
            key = u.split("?")[0]
            if key not in seen:
                seen.add(key)
                print(f"  {u[:150]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
