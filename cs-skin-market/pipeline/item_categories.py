# -*- coding: utf-8 -*-
"""品类识别（M-6, 2026-08-11）：discover 发现空间扩展——无磨损品类（印花/武器箱/挂件/收藏品/胶囊）进发现榜。

skin=枪皮（含磨损词），sticker=印花，case=武器箱，charm=挂件，collection=收藏品，capsule=胶囊，other=其他。
按 csQAQ 命名惯例匹配；角色/特工（无磨损词且非以上品类）归 other，暂不进发现空间。
"""
DISCOVER_CATEGORY_LABELS = {
    "skin": "枪皮", "sticker": "印花", "case": "武器箱", "charm": "挂件",
    "collection": "收藏品", "capsule": "胶囊", "other": "其他",
}


def discover_category(name):
    """按 csQAQ 命名惯例识别品类；unknown/角色归 other。"""
    if not name:
        return "other"
    if name.startswith("印花 |"):
        return "sticker"
    if name.startswith("挂件 |"):
        return "charm"
    if name.endswith("武器箱"):
        return "case"
    if "收藏品" in name:
        return "collection"
    if "胶囊" in name:
        return "capsule"
    if "崭新出厂" in name:
        return "skin"
    return "other"
