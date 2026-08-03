# -*- coding: utf-8 -*-
"""验证 day=365 覆盖质量 (临时, 2026-08-03)"""
import asyncio, sys
from collections import Counter
sys.path.insert(0, '.')
import httpx
from pipeline import db
from pipeline.collector_youpin import _api_headers

async def probe(tid, name):
    url = "https://pc-api.youpin898.com/api/youpin/price/trend/data"
    body = {"filterTemplateTypeNames": [], "templateId": str(tid), "orderType": "1",
            "day": "365", "templateTypeName": "", "customizeDay": False}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=body, headers=_api_headers())
        payload = resp.json()
    if payload.get("code") != 0:
        print(f"{name}: code={payload.get('code')} {payload.get('msg')}")
        return
    rows = (payload.get("data") or {}).get("tradeDataList") or []
    recs = []
    for r in rows:
        d = str(r.get("localDate") or "")
        try:
            p = float(r.get("price"))
        except (TypeError, ValueError):
            continue
        if d and p > 0:
            recs.append((d, p))
    dates = [d for d, _ in recs]
    print(f"\n{name} (template={tid}): {len(recs)} 条 | {min(dates)} ~ {max(dates)}")
    # 按月分布
    mon = Counter(d[:7] for d in dates)
    print('  按月条数:', dict(sorted(mon.items())))
    # 间隔检查
    from datetime import datetime, timedelta
    ds = sorted(set(dates))
    gaps = []
    for i in range(1, len(ds)):
        gap = (datetime.strptime(ds[i], '%Y-%m-%d') - datetime.strptime(ds[i-1], '%Y-%m-%d')).days
        if gap > 3:
            gaps.append((ds[i-1], ds[i], gap))
    print(f'  唯一日期 {len(ds)} 天, 间隔>3天的缺口 {len(gaps)} 个')
    for g in gaps[:10]:
        print(f'    {g[0]} -> {g[1]} (缺{g[2]}天)')
    # 1/15-2/10 窗口覆盖
    win = [d for d in ds if '2026-01-15' <= d <= '2026-02-10']
    print(f'  2026-01-15~02-10 覆盖天数: {len(win)}')

async def main():
    conn = db.get_conn()
    rows = conn.execute("SELECT yyyp_id, name FROM items WHERE yyyp_id > 0 ORDER BY id LIMIT 3").fetchall()
    conn.close()
    for tid, nm in rows:
        await probe(tid, nm)

asyncio.run(main())