# -*- coding: utf-8 -*-
"""悠悠有品 (youpin898.com) 单品日成交量采集器（纯 HTTP，秒级）。

使用悠悠有品 PC 站趋势接口获取单品近 90 日逐笔成交记录，
按 localDate 聚合为 {date: 日成交量}，作为 K 线真实成交量来源
（csQAQ chart API 无真实成交量，SteamDT 已弃用）。

认证：data/uu_headers.json（用户浏览器登录态，约 10 天有效，不入库）。
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

import httpx

_log = logging.getLogger(__name__)

API_URL = "https://pc-api.youpin898.com/api/youpin/price/trend/data"
HEADERS_PATH = Path(__file__).resolve().parent.parent / "data" / "uu_headers.json"

_headers_cache: dict | None = None
# 84101 登录失效熔断：当天不再重复请求（软过期回退由调用方处理）
_auth_failed_date: str = ""


def _api_headers() -> dict:
    """读取悠悠有品登录态 headers（data/uu_headers.json）。"""
    global _headers_cache
    if _headers_cache:
        return _headers_cache
    if not HEADERS_PATH.exists():
        _log.warning("悠悠认证文件 uu_headers.json 不存在，成交量接口不可用")
        return {}
    try:
        with open(HEADERS_PATH, "r", encoding="utf-8") as _f:
            _headers_cache = json.load(_f)
        return _headers_cache
    except Exception as _e:
        _log.warning(f"uu_headers.json 解析失败: {_e}")
        return {}


async def fetch_youpin_volume(template_id: str, days: int = 90) -> dict[str, int]:
    """获取悠悠有品单品近 days 日成交量。

    Args:
        template_id: 悠悠模板 ID（csqaq goods_info.yyyp_id）。
        days: 拉取天数，支持 7/30/90/180。

    Returns:
        {date(YYYY-MM-DD): 当日成交量}；失败或未认证返回 {}。
    """
    global _auth_failed_date
    headers = _api_headers()
    template_id = str(template_id or "")
    if not headers or not template_id:
        return {}
    from datetime import datetime, timezone, timedelta
    _today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    if _auth_failed_date == _today:
        return {}  # 登录已失效，当天熔断，避免重复请求
    body = {
        "filterTemplateTypeNames": [],
        "templateId": template_id,
        "orderType": "1",
        "day": str(days),
        "templateTypeName": "",
        "customizeDay": False,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(API_URL, json=body, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        if payload.get("code") != 0:
            if payload.get("code") == 84101:
                _auth_failed_date = _today
                _log.warning(f"悠悠登录态失效(code=84101)，当天熔断，改用历史缓存+Steam兜底: {payload.get('msg')}")
            else:
                _log.warning(f"悠悠成交量接口返回 code={payload.get('code')} msg={payload.get('msg')}")
            return {}
        rows = (payload.get("data") or {}).get("tradeDataList") or []
        if not rows:
            return {}
        counts = Counter(str(row.get("localDate") or "") for row in rows)
        result = {date: int(cnt) for date, cnt in counts.items() if date}
        _log.info(f"悠悠成交量: template={template_id} 覆盖天数={len(result)} 总笔数={len(rows)}")
        return result
    except Exception as _e:
        _log.warning(f"悠悠成交量获取失败 template={template_id}: {_e}")
        return {}
