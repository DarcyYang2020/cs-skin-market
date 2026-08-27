# -*- coding: utf-8 -*-
"""R3 策略隔离评估 · 单族模式族开回放（2026-08-27，②研究窗口，预注册 r3-family-isolation-prereg-2026-08-27.md 已冻结 DR）。

与 run_family_variant_replay.py / run_cq_add1_replay.py（加族变体）不同，本脚本是「单族模式」：
只注入目标策略组（6 族：恐慌/深值/趋势买涨/供给/反转/基础），关闭其他族触发，独立回放全池 3 年，
输出该族独立信号集 + delta 清单（零漂移校验）。研究脚本，不改 pipeline/ 生产代码。

注入机制（复用 CQ-ADD-1 写法，③点名"tuple/派生列表漏 patch"教训）：
1. 非目标族 trigger 替换为恒 False 闭包（不删族、不重建派生结构——panic_fam 硬编码查找 /
   _POST_FAMILIES / 买涨腿 loop 全部保持，只禁触发）；
2. patch decide_fusion_signal（inspect+exec，同 CQ-ADD-1）：
   - 非 base 族：守卫1 前关闭基础 buy 路径（fd.action buy→watch）；
   - deep_dip 开关：base 族关闭 P0-7b 深度回调低吸变换（该信号归反转族评估）；
3. 目标族默认关族经 env 开启（rise_contract / xishou_mid / second_wave，声明为「引擎已注册默认关族，评估期开启」）。
4. oos_guard.require_fit 逐日期守卫（预注册声明放行，val 段仅四关预注册验证触碰）。

用法（系统 python 3.11，含 jinja2/fastapi）：
  CS_R3_FAMILY=panic  python references/run_family_isolation_replay.py --smoke
  CS_R3_FAMILY=panic  python references/run_family_isolation_replay.py
族 key：panic / deep / rise / supply / reversal / base。
"""
import importlib.util
import inspect
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

# ---- 预注册声明（R3 判据已冻结 DR；val 段触碰均为预注册验证动作）----
PREREG = "r3-family-isolation-2026-08-27"

# ---- 族 key 由环境变量传递（spawn 子进程继承 os.environ，保证主/子进程口径一致）----
os.environ.setdefault("CS_R3_FAMILY", "panic")
_R3_FAMILY = os.environ["CS_R3_FAMILY"]

# ---- 6 族分组（预注册 §1 + 用户核实口径；族 key 与 item_analysis.SIGNAL_FAMILIES 一致）----
# labels = 该族输出的 action_label 关键词白名单（反转族含 P0-7b 深度回调低吸，归并预注册/用户两口径）
FAMILY_DEFS = {
    "panic":    {"label": "恐慌",     "families": ("panic_resonance", "panic_easing"),
                 "labels": ("恐慌共振", "恐慌退潮"),
                 "base_keep": False, "deep_dip": False, "open_envs": {}},
    "deep":     {"label": "深值",     "families": ("deep_value",),
                 "labels": ("深值",),
                 "base_keep": False, "deep_dip": False, "open_envs": {}},
    "rise":     {"label": "趋势买涨", "families": ("rise_accum", "rise_contract"),
                 "labels": ("吸筹型上涨", "深收缩慢涨"),
                 "base_keep": False, "deep_dip": False,
                 "open_envs": {"CS_ENGINE_RISE_CONTRACT": "1"}},
    "supply":   {"label": "供给",     "families": ("supply_accum",),
                 "labels": ("供给收缩",),
                 "base_keep": False, "deep_dip": False, "open_envs": {}},
    "reversal": {"label": "反转",     "families": ("xishou_mid", "second_wave"),
                 "labels": ("惜售中段", "二波回调", "深度回调低吸"),
                 "base_keep": True, "deep_dip": True,
                 "open_envs": {"CS_ENGINE_XISHOU_MID": "1", "CS_ENGINE_C_WAVE": "1"}},
    "base":     {"label": "基础",     "families": (),
                 "labels": ("🟢 分批建仓", "🟢 周期吸筹·分批建仓"),
                 "match_mode": "exact",  # base label 与其他族共享「·分批建仓」后缀，须精确匹配
                 "base_keep": True, "deep_dip": False, "open_envs": {}},
}
if _R3_FAMILY not in FAMILY_DEFS:
    raise SystemExit("未知族 key: %r（可选 panic/deep/rise/supply/reversal/base）" % _R3_FAMILY)
