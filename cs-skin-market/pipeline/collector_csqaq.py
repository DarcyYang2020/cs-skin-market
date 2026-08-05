# -*- coding: utf-8 -*-
"""csqaq.com Playwright data collector.
Navigates directly to goods page and intercepts chart API.
"""

import asyncio, json, re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

TZ_BJ = timezone(timedelta(hours=8))
_csq_log = logging.getLogger(__name__)
CSQAQ_WEB = "https://csqaq.com"

# === Browser singleton (reuse across calls) ===
_browser_pw = None
_browser_inst = None
_browser_last_used = 0

async def _get_browser():
    """Get or create Playwright browser instance (with retry for Windows asyncio issue)."""
    for attempt in range(3):
        try:
            return await _get_browser_once()
        except NotImplementedError:
            if attempt < 2:
                await asyncio.sleep(1)
            else:
                raise
    return None, None


async def _get_browser_once():

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
            pass
        _browser_inst = None
        _browser_pw = None
    from playwright.async_api import async_playwright
    _browser_pw = await async_playwright().start()
    launch_kw = dict(headless=True)
    _browser_inst = await _browser_pw.chromium.launch(**launch_kw)
    _browser_last_used = now
    return _browser_pw, _browser_inst

# ============================================================
# Data container
# ============================================================
class ItemData:
    def __init__(self):
        self.good_id: int = 0
        self.name: str = ""
        self.steam_name: str = ""
        self.price_rmb: float = 0.0
        self.price_buff: float = 0.0
        self.price_steam: float = 0.0
        self.volume_day: int = 0
        self.volume_total: int = 0
        self.turnover_number: int = 0  # Steam market daily volume (from info/good)
        self.yyyp_id: str = ""  # youpin898 template id (from info/good)
        self.in_sale_count: int = 0
        self.survive_count: int = 0  # 存世量（statistic_list 对应磨损的 statistic）
        self.order_book: Optional[dict] = None
        self.kline_90d: list = []

def _chart_to_daily_ohlc(cd: dict) -> list:
    """Aggregate 10-min chart data into daily OHLCV bars.
    Returns list of Bar objects with close, high, low, volume, in_sale_count.
    """
    ts_arr = cd.get("timestamp", [])
    price_arr = cd.get("main_data", [])
    num_arr = cd.get("num_data", [])
    tx_arr = cd.get("tx_data", [])
    tx_count_arr = cd.get("txcount_data", [])
    survive_arr = cd.get("survive_data", [])

    class Bar:
        def __init__(self, ts, close, high, low, volume, in_sale, tx_amount, tx_count, survive):
            self.ts = ts
            self.date = ""  # set below
            self.close = close
            self.high = high
            self.low = low
            self.volume = volume
            self.in_sale_count = in_sale
            self.tx_amount = tx_amount
            self.tx_count = tx_count
            self.survive = survive

    daily = {}
    for i in range(min(len(ts_arr), len(price_arr))):
        if i >= len(price_arr) or price_arr[i] is None or price_arr[i] == "":
            continue
        try:
            price = float(price_arr[i])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        ts = int(ts_arr[i]) // 1000 if ts_arr[i] else 0
        dt = datetime.fromtimestamp(ts, tz=TZ_BJ)
        day_key = dt.strftime("%Y-%m-%d")
        vol = float(tx_count_arr[i]) if i < len(tx_count_arr) and tx_count_arr[i] is not None else 0
        tx_amt = float(tx_arr[i]) if i < len(tx_arr) and tx_arr[i] is not None else 0
        tx_cnt = int(tx_count_arr[i]) if i < len(tx_count_arr) and tx_count_arr[i] is not None else 0
        survive = int(survive_arr[i]) if i < len(survive_arr) and survive_arr[i] is not None else 0
        if day_key in daily:
            b = daily[day_key]
            if price > b.high: b.high = price
            if price < b.low: b.low = price
            b.close = price
            b.volume += vol
            b.date = day_key; b.in_sale_count = int(float(num_arr[i])) if i < len(num_arr) and num_arr[i] is not None else 0
            b.tx_amount += tx_amt
            b.tx_count += tx_cnt
            b.survive = survive
        else:
            b = Bar(ts, price, price, price, vol, int(float(num_arr[i])) if i < len(num_arr) and num_arr[i] is not None else 0, tx_amt, tx_cnt, survive); b.date = day_key; daily[day_key] = b

    return list(daily.values())

