# -*- coding: utf-8 -*-
"""无注入全池重放 vs 基线 377 一致性核查（2026-08-20，②研究窗口）。
用于判定重建回放库与基线生成时数据是否一致。只读，不改生产。"""
import importlib.util
import json
import multiprocessing as mp
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = os.environ.get("CS_MODEL_DB") or str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

BASELINE = ROOT / "data" / "_exp_cycle_replay_fullpool_2026.json"
_ARCHIVED_RUNNER = ROOT / "references" / "scripts-archive" / "run_item_backtest.py"
HQ_EXCLUDE_MARKERS = ("印花 |", "游击队", "军刀勇士", "特警", "巴西第一营", "海豹部队")
POLLUTED_ITEMS = {"AK-47 | 流金王朝 (崭新出厂)", "挂件 | 丁烷拍档"}

_G = {}


def _load_runner():
    spec = importlib.util.spec_from_file_location("_rib2", str(_ARCHIVED_RUNNER))
    rib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rib)
    return rib


def pool_items():
    conn = sqlite3.connect(os.environ["CS_MODEL_DB"])
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT i.id, i.name FROM items i JOIN price_history p ON p.item_id = i.id GROUP BY i.id""").fetchall()
    conn.close()
    rib = _load_runner()
    return {r["id"]: r["name"] for r in rows
            if r["name"] not in rib.EXCLUDED_ITEMS
            and r["name"] not in POLLUTED_ITEMS
            and not any(m in r["name"] for m in HQ_EXCLUDE_MARKERS)}


def _init_worker(market_ctx):
    _G["market_ctx"] = market_ctx


def _worker(args):
    iid, name, start, end, warmup = args
    rib = _load_runner()
    try:
        return rib.backtest_item(iid, name, start, end, warmup, _G["market_ctx"], cost=0.02)
    except Exception as exc:
        return {"item_id": iid, "name": name, "signals": [], "error": str(exc)}


def main():
    from pipeline.backtest_common import build_market_context
    START, END, WARMUP = "2023-11-17", "2026-08-05", 30
    market_ctx = build_market_context(START, end=END)
    items = pool_items()
    print("pool items:", len(items), flush=True)
    n_workers = min(8, max(2, os.cpu_count() or 4))
    jobs = [(iid, name, START, END, WARMUP) for iid, name in sorted(items.items())]
    with mp.Pool(processes=n_workers, initializer=_init_worker, initargs=(market_ctx,)) as pool:
        results = pool.map(_worker, jobs, chunksize=1)
    sigs = [s for s in (r.get("signals", []) for r in results) for s in s if s.get("net14") is not None]
    base = json.load(open(BASELINE, encoding="utf-8")).get("signals", [])
    base = [s for s in base if s.get("net14") is not None]
    bkeys = {(s["name"], s["date"]) for s in base}
    rkeys = {(s["name"], s["date"]) for s in sigs}
    missing = [k for k in bkeys if k not in rkeys]
    extra = [k for k in rkeys if k not in bkeys]
    print(f"基线 {len(base)} | 无注入重放 {len(sigs)} | 缺失 {len(missing)} | 新增 {len(extra)}")
    from collections import Counter
    print("缺失月份 top:", Counter(k[1][:7] for k in missing).most_common(8))
    print("新增月份 top:", Counter(k[1][:7] for k in extra).most_common(8))
    # 字节漂移（matched 中 net14 变化）
    by_key_r = {(s["name"], s["date"]): s for s in sigs}
    drift = [k for k in bkeys if k in rkeys and by_key_r[k].get("net14") != next(s.get("net14") for s in base if (s["name"], s["date"]) == k)]
    print("matched 中 net14 漂移:", len(drift))


if __name__ == "__main__":
    mp.freeze_support()
    main()
