# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 16：单品页原生交互（点K线tab）捕获响应（2026-08-27）。只读。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

URL = "https://www.steamdt.com/cs2/M4A1-S%20%7C%20Blood%20Tiger%20(Factory%20New)"

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        resp_bodies = {}
        async def on_resp(resp):
            u = resp.url
            if "/api/" in u and resp.status == 200:
                try:
                    body = await resp.text()
                    if '"success": true' in body:
                        resp_bodies[u.split("?")[0]] = body[:600]
                except Exception:
                    pass
        page.on("response", on_resp)
        await page.goto(URL, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(10)
        # 找 tab 按钮（行情/收藏/今日/本周 等）点击
        try:
            btns = page.locator("button, [class*='tab'], [class*='Tab']")
            n = await btns.count()
            print(f"找到 {n} 个 tab 元素，尝试点击前几个")
            for i in range(min(n, 6)):
                try:
                    txt = (await btns.nth(i).inner_text())[:20].strip()
                    await btns.nth(i).click(timeout=3000)
                    await asyncio.sleep(2)
                    print(f"  点击 #{i} [{txt}]")
                except Exception as e:
                    print(f"  点击 #{i} 失败 {str(e)[:40]}")
        except Exception as e:
            print("tab 定位失败:", str(e)[:60])
        await asyncio.sleep(3)
        print(f"\n=== 成功响应 {len(resp_bodies)} 个 ===")
        for u, b in resp_bodies.items():
            print(f"  {u[len('https://www.steamdt.com'):]}")
            print(f"    {b[:280]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