def _chart_to_raw(cd: dict) -> list:
    """Convert chart data to raw point list for backtesting."""
    ts_arr = cd.get("timestamp", [])
    price_arr = cd.get("main_data", [])
    vol_arr = cd.get("num_data", [])
    out = []
    for i in range(min(len(ts_arr), len(price_arr))):
        try:
            p = float(price_arr[i]) if price_arr[i] is not None else 0
            v = float(vol_arr[i]) if i < len(vol_arr) and vol_arr[i] is not None else 0
        except (TypeError, ValueError):
            continue
        out.append([ts_arr[i], p, v])
    return out

def _extract_chart(item, data, set_price=True) -> int:
    """Populate ItemData from csQAQ chart response. Returns number of daily bars.
    set_price=False: fallback (Buff/C5GAME) chart must NOT overwrite the
    youpin-anchored price (定价锚: 悠悠 > Buff > C5GAME).
    """
    if not data or data.get('code') != 200 or not data.get('data'):
        return 0
    cd = data['data']
    item._daily_bars = _chart_to_daily_ohlc(cd)
    item._kline_raw = _chart_to_raw(cd)
    item.kline_90d = item._daily_bars[:]
    nums = cd.get('num_data', [])
    prices = cd.get('main_data', [])
    if nums and prices:
        try:
            item.volume_day = max(int(float(nums[-1])), 0) if nums[-1] else 0
        except (TypeError, ValueError):
            item.volume_day = 0
    if set_price:
        if item._daily_bars:
            try:
                item.price_rmb = item._daily_bars[-1].close
            except (TypeError, ValueError, IndexError):
                item.price_rmb = 0.0
        elif prices:
            try:
                item.price_rmb = float(prices[-1])
            except (TypeError, ValueError):
                item.price_rmb = 0.0
    if nums:
        try:
            item.volume_total = max((int(float(v)) if v else 0) for v in nums)
        except (TypeError, ValueError):
            item.volume_total = 0
    return len(item.kline_90d)

# ============================================================
# Search for good_id by name
# ============================================================


# Wear condition mapping
WEAR_CONDITIONS = ["崭新出厂", "略有磨损", "久经沙场", "破损不堪", "战痕累累"]

def _extract_wear(query: str) -> str:
    """Extract wear condition from query string. Returns empty string if none found."""
    for wc in WEAR_CONDITIONS:
        if wc in query:
            return wc
    return ""

def _has_wear_conflict(query: str, result_title: str) -> bool:
    """Check if query specifies a wear condition that conflicts with the result."""
    q_wear = _extract_wear(query)
    if not q_wear:
        return False
    r_wear = _extract_wear(result_title)
    if not r_wear:
        return False
    return q_wear != r_wear


