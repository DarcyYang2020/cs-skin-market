# -*- coding: utf-8 -*-
"""全市场快照采集（2026-08-04，样本扩容数据积累）。

数据源：csqaq.com /detail 页面触发 info/get_page_list。
通过路由改写 POST body（page_index/page_size）翻页，走页面会话绕过 IP 白名单。
快照含悠悠锚价(yyyp_sell_price) + 在售数(yyyp_sell_num)，仅当前快照，无历史。
"""
import asyncio, json, logging
from datetime import datetime, timezone, timedelta

from .collector_csqaq import _get_browser, CSQAQ_WEB, _csq_log

TZ_BJ = timezone(timedelta(hours=8))
_log = logging.getLogger(__name__)
DEFAULT_PAGE_SIZE = 200
DEFAULT_MAX_PAGES = 25  # 25 页 × 200 = 5000 品（/detail 默认按热度排序，取最热池）


async def fetch_market_snapshot(max_pages: int = DEFAULT_MAX_PAGES, page_size: int = DEFAULT_PAGE_SIZE):
    """拉取全市场价格快照，返回 list[dict]。

    每页一次页面加载（约 4-5s），翻到空页或 max_pages 停止。
    rows: {good_id, name, exterior_localized_name, rarity_localized_name,
           yyyp_sell_price, yyyp_sell_num}
    """
    pw, browser = await _get_browser()
    rows = []
    empty = 0
    for page_index in range(1, max_pages + 1):
        page = await browser.new_page()
        captured = {"body": None}
        try:
            async def rewrite(route, request):
                if "info/get_page_list" in request.url:
                    try:
                        body = {"page_index": page_index, "page_size": page_size,
                                "search": "", "filter": {}}
                        await route.continue_(post_data=json.dumps(body, ensure_ascii=False))
                    except Exception:
                        await route.continue_()
                else:
                    await route.continue_()

            async def on_response(response):
                try:
                    if "info/get_page_list" in response.url and response.ok:
                        captured["body"] = await response.text()
                except Exception:
                    pass

            await page.route("**/info/get_page_list**", rewrite)
            page.on("response", on_response)
            try:
                await page.goto(f"{CSQAQ_WEB}/detail", wait_until="domcontentloaded", timeout=20000)
            except Exception as ge:
                _csq_log.warning(f"fetch_market_snapshot page {page_index} goto failed: {ge}")
            for _ in range(40):
                if captured["body"]:
                    break
                await asyncio.sleep(0.25)
            if not captured["body"]:
                empty += 1
                continue
            data = json.loads(captured["body"]).get("data") or {}
            items = data.get("data") or []
            if not items:
                break  # 翻到空页，结束
            for it in items:
                try:
                    rows.append({
                        "good_id": int(it.get("id") or 0),
                        "name": it.get("name"),
                        "exterior_localized_name": it.get("exterior_localized_name"),
                        "rarity_localized_name": it.get("rarity_localized_name"),
                        "yyyp_sell_price": it.get("yyyp_sell_price"),
                        "yyyp_sell_num": it.get("yyyp_sell_num"),
                    })
                except (TypeError, ValueError):
                    continue
            _csq_log.info(f"fetch_market_snapshot page {page_index}: {len(items)} items (累计 {len(rows)})")
        finally:
            await page.close()
    return rows