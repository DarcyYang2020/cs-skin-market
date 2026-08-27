# -*- coding: utf-8 -*-
"""S1 悠悠有品采集可行性预研 · 第四轮（2026-08-27）。

挖正确详情路由：dump 在售列表首品全字段 + 首页点商品卡片观察跳转 URL。
"""
import asyncio
import io
import json
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright


async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        nav = []

        async def on_nav(url):
            if url.startswith("https://www.youpin898.com"):
                nav.append(url)

        page.on("framenavigated", lambda f: on_nav(f.url) if f == page.main_frame else None)
        await page.goto("https://www.youpin898.com/", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(6)

        # dump 在售列表首品全字段
        try:
            j = await page.evaluate(
                "async () => { const r = await fetch('https://pc-api.youpin898.com/api/homepage/pc/commodity/page?pageNum=1&pageSize=20', {headers:{'Accept':'application/json'}}); const j = await r.json(); return j.Data.contents[0]; }")
            print("=== 在售列表首品全字段 ===")
            for k, v in j.items():
                print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:120]}")
        except Exception as e:
            print(f"[在售字段 dump 失败] {e}")

        # 点首页第一个商品卡片，看跳转
        try:
            cards = page.locator("a").filter(has_text="在售")
            print(f"=== 找到 {await cards.count()} 个含'在售'的链接元素 ===")
            if await cards.count() > 0:
                href = await cards.first.get_attribute("href")
                print(f"  首个卡片 href: {href}")
                nav.clear()
                await cards.first.click(timeout=5000)
                await asyncio.sleep(4)
                print(f"  点击后 main frame URL: {page.url}")
                print(f"  导航历史: {nav[:5]}")
        except Exception as e:
            print(f"[点卡片失败] {e}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(probe())
