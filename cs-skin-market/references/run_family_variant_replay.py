# -*- coding: utf-8 -*-
"""候选族「族开回放」研究脚本变体（2026-08-20，②；③裁定 CD：不改 pipeline/）。

复用回放内核（scripts-archive/run_item_backtest.py 的 backtest_item），运行时注入两新族注册表
（bull_steady=①牛市稳态上行 / crash_vol=②急跌高波动），输出独立文件 + delta 清单。

用法（系统 python 3.11，含 jinja2/fastapi）:
  python references/run_family_variant_replay.py --smoke      # 3 品 smoke（字节一致核对）
  python references/run_family_variant_replay.py              # 全池并行族开回放
"""
import importlib.util
import inspect
import json
import math
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
OUT = ROOT / "data" / os.environ.get("CS_ENGINE_FAMVAR_OUT", "_exp_family_variant_replay_2026-08-20.json")
BASELINE = ROOT / "data" / "_exp_cycle_replay_fullpool_2026.json"
HQ_EXCLUDE_MARKERS = ("印花 |", "游击队", "军刀勇士", "特警", "巴西第一营", "海豹部队")
POLLUTED_ITEMS = {"AK-47 | 流金王朝 (崭新出厂)", "挂件 | 丁烷拍档"}

_MCHG7 = None


def _build_mchg7():
    conn = sqlite3.connect(os.environ["CS_MODEL_DB"])
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT date, value FROM market_index ORDER BY date").fetchall()
    conn.close()
    dates = [r["date"] for r in rows]
    vals = [r["value"] for r in rows]
    out = {}
    for i in range(len(vals)):
        if i >= 7 and vals[i - 7] and vals[i - 7] > 0:
            out[dates[i]] = (vals[i] / vals[i - 7] - 1) * 100
    return out


