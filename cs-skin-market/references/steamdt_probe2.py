# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 2：API 返回字段核实（2026-08-27）。只读，不落库。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.steamdt.com/", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(4)

        endpoints = {
            "大盘统计": "https://www.steamdt.com/api/index/statistics/v1/summary",
            "在线人数": "https://www.steamdt.com/api/index/players/v1/statistics",
            "热门板块": "https://www.steamdt.com/api/index/skin-folder/v1/hot?limit=5",
        }
        for name, url in endpoints.items():
            try:
                j = await page.evaluate(
                    "async (u) => { const r = await fetch(u, {headers:{'Accept':'application/json'}}); return await r.json(); }", url)
                print(f"=== {name}: {url.split('/api/')[1][:50]}")
                s = json.dumps(j, ensure_ascii=False)
                print(s[:900])
                print()
            except Exception as e:
                print(f"=== {name} 失败: {str(e)[:80]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
