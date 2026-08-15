# -*- coding: utf-8 -*-
"""大户集中度快照采集（2026-08-04，P1 数据积累）。

数据源：csqaq.com /monitor 页面触发 monitor/rank。
通过路由改写 POST body（good_id）指定目标品，走页面会话绕过 IP 白名单。
返回持有量 Top N 大户（按 num 降序）：[{steam_name, steam_id, num}]。
仅当前快照，无历史；每日采集一次，存 monitor_rank_snapshot 表。
"""
import asyncio, json, logging

from .collector_csqaq import _get_browser, CSQAQ_WEB, _csq_log

_log = logging.getLogger(__name__)
DEFAULT_TOP_N = 50  # 每品保留 Top 50 大户（集中度分析 Top10/20/50 足够，控数据量）


async def fetch_monitor_rank(good_id: int, top_n: int = DEFAULT_TOP_N):
    """拉取单品库存监控持有量排行，返回 list[dict]（按持有量降序裁剪 top_n）。

    页面加载偶发失败（空结果），重试 2 次（各开新页），成功即返回。
    rows: {steam_name, steam_id, num}
    """
    pw, browser = await _get_browser()
    for attempt in range(3):
        rows = await _attempt(browser, good_id, top_n)
        if rows:
            return rows
        if attempt < 2:
            await asyncio.sleep(0.5)
    return []


async def _attempt(browser, good_id: int, top_n: int):
    page = await browser.new_page()
    captured = {"body": None}
    try:
        async def rewrite(route, request):
            if "monitor/rank" in request.url:
                try:
                    await route.continue_(post_data=json.dumps({"good_id": str(good_id)}))
                except Exception:
                    await route.continue_()
            else:
                await route.continue_()

        async def on_response(response):
            try:
                if "monitor/rank" in response.url and response.ok:
                    captured["body"] = await response.text()
            except Exception:
                _log.warning("cs-skin-market/pipeline/collector_monitor.py unexpected error near line 50", exc_info=True)

        await page.route("**/monitor/rank**", rewrite)
        page.on("response", on_response)
        try:
            await page.goto(f"{CSQAQ_WEB}/monitor", wait_until="domcontentloaded", timeout=20000)
        except Exception as ge:
            _csq_log.warning(f"fetch_monitor_rank goto /monitor failed: {ge}")
        for _ in range(40):
            if captured["body"]:
                break
            await asyncio.sleep(0.25)
        if not captured["body"]:
            return []
        data = json.loads(captured["body"])
        rows = data.get("data") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        out = []
        for r in rows:
            try:
                num = int(r.get("num") or 0)
                if num <= 0:
                    continue
                out.append({"steam_name": r.get("steam_name"), "steam_id": r.get("steam_id"), "num": num})
            except (TypeError, ValueError):
                continue
            if len(out) >= top_n:
                break
        return out
    finally:
        await page.close()