_FAM = FAMILY_DEFS[_R3_FAMILY]
for _k, _v in _FAM["open_envs"].items():  # 目标族默认关族开启（须在 import 前 setenv，SIGNAL_FAMILIES 定义读 env）
    os.environ.setdefault(_k, _v)

import pipeline.item_analysis as ia  # noqa: E402

_ARCHIVED_RUNNER = ROOT / "references" / "scripts-archive" / "run_item_backtest.py"
BASELINE = ROOT / "data" / "_exp_cycle_replay_fullpool_2026.json"
OUT = ROOT / "data" / ("_exp_family_%s_replay_2026-08-27.json" % _R3_FAMILY)
HQ_EXCLUDE_MARKERS = ("印花 |", "游击队", "军刀勇士", "特警", "巴西第一营", "海豹部队")
POLLUTED_ITEMS = {"AK-47 | 流金王朝 (崭新出厂)", "挂件 | 丁烷拍档"}
START, END, WARMUP = "2023-11-17", "2026-08-05", 30

_G = {}


def _never(F):
    """非目标族触发器：恒 False（保留族对象与派生结构，只禁触发）。"""
    return False


def _patch_decide_fusion_signal():
    """patch decide_fusion_signal（inspect+exec，同 CQ-ADD-1 机制；不落生产代码）：
    1) 非 base 族：守卫1 前关闭基础 buy 路径（基础信号=base 族专属）；
    2) deep_dip 开关：base 族关闭 P0-7b 深度回调低吸变换（该信号归反转族评估）。"""
    src = inspect.getsource(ia.decide_fusion_signal)
    old1 = """    bucket = _state_bucket(market_180d_change, market_30d_change)

    # ---- 基础族：守卫1（市场弱/存世量/半山腰/7天去重/飞刀确认）----
    _apply_guards(fd, F, _GUARD1)"""
    new1 = """    bucket = _state_bucket(market_180d_change, market_30d_change)

    # ---- [R3 单族模式] 基础 buy 路径开关（base_keep=0 → 关闭，基础信号归 base 族评估）----
    if _R3_SINGLE_FAMILY["base_keep"] == 0 and fd.action == "buy":
        fd.action = "watch"
        fd.action_label = "（R3 单族模式：基础路径关闭）"
        fd.position_limit = 0.0

    # ---- 基础族：守卫1（市场弱/存世量/半山腰/7天去重/飞刀确认）----
    _apply_guards(fd, F, _GUARD1)"""
    assert old1 in src, "patch1 失败：守卫1 段未找到"
    src = src.replace(old1, new1)
    old2 = """    elif fd.action == "buy":
        # ---- P0-7b：周期吸筹需大盘深跌共振；D方案深度回调低吸例外 ----
        _deep_dip_transform(fd, F)"""
    new2 = """    elif fd.action == "buy":
        # ---- P0-7b：周期吸筹需大盘深跌共振；D方案深度回调低吸例外 ----
        if _R3_SINGLE_FAMILY["deep_dip"] == 1:
            _deep_dip_transform(fd, F)"""
    assert old2 in src, "patch2 失败：P0-7b 段未找到"
    src = src.replace(old2, new2)
    ia._R3_SINGLE_FAMILY = {"base_keep": 1 if _FAM["base_keep"] else 0,
                            "deep_dip": 1 if _FAM["deep_dip"] else 0,
                            "family": _R3_FAMILY}
    exec(src, ia.__dict__)


def inject():
    """单族模式注入：patch 决策核心 + 非目标族 trigger 恒 False。"""
    _patch_decide_fusion_signal()
    target = _FAM["families"]
    for fam in ia.SIGNAL_FAMILIES:
        if fam.key not in target:
            fam.trigger = _never


def _load_runner():
    spec = importlib.util.spec_from_file_location("_r3_rib", str(_ARCHIVED_RUNNER))
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


def _base_key(s):
    """零漂移匹配键：同品同日同 net14 视为同一信号（label 可演变——
    例：基线 2025-06-04 沙漠之鹰「弱市抗跌·分批介入」为旧 label，单开以「深值·大盘企稳」发射，net14 一致）。
    去重交互导致的消失（族内 7 日去重自约束）单独归因，不判为漂移。"""
    return (s["date"], s["name"], s.get("net14"))


