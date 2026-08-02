# -*- coding: utf-8 -*-
"""修复 5 个模板错配品的 K 线：重新抓取 platform=2(悠悠) K线覆盖库内 Buff/C5 fallback 错价。"""
import sys, io, asyncio, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import collector_csqaq, collector_youpin, db

TARGETS = [
    (111,  'AK-47 | 霓虹革命 (崭新出厂)'),
    (1332, 'M4A4 | 地狱烈焰 (崭新出厂)'),
    (14758,'MP9 | 星使 (崭新出厂)'),
    (590,  '沙漠之鹰 | 纳迦蛇神 (崭新出厂)'),
    (144,  'AK-47 | 皇后 (崭新出厂)'),
]

async def fix_one(gid, name):
    item = await collector_csqaq.fetch_item_detail(gid)
    if not item:
        return f"FAIL {name}: no detail"
    bars, _ = await collector_csqaq.fetch_kline_90d(gid)
    if not bars:
        return f"FAIL {name}: no kline"
    vol_map = {}
    if item.yyyp_id:
        vol_map = await collector_youpin.fetch_youpin_volume(item.yyyp_id)
    for b in bars:
        d = getattr(b, "date", "")
        v = vol_map.get(d, 0)
        b.volume = int(v) if v and v > 0 else 0
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT id FROM items WHERE name=?", (name,)).fetchone()
        if not row:
            return f"FAIL {name}: item not in db"
        db.save_price_history_batch(conn, row["id"], bars)
        conn.commit()
    finally:
        conn.close()
    closes = [b.close for b in bars if b.close > 0]
    first, last = bars[0].date, bars[-1].date
    lo, hi = (min(closes), max(closes)) if closes else (0, 0)
    print(f"OK {name}: yyyp={item.yyyp_id} DOM价={item.price_rmb} bars={len(bars)} [{first}~{last}] range={lo}~{hi} vol_days={sum(1 for b in bars if b.volume>0)}")

async def main():
    for gid, name in TARGETS:
        try:
            print(await fix_one(gid, name))
        except Exception as e:
            print(f"ERR {name}: {e}")

asyncio.run(main())
