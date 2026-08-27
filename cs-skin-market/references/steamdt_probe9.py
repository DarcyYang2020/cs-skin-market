# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 9：API 文档链接 + 商品详情路由挖掘（2026-08-27）。只读。"""
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
            if "/api/" in u or "doc" in u.lower() or "swagger" in u.lower():
                apis.append((resp.status, u.split("?")[0]))
        page.on("response", on_resp)
        await page.goto("https://www.steamdt.com/", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(6)

        # 找页面所有链接（含 api_doc / apikey 图标 href）
        links = await page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('a').forEach(a => {
                const h = a.getAttribute('href')||'';
                const t = (a.innerText||'').trim();
                if (out.length < 40) out.push(h + ' | ' + t.slice(0,30));
            });
            return out;
        }""")
        print("=== 页面全部链接 ===")
        for l in links: print(" ", l[:100])
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