def _keep_label(label):
    """信号 label 是否属于目标族（关键词白名单；base 族精确匹配，防「·分批建仓」后缀误匹配其他族）。"""
    lab = label or ""
    if _FAM.get("match_mode") == "exact":
        return lab in _FAM["labels"]
    return any(k in lab for k in _FAM["labels"])


def _period_of(mc):
    """信号日所属大盘五时期（market_context.state_bucket 口径，补记到信号）。"""
    from pipeline.market_context import state_bucket as _sb
    try:
        return _sb(mc.get("chg180", 0.0), mc.get("chg30", 0.0))
    except Exception:
        return None


def _init_worker(market_ctx, all_engine=False):
    global _G
    if not all_engine:
        inject()
    _G["market_ctx"] = market_ctx
    _G["all_engine"] = all_engine


def _worker(args):
    from pipeline.oos_guard import require_fit
    iid, name, start, end, warmup = args
    rib = _load_runner()
    market_ctx = _G["market_ctx"]
    try:
        r = rib.backtest_item(iid, name, start, end, warmup, market_ctx, cost=0.02)
    except Exception as exc:
        return {"item_id": iid, "name": name, "signals": [], "error": str(exc)}
    # oos 守院（预注册验证动作放行）+ 目标 label 白名单（单族模式）+ 五时期补记
    kept, dropped = [], []
    for s in r.get("signals", []):
        if s.get("net14") is None:
            continue
        require_fit(s["date"], prereg=PREREG, label="R3 单族回放(%s)" % _R3_FAMILY)
        mc = market_ctx.get(s["date"]) or {}
        s["_period"] = _period_of(mc)
        if _G.get("all_engine"):
            kept.append(s)
        elif _keep_label(s.get("action_label", "")):
            s["_single_family"] = _R3_FAMILY
            kept.append(s)
        else:
            dropped.append(s)
    r["signals"] = kept
    r["dropped_other_family"] = len(dropped)
    return r


def smoke():
    from pipeline.backtest_common import build_market_context
    inject()
    market_ctx = build_market_context(START, end=END)
    rib = _load_runner()
    baseline = _load_baseline_by_name()
    items = pool_items()
    sig_counts = Counter(s["name"] for s in json.load(open(BASELINE, encoding="utf-8")).get("signals", []))
    cands = sorted(items.items(), key=lambda kv: -sig_counts.get(kv[1], 0))
    smoke_names = [n for _, n in cands[:3]]
    smoke_items = {iid: n for iid, n in items.items() if n in smoke_names}
    print("smoke 品:", list(smoke_items.values()), flush=True)
    all_ok = True
    for iid, name in sorted(smoke_items.items()):
        r = rib.backtest_item(iid, name, START, END, WARMUP, market_ctx, cost=0.02)
        sigs = [s for s in r.get("signals", []) if s.get("net14") is not None]
        fam_sigs = [s for s in sigs if _keep_label(s.get("action_label", ""))]
        other = [s for s in sigs if not _keep_label(s.get("action_label", ""))]
        base = baseline.get(name, [])
        # 零漂移核对：基线中目标族信号（同品同日同 net14）应全在单开输出（label 可演变；消失=去重自约束归因）
        base_sigs = [s for s in base if _keep_label(s.get("action_label", ""))]
        fam_keys = {_base_key(s) for s in fam_sigs}
        missing = [s for s in base_sigs if _base_key(s) not in fam_keys]
        all_ok &= (len(missing) == 0)
        print(f"\n== {name} ==")
        print(f"  单开信号 {len(sigs)}（族 {len(fam_sigs)} / 其他 {len(other)}） 基线族信号 {len(base_sigs)} 缺失 {len(missing)}")
        for s in fam_sigs:
            print(f"    {s['date']}  {s['action_label'][:24]}  net14={s.get('net14')}")
        if missing:
            for s in missing[:5]:
                print("    缺失:", s["date"], s["action_label"][:20], "net14=", s.get("net14"), "（归因：族内去重自约束/label 演变）")
    print("\n=== smoke 汇总（族 %s）===" % _R3_FAMILY)
    print("基线族信号保持（零漂移）:", "PASS" if all_ok else "FAIL")
    return all_ok


