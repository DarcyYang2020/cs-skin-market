# -*- coding: utf-8 -*-
"""S1 悠悠有品采集可行性预研 · 第三轮探针（2026-08-27）。

详情页交互验证：滚动到底 + 点击「求购」入口 + 等待懒加载，确认 求购/成交 数据
是「懒加载可触发」还是「登录墙」。仅探测不落库。
"""
import asyncio
import io
import json
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

GID = 100354
CAP = {}


async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        async def on_response(resp):
            url = resp.url
            if re.search(r"(api|goods|buy|sell|order|trade|detail|history|price|commodity|listing)", url, re.I):
                if url not in CAP:
                    CAP[url] = {"status": resp.status,
                                "ctype": (resp.headers.get("content-type") or "")[:30]}
                    try:
                        if "json" in (resp.headers.get("content-type") or ""):
                            CAP[url]["sample"] = (await resp.text())[:220]
                    except Exception:
                        pass

        page.on("response", on_response)
        try:
            await page.goto(f"https://www.youpin898.com/goods/{GID}", wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            print(f"[goto] {e}")
        await asyncio.sleep(5)
        # 滚动到底触发懒加载
        for _ in range(6):
            try:
                await page.mouse.wheel(0, 3000)
            except Exception:
                pass
            await asyncio.sleep(1.2)
        # 点「求购」tab 若存在
        for txt in ("求购", "在售挂单", "成交记录", "购买"):
            try:
                el = page.locator(f"text={txt}").first
                if await el.count() > 0:
                    await el.click(timeout=3000)
                    print(f"[点击 tab] {txt}")
                    await asyncio.sleep(3)
            except Exception:
                pass
        try:
            text = await page.inner_text("body")
            seg = re.findall(r"[^\n]{0,30}(求购|成交|在售|价格|¥)[^\n]{0,30}", text)
            print(f"=== 详情页交互后可见片段({len(seg)}): {seg[:10]}")
            print("=== body 文本前 1200 字 ===")
            print(text[:1200].replace("\n", " | "))
        except Exception as e:
            print(f"[DOM] {e}")
        print(f"=== 交互后捕获响应 {len(CAP)} 个 ===")
        for url, info in list(CAP.items())[:20]:
            print(f"  [{info['status']}] {url[:130]}")
            if info.get("sample"):
                print(f"      样本: {info['sample'][:150]}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(probe())
