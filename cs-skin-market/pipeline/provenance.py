# -*- coding: utf-8 -*-
"""D4 派生级血缘台账（2026-08-27）。

派生层重建时 append 一行 JSON 到 data/provenance.jsonl（键 = ts/script/inputs/params/version）。
rebuild_derived 每次重建自动调用本模块；台账格式固定、可机器读。
"""
import json
import os
from datetime import datetime

from .config import DATA_DIR, TZ_BJ

PROVENANCE_PATH = os.path.join(str(DATA_DIR), "provenance.jsonl")


def append(script, inputs, params=None, version=None, ts=None):
    """追加一条血缘记录，返回完整记录 dict（含 ts）。"""
    rec = {
        "ts": ts or datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "script": script,
        "inputs": inputs,
        "params": params or {},
        "version": version,
    }
    try:
        with open(PROVENANCE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec
