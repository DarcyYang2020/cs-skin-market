# -*- coding: utf-8 -*-
"""只读：实盘 fixture 品独特性状态行预览。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import db  # noqa: E402
from webapp.analysis_service import _uniqueness_note  # noqa: E402

c = db.get_conn()
names = [r["name"] for r in c.execute(
    "SELECT name FROM items WHERE good_id>0 AND name LIKE ?", ("%抽象派 1337%",))]
for n in ("AK-47 | 抽象派 1337 (崭新出厂)", "FN57 | 霸意大名 (崭新出厂)"):
    print("==", n)
    for line in _uniqueness_note(n):
        print("  ", line)
c.close()
