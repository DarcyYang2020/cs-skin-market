# -*- coding: utf-8 -*-
import asyncio, sys
sys.path.insert(0, '.')
import httpx
from pipeline import db
from pipeline.collector_youpin import _api_headers

async def probe():
    conn = db.get_conn()
    row = conn.execute("SELECT yyyp_id FROM items WHERE yyyp_id > 0 LIMIT 1").fetchone()
    conn.close()
    tid = row[0]
    url = "https://pc-api.youpin898.com/api/youpin/price/trend/data"
    body = {"filterTemplateTypeNames": [], "templateId": str(tid), "orderType": "1",
            "day": "365", "templateTypeName": "", "customizeDay": False}
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, json=body, headers=_api_headers())
                payload = resp.json()
            if payload.get("code") != 0:
                print(f"第{attempt+1}次: code={payload.get('code')} msg={payload.get('msg')}")
                continue
            rows = (payload.get("data") or {}).get("tradeDataList") or []
            dates = [str(r.get("localDate") or "") for r in rows if r.get("localDate")]
            print(f"第{attempt+1}次: {len(rows)} 条 | {min(dates)} ~ {max(dates)}")
            return
        except Exception as e:
            print(f"第{attempt+1}次: ERROR {e}")
        await asyncio.sleep(2)

asyncio.run(probe())