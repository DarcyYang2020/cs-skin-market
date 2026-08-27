# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 5：大盘指数页路由 + 单品详情页（成交记录/10min 粒度）（2026-08-27）。只读。"""
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

        # 1) 大盘指数详情页（找 K 线历史 API）
        for path in ["/index", "/market-index", "/marketIndex", "/big-index"]:
            try:
                await page.goto(f"https://www.steamdt.com{path}", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(3)
                t = await page.title()
                txt = await page.evaluate("() => document.body.innerText")
                has_kline = "K线" in txt or "日线" in txt or "时线" in txt
                print(f"=== {path} -> title={t} K线元素={has_kline} len={len(txt)}")
                if has_kline:
                    print("   文本片段:", txt[:400].replace("\n"," | "))
                    break
            except Exception as e:
                print(f"=== {path} 失败 {str(e)[:50]}")
        print("\n=== 该页新增 API ===")
        seen = set()
        for st, u in apis:
            if u not in seen:
                seen.add(u)
                print(f"  [{st}] {u[len('https://www.steamdt.com'):]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
