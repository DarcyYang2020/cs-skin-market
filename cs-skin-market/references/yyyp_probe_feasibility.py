# -*- coding: utf-8 -*-
"""S1 悠悠有品采集可行性预研探针（2026-08-27，研发窗口，roadmap v82 Wave3 S1）。

探针目标：确认 https://www.youpin898.com 的 在售列表 / 求购列表 / 成交记录 是否可采。
方法：Playwright headless 打开首页 + 捕获 XHR/JSON 响应，识别内部 API 端点；
     尝试进入商品详情页查成交记录。仅探测不落库、不动生产。
输出：打印发现（端点/字段/可达性/反爬信号）。
"""
import asyncio
import io
import json
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

BASE = "https://www.youpin898.com"
API_URLS = {}


async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        async def on_response(resp):
            url = resp.url
            if not any(k in url.lower() for k in
                       ("api", "market", "goods", "buy", "sell", "order",
                        "trade", "list", "search", "detail", "history")):
                return
            if url in API_URLS:
                return
            info = {"status": resp.status, "ctype": (resp.headers.get("content-type") or "")[:40]}
            try:
                if "json" in (resp.headers.get("content-type") or "") or re.search(r"\.(json|api)", url):
                    body = await resp.text()
                    info["sample"] = body[:300]
                    try:
                        j = json.loads(body)
                        info["json_keys"] = list(j.keys())[:8]
                        d = j.get("data")
                        if isinstance(d, dict):
                            info["data_keys"] = list(d.keys())[:8]
                    except Exception:
                        pass
            except Exception as e:
                info["error"] = str(e)[:80]
            API_URLS[url] = info

        page.on("response", on_response)
        try:
            await page.goto(BASE, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            print(f"[goto 首页失败] {e}")
        await asyncio.sleep(6)
        try:
            title = await page.title()
            print(f"=== 首页 title: {title}")
            text = await page.inner_text("body")
            seg = re.findall(r"[^\n]{0,24}(在售|求购|成交)[^\n]{0,24}", text)
            print(f"=== 首页可见文本含(在售/求购/成交)片段数: {len(seg)}，样例: {seg[:6]}")
            # 找商品链接（详情页入口）
            links = await page.eval_on_selector_all(
                "a", "els => els.map(e => ({href:e.href, t:(e.innerText||'').trim().slice(0,20)})).filter(x=>x.href&&x.href.length>10).slice(0,8)")
            print("=== 首页前 8 个链接:", json.dumps(links, ensure_ascii=False)[:400])
        except Exception as e:
            print(f"[DOM 解析失败] {e}")
        print(f"=== 捕获 JSON/XHR 响应 {len(API_URLS)} 个 ===")
        for url, info in list(API_URLS.items())[:25]:
            print(f"  [{info['status']}] {url[:120]}")
            if info.get("json_keys"):
                print(f"      json_keys={info['json_keys']} data_keys={info.get('data_keys')}")
            if info.get("sample"):
                print(f"      样本: {info['sample'][:180]}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(probe())
