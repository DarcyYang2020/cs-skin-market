# -*- coding: utf-8 -*-
"""重试失败项：名称变体 + K线重试。"""
import sys, io, asyncio, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_sample_items import collect_one

RETRY = [
    ("反恐精英箱", "AK-47 | 表面淬火 (崭新出厂)", ["AK-47 表面淬火 (崭新出厂)"]),
]

async def main():
    for i, (case, display, queries) in enumerate(RETRY, 1):
        print(f"[retry {i}/{len(RETRY)}] {case}: {display}")
        lines = []
        await collect_one(case, display, queries, lines)
        for l in lines:
            print(l)

asyncio.run(main())