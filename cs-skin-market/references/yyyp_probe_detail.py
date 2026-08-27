# -*- coding: utf-8 -*-
"""S1 悠悠有品采集可行性预研 · 第二轮探针（2026-08-27，研发窗口）。

目标：在售列表已确认可采（/api/homepage/pc/commodity/page）。
本轮：取商品 id → 进详情页，抓 求购列表 / 成交记录 的 API 与登录/反爬信号。
"""
import asyncio
import io
import json
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

MARKET_API = "https://pc-api.youpin898.com/api/homepage/pc/commodity/page"
DETAILS = {}  # url -> info


async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 1) 直连在售列表 API 拿第一个商品 id
        first_id = None
        async with page.expect_response(lambda r: "commodity/page" in r.url) as ri:
            await page.goto("https://www.youpin898.com/", wait_until="domcontentloaded", timeout=25000)
        try:
            resp = await ri.value
            j = json.loads(await resp.text())
            contents = j.get("Data", {}).get("contents") or []
            if contents:
                first_id = contents[0].get("id")
                print(f"=== 在售列表首个商品 id = {first_id}（共 {j.get('TotalCount')} 件）")
                print(f"    首品字段样例: {json.dumps(contents[0], ensure_ascii=False)[:300]}")
        except Exception as e:
            print(f"[列表解析失败] {e}")

        # 2) 进详情页，捕获所有 JSON/XHR
        async def on_response(resp):
            url = resp.url
            if not re.search(r"(api|goods|buy|sell|order|trade|detail|history|price|commodity)", url, re.I):
                return
            if url in DETAILS:
                return
            info = {"status": resp.status}
            try:
                ct = resp.headers.get("content-type") or ""
                if "json" in ct or re.search(r"\.(json|api)", url):
                    body = await resp.text()
                    info["sample"] = body[:260]
                    try:
                        j = json.loads(body)
                        info["json_keys"] = list(j.keys())[:8]
                        d = j.get("data") or j.get("Data")
                        if isinstance(d, dict):
                            info["data_keys"] = list(d.keys())[:12]
                    except Exception:
                        pass
            except Exception as e:
                info["error"] = str(e)[:60]
            DETAILS[url] = info

        page.on("response", on_response)
        if first_id:
            for cand in (f"https://www.youpin898.com/goods/{first_id}",
                         f"https://www.youpin898.com/market/goods/{first_id}",
                         f"https://www.youpin898.com/commodity/{first_id}"):
                try:
                    await page.goto(cand, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(4)
                    cur = page.url
                    print(f"=== 尝试详情页 {cand} → 最终 {cur[:90]}")
                    if cur.startswith("https://www.youpin898.com") and "/goods/" in cur:
                        break
                except Exception as e:
                    print(f"[详情页失败 {cand}] {e}")
            await asyncio.sleep(3)
            try:
                text = await page.inner_text("body")
                seg = re.findall(r"[^\n]{0,26}(求购|成交|在售)[^\n]{0,26}", text)
                print(f"=== 详情页可见(求购/成交/在售)片段: {seg[:8]}")
            except Exception as e:
                print(f"[详情 DOM 失败] {e}")
        print(f"=== 详情页捕获 JSON/XHR {len(DETAILS)} 个 ===")
        for url, info in list(DETAILS.items())[:22]:
            print(f"  [{info['status']}] {url[:130]}")
            if info.get("json_keys"):
                print(f"      keys={info['json_keys']} data={info.get('data_keys')}")
            if info.get("sample"):
                print(f"      样本: {info['sample'][:160]}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(probe())
