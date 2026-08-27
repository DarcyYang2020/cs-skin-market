# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 3：历史深度 + 单品粒度 + 登录墙（2026-08-27）。只读。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.steamdt.com/", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(4)

        tests = {
            "大盘历史(日K,近30日)": "https://www.steamdt.com/api/index/statistics/v1/kline?type=day&limit=30",
            "大盘历史(时K)": "https://www.steamdt.com/api/index/statistics/v1/kline?type=hour&limit=48",
            "大盘历史(周K)": "https://www.steamdt.com/api/index/statistics/v1/kline?type=week&limit=52",
            "板块指数全量": "https://www.steamdt.com/api/index/item-block/v1/summary",
            "用户信息(登录墙测试)": "https://www.steamdt.com/api/user/account/v1/info",
        }
        for name, url in tests.items():
            try:
                j = await page.evaluate(
                    "async (u) => { const r = await fetch(u, {headers:{'Accept':'application/json'}}); const t = await r.text(); try { return {status: r.status, json: JSON.parse(t)} } catch(e) { return {status: r.status, text: t.slice(0,200)} } }", url)
                print(f"=== {name} [HTTP {j['status']}]")
                if 'json' in j:
                    s = json.dumps(j['json'], ensure_ascii=False)
                    print(s[:700])
                else:
                    print(j['text'])
                print()
            except Exception as e:
                print(f"=== {name} 失败: {str(e)[:80]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
