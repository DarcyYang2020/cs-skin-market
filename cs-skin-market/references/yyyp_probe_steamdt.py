# -*- coding: utf-8 -*-
"""W7-2 steamdt 成交额组件 · 预研探针（2026-08-27，运维窗口）。

目标：①定位悠悠有品 steamdt/行情数据页面与 API；②核实字段（成交额/成交量/在线人数/指数）；
③历史深度；④是否需登录。只读探针，不落库、不动生产。
"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        nav, apis = [], []

        async def on_nav(url):
            if "youpin898.com" in url and "=" not in url.split("?")[0].rstrip("/").rsplit("/",1)[-1]:
                nav.append(url)
        async def on_resp(resp):
            u = resp.url
            if "api" in u or "steam" in u.lower() or "market" in u.lower():
                if resp.status == 200:
                    apis.append((resp.status, u))

        page.on("framenavigated", lambda f: on_nav(f.url) if f == page.main_frame else None)
        page.on("response", on_resp)

        # 1) 首页 + 常见行情路由探测
        for path in ["/", "/market", "/market/", "/data", "/steamdt", "/steam", "/marketData"]:
            try:
                await page.goto(f"https://www.youpin898.com{path}", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2.5)
                print(f"=== {path} -> {page.url} | title={await page.title()}")
            except Exception as e:
                print(f"=== {path} -> 失败 {str(e)[:60]}")

        # 2) 首页网络请求盘点（找行情/成交相关 API）
        print("\n=== 首页捕获 API（含 steam/market/api）===")
        seen = set()
        for st, u in apis:
            key = u.split("?")[0]
            if key not in seen:
                seen.add(key)
                print(f"  [{st}] {u[:140]}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
