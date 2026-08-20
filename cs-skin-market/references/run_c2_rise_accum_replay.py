# -*- coding: utf-8 -*-
"""C2-RISE-ACCUM 族变体回放研究脚本（2026-08-20，②；CL 卡执行，仅研究不落地）。

复用回放内核（scripts-archive/run_item_backtest.py 的 backtest_item），运行时**替换**
rise_accum 的 trigger（chg7>3 → chg7>10，其余条件一律不动），输出独立文件 + delta 清单。

用法（系统 python 3.11，含 jinja2/fastapi）:
  python references/run_c2_rise_accum_replay.py --smoke   # 3 品 smoke（字节一致核对）
  python references/run_c2_rise_accum_replay.py            # 全池并行回放
"""
import importlib.util
import json
import multiprocessing as mp
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["CS_MODEL_DB"] = os.environ.get("CS_MODEL_DB") or str(ROOT / "data" / "replay_cycle_win.db")
sys.path.insert(0, str(ROOT))

import pipeline.item_analysis as ia  # noqa: E402

_ARCHIVED_RUNNER = ROOT / "references" / "scripts-archive" / "run_item_backtest.py"
OUT = ROOT / "data" / os.environ.get("CS_ENGINE_C2_OUT", "_exp_c2_rise_accum_replay_2026-08-20.json")
BASELINE = ROOT / "data" / "_exp_cycle_replay_fullpool_2026.json"
HQ_EXCLUDE_MARKERS = ("印花 |", "游击队", "军刀勇士", "特警", "巴西第一营", "海豹部队")
POLLUTED_ITEMS = {"AK-47 | 流金王朝 (崭新出厂)", "挂件 | 丁烷拍档"}

RISE_KEY = "rise_accum"
RISE_MARK = "吸筹型上涨"


def _trigger_rise_accum_c2(F):
    """C2 变体 trigger：与基线 rise_accum 完全一致，仅 chg7 下限 3→10。"""
    return (
        os.environ.get("CS_ENGINE_RISE_ACCUM", "1") == "1"
        and len(F["supply_hist"]) >= 60 and len(F["prices"]) >= 8
        and not (F["survive"] > 0 and F["survive"] < 3000)
        and F["s30"] is not None and F["s30"] > 0
        and F["s7"] is not None and F["s7"] <= F["s30"] * 0.85
        and F["chg7"] is not None and F["chg7"] > 10  # C2: 3 → 10
        and (ia._rise_chg7_cap() <= 0 or F["chg7"] <= ia._rise_chg7_cap())
        and (float(os.environ.get("CS_ENGINE_RISE_TH_MIN", "55")) <= 0
             or F["market_th"] is not None and F["market_th"] >= float(os.environ.get("CS_ENGINE_RISE_TH_MIN", "55")))
        and F["supply_change_30d"] is not None and F["supply_change_30d"] > 5
        and not ia._dedup_gate(F, 28)  # rise_accum
    )


def inject():
    """运行时替换 rise_accum trigger（SignalFamily 为普通 dataclass，改属性即时生效，
    SIGNAL_FAMILIES / BY_KEY / _POST_FAMILIES 引用同一对象，无需重建——③点名 tuple 漏 patch 在此模式天然免疫）。"""
    fam = ia.SIGNAL_FAMILY_BY_KEY[RISE_KEY]
    assert "吸筹型上涨" in fam.label, f"rise_accum label 异常: {fam.label}"
    fam.trigger = _trigger_rise_accum_c2
    print(f"inject OK: rise_accum trigger chg7>3 -> chg7>10 (label={fam.label}, prio={fam.priority}, limit={fam.limit})", flush=True)


def _load_runner():
    spec = importlib.util.spec_from_file_location("_c2_rib", str(_ARCHIVED_RUNNER))
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


def _load_baseline():
    d = json.load(open(BASELINE, encoding="utf-8"))
    return [s for s in d.get("signals", []) if s["name"] not in POLLUTED_ITEMS]


def is_rise(s):
    return RISE_MARK in s.get("action_label", "")


def _byte_identity(name, old_sigs, base_sigs):
    """既有（非 rise_accum）信号 (date, action_label, net14) 与基线逐条一致。"""
    base_keys = sorted((s["date"], s["action_label"], s.get("net14"))
                       for s in base_sigs if s.get("fwd14") is not None and not is_rise(s))
    old_keys = sorted((s["date"], s["action_label"], s.get("net14"))
                      for s in old_sigs if s.get("fwd14") is not None and not is_rise(s))
    return base_keys == old_keys, len(base_keys), len(old_keys)