def _has_skin_mismatch(query: str, result_title: str) -> bool:
    """Check if query's Chinese skin name chars overlap with result title."""
    chinese_q = set(c for c in query if '一' <= c <= '鿿')
    if not chinese_q:
        return False  # No Chinese chars in query, can't verify
    chinese_r = set(c for c in result_title if '一' <= c <= '鿿')
    if not chinese_r:
        return False  # No Chinese chars in result, skip check
    overlap = chinese_q & chinese_r
    # Require at least 50% of query Chinese chars to match
    if len(overlap) < max(1, len(chinese_q) // 2):
        return True  # Mismatch!
    return False

async def search_good_id(query: str) -> tuple[int, str]:
    """Search csQAQ for a good_id by name.
    1. Normalize " | " to " " for Chinese search
    2. Trigger csQAQ autocomplete via React fiber
    3. Filter out StatTrak/纪念品 results
    4. Click best match, extract good_id from URL
    """
    query = query.replace(" | ", " ").replace("|", " ")

    pw, browser = await _get_browser()
    page = await browser.new_page()
    
    try:
        await page.goto(CSQAQ_WEB, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("#rc_select_0", timeout=6000)
        except Exception:
            pass
        
        # Trigger autocomplete via React fiber (inject value; return value unused)
        await page.evaluate("""
            async (q) => {
                const el = document.querySelector("#rc_select_0");
                if (!el) return "no el";
                const fiberKey = Object.keys(el).find(
                    k => k.startsWith("__reactFiber") || k.startsWith("__reactInternalInstance")
                );
                if (!fiberKey) return "no fiber";
                const fiber = el[fiberKey];
                let node = fiber;
                let tries = 0;
                while (node && tries < 30) {
                    const props = node.memoizedProps;
                    if (props && (props.onChange || props.onSearch)) {
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, "value"
                        ).set;
                        setter.call(el, q);
                        if (props.onChange) props.onChange({ target: { value: q } });
                        else if (props.onSearch) props.onSearch(q);
                        return "ok";
                    }
                    node = node.return || node.stateNode;
                    tries++;
                }
                return "no handler";
            }
        """, query)
        
        try:
            await page.wait_for_selector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)", timeout=6000)
        except Exception:
            pass
        
        dropdown = await page.query_selector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")
        if not dropdown:
            _csq_log.warning(f"Search '{query}': no dropdown")
            return 0, ""
        
        items = await dropdown.query_selector_all(".ant-select-item-option, [role='option'], .ant-select-item")
        
        candidates = []
        for item in items:
            try:
                title = (await item.inner_text()).strip()
                if not title or title.isdigit():
                    continue
                if "StatTrak" in title or "纪念品" in title:
                    continue
                candidates.append((title, item))
            except Exception:
                continue
        
        if not candidates:
            _csq_log.warning(f"Search '{query}': all filtered out")
            return 0, ""
        
        best_title, best_item = candidates[0]
        await best_item.click()
        try:
            await page.wait_for_url("**/goods/**", timeout=8000)
        except Exception:
            pass
        
        url_match = re.search(r"/goods/(\d+)", page.url)
        if url_match:
            gid = int(url_match.group(1))
            _csq_log.info(f"Search '{query}' -> good_id={gid} '{best_title}'")
            return gid, best_title
        
        _csq_log.warning(f"Search '{query}': no good_id in URL")
        return 0, ""
    
    finally:
        await page.close()



async def _wait_chart(page, captured, timeout=2.5):
    """Wait briefly for the chart API response to be captured (poll, no fixed sleep)."""
    for _ in range(int(timeout * 10)):
        if captured.get("chart"):
            return True
        await asyncio.sleep(0.1)
    return False


async def _modify_chart_route(route, request, platform=2):
    """Modify chart API request with given platform."""
    if "info/chart" in request.url:
        try:
            body = json.loads(request.post_data)
            body["period"] = "90"
            body["key"] = "sell_price"
            body["platform"] = platform
            await route.continue_(post_data=json.dumps(body))
        except Exception:
            await route.continue_()
    else:
        await route.continue_()

async def fetch_item_detail(good_id: int):
    """Fetch item detail + 90-day K-line with retry (csQAQ chart API is flaky)."""
    for attempt in range(3):
        item = await _fetch_item_detail_once(good_id)
        if item and len(item.kline_90d) > 0:
            return item
        if attempt < 2:
            await asyncio.sleep(1.5)
    return item


async def _fetch_item_detail_once(good_id: int):
    """Async: Fetch item detail + 90-day K-line from csqaq.com/goods/{good_id}."""
    item = ItemData()
    item.good_id = good_id
    pw, browser = await _get_browser()
    page = await browser.new_page()
    captured = {'chart': None, 'detail': None, 'buy_chart': None}
    want_buy = {'flag': False}
    try:
        async def on_response(response):
            url = response.url
            try:
                if "info/chart" in url and response.ok:
                    body = await response.text()
                    if want_buy['flag']:
                        captured["buy_chart"] = body
                        want_buy['flag'] = False
                    else:
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
                    body["platform"] = 2
                    await route.continue_(post_data=json.dumps(body))
                except Exception:
                    await route.continue_()
            else:
                await route.continue_()
        page.on('response', on_response)
        await page.route('**/info/chart**', modify_chart)
        try:
            await page.goto(f'{CSQAQ_WEB}/goods/{good_id}', wait_until='domcontentloaded', timeout=25000)
        except Exception as _ge:
            _csq_log.warning(f"goto goods/{good_id} failed: {_ge}")
        await _wait_chart(page, captured)
        if captured['chart']:
            try:
                _extract_chart(item, json.loads(captured['chart']))
            except Exception:
                pass
        # Retry with Buff (platform=1) / C5GAME (platform=3) if chart still empty
        for fb_platform, fb_name in ((1, "Buff"), (3, "C5GAME")):
            if item.kline_90d:
                break
            _csq_log.info(f"Empty chart from platform=2, retrying with platform={fb_platform} ({fb_name}) good_id={good_id}")
            try:
                captured['chart'] = None
                await page.route('**/info/chart**', lambda r, req, p=fb_platform: _modify_chart_route(r, req, platform=p))
                await page.goto(f'{CSQAQ_WEB}/goods/{good_id}', wait_until='domcontentloaded', timeout=25000)
                await _wait_chart(page, captured)
                if captured['chart']:
                    # fallback chart fills K-line only; price stays youpin-anchored
                    _extract_chart(item, json.loads(captured['chart']), set_price=False)
                    _csq_log.info(f"{fb_name} platform returned {len(item.kline_90d)} bars")
            except Exception as e2:
                _csq_log.warning(f"{fb_name} retry failed: {e2}")

        # 定价锚：悠悠有品 DOM 价最高优先级（最后覆盖，任何 chart close 都不得覆盖）
        try:
            yyyp_price = await page.evaluate("() => { const el = document.querySelector('.ant-statistic-content-value'); if (el) return el.innerText.trim(); return ''; }")
            if yyyp_price:
                p = float(yyyp_price.replace(',', '').replace('\u00a5', ''))
                if p > 0:
                    item.price_rmb = p
        except Exception:
            pass
        if captured['detail']:
            try:
                dd = json.loads(captured['detail'])
                if dd.get('code') == 200 and dd.get('data'):
                    d = dd['data']
                    gi = d.get('goods_info', d)  # fallback to d itself
                    item.name = gi.get('name', '') or item.name
                    item.steam_name = gi.get('market_hash_name', '') or gi.get('steam_name', '')
                    # Only use detail API price if chart price is 0 (stale fallback)
                    if item.price_rmb == 0:
                        try:
                            for pk in ('yyyp_sell_price', 'sell_price', 'price'):
                                pv = gi.get(pk, 0)
                                if pv and float(pv) > 0:
                                    item.price_rmb = float(pv)
                                    break
                        except (TypeError, ValueError):
                            pass
                    item.in_sale_count = int(gi.get('in_sale_count', gi.get('sale_num', gi.get('buff_sell_num', 0))) or 0)
                    # 存世量：statistic_list 按 good_id 匹配当前磨损档的 statistic（普通版仅留帖纹盘面）
                    for _sl in (d.get('statistic_list') or []):
                        try:
                            if int(_sl.get('id') or 0) == good_id:
                                item.survive_count = int(_sl.get('statistic') or 0)
                                break
                        except (TypeError, ValueError):
                            continue
                    item.turnover_number = int(gi.get('turnover_number', 0) or 0)
                    item.yyyp_id = str(gi.get('yyyp_id', '') or '')
            except Exception:
                pass
        # Build order_book from the page native 求购价 chart (uses browser session,
        # bypasses the ApiToken IP whitelist that blocks direct /info/chart POST).
        if not page.is_closed() and item.price_rmb > 0:
            try:
                btns = await page.query_selector_all("button")
                for b in btns:
                    t = (await b.inner_text()).strip()
                    if t == "出售价":
                        await b.click()
                        break
                await page.wait_for_timeout(800)
                want_buy["flag"] = True
                clicked = await page.evaluate("""() => {
                    const els = document.querySelectorAll('.ant-dropdown-menu-item, [role="menuitem"], li[class*="menu"]');
                    for (const el of els) {
                        if ((el.innerText || '').trim().includes('求购价')) { el.click(); return true; }
                    }
                    return false;
                }""")
                if clicked:
                    await page.wait_for_timeout(3000)
            except Exception:
                pass
        if captured.get("buy_chart") and item.price_rmb > 0:
            try:
                bd = json.loads(captured["buy_chart"])
                if bd.get("code") == 200 and bd.get("data"):
                    cd_buy = bd["data"]
                    buy_bars = _chart_to_daily_ohlc(cd_buy)
                    buy_prices = [b.close for b in buy_bars if b.close > 0]
                    if buy_prices:
                        highest_buy = buy_prices[-1]
                        spread_pct = round((item.price_rmb - highest_buy) / item.price_rmb * 100, 1)

                        def _bid_chg(series, n):
                            if len(series) > n and series[-n - 1] > 0:
                                return round((series[-1] - series[-n - 1]) / series[-n - 1] * 100, 1)
                            return None

                        sell_by_date = {}
                        for b in item.kline_90d:
                            if getattr(b, "close", 0) > 0:
                                sell_by_date[b.date] = b.close
                        spreads = []
                        for b in buy_bars:
                            s = sell_by_date.get(b.date)
                            if s and s > 0:
                                spreads.append((s - b.close) / s * 100)
                        spread_avg = round(sum(spreads) / len(spreads), 1) if spreads else None
                        spread_7d_avg = round(sum(spreads[-7:]) / len(spreads[-7:]), 1) if len(spreads) >= 7 else None
                        item.order_book = {
                            "spread_pct": max(0.0, spread_pct),
                            "depth": item.volume_total,
                            "bid_count": int(item.in_sale_count * 0.1) if item.in_sale_count > 0 else 0,
                            "highest_buy": round(highest_buy, 2),
                            "bid_7d_chg": _bid_chg(buy_prices, 7),
                            "bid_30d_chg": _bid_chg(buy_prices, 30),
                            "spread_avg": spread_avg,
                            "spread_7d_avg": spread_7d_avg,
                        }
            except Exception:
                pass
        return item
    finally:
        await page.close()


async def _capture_proxies_api(browser, keyword: str, tries: int = 3):
    """Open the csqaq market homepage and capture a /proxies/api/v1/* response.

    Direct API calls are blocked by the ApiToken IP whitelist (401 when the
    account-bound IP changes); the browser carries the page session so these
    endpoints succeed. Returns raw response text or None.
    """
    page = await browser.new_page()
    captured = {"body": None}
    try:
        async def on_response(response):
            try:
                if keyword in response.url and response.ok:
                    captured["body"] = await response.text()
            except Exception:
                pass
        page.on("response", on_response)
        for attempt in range(tries):
            captured["body"] = None
            await page.goto(f'{CSQAQ_WEB}/', wait_until='domcontentloaded', timeout=25000)
            for _ in range(40):
                if captured["body"]:
                    return captured["body"]
                await asyncio.sleep(0.25)
        return None
    finally:
        await page.close()


async def fetch_index_kline_via_browser():
    """Fallback: intercept sub_data (market daily kline) on the homepage.

    Returns list of (date_str, value) close pairs (2020-12-31+), same shape
    as collector.fetch_index_kline(). main_data rows are [close, chg, chg_pct].
    """
    pw, browser = await _get_browser()
    try:
        body = await _capture_proxies_api(browser, "sub_data")
        if not body:
            return []
        payload = json.loads(body)
        data = payload.get("data") or {}
        ts_arr = data.get("timestamp", [])
        md_arr = data.get("main_data", [])
        points = []
        for i in range(min(len(ts_arr), len(md_arr))):
            try:
                row = md_arr[i]
                close = float(row[0]) if isinstance(row, (list, tuple)) and row else 0
                if close <= 0 or not ts_arr[i]:
                    continue
                dt = datetime.fromtimestamp(int(ts_arr[i]) / 1000, tz=TZ_BJ)
                points.append((dt.strftime("%Y-%m-%d"), close))
            except (TypeError, ValueError, OSError):
                continue
        return points
    finally:
        pass


async def fetch_current_data_via_browser():
    """Fallback: intercept current_data on the homepage (repairs the dangling
    import in collector._current_data_with_fallback)."""
    pw, browser = await _get_browser()
    try:
        body = await _capture_proxies_api(browser, "current_data")
        if not body:
            return None
        payload = json.loads(body)
        return payload.get("data") if payload.get("code") == 200 else None
    finally:
        pass


async def fetch_kline_90d(good_id: int):
    """Async: Get 90-day K-line data."""
    pw, browser = await _get_browser()
    page = await browser.new_page()
    captured = {'chart': None}
    try:
        async def on_response(response):
            url = response.url
            try:
                if "info/chart" in url and response.ok:
                    body = await response.text()
                    captured["chart"] = body
            except Exception:
                pass
        async def modify_chart(route, request):
            if "info/chart" in request.url:
                try:
                    body = json.loads(request.post_data)
                    body["period"] = "90"
                    body["key"] = "sell_price"
                    body["platform"] = 2
                    await route.continue_(post_data=json.dumps(body))
                except Exception:
                    await route.continue_()
            else:
                await route.continue_()
        page.on('response', on_response)
        await page.route('**/info/chart**', modify_chart)
        try:
            await page.goto(f'{CSQAQ_WEB}/goods/{good_id}', wait_until='domcontentloaded', timeout=15000)
        except Exception as _ge:
            _csq_log.warning(f"fetch_kline_90d goto goods/{good_id} failed: {_ge}")
        await _wait_chart(page, captured)
        ohlc, raw = [], []
        if captured['chart']:
            data = json.loads(captured['chart'])
            if data.get('code') == 200 and data.get('data'):
                cd = data['data']
                ohlc = _chart_to_daily_ohlc(cd)
                raw = _chart_to_raw(cd)

        # Retry with Buff (platform=1) / C5GAME (platform=3) if chart still empty
        for fb_platform, fb_name in ((1, "Buff"), (3, "C5GAME")):
            if ohlc:
                break
            _csq_log.info(f"fetch_kline_90d: empty from platform=2, retry platform={fb_platform} ({fb_name}) good_id={good_id}")
            try:
                captured['chart'] = None
                await page.route('**/info/chart**', lambda r, req, p=fb_platform: _modify_chart_route(r, req, platform=p))
                await page.goto(f'{CSQAQ_WEB}/goods/{good_id}', wait_until='domcontentloaded', timeout=15000)
                await _wait_chart(page, captured)
                if captured['chart']:
                    data2 = json.loads(captured['chart'])
                    if data2.get('code') == 200 and data2.get('data'):
                        cd2 = data2['data']
                        ohlc = _chart_to_daily_ohlc(cd2)
                        raw = _chart_to_raw(cd2)
                        _csq_log.info(f"fetch_kline_90d {fb_name} returned {len(ohlc)} bars")
            except Exception as e2:
                _csq_log.warning(f"fetch_kline_90d {fb_name} retry failed: {e2}")

        return ohlc, raw
    finally:
        await page.close()


async def fetch_simple_kline(good_id: int, max_time_ms: int):
    """深度历史 K 线（simple/chartAll，2026-08-04 实测）。

    通过路由改写把商品页 info/chart 请求替换为 info/simple/chartAll
    （body: good_id/plat=2 悠悠/periods=1day/max_time），走页面会话绕过 IP 白名单。
    返回 [{t(ms str), o, c, h, l, v}]，约 150 个日线点（向前分页由 max_time 控制）。

    实测改写后响应延迟波动大（2s~11s+），故等待 12s + 失败重试 2 次（各开新页）。
    """
    pw, browser = await _get_browser()

    async def attempt():
        page = await browser.new_page()
        captured = {"chart": None}
        try:
            async def on_response(response):
                try:
                    if "info/simple/chartAll" in response.url and response.ok:
                        captured["chart"] = await response.text()
                except Exception:
                    pass

            async def rewrite(route, request):
                if "info/chart" in request.url:
                    try:
                        new_url = request.url.replace("/info/chart", "/info/simple/chartAll")
                        body = {"good_id": str(good_id), "plat": 2, "periods": "1day",
                                "max_time": max_time_ms}
                        await route.continue_(url=new_url, post_data=json.dumps(body))
                    except Exception:
                        await route.continue_()
                else:
                    await route.continue_()

            page.on("response", on_response)
            await page.route("**/info/chart**", rewrite)
            try:
                await page.goto(f"{CSQAQ_WEB}/goods/{good_id}", wait_until="domcontentloaded", timeout=15000)
            except Exception as ge:
                _csq_log.warning(f"fetch_simple_kline goto goods/{good_id} failed: {ge}")
            await _wait_chart(page, captured, timeout=12.0)
            if captured["chart"]:
                data = json.loads(captured["chart"])
                if data.get("code") == 200 and data.get("data"):
                    return data["data"]
            return None
        finally:
            await page.close()

    for attempt_no in range(3):
        data = await attempt()
        if data:
            return data
        if attempt_no < 2:
            await asyncio.sleep(1.0)
    return []



async def fetch_history_deep(good_id: int, min_date: str = "2025-01-01", start_date: str | None = None):
    """深度历史日线价格回填（simple/chartAll 多窗口向前翻页）。

    min_date: 回填下界（默认 2025-01-01：2024 及更早市场逻辑已过时，不纳入）。
    start_date: 已有数据起点（含）；只补 [min_date, start_date) 区间，避免重复抓已覆盖窗口。
    返回 [(date_str, close), ...] 升序；仅价格，不含成交量（v 字段口径未确认，勿用于量）。
    """
    from datetime import datetime as _dt
    min_ts = int(_dt.strptime(min_date, "%Y-%m-%d").replace(tzinfo=TZ_BJ).timestamp() * 1000)
    now_ts = int(datetime.now(TZ_BJ).timestamp() * 1000)
    if start_date:
        try:
            start_ts = int(_dt.strptime(start_date, "%Y-%m-%d").replace(tzinfo=TZ_BJ).timestamp() * 1000)
            now_ts = min(now_ts, start_ts - 86400000)  # 只取已有起点之前
        except ValueError:
            pass
    if now_ts < min_ts:
        return []
    points: list = []
    max_time = now_ts
    empty_run = 0
    while max_time >= min_ts and empty_run < 2:
        data = await fetch_simple_kline(good_id, max_time)
        if not data:
            empty_run += 1
            max_time -= 150 * 86400000
            continue
        empty_run = 0
        pts = []
        for p in data:
            try:
                t = int(p["t"])
                c = float(p.get("c") or 0)
                d = _dt.fromtimestamp(t / 1000, tz=TZ_BJ).strftime("%Y-%m-%d")
                if c > 0:
                    pts.append((t, d, c))
            except (KeyError, TypeError, ValueError):
                continue
        pts.sort()
        for t, d, c in pts:
            if min_ts <= t <= now_ts:
                points.append((d, c))
        # 回拨到本窗口最早点前一天，继续向前翻页
        earliest_t = pts[0][0] if pts else max_time - 150 * 86400000
        next_max = earliest_t - 86400000
        if next_max >= max_time:  # 防御：无进展则强制回拨 150 天
            next_max = max_time - 150 * 86400000
        max_time = next_max
    # 去重保序
    seen, out = set(), []
    for d, c in points:
        if d not in seen:
            seen.add(d)
            out.append((d, c))
    out.sort()
    _csq_log.info(f"fetch_history_deep good_id={good_id}: {len(out)} points")
    return out


