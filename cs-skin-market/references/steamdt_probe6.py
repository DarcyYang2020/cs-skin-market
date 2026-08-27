# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 6：单品详情页成交记录/10min 粒度（2026-08-27）。只读。"""
import asyncio, io, json, sys, re
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

        # 从首页找第一个商品链接（成交榜/在售价榜）
        await page.goto("https://www.steamdt.com/", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(6)
        links = await page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('a').forEach(a => {
                const h = a.getAttribute('href')||'';
                if (/\\/item\\/|\\/goods\\/|\\/skin\\/|\\/market\\//.test(h) && out.length < 5) out.push(h);
            });
            return out;
        }""")
        print("商品链接候选:", links)
        target = links[0] if links else None
        if target:
            await page.goto("https://www.steamdt.com" + (target if target.startswith("/") else "/" + target),
                            wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(6)
            print(f"\n=== 单品页 title={await page.title()} url={page.url}")
            txt = await page.evaluate("() => document.body.innerText")
            print("文本片段:", txt[:500].replace("\n", " | "))
        print("\n=== 全部 API ===")
        seen = set()
        for st, u in apis:
            if u not in seen:
                seen.add(u)
                print(f"  [{st}] {u[len('https://www.steamdt.com'):]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
