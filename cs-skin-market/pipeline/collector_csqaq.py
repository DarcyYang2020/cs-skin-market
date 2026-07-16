# -*- coding: utf-8 -*-
"""csqaq.com Playwright data collector.
Navigates directly to goods page and intercepts chart API.
"""

import asyncio, json, re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

TZ_BJ = timezone(timedelta(hours=8))
from .logutil import get_logger
_csq_log = get_logger()
CSQAQ_WEB = "https://csqaq.com"
CSQAQ_WEB = "https://csqaq.com"

# === Browser singleton (reuse across calls) ===
_browser_pw = None
_browser_inst = None
_browser_last_used = 0

async def _get_browser():
    global _browser_pw, _browser_inst, _browser_last_used
    import time as _time
    now = _time.time()
    # Recycle browser if older than 5 minutes
    if _browser_pw and _browser_inst and (now - _browser_last_used) < 300:
        _browser_last_used = now
        return _browser_pw, _browser_inst
    # Close old if exists
    if _browser_inst:
        try:
            await _browser_inst.close()
        except Exception:
            pass  # browser may already be closed
    if _browser_pw:
        try:
            await _browser_pw.stop()
        except Exception:
            pass  # playwright may already be stopped
    from playwright.async_api import async_playwright
    _browser_pw = await async_playwright().start()
    _browser_inst = await _browser_pw.chromium.launch(headless=True, proxy=_PROXY)
    _browser_last_used = now
    return _browser_pw, _browser_inst
_PROXY = None

try:
    from .config import PROXY as _P
    _PROXY = {"server": _P} if _P else None
except ImportError:
    pass  # config.py not available or missing PROXY


class KLinePoint:
    def __init__(self, date="", open=0.0, high=0.0, low=0.0, close=0.0, volume=0):
        self.date, self.open, self.high, self.low, self.close, self.volume = date, open, high, low, close, volume


class ItemData:
    def __init__(self):
        self.name = self.steam_name = self.weapon = self.skin = self.wear = ""
        self.price_rmb = self.volume_day = self.volume_total = 0
        self.trend = ""
        self.order_book = None
        self.kline_90d = []
        self._daily_bars = []
        self._kline_raw = []
        self.good_id = 0
        self.sector = ""
        self.rarity_name = self.exterior_name = ""
        self.sell_price_rate_1 = self.sell_price_rate_7 = self.sell_price_rate_15 = 0.0
        self.sell_price_rate_30 = self.sell_price_rate_90 = self.sell_price_rate_180 = 0.0
        self.type_name = ""
        self.quality_name = ""
        self.group_hash_name = ""
        self.case_name = ""
        self.case_discontinued = False
        self.case_created = ""
        self.rank_num = 0
        self.rank_change = 0
        self.statistic_variants = []

class OrderBook:
    def __init__(self, lowest_sell=0.0, highest_buy=0.0, sell_count=0, buy_count=0):
        self.lowest_sell, self.highest_buy = lowest_sell, highest_buy
        self.sell_count, self.buy_count = sell_count, buy_count
        self.spread_rmb = self.spread_pct = self.bid_depth = 0.0


def _chart_to_daily_ohlc(chart_data: dict) -> list:
    """Convert chart {timestamp, main_data, num_data} to daily KLinePoint list."""
    ts = chart_data.get("timestamp", [])
    prices = chart_data.get("main_data", [])
    sc = chart_data.get("num_data", [])
    if not ts or not prices:
        return []
    daily = defaultdict(list)
    for i in range(min(len(ts), len(prices))):
        ts_s = ts[i] / 1000.0
        d = datetime.fromtimestamp(ts_s, tz=TZ_BJ).strftime("%Y-%m-%d")
        p = float(prices[i]) if prices[i] is not None else 0.0
        n = int(sc[i]) if i < len(sc) and sc[i] is not None else 0
        if p > 0:
            daily[d].append({"price": p, "count": n})
    result = []
    for d in sorted(daily.keys()):
        pts = daily[d]
        pl = [p["price"] for p in pts]
        vl = [p["count"] for p in pts]
        result.append(KLinePoint(date=d, open=pl[0], high=max(pl), low=min(pl), close=pl[-1], volume=max(vl)))
    return result


