# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 15：在单品页上下文内复现 POST（2026-08-27）。只读。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

URL = "https://www.steamdt.com/cs2/M4A1-S%20%7C%20Blood%20Tiger%20(Factory%20New)"

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(6)
        tests = [
            ("单品主数据", {"appId":730,"marketHashName":"M4A1-S | Blood Tiger (Factory New)"}),
            ("走势K线 日级", {"platform":"ALL","typeDay":1,"dateType":4,"specialStyle":"","timestamp":1787835985832,"itemId":"23474"}),
            ("走势K线 时级", {"platform":"ALL","typeDay":1,"dateType":3,"specialStyle":"","timestamp":1787835985832,"itemId":"23474"}),
        ]
        for name, body in tests:
            try:
                j = await page.evaluate(
                    "async (a) => { const r = await fetch(a[0], {method:'POST', headers:{'Content-Type':'application/json','Accept':'application/json'}, body: JSON.stringify(a[1])}); const t = await r.text(); try { return {status: r.status, json: JSON.parse(t)} } catch(e) { return {status: r.status, text: t.slice(0,150)} } }",
                    ["https://www.steamdt.com/api/user/steam/type-trend/v2/item/details" if "K线" in name else "https://www.steamdt.com/api/user/skin/v1/item", body])
                print(f"=== {name} [HTTP {j['status']}]")
                if 'json' in j:
                    s = json.dumps(j['json'], ensure_ascii=False)
                    print(s[:1100])
                else:
                    print(j['text'])
                print()
            except Exception as e:
                print(f"=== {name} 失败: {str(e)[:60]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
