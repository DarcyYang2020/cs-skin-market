# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 17：完整字段 dump 存证（2026-08-27）。只读。"""
import asyncio, io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.steamdt.com/", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(4)
        eps = {
            "summary": "https://www.steamdt.com/api/index/statistics/v1/summary",
            "players": "https://www.steamdt.com/api/index/players/v1/statistics",
            "blocks": "https://www.steamdt.com/api/index/item-block/v1/summary",
        }
        out = {}
        for k, u in eps.items():
            j = await page.evaluate(
                "async (u) => { const r = await fetch(u, {headers:{'Accept':'application/json'}}); return await r.json(); }", u)
            out[k] = j
        with open("data/_exp_w7_2_steamdt_probe.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        # 打印字段结构摘要
        for k, j in out.items():
            d = j.get("data", {})
            if isinstance(d, dict):
                print(f"=== {k}: data 字段: {list(d.keys())}")
                if k == "summary":
                    print("  todayStatistics:", json.dumps(d.get("todayStatistics", {}), ensure_ascii=False)[:400])
                    print("  historyMarketIndexList 点数:", len(d.get("historyMarketIndexList", [])))
                if k == "players":
                    print("  history 点数:", len(d.get("history", [])))
            elif isinstance(d, list):
                print(f"=== {k}: data 是 list, len={len(d)}")
                if d: print("  首项:", json.dumps(d[0], ensure_ascii=False)[:300])
        await browser.close()
        print("\n存证: data/_exp_w7_2_steamdt_probe.json")

if __name__ == "__main__":
    asyncio.run(probe())
