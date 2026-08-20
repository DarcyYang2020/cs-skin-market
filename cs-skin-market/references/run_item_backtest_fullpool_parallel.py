# -*- coding: utf-8 -*-
"""全池并行回放（2026-08-19）：replay_cycle_win.db 240 品 × 3 年窗口，多进程加速。

复用 scripts-archive/run_item_backtest.py 的 backtest_item 逻辑，用 multiprocessing.Pool
把 240 品分给多个 worker 并行评估。只读，输出 data/_exp_cycle_replay_fullpool_2026.json。

用法（须系统 python 3.11，含 jinja2/fastapi）:
  CS_ENGINE_PERIOD_ROUTE=1 python references/run_item_backtest_fullpool_parallel.py
"""
import importlib.util
import json
import multiprocessing as mp
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = os.environ.get("CS_MODEL_DB") or str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

_ARCHIVED_RUNNER = ROOT / "references" / "scripts-archive" / "run_item_backtest.py"
OUT = ROOT / "data" / os.environ.get("CS_ENGINE_REPLAY_OUT", "_exp_cycle_replay_fullpool_2026.json")

# 全池除贴纸/角色（DATA-1 后：纳入手套/武器箱/挂件/冷门枪）
HQ_EXCLUDE_MARKERS = ("印花 |", "游击队", "军刀勇士", "特警", "巴西第一营", "海豹部队")
# 污染数据（用户 2026-08-20 裁定）：接口无 3 年历史（流金王朝最早 2025-09-25 / 丁烷拍档 2025-10-09），排除出研究池。
POLLUTED_ITEMS = {"AK-47 | 流金王朝 (崭新出厂)", "挂件 | 丁烷拍档"}

_G = {}


def pool_a_items():
    import sqlite3
    conn = sqlite3.connect(os.environ["CS_MODEL_DB"])
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT i.id, i.name, MIN(p.date) first_date
           FROM items i JOIN price_history p ON p.item_id = i.id
           GROUP BY i.id""").fetchall()
    conn.close()
    # 排除归档脚本的 EXCLUDED_ITEMS + 贴纸/角色标记
    spec = importlib.util.spec_from_file_location("_rib_meta", str(_ARCHIVED_RUNNER))
    rib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rib)
    return {r["id"]: r["name"] for r in rows
            if r["name"] not in rib.EXCLUDED_ITEMS
            and r["name"] not in POLLUTED_ITEMS
            and not any(m in r["name"] for m in HQ_EXCLUDE_MARKERS)}


def _init_worker(market_ctx):
    global _G
    spec = importlib.util.spec_from_file_location("_rib_w", str(_ARCHIVED_RUNNER))
    rib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rib)
    _G["rib"] = rib
    _G["market_ctx"] = market_ctx


def _worker(args):
    iid, name, start, end, warmup = args
    rib = _G["rib"]
    market_ctx = _G["market_ctx"]
    try:
        return rib.backtest_item(iid, name, start, end, warmup, market_ctx, cost=0.02)
    except Exception as exc:  # 单品异常不阻断整池
        return {"item_id": iid, "name": name, "signals": [], "error": str(exc)}


def main():
    START, END, WARMUP = "2023-11-17", "2026-08-05", 30
    from pipeline.backtest_common import build_market_context
    market_ctx = build_market_context(START, end=END)
    print("market ctx dates:", len(market_ctx), flush=True)
    items = pool_a_items()
    print("pool items:", len(items), flush=True)

    n_workers = min(8, max(2, os.cpu_count() or 4))
    print("workers:", n_workers, flush=True)
    t0 = datetime.now()
    jobs = [(iid, name, START, END, WARMUP) for iid, name in sorted(items.items())]

    with mp.Pool(processes=n_workers, initializer=_init_worker, initargs=(market_ctx,)) as pool:
        results = pool.map(_worker, jobs, chunksize=1)

    sigs_out = [s for r in results for s in r.get("signals", []) if s.get("fwd14") is not None]
    misses_out = [m for r in results for m in r.get("proximity_misses", [])]
    errs = [r for r in results if r.get("error")]
    switches = ",".join("%s=1" % k for k in sorted(os.environ) if k.startswith("CS_ENGINE_") and os.environ[k] == "1")

    # 复用归档 summarize 计算 aggregate
    spec = importlib.util.spec_from_file_location("_rib_s", str(_ARCHIVED_RUNNER))
    rib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rib)
    rows, agg = rib.summarize(results)
    agg["signals"] = len(sigs_out)

    out = {"args": {"start": START, "end": END, "warmup": WARMUP,
                    "pool": "全池除贴纸/角色约234品(DATA-1 3年历史,含手套/武器箱/挂件/冷门枪)",
                    "db": os.environ["CS_MODEL_DB"],
                    "engine": "v2-T13 全池并行回放 (period_route + 去量 v2 引擎)",
                    "env_switches": switches or None,
                    "n_workers": n_workers},
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "aggregate": agg, "per_item": rows, "signals": sigs_out,
           "proximity_misses": misses_out, "errors": errs}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("signals:", len(sigs_out), "| errors:", len(errs), "| saved", OUT, flush=True)
    print("by signal_type:", dict(Counter(s.get("signal_type") for s in sigs_out)), flush=True)
    print("elapsed:", str(datetime.now() - t0)[:8], flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    main()
