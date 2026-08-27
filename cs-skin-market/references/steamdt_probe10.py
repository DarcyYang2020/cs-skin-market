# -*- coding: utf-8 -*-
"""W7-2 steamdt.com 预研探针 10：open.steamdt.com 开放 API 端点探测（2026-08-27）。只读，不带 Key 只判 401/404。"""
import urllib.request, urllib.error, json

BASE = "https://open.steamdt.com/open/cs2/v1"
candidates = [
    "/index", "/market-index", "/index/statistics", "/statistics",
    "/market", "/deals", "/trade", "/turnover",
    "/players", "/online", "/online-users",
    "/skin", "/item", "/skin/{id}", "/price",
    "/kline", "/history", "/block", "/folder",
    "/wear", "/list", "/search",
]
print("=== open.steamdt.com 端点探测（无 Key，401=存在需认证 / 404=不存在）===")
for c in candidates:
    url = BASE + c
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            body = r.read(150).decode("utf-8", errors="replace")
            print(f"  [HTTP {r.status}] {c} -> {body[:90]}")
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] {c} -> {e.read(120).decode('utf-8', errors='replace')[:80]}")
    except Exception as e:
        print(f"  [ERR] {c} -> {str(e)[:60]}")
