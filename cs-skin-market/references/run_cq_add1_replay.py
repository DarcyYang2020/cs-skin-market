# -*- coding: utf-8 -*-
"""CQ-ADD-1「牛市上行段高选择性窄化」候选族开回放研究脚本（2026-08-20，②研究窗口，CU 立项）。

复用回放内核（scripts-archive/run_item_backtest.py 的 backtest_item），运行时注入新族注册表
（cq_add1=🟢 牛市上行·高选择性窄化：大盘上行 drop21(3.7,15] ∩ 供给收缩 sc30<=-5 ∩
低波动 vol30<=50 ∩ 大盘7日动量 mchg7>4），输出独立文件 + 供 delta 清单/四关使用。

判据预注册见 references/cq-add1-prereg-2026-08-20.md（跑前定死：added>=10,000 自动驳回
对齐 CE bull_steady 证伪；单月>50% 驳回；验证段 >=2025-08-10 不显著即证伪）。

用法（系统 python 3.11，含 jinja2/fastapi）:
  python references/run_cq_add1_replay.py --smoke      # 3 品 smoke（字节一致核对）
  python references/run_cq_add1_replay.py              # 全池并行族开回放
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
OUT = ROOT / "data" / os.environ.get("CS_ENGINE_FAMVAR_OUT", "_exp_cq_add1_replay_2026-08-20.json")
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


def _trigger_cq_add1(F):
    """CQ-ADD-1 高选择性窄化（预注册 cq-add1-prereg-2026-08-20.md §二，跑前定死）：
    大盘上行 drop21(3.7,15] ∩ 供给收缩 sc30<=-5 ∩ 低波动 vol30<=50 ∩ 大盘7日 mchg7>4。"""
    v30 = _vol_pct(F["prices"], 30)
    m7 = _MCHG7.get(F.get("signal_date"))
    d21 = F.get("drop21")
    sc30 = F.get("supply_change_30d")
    return (d21 is not None and 3.7 < d21 <= 15
            and sc30 is not None and sc30 <= -5
            and v30 is not None and v30 <= 50
            and m7 is not None and m7 > 4)


def inject(mchg7):
    global _MCHG7
    _MCHG7 = mchg7
    f1 = ia.SignalFamily(key="cq_add1", label="🟢 牛市上行·高选择性窄化·分批建仓",
                         priority=22, limit=0.12, trigger=_trigger_cq_add1)
    # 三处派生结构必须同步重建（③点名"tuple/派生列表漏 patch"）
    ia.SIGNAL_FAMILIES = tuple(ia.SIGNAL_FAMILIES) + (f1,)
    ia.SIGNAL_FAMILY_BY_KEY = {fam.key: fam for fam in ia.SIGNAL_FAMILIES}
    ia._POST_FAMILIES = tuple(sorted(
        (fam for fam in ia.SIGNAL_FAMILIES if fam.key != "panic_resonance"),
        key=lambda f: -f.priority))
    ia.DEDUP_PRIO_BY_LABEL["牛市上行·高选择性窄化"] = 22
    # 买涨腿硬编码循环：尾加 cq_add1（从 hold/reduce 段升级，与 rise_accum 同腿）
    src = inspect.getsource(ia.decide_fusion_signal)
    old = '("rise_accum", "rise_contract", "volatile_accum", "rs_accum", "ct_accum")'
    new = '("rise_accum", "rise_contract", "volatile_accum", "rs_accum", "ct_accum", "cq_add1")'
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

    total_new = {"cq_add1": 0}
    all_ok = True
    for iid, name in sorted(smoke_items.items()):
        r = rib.backtest_item(iid, name, "2023-11-17", "2026-08-05", 30, market_ctx, cost=0.02)
        sigs = [s for s in r.get("signals", []) if s.get("fwd14") is not None]
        new = [s for s in sigs if s.get("action_label", "").startswith("🟢 牛市上行·高选择性窄化")]
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
            total_new["cq_add1"] += 1
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
                 "pool": "全池除贴纸/角色/污染（CQ-ADD-1 窄化变体：cq_add1 注入）",
                 "engine": "v2-T13 + cq_add1 候选族注入（研究脚本变体，不改 pipeline/）",
                 "db": os.environ["CS_MODEL_DB"]},
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "signals": sigs_out, "errors": errs,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    new = [s for s in sigs_out if s.get("action_label", "").startswith("🟢 牛市上行·高选择性窄化")]
    print("total signals:", len(sigs_out), "| new-family:", len(new), "| errors:", len(errs), "| saved", OUT)
    print("new by month:", dict(sorted(Counter(s["date"][:7] for s in new).items())))
    print("new by family:", dict(Counter(s["action_label"] for s in new)))


if __name__ == "__main__":
    mp.freeze_support()
    if "--smoke" in sys.argv:
        smoke()
    else:
        full()