def _chart_to_raw(chart_data: dict) -> list:
    ts = chart_data.get("timestamp", [])
    prices = chart_data.get("main_data", [])
    sc = chart_data.get("num_data", [])
    raw = []
    for i in range(len(ts)):
        raw.append({
            "timestamp": ts[i],
            "price": float(prices[i]) if i < len(prices) and prices[i] is not None else 0.0,
            "in_sale": int(sc[i]) if i < len(sc) and sc[i] is not None else 0,
            "volume": 0, "tx_amount": 0.0, "tx_count": 0, "survive_num": 0,
        })
    return raw


async def _browser():
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, proxy=_PROXY)
    return pw, b


async def search_good_id(item_name: str) -> tuple[int, str]:
    """Async: Search csqaq.com for an item, return (good_id, page_title)."""
    pw, browser = await _get_browser()
    page = await browser.new_page()
    
    good_id = 0
    title = ""
    
    try:
        await page.goto(f"{CSQAQ_WEB}/home", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)
        await page.wait_for_selector(".ant-select-selector", timeout=8000)
        
        # Click and wait for Ant Design select to initialize
        await page.click(".ant-select-selector")
        await page.wait_for_timeout(500)
        
        # Focus the input and type
        await page.click("input")
        await page.wait_for_timeout(200)
        await page.type("input", item_name, delay=30)
        await page.wait_for_timeout(1500)
        await page.wait_for_selector(".ant-select-item-option", timeout=5000)
        
        opt = page.locator(".ant-select-item-option")
        cnt = await opt.count()
        _csq_log.info(f"Search options: {cnt}")
        # First pass: find non-StatTrak, non-Souvenir option
        clicked = False
        for i in range(cnt):
            if await opt.nth(i).is_visible():
                txt = await opt.nth(i).text_content()
                txt_clean = txt.strip() if txt else ""
                # Skip StatTrak and Souvenir variants
                if "StatTrak" in txt_clean or "StatTrak\u2122" in txt_clean or "\u2122" in txt_clean or "\u7eaa\u5ff5\u54c1" in txt_clean:
                    _csq_log.info(f"Skipping StatTrak/Souvenir: {txt_clean}")
                    continue
                _csq_log.info(f"Clicking: {txt_clean}")
                await opt.nth(i).click(force=True, timeout=5000)
                clicked = True
                break
        # Fallback: if all results are StatTrak, use the first one
        if not clicked:
            for i in range(cnt):
                if await opt.nth(i).is_visible():
                    txt = await opt.nth(i).text_content()
                    _csq_log.info(f"Fallback clicking: {txt.strip() if txt else ''}")
                    await opt.nth(i).click(force=True, timeout=5000)
                    break
        
        await page.wait_for_timeout(2000)
        
        url = page.url
        m = re.search(r'/goods/(\d+)', url)
        if m:
            good_id = int(m.group(1))
        title = await page.evaluate("() => document.title.split('-')[0].trim()")
        _csq_log.info(f"Navigated: {url}, good_id={good_id}, title={title}")

        # Post-navigation StatTrak check: if we landed on a StatTrak variant,
        # try clicking the next non-StatTrak option
        if "StatTrak" in title or "StatTrak\u2122" in title:
            _csq_log.info("Landed on StatTrak variant, retrying...")
            good_id = 0
            # Go back and try next option
            clicked_alt = False
            for j in range(cnt):
                if j == i:
                    continue  # skip the one we already tried
                alt_txt = await opt.nth(j).text_content() if await opt.nth(j).is_visible() else ""
                alt_clean = alt_txt.strip() if alt_txt else ""
                if "StatTrak" in alt_clean or "StatTrak\u2122" in alt_clean or "\u2122" in alt_clean or "\u7eaa\u5ff5\u54c1" in alt_clean:
                    continue
                if not alt_clean:
                    continue
                _csq_log.info(f"Retry clicking: {alt_clean}")
                await page.goto(f"{CSQAQ_WEB}/home", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1500)
                await page.click(".ant-select-selector")
                await page.wait_for_timeout(300)
                await page.click("input")
                await page.wait_for_timeout(200)
                await page.type("input", item_name, delay=30)
                await page.wait_for_timeout(2000)
                opt2 = page.locator(".ant-select-item-option")
                if await opt2.nth(j).is_visible():
                    await opt2.nth(j).click(force=True, timeout=5000)
                    await page.wait_for_timeout(2000)
                    url2 = page.url
                    m2 = re.search(r'/goods/(\d+)', url2)
                    if m2:
                        good_id = int(m2.group(1))
                    title = await page.evaluate("() => document.title.split('-')[0].trim()")
                    _csq_log.info(f"Retry result: url={url2}, good_id={good_id}, title={title}")
                clicked_alt = True
                break
            if not clicked_alt:
                _csq_log.warning("No non-StatTrak alternative found, using original StatTrak result")
                # Recover the original StatTrak good_id from the first navigation
                if good_id == 0 and m:
                    good_id = int(m.group(1))
    finally:
        await page.close()
        # Browser kept alive for reuse
    
    return good_id, title


