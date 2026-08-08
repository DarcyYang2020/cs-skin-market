"""
csQAQ API data collector (v3).
csQAQ API + csqaq.com Playwright data collector.
No browser automation needed — all data via csQAQ REST API.
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.parse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from .config import CSQAQ_BASE, API_TOKEN, API_RATE_LIMIT, DATA_DIR
import logging
_log = logging.getLogger(__name__)

TZ_BJ = timezone(timedelta(hours=8))


# ============================================================
#  Data classes (unchanged from original)
# ============================================================

@dataclass
class MarketIndex:
    value: float = 0.0
    change_7d: float = 0.0
    mood: str = ""


@dataclass
class OrderBook:
    """Buy/sell order book snapshot."""
    lowest_sell: float = 0.0
    highest_buy: float = 0.0
    sell_count: int = 0
    buy_count: int = 0
    spread_rmb: float = 0.0
    spread_pct: float = 0.0
    bid_depth: float = 0.0
    raw_lines: list[str] = field(default_factory=list)


@dataclass
class SectorFlow:
    name: str = ""
    change_pct: float = 0.0
    rank: int = 99
    momentum: str = ""


@dataclass
class KLinePoint:
    date: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0


@dataclass
class ItemData:
    name: str = ""
    steam_name: str = ""
    weapon: str = ""
    skin: str = ""
    wear: str = ""
    price_rmb: float = 0.0
    volume_day: int = 0
    volume_total: int = 0
    trend: str = ""
    order_book: Optional[OrderBook] = None
    kline_30d: list[KLinePoint] = field(default_factory=list)
    sector: str = ""
    raw_lines: list[str] = field(default_factory=list)
    good_id: int = 0  # NEW: csQAQ primary key


# ============================================================
#  HTTP helpers
# ============================================================

def _api_call(method: str, path: str, body: dict | None = None) -> dict:
    """Call csQAQ API with rate-limit protection."""
    time.sleep(API_RATE_LIMIT)
    url = CSQAQ_BASE + path
    req = urllib.request.Request(url, method=method)
    req.add_header("ApiToken", API_TOKEN)
    data_bytes = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data_bytes = json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(req, data=data_bytes, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = ""
        _log.warning(f"HTTP {e.code} on {method} {path}: {err_body[:200]}")
        return {"code": e.code, "msg": str(e), "data": None}
    except Exception as e:
        _log.error(f"Error on {method} {path}: {e}")
        return {"code": -1, "msg": str(e), "data": None}


def _api_get(path: str) -> dict:
    return _api_call("GET", path)


def _api_post(path: str, body: dict) -> dict:
    return _api_call("POST", path, body)


def bind_local_ip() -> str:
    """(Re)bind current public IP to csQAQ API whitelist (POST /sys/bind_local_ip).

    Direct API requires IP whitelist; dynamic ISP IPs can change.
    Called at the start of daily collection (30s/次 rate limit)."""
    resp = _api_post("/sys/bind_local_ip", {})
    data = resp.get("data")
    if resp.get("code") == 200 and data:
        _log.info(f"bind_local_ip ok: {data}")
        return str(data)
    _log.warning(f"bind_local_ip failed: code={resp.get('code')} msg={resp.get('msg')}")
    return ""

def _parse_good_id(raw: int | None) -> int:
    if raw is None:
        return 0
    return int(raw)


def _parse_price(raw) -> float:
    if raw is None:
        return 0.0
    return float(raw)


def _parse_int(raw) -> int:
    if raw is None:
        return 0
    return int(raw)


# ============================================================
#  Market index
# ============================================================



def _run_browser_fallback(coro_factory, label):
    """Run a browser-fallback coroutine from sync code.

    - In worker/background threads, asyncio.run works fine.
    - In FastAPI request context an event loop already exists; the Playwright
      browser instance is bound to that loop, so asyncio.run would raise
      RuntimeError. In that case skip the fallback (API 401 persists).
    """
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    if in_loop:
        _log.warning(f"{label}: API 401 fallback skipped (running event loop, browser is loop-bound)")
        return None
    try:
        return asyncio.run(coro_factory())
    except Exception as e:
        _log.error(f"{label}: browser fallback failed: {e}")
        return None


def _current_data_with_fallback() -> dict | None:
    """Fetch /current_data?type=init with 401 fallback to browser.

    401（绑定 IP 校验，出口 IP 轮换导致间歇失败）→ 先 bind_local_ip 重新绑定再重试一次；
    仍 401 才走浏览器兜底（Web 请求线程内浏览器跨 loop 不可用，兜底可能失败）。
    """
    resp = _api_get("/current_data?type=init")
    data = resp.get("data")
    if resp.get("code") == 401 and not data:
        _log.warning("current_data: API 401 (IP binding mismatch), rebind then retry")
        try:
            bind_local_ip()
        except Exception as _be:
            _log.warning(f"current_data: bind_local_ip failed: {_be}")
        resp2 = _api_get("/current_data?type=init")
        data = resp2.get("data")
        if resp2.get("code") == 401 and not data:
            _log.warning("current_data: API 401 after rebind, falling back to browser")
            from .collector_csqaq import fetch_current_data_via_browser
            return _run_browser_fallback(fetch_current_data_via_browser, "current_data")
    return data

def fetch_market_index() -> MarketIndex | None:
    """Fetch CS composite index via csQAQ current_data API.
    Falls back to browser interception on 401 IP binding mismatch."""
    data = _current_data_with_fallback()
    if not data:
        _log.warning("fetch_market_index: no data")
        return None

    sub_indices = data.get("sub_index_data", [])
    main_idx = None
    for si in sub_indices:
        if si.get("name_key") == "init" or si.get("name") == "饰品指数":
            main_idx = si
            break
    if main_idx is None and sub_indices:
        main_idx = sub_indices[0]

    result = MarketIndex()
    if main_idx:
        result.value = _parse_price(main_idx.get("market_index"))
        result.change_7d = float(main_idx.get("chg_rate", 0))
        # mood from greedy data (uses level: low=fear, high=greed)
        greedy = data.get("greedy_status", {})
        level = greedy.get("level", "")
        if level == "low":
            result.mood = "恐惧"
        elif level == "high":
            result.mood = "贪婪"
        elif level == "medium":
            result.mood = "中性"
        else:
            result.mood = "neutral"

        return result


def fetch_index_kline() -> list:
    return _cached_kline(_fetch_index_kline_raw)

# === K-line cache (valid 1 hour) ===
import time as _time_mod
_kline_cache = {"data": None, "ts": 0}

def _cached_kline(fetcher, *args):
    now = _time_mod.time()
    if _kline_cache["data"] is not None and (now - _kline_cache["ts"]) < 3600:
        return _kline_cache["data"]
    result = fetcher(*args)
    _kline_cache["data"] = result
    _kline_cache["ts"] = now
    return result


def _fetch_index_kline_raw() -> list:
    """Fetch daily index K-line data from csQAQ API.
    GET /api/v1/sub/kline?id=1&type=1day
    Returns list of (date_str, value) tuples (close price).
    
    Falls back to Playwright browser interception when API returns 401
    (IP binding mismatch due to dynamic ISP IP changes).
    """
    resp = _api_get("/sub/kline?id=1&type=1day")
    data = resp.get("data")
    
    # Fallback: 401 -> browser interception (same session-bypass as current_data)
    if resp.get("code") == 401 and not data:
        _log.warning("fetch_index_kline: API 401 (IP binding mismatch), rebind then retry")
        try:
            bind_local_ip()
        except Exception as _be:
            _log.warning(f"fetch_index_kline: bind_local_ip failed: {_be}")
        resp2 = _api_get("/sub/kline?id=1&type=1day")
        data = resp2.get("data")
        if resp2.get("code") != 401 or data:
            return _parse_kline_points(data) if data else []
        _log.warning("fetch_index_kline: API 401 after rebind, falling back to browser")
        from .collector_csqaq import fetch_index_kline_via_browser
        points = _run_browser_fallback(fetch_index_kline_via_browser, "index_kline")
        if points:
            return points
        _log.warning("fetch_index_kline: browser fallback returned empty")
        return []
    
    return _parse_kline_points(data)


def _parse_kline_points(data) -> list:
    """sub/kline data 解析为 (date_str, close) 列表；异常行跳过。"""
    if not data or not isinstance(data, list):
        _log.warning("fetch_index_kline: no data from API")
        return []
    points = []
    for row in data:
        try:
            ts = int(row.get("t", 0)) / 1000.0
            if ts <= 0:
                continue
            dt = datetime.fromtimestamp(ts, tz=TZ_BJ)
            date_str = dt.strftime("%Y-%m-%d")
            close_val = float(row.get("c", 0))
            points.append((date_str, close_val))
        except (ValueError, TypeError, OSError):
            continue
    return points


# ============================================================
#  Sector flow
# ============================================================


def search_items(query: str, max_results: int = 10) -> list[ItemData]:
    """Search items by keyword via csQAQ suggest API (GET /search/suggest?text=).

    Old /goods/search_good_id is permanently deprecated (401 even after IP binding).
    suggest returns [{id: str, value: 中文全名}]; price/hash are filled later
    by fetch_item_detail (goods_info)."""
    encoded = urllib.parse.quote(query, safe="")
    resp = _api_get(f"/search/suggest?text={encoded}")
    items_data = resp.get("data")
    if not items_data or not isinstance(items_data, list):
        return []

    results = []
    for sd in items_data[:max_results]:
        item = ItemData()
        item.name = sd.get("value", "")
        item.good_id = _parse_good_id(sd.get("id"))
        results.append(item)
    return results


def get_good_id_by_market_hash(market_hash_name: str) -> int:
    """Resolve a MarketHashName to csQAQ good_id.

    Old /goods/get_good_id is permanently deprecated (401 even after IP binding);
    use /goods/getPriceByMarketHashName (batch hash -> goodId)."""
    resp = _api_post("/goods/getPriceByMarketHashName", {"marketHashNameList": [market_hash_name]})
    data = resp.get("data") or {}
    success = data.get("success") or {}
    hit = success.get(market_hash_name) or {}
    gid = _parse_good_id(hit.get("goodId"))
    if gid:
        return gid
    # fallback: suggest search (Chinese name may still match)
    results = search_items(market_hash_name, max_results=1)
    if results:
        return results[0].good_id
    return 0


# ============================================================
#  Item detail
# ============================================================

def fetch_item_detail(name_or_hash: str | None = None, good_id: int = 0,
                      pw=None, browser=None) -> ItemData | None:
    """Fetch single item detail from csQAQ.
    Accepts either good_id directly, or name/market_hash_name for lookup.
    pw/browser params kept for backward compatibility (ignored)."""
    if not good_id and name_or_hash:
        # try search first
        results = search_items(name_or_hash, max_results=1)
        if results:
            good_id = results[0].good_id
        else:
            good_id = get_good_id_by_market_hash(name_or_hash)

    if not good_id:
        _log.warning("fetch_item_detail: no good_id found")
        return None

    # 1. Get basic detail (old /info/good_detail is permanently deprecated 401;
    #    new /info/good?id= returns data.goods_info with price/volume/order book)
    resp = _api_get(f"/info/good?id={good_id}")
    payload = resp.get("data") or {}
    detail = payload.get("goods_info") or {}
    if not detail:
        return None

    item = ItemData()
    item.good_id = good_id
    item.name = detail.get("name", "")
    item.steam_name = detail.get("market_hash_name", "")
    # Price: prefer buff_sell_price (most liquid market)
    item.price_rmb = _parse_price(
        detail.get("buff_sell_price") or
        detail.get("yyyp_sell_price") or
        detail.get("c5_sell_price") or
        detail.get("steam_sell_price")
    )
    item.volume_total = _parse_int(
        detail.get("buff_sell_num") or
        detail.get("yyyp_sell_num")
    )
    item.volume_day = _parse_int(detail.get("turnover_number"))

    # Build order book from goods_info bid/ask
    ob = OrderBook()
    ob.lowest_sell = _parse_price(detail.get("buff_sell_price"))
    ob.highest_buy = round(_parse_price(detail.get("buff_buy_price")), 2)
    ob.sell_count = item.volume_total
    if ob.lowest_sell > 0 and ob.highest_buy > 0:
        ob.spread_rmb = round(ob.lowest_sell - ob.highest_buy, 2)
        ob.spread_pct = round(ob.spread_rmb / ob.lowest_sell * 100, 1)
    item.order_book = ob

    return item








def _save_debug(name: str, text_lines: list[str]) -> None:
    import re
    safe = re.sub(r'[<>:"/\\\\|?*]', '_', name)[:60]
    path = DATA_DIR / f"_debug_{safe}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\
".join(text_lines[:300]), encoding="utf-8")


def _is_stat_trak(name: str) -> bool:
    return False  # csQAQ search auto-filters


def _guess_sector(weapon: str, skin: str) -> str:
    """Map a weapon/skin to sector category."""
    weapon = (weapon or "").lower()
    skin = (skin or "").lower()
    knife_kw = ["knife", "bayonet", "karambit", "m9", "butterfly", "flip", "gut",
                "huntsman", "falchion", "shadow", "bowie", "nomad", "skeleton",
                "survival", "paracord", "ursus", "stiletto", "talon", "classic", "kukri"]
    if any(w in weapon for w in knife_kw):
        return "匕首"
    glove_kw = ["glove", "driver", "specialist", "sport", "moto", "hand",
                "bloodhound", "hydra", "broken fang"]
    if any(w in weapon for w in glove_kw):
        return "手套"
    if "sticker" in weapon:
        return "印花"
    if "music" in weapon:
        return "音乐盒"
    if "agent" in weapon:
        return "探员"
    if weapon:
        return "步枪/手枪"
    return "其他"