def _vol_pct(prices, k):
    if not prices or len(prices) < k + 1:
        return None
    rets = [(prices[j] - prices[j - 1]) / prices[j - 1]
            for j in range(len(prices) - k, len(prices)) if prices[j - 1] and prices[j - 1] > 0]
    if len(rets) < k:
        return None
    m = sum(rets) / len(rets)
    sd = (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5
    return sd * (252 ** 0.5) * 100


def _trigger_bull(F):
    v30 = _vol_pct(F["prices"], 30)
    m7 = _MCHG7.get(F.get("signal_date"))
    d21 = F.get("drop21")
    return (v30 is not None and v30 <= 79.4
            and m7 is not None and -7.3 < m7 <= 4.1
            and d21 is not None and d21 > 3.7)


def _trigger_crash(F):
    v30 = _vol_pct(F["prices"], 30)
    v7 = _vol_pct(F["prices"], 7)
    m7 = _MCHG7.get(F.get("signal_date"))
    d21 = F.get("drop21")
    return (v30 is not None and v30 > 79.4
            and v7 is not None and v7 > 421.2
            and m7 is not None and m7 <= -7.3
            and d21 is not None and d21 > -48.4)


def inject(mchg7):
    global _MCHG7
    _MCHG7 = mchg7
    f1 = ia.SignalFamily(key="bull_steady", label="🟢 牛市稳态上行·分批建仓",
                         priority=22, limit=0.12, trigger=_trigger_bull)
    f2 = ia.SignalFamily(key="crash_vol", label="🟢 急跌高波动·分批建仓",
                         priority=20, limit=0.10, trigger=_trigger_crash)
    # 三处派生结构必须同步重建（③点名"tuple/派生列表漏 patch"）
    ia.SIGNAL_FAMILIES = tuple(ia.SIGNAL_FAMILIES) + (f1, f2)
    ia.SIGNAL_FAMILY_BY_KEY = {fam.key: fam for fam in ia.SIGNAL_FAMILIES}
    ia._POST_FAMILIES = tuple(sorted(
        (fam for fam in ia.SIGNAL_FAMILIES if fam.key != "panic_resonance"),
        key=lambda f: -f.priority))
    ia.DEDUP_PRIO_BY_LABEL["牛市稳态上行"] = 22
    ia.DEDUP_PRIO_BY_LABEL["急跌高波动"] = 20
    # 买涨腿硬编码循环：尾加 bull_steady（① 从 hold/reduce 段升级）
    src = inspect.getsource(ia.decide_fusion_signal)
    old = '("rise_accum", "rise_contract", "volatile_accum", "rs_accum", "ct_accum")'
    new = '("rise_accum", "rise_contract", "volatile_accum", "rs_accum", "ct_accum", "bull_steady")'
    assert old in src, "买涨腿 loop 未找到，patch 失败"
    exec(src.replace(old, new), ia.__dict__)


def _load_runner():
    spec = importlib.util.spec_from_file_location("_famvar_rib", str(_ARCHIVED_RUNNER))
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


def _load_baseline_by_name():
    d = json.load(open(BASELINE, encoding="utf-8"))
    out = {}
    for s in d.get("signals", []):
        out.setdefault(s["name"], []).append(s)
    return out


def smoke():
    from pipeline.backtest_common import build_market_context
    mchg7 = _build_mchg7()
    inject(mchg7)
    market_ctx = build_market_context("2023-11-17", end="2026-08-05")
    rib = _load_runner()
    baseline = _load_baseline_by_name()
    items = pool_items()
    # 选 3 品：A=有历史信号最多；B/C=分别落①/②区域的品
    sig_counts = Counter(s["name"] for s in json.load(open(BASELINE, encoding="utf-8")).get("signals", []))
    cands = sorted(items.items(), key=lambda kv: -sig_counts.get(kv[1], 0))
    smoke_names = [n for _, n in cands[:2]]
    # 补一个高波动品（② 区域）：用 2025-10 附近大跌的品
    smoke_names.append("AWP | 二西莫夫 (久经沙场)")
    smoke_names = [n for n in smoke_names if n in items.values()]
    smoke_items = {iid: n for iid, n in items.items() if n in smoke_names}
    print("smoke 品:", list(smoke_items.values()), flush=True)

    total_new = {"bull_steady": 0, "crash_vol": 0}
    all_ok = True
    for iid, name in sorted(smoke_items.items()):
        r = rib.backtest_item(iid, name, "2023-11-17", "2026-08-05", 30, market_ctx, cost=0.02)
        sigs = [s for s in r.get("signals", []) if s.get("fwd14") is not None]
        new = [s for s in sigs if s.get("action_label", "").startswith("🟢 牛市稳态上行") or s.get("action_label", "").startswith("🟢 急跌高波动")]
        old_sigs = [s for s in sigs if s not in new]
        base = baseline.get(name, [])
        # 字节一致：既有信号 (date, action_label, net14) 与基线逐条一致
        base_keys = sorted((s["date"], s["action_label"], s.get("net14")) for s in base if s.get("fwd14") is not None)
        old_keys = sorted((s["date"], s["action_label"], s.get("net14")) for s in old_sigs)
        ident = base_keys == old_keys
        all_ok &= ident
        print(f"\n== {name} ==")
        print(f"  基线信号 {len(base_keys)} 条 / 族开既有信号 {len(old_keys)} 条 / 字节一致={ident}")
        print(f"  新族信号 {len(new)} 条：{Counter(s['action_label'] for s in new)}")
        for s in new:
            total_new["bull_steady" if "牛市稳态" in s["action_label"] else "crash_vol"] += 1
            print(f"    {s['date']}  {s['action_label'][:20]}  net14={s.get('net14')}")
    print("\n=== smoke 汇总 ===")
    print("既有信号字节一致:", "PASS" if all_ok else "FAIL")
    print("新族信号数:", total_new)
    return all_ok


_G = {}


def _init_worker(market_ctx, mchg7):
    global _G
    inject(mchg7)
    _G["market_ctx"] = market_ctx


def _worker(args):
    iid, name, start, end, warmup = args
    rib = _load_runner()
    market_ctx = _G["market_ctx"]
    try:
        return rib.backtest_item(iid, name, start, end, warmup, market_ctx, cost=0.02)
    except Exception as exc:
        return {"item_id": iid, "name": name, "signals": [], "error": str(exc)}


def full():
    from pipeline.backtest_common import build_market_context
    mchg7 = _build_mchg7()
    START, END, WARMUP = "2023-11-17", "2026-08-05", 30
    market_ctx = build_market_context(START, end=END)
    items = pool_items()
    print("pool items:", len(items), flush=True)
    n_workers = min(8, max(2, os.cpu_count() or 4))
    jobs = [(iid, name, START, END, WARMUP) for iid, name in sorted(items.items())]

    with mp.Pool(processes=n_workers, initializer=_init_worker, initargs=(market_ctx, mchg7)) as pool:
        results = pool.map(_worker, jobs, chunksize=1)

    sigs_out = [s for r in results for s in r.get("signals", []) if s.get("fwd14") is not None]
    errs = [r for r in results if r.get("error")]
    out = {
        "args": {"start": START, "end": END, "warmup": WARMUP,
                 "pool": "全池除贴纸/角色/污染（族开变体：bull_steady + crash_vol）",
                 "engine": "v2-T13 + 两候选族注入（研究脚本变体，不改 pipeline/）",
                 "db": os.environ["CS_MODEL_DB"]},
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "signals": sigs_out, "errors": errs,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    new = [s for s in sigs_out if s.get("action_label", "").startswith("🟢 牛市稳态上行") or s.get("action_label", "").startswith("🟢 急跌高波动")]
    print("total signals:", len(sigs_out), "| new-family:", len(new), "| errors:", len(errs), "| saved", OUT)
    print("new by month:", dict(sorted(Counter(s["date"][:7] for s in new).items())))
    print("new by family:", dict(Counter(s["action_label"] for s in new)))


if __name__ == "__main__":
    mp.freeze_support()
    if "--smoke" in sys.argv:
        smoke()
    else:
        full()
