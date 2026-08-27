# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 12：单品 API 返回核实（10min 粒度 + 历史深度）（2026-08-27）。只读。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

URL = "https://www.steamdt.com/cs2/M4A1-S%20%7C%20Blood%20Tiger%20(Factory%20New)"

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(5)

        tests = {
            "单品主数据": "https://www.steamdt.com/api/user/skin/v1/item?hash=M4A1-S%20%7C%20Blood%20Tiger%20%28Factory%20New%29",
            "成交/磨损详情": "https://www.steamdt.com/api/user/skin/v2/sale-wear-detail",
            "走势(K线)": "https://www.steamdt.com/api/user/steam/type-trend/v2/item/details",
            "单品异动": "https://www.steamdt.com/api/index/item/change/v1/list",
        }
        for name, url in tests.items():
            try:
                j = await page.evaluate(
                    "async (u) => { const r = await fetch(u, {headers:{'Accept':'application/json'}}); const t = await r.text(); try { return {status: r.status, json: JSON.parse(t)} } catch(e) { return {status: r.status, text: t.slice(0,150)} } }", url)
                print(f"=== {name} [HTTP {j['status']}]")
                if 'json' in j:
                    s = json.dumps(j['json'], ensure_ascii=False)
                    print(s[:800])
                else:
                    print(j['text'])
                print()
            except Exception as e:
                print(f"=== {name} 失败: {str(e)[:60]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
