# -*- coding: utf-8 -*-
"""steamdt.com Playwright volume collector.

Navigates directly to /cs2/{market_hash_name} and intercepts the
K-line API to extract real trading volume (tx_count) aggregated to daily.

Fallback: if direct URL returns 404, searches via steamdt homepage.
"""

import asyncio, json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

TZ_BJ = timezone(timedelta(hours=8))

_stdt_log = logging.getLogger(__name__)

STEAMDT_WEB = "https://www.steamdt.com"

async def _get_browser():
    from .collector_csqaq import _get_browser as _csq_browser
    return await _csq_browser()


async def fetch_steamdt_volume(market_hash_name: str) -> dict[str, int]:
    """Fetch daily trading volume from steamdt page.

    Since the type-trend API no longer works, scrapes
    "今日推算成交" from the item detail page.

    Returns:
        dict mapping date string "YYYY-MM-DD" to daily tx_count (int).
    """
    pw, browser = await _get_browser()
    encoded = quote(market_hash_name, safe="")
    url = f"{STEAMDT_WEB}/cs2/{encoded}"
    
    page = await browser.new_page()
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if resp and resp.status == 404:
            return {}
        
        await page.wait_for_timeout(5000)
        text = await page.inner_text("body")
        
        # Extract "今日推算成交: N"
        import re
        m = re.search(r'今日推算成交\s*:?\s*(\d+)', text)
        if not m:
            m = re.search(r'推算成交\s*:?\s*(\d+)', text)
        if not m:
            m = re.search(r'成交\s*\(\s*(\d+)\s*\)', text)
        
        if m:
            volume = int(m.group(1))
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            _stdt_log.info(f"steamdt volume: {today} = {volume}")
            return {today: volume}
        
        return {}
    except Exception as e:
        _stdt_log.warning(f"steamdt volume fetch failed: {e}")
        return {}
    finally:
        await page.close()


def _parse_kline_response(kline_body: dict) -> dict[str, int]:
    """Parse steamdt K-line into {date: daily_tx_count}."""
    if not kline_body.get("body"):
        return {}

    try:
        data = json.loads(kline_body["body"])
        pts = data.get("data")
        if not pts or not isinstance(pts, list):
            return {}
    except (json.JSONDecodeError, KeyError):
        return {}

    daily_tx = defaultdict(int)
    for p in pts:
        if not isinstance(p, list) or len(p) < 7:
            continue
        try:
            ts = int(p[0])
            dt = datetime.fromtimestamp(ts, tz=TZ_BJ).strftime("%Y-%m-%d")
            tx = p[6]
            if tx is not None:
                daily_tx[dt] += int(tx)
        except (ValueError, TypeError):
            continue

    _stdt_log.info(f"steamdt volume: {len(daily_tx)} daily bars, total tx={sum(daily_tx.values())}")
    return dict(daily_tx)


def merge_daily_volume(kline_90d: list, steamdt_vol: dict[str, int]) -> list:
    """Fill KLinePoint.volume with real tx_count from steamdt.

    Args:
        kline_90d: list of KLinePoint from csQAQ (volume currently 0)
        steamdt_vol: {date_str: tx_count} from steamdt

    Returns:
        Same list with volume field populated.
    """
    for bar in kline_90d:
        if bar.date in steamdt_vol:
            bar.volume = steamdt_vol[bar.date]
    filled = sum(1 for b in kline_90d if b.volume > 0)
    _stdt_log.info(f"Volume merge: {filled}/{len(kline_90d)} bars filled")
    return kline_90d
