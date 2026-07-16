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
from dataclasses import dataclass, field, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .config import CSQAQ_BASE, API_TOKEN, API_RATE_LIMIT, DATA_DIR
from .logutil import get_logger
_log = get_logger()

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

def fetch_market_index() -> MarketIndex | None:
    """Fetch CS composite index via csQAQ current_data API."""
    resp = _api_get("/current_data?type=init")
    data = resp.get("data")
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
        # mood from greedy data
        greedy = data.get("greedy_status", {})
        label = greedy.get("label", "")
        level = greedy.get("level", "")
        if "恐惧" in str(label):
            result.mood = "cold"
        elif "贪婪" in str(label):
            result.mood = "hot"
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
    Returns list of (date_str, value) tuples (close price)."""
    resp = _api_get("/sub/kline?id=1&type=1day")
    data = resp.get("data")
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

def fetch_sector_flow() -> list[SectorFlow]:
    """Fetch sector/type flow data from csQAQ current_data."""
    resp = _api_get("/current_data?type=init")
    data = resp.get("data")
    if not data:
        return []

    sectors = []
    type_data = data.get("chg_type_data", [])
    for i, td in enumerate(type_data):
        sf = SectorFlow()
        sf.name = td.get("name", "")
        sf.change_pct = float(td.get("price_diff_1", 0))
        sf.rank = i + 1
        # determine momentum
        diff_7 = float(td.get("price_diff_7", 0))
        if diff_7 > 3:
            sf.momentum = "hot"
        elif diff_7 > 0:
            sf.momentum = "warm"
        elif diff_7 > -3:
            sf.momentum = "cool"
        else:
            sf.momentum = "cold"
        sectors.append(sf)

    # Sort by 1-day change descending
    sectors.sort(key=lambda s: s.change_pct, reverse=True)
    for i, s in enumerate(sectors):
        s.rank = i + 1
    return sectors


# ============================================================
#  Item search
# ============================================================

def search_items(query: str, max_results: int = 10) -> list[ItemData]:
    """Search items by keyword via csQAQ autocomplete API."""
    encoded = urllib.parse.quote(query, safe="")
    resp = _api_get(f"/goods/search_good_id?keyword={encoded}")
    items_data = resp.get("data")
    if not items_data:
        return []

    results = []
    for sd in items_data[:max_results]:
        item = ItemData()
        item.name = sd.get("name", "")
        item.steam_name = sd.get("market_hash_name", "")
        item.good_id = _parse_good_id(sd.get("id"))
        item.price_rmb = _parse_price(sd.get("price", sd.get("buff_sell_price")))
        results.append(item)
    return results


def get_good_id_by_market_hash(market_hash_name: str) -> int:
    """Resolve a MarketHashName to csQAQ good_id."""
    resp = _api_post("/goods/get_good_id", {"market_hash_name": market_hash_name})
    data = resp.get("data")
    if data and isinstance(data, dict):
        return _parse_good_id(data.get("id"))
    # fallback: search
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

    # 1. Get basic detail
    resp = _api_get(f"/info/good_detail?good_id={good_id}")
    detail = resp.get("data")
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

    # 2. Get chart data for volume and order book
    chart_resp = _api_post("/info/chart", {
        "good_id": good_id,
        "key": "sell_num",
        "platform": 1,  # BUFF
    })
    chart_data = chart_resp.get("data", [])
    if chart_data and isinstance(chart_data, list):
        # Last point is current
        last = chart_data[-1]
        if isinstance(last, list) and len(last) >= 2:
            item.volume_total = _parse_int(last[1])

    # Get buy price for order book
    buy_resp = _api_post("/info/chart", {
        "good_id": good_id,
        "key": "buy_price",
        "platform": 1,
    })
    buy_data = buy_resp.get("data", [])
    highest_buy = 0.0
    if buy_data and isinstance(buy_data, list):
        last_buy = buy_data[-1]
        if isinstance(last_buy, list) and len(last_buy) >= 2:
            highest_buy = _parse_price(last_buy[1])

    # Get turnover for volume_day
    vol_resp = _api_post("/info/chart", {
        "good_id": good_id,
        "key": "turnover_number",
        "platform": 3,  # Steam
    })
    vol_data = vol_resp.get("data", [])
    if vol_data and isinstance(vol_data, list):
        last_vol = vol_data[-1]
        if isinstance(last_vol, list) and len(last_vol) >= 2:
            item.volume_day = _parse_int(last_vol[1])

    # Build order book
    ob = OrderBook()
    ob.lowest_sell = item.price_rmb
    ob.highest_buy = round(highest_buy, 2)
    ob.sell_count = item.volume_total
    if ob.lowest_sell > 0 and ob.highest_buy > 0:
        ob.spread_rmb = round(ob.lowest_sell - ob.highest_buy, 2)
        ob.spread_pct = round(ob.spread_rmb / ob.lowest_sell * 100, 1)
    item.order_book = ob

    return item


def fetch_item_detail_by_id(good_id: int) -> ItemData | None:
    """Fetch item detail directly by csQAQ good_id."""
    return fetch_item_detail(good_id=good_id)


# ============================================================
#  K-line data
# ============================================================

def fetch_kline(good_id: int, days: int = 30, platform: int = 1) -> list[dict]:
    """Fetch K-line data for a single item.
    Returns list of {timestamp, price, in_sale, volume, tx_amount, tx_count, survive_num}"""
    resp = _api_post("/info/kline", {
        "good_id": good_id,
        "day": days,
        "platform": platform,
    })
    data = resp.get("data")
    if not data or not isinstance(data, list):
        return []

    points = []
    for row in data:
        if isinstance(row, list) and len(row) >= 5:
            try:
                points.append({
                    "timestamp": int(row[0]) if row[0] is not None else 0,
                    "price": _parse_price(row[1]),
                    "in_sale": _parse_int(row[2]) if len(row) > 2 else 0,
                    "volume": _parse_int(row[3]) if len(row) > 3 else 0,
                    "tx_amount": _parse_price(row[4]) if len(row) > 4 else 0,
                    "tx_count": _parse_int(row[5]) if len(row) > 5 else 0,
                    "survive_num": _parse_int(row[6]) if len(row) > 6 else 0,
                })
            except (ValueError, TypeError):
                continue
    return points


def fetch_survive(good_id: int) -> list:
    """Fetch survive count history (180 days)."""
    resp = _api_get(f"/info/survive?good_id={good_id}")
    data = resp.get("data")
    if not data or not isinstance(data, list):
        return []
    return data


# ============================================================
#  Batch helpers (for watchlist scan)
# ============================================================

def fetch_multi_prices(market_hash_names: list[str]) -> dict:
    """Batch fetch prices for multiple items by marketHashName."""
    if not market_hash_names:
        return {}
    # Limit batch size to avoid timeouts
    resp = _api_post("/goods/get_multi_sell_info", {
        "market_hash_names": market_hash_names[:50],
    })
    data = resp.get("data")
    if not data:
        return {}
    if isinstance(data, list):
        return {d.get("market_hash_name", ""): d for d in data}
    return {}


# ============================================================
#  Legacy compatibility stubs (no-op, kept for old callers)
# ============================================================

# csqaq Playwright collector (for 90-day K-line and item detail)
try:
    from .collector_csqaq import (
        search_good_id,
        fetch_item_detail as fetch_item_detail_csqaq,
        fetch_kline_90d,
    )
except ImportError:
    pass


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