def _smoke_init():
    global _G
    inject()
    from pipeline.backtest_common import build_market_context
    _G["market_ctx"] = build_market_context("2023-11-17", end="2026-08-05")


def _smoke_one(args):
    """单进程跑一个品（Pool worker 隔离，规避单进程多品状态性崩溃——既有问题）。"""
    iid, name = args
    rib = _load_runner()
    r = rib.backtest_item(iid, name, "2023-11-17", "2026-08-05", 30, _G["market_ctx"], cost=0.02)
    return name, [s for s in r.get("signals", []) if s.get("fwd14") is not None]


def smoke():
    items = pool_items()
    baseline = _load_baseline()
    base_by_name = {}
    for s in baseline:
        base_by_name.setdefault(s["name"], []).append(s)
    # 3 品：A=rise_accum 信号最多（含被砍段）；B=含被砍段；C=无 rise_accum 的对照（字节一致）
    ra_counts = Counter(s["name"] for s in baseline if is_rise(s))
    names = [n for n, _ in ra_counts.most_common(2)]
    names.append("沙漠之鹰 | 后发制人 (崭新出厂)")
    names = [n for n in names if n in items.values()]
    smoke_items = [(iid, n) for iid, n in items.items() if n in names]
    print("smoke 品:", [n for _, n in smoke_items], flush=True)

    with mp.Pool(processes=len(smoke_items), initializer=_smoke_init) as pool:
        results = pool.map(_smoke_one, smoke_items)

    all_ok = True
    ra_before = ra_after = 0
    for name, sigs in sorted(results):
        new_ra = [s for s in sigs if is_rise(s)]
        old_sigs = [s for s in sigs if not is_rise(s)]
        base = base_by_name.get(name, [])
        base_ra = [s for s in base if is_rise(s)]
        ident, nb, no = _byte_identity(name, old_sigs, base)
        all_ok &= ident
        ra_before += len(base_ra)
        ra_after += len(new_ra)
        print(f"\n== {name} ==")
        print(f"  基线非RA {nb} / 变体非RA {no} / 字节一致={ident}")
        print(f"  rise_accum: 基线 {len(base_ra)} -> 变体 {len(new_ra)}")
        base_dates = {s["date"] for s in base_ra}
        new_dates = {s["date"] for s in new_ra}
        print(f"  被砍日期: {sorted(base_dates - new_dates)}")
    print("\n=== smoke 汇总 ===")
    print("非 rise_accum 字节一致:", "PASS" if all_ok else "FAIL")
    print(f"rise_accum 基线 {ra_before} -> 变体 {ra_after}")
    return all_ok


_G = {}


def _init_worker():
    global _G
    inject()
    from pipeline.backtest_common import build_market_context
    _G["market_ctx"] = build_market_context("2023-11-17", end="2026-08-05")


def _worker(args):
    iid, name, start, end, warmup = args
    rib = _load_runner()
    market_ctx = _G["market_ctx"]
    try:
        return rib.backtest_item(iid, name, start, end, warmup, market_ctx, cost=0.02)
    except Exception as exc:
        return {"item_id": iid, "name": name, "signals": [], "error": str(exc)}


def full():
    inject()
    START, END, WARMUP = "2023-11-17", "2026-08-05", 30
    items = pool_items()
    print("pool items:", len(items), flush=True)
    n_workers = min(8, max(2, os.cpu_count() or 4))
    jobs = [(iid, name, START, END, WARMUP) for iid, name in sorted(items.items())]

    with mp.Pool(processes=n_workers, initializer=_init_worker) as pool:
        results = pool.map(_worker, jobs, chunksize=1)

    sigs_out = [s for r in results for s in r.get("signals", []) if s.get("fwd14") is not None]
    errs = [r for r in results if r.get("error")]
    out = {
        "args": {"start": START, "end": END, "warmup": WARMUP,
                 "pool": "全池除贴纸/角色/污染（C2 变体：rise_accum chg7>3→>10 替换 trigger）",
                 "engine": "v2-T13 + C2 trigger 替换（研究脚本变体，不改 pipeline/）",
                 "db": os.environ["CS_MODEL_DB"]},
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "signals": sigs_out, "errors": errs,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    ra = [s for s in sigs_out if is_rise(s)]
    print("total signals:", len(sigs_out), "| rise_accum:", len(ra), "| errors:", len(errs), "| saved", OUT)
    print("rise_accum 按月:", dict(sorted(Counter(s["date"][:7] for s in ra).items())))


if __name__ == "__main__":
    mp.freeze_support()
    if "--smoke" in sys.argv:
        smoke()
    else:
        full()