async def fetch_item_detail(good_id: int) -> Optional[ItemData]:
    """Async: Fetch item detail + 90-day K-line from csqaq.com/goods/{good_id}.
    Uses Playwright with route interception for period=90 chart data.
    Also captures good_detail response for price/volume info.
    """
    item = ItemData()
    item.good_id = good_id
    
    pw, browser = await _get_browser()
    page = await browser.new_page()
    
    captured = {"chart": None, "detail": None}
    
    try:
        async def on_response(response):
            url = response.url
            try:
                if "info/chart" in url and response.ok:
                    body = await response.text()
                    captured["chart"] = body
                if "info/good?id=" in url and response.ok:
                    body = await response.text()
                    captured["detail"] = body
            except Exception:
                pass
        
        async def modify_chart(route, request):
            if "info/chart" in request.url:
                try:
                    body = json.loads(request.post_data)
                    body["period"] = "90"
                    body["key"] = "sell_price"
                    body["platform"] = 1
                    await route.continue_(post_data=json.dumps(body))
                except Exception:
                    await route.continue_()
            else:
                await route.continue_()
        
        page.on("response", on_response)
        await page.route("**/info/chart**", modify_chart)
        
        await page.goto(f"{CSQAQ_WEB}/goods/{good_id}", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(6000)  # Reduced from 10s, chart loads via API
        
        # 1. Parse chart data
        if captured["chart"]:
            data = json.loads(captured["chart"])
            if data.get("code") == 200 and data.get("data"):
                cd = data["data"]
                item._daily_bars = _chart_to_daily_ohlc(cd)
                item._kline_raw = _chart_to_raw(cd)
                item.kline_90d = item._daily_bars[:]
                ts = cd.get("timestamp", [])
                prices = cd.get("main_data", [])
                nums = cd.get("num_data", [])
                if prices:
                    item.price_rmb = float(prices[-1]) if prices[-1] is not None else 0.0
                if nums:
                    item.volume_total = int(nums[-1]) if nums[-1] is not None else 0
                _csq_log.info(f"Chart: {len(ts)} pts, {len(item._daily_bars)} daily bars")
        
        # 2. Parse detail data
        if captured["detail"]:
            data = json.loads(captured["detail"])
            if data.get("code") == 200:
                gi = data["data"].get("goods_info", {})
                item.name = gi.get("name", item.name)
                item.steam_name = gi.get("market_hash_name", "")
                item.sell_price_rate_1 = float(gi.get("sell_price_rate_1", 0))
                item.sell_price_rate_7 = float(gi.get("sell_price_rate_7", 0))
                item.sell_price_rate_15 = float(gi.get("sell_price_rate_15", 0))
                item.sell_price_rate_30 = float(gi.get("sell_price_rate_30", 0))
                item.sell_price_rate_90 = float(gi.get("sell_price_rate_90", 0))
                item.sell_price_rate_180 = float(gi.get("sell_price_rate_180", 0))
                item.rarity_name = gi.get("rarity_localized_name", "")
                item.exterior_name = gi.get("exterior_localized_name", "")
                item.type_name = gi.get("type_localized_name", "")
                item.quality_name = gi.get("quality_localized_name", "")
                item.group_hash_name = gi.get("group_hash_name", "")
                item.rank_num = int(gi.get("rank_num", 0))
                item.rank_change = int(gi.get("rank_num_change", 0))
                
                # Container/case info
                container = data["data"].get("container", [])
                if container and isinstance(container, list) and len(container) > 0:
                    c = container[0]
                    item.case_name = c.get("name", "")
                    item.case_discontinued = c.get("comment", "") == "\u7edd\u7248"
                    item.case_created = c.get("created_at", "")
                
                # Statistic variants (same skin, different wears)
                sl = data["data"].get("statistic_list", [])
                if isinstance(sl, list):
                    item.statistic_variants = sl
                
                buff_sell = float(gi.get("buff_sell_price", 0))
                if buff_sell > 0:
                    item.price_rmb = buff_sell
                
                item.volume_total = int(gi.get("buff_sell_num", item.volume_total))
                item.volume_day = int(gi.get("turnover_number", 0))
                
                buy_price = float(gi.get("buff_buy_price", 0))
                buy_num = int(gi.get("buff_buy_num", 0))
                if buy_price > 0 and item.price_rmb > 0:
                    ob = OrderBook(item.price_rmb, buy_price, item.volume_total, buy_num)
                    ob.spread_rmb = round(ob.lowest_sell - ob.highest_buy, 2)
                    ob.spread_pct = round(ob.spread_rmb / ob.lowest_sell * 100, 1)
                    item.order_book = ob
    finally:
        await page.close()
        # Browser kept alive for reuse
    
    return item if item.price_rmb > 0 else None


async def fetch_kline_90d(good_id: int) -> tuple[list, list]:
    """Async: Get 90-day K-line data. Returns (daily_ohlc_list, raw_points_list)."""
    pw, browser = await _get_browser()
    page = await browser.new_page()
    
    chart_data = {}
    try:
        async def on_response(response):
            if "info/chart" in response.url:
                try:
                    chart_data["body"] = await response.text()
                except Exception:
                    pass
        
        async def modify_chart(route, request):
            if "info/chart" in request.url:
                try:
                    body = json.loads(request.post_data)
                    body["period"] = "90"
                    body["key"] = "sell_price"
                    body["platform"] = 1
                    await route.continue_(post_data=json.dumps(body))
                except Exception:
                    await route.continue_()
            else:
                await route.continue_()
        
        page.on("response", on_response)
        await page.route("**/info/chart**", modify_chart)
        
        await page.goto(f"{CSQAQ_WEB}/goods/{good_id}", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(6000)  # Reduced from 10s, chart loads via API
        
        ohlc, raw = [], []
        if chart_data.get("body"):
            data = json.loads(chart_data["body"])
            if data.get("code") == 200 and data.get("data"):
                cd = data["data"]
                ohlc = _chart_to_daily_ohlc(cd)
                raw = _chart_to_raw(cd)
    finally:
        await page.close()
        # Browser kept alive for reuse
    
    return ohlc, raw