def full(all_engine=False):
    from pipeline.backtest_common import build_market_context
    if not all_engine:
        inject()
    market_ctx = build_market_context(START, end=END)
    items = pool_items()
    print("pool items:", len(items), "| mode:", "全引擎(无注入参照)" if all_engine else ("单族:" + _R3_FAMILY), flush=True)
    n_workers = min(int(os.environ.get("CS_R3_WORKERS", "8")), max(2, os.cpu_count() or 4))
    jobs = [(iid, name, START, END, WARMUP) for iid, name in sorted(items.items())]

    with mp.Pool(processes=n_workers, initializer=_init_worker,
                 initargs=(market_ctx, all_engine)) as pool:
        results = pool.map(_worker, jobs, chunksize=1)

    if all_engine:
        sigs_out = [s for r in results for s in r.get("signals", []) if s.get("net14") is not None]
        for s in sigs_out:
            mc = market_ctx.get(s["date"]) or {}
            s["_period"] = _period_of(mc)
        out = {
            "args": {"start": START, "end": END, "warmup": WARMUP,
                     "pool": "全池除贴纸/角色/污染（当前引擎无注入全池，R3 零漂移参照）",
                     "engine": "v2-T13 当前引擎（无注入）",
                     "db": os.environ["CS_MODEL_DB"]},
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "signals": sigs_out, "errors": errs if (errs := [r for r in results if r.get("error")]) else [],
        }
        out_path = ROOT / "data" / "_exp_current_engine_fullpool_2026-08-27.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("current-engine baseline saved:", out_path, "| signals:", len(sigs_out))
        return

    sigs_out = [s for r in results for s in r.get("signals", [])]
    errs = [r for r in results if r.get("error")]
    # delta 清单（零漂移校验）：基线中该族信号（同品同日同 net14）保持 + 新增（去重释放/默认关族开启）
    base = json.load(open(BASELINE, encoding="utf-8"))
    base_sigs = [s for s in base["signals"] if s.get("net14") is not None and _keep_label(s.get("action_label", ""))]
    base_keys = {_base_key(s) for s in base_sigs}
    fam_keys = {_base_key(s) for s in sigs_out}
    missing = [s for s in base_sigs if _base_key(s) not in fam_keys]
    added = [s for s in sigs_out if _base_key(s) not in base_keys]
    kept = len(base_keys & fam_keys)
    out = {
        "args": {"start": START, "end": END, "warmup": WARMUP,
                 "family": _R3_FAMILY, "family_label": _FAM["label"],
                 "families": list(_FAM["families"]), "labels": list(_FAM["labels"]),
                 "base_keep": _FAM["base_keep"], "deep_dip": _FAM["deep_dip"],
                 "open_envs": dict(_FAM["open_envs"]),
                 "pool": "全池除贴纸/角色/污染（R3 单族模式：%s）" % _R3_FAMILY,
                 "engine": "v2-T13 + 单族注入（研究脚本变体，不改 pipeline/）",
                 "prereg": PREREG,
                 "db": os.environ["CS_MODEL_DB"]},
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "delta": {"baseline_family_sigs": len(base_sigs),
                  "kept_keys": kept,
                  "missing": [{"date": s["date"], "name": s["name"], "label": s.get("action_label"),
                               "net14": s.get("net14"),
                               "note": "消失归因：族内 7 日去重自约束或 label 演变（基线旧 label 同 net14 信号以新 label 发射）"} for s in missing],
                  "added_sigs": len(added),
                  "zero_drift": (len(missing) == 0),
                  "zero_drift_note": "零漂移=基线族信号同键(品,日,net14)全保持；消失须归因于去重自约束/label 演变，非引擎漂移"},
        "signals": sigs_out, "errors": errs,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("total signals:", len(sigs_out), "| errors:", len(errs), "| saved", OUT, flush=True)
    print("delta: baseline_family=%d kept=%d missing=%d added=%d zero_drift=%s" % (
        out["delta"]["baseline_family_sigs"], out["delta"]["kept_keys"],
        len(out["delta"]["missing"]), out["delta"]["added_sigs"], out["delta"]["zero_drift"]))
    print("by label:", dict(Counter(s["action_label"] for s in sigs_out)))
    print("by period:", dict(Counter(s.get("_period") for s in sigs_out)))
    print("by month:", dict(sorted(Counter(s["date"][:7] for s in sigs_out).items())))


if __name__ == "__main__":
    mp.freeze_support()
    if "--all-engine" in sys.argv:
        full(all_engine=True)
    elif "--smoke" in sys.argv:
        smoke()
    else:
        full()
