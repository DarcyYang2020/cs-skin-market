# -*- coding: utf-8 -*-
"""P0-8 深值层分批拟合（回测先行，不改引擎）。

用法（在 cs-skin-market 目录下执行）：
  python references/tranche_fit_deepvalue.py --replay [--limit "A;B"]   # 当前引擎全量回放 -> data/deepvalue_replay_tmp.json
  python references/tranche_fit_deepvalue.py --fit                       # 筛 deep_value 信号 + 分批网格拟合

安全约束：
- 只读复用 run_item_backtest.backtest_item（当前引擎，含 P0-8 通道）
- 输出写到 data/deepvalue_replay_tmp.json，绝不覆盖 data/item_backtest_latest.json（88 信号基准）
"""
import sys, io, json, argparse, statistics
from datetime import datetime
from collections import defaultdict
sys.path.insert(0, ".")

SAVE = "data/deepvalue_replay_tmp.json"


# ---------------- 回放 ----------------
def do_replay(limit=None):
    from run_item_backtest import backtest_item, load_items
    from pipeline.backtest_common import patch_sentiment, build_market_context

    patch_sentiment(50.0)
    market_ctx = build_market_context("2025-11-02")
    print(f"market context dates: {len(market_ctx)}", flush=True)
    items = load_items()
    if limit:
        items = {i: n for i, n in items.items() if n in limit}
    results = []
    for iid, iname in sorted(items.items()):
        r = backtest_item(iid, iname, "2025-11-02", None, 60, market_ctx, cost=0.02)
        sigs = [s for s in r.get("signals", []) if "fwd14" in s]
        print(f"== {iname[:40]} days={r.get('days')} signals={len(sigs)}", flush=True)
        results.append(r)
    all_sigs = [s for r in results for s in r.get("signals", []) if "fwd14" in s]
    with open(SAVE, "w", encoding="utf-8") as f:
        json.dump({"replay_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "signals": all_sigs}, f, ensure_ascii=False, indent=1)
    print(f"\nsaved: {SAVE}  signals={len(all_sigs)}", flush=True)


# ---------------- 分批模拟（口径与 references/tranche_fit.py 一致） ----------------
def sim_signal(sig, plan, cost=0.02, hold=14):
    entry = sig["entry_price"]
    fwd = sig.get("fwd_series") or []
    n = len(fwd)
    if n == 0:
        return None
    h = min(hold, n)
    exit_px = fwd[h - 1]
    buys = [(entry, plan[0])]
    for thr, w in plan[1:]:
        thr_px = entry * (1 - thr / 100.0)
        idx = next((j for j in range(n) if fwd[j] <= thr_px), None)
        if idx is not None:
            buys.append((fwd[idx], w))
    total_w = sum(w for _, w in buys)
    w_ret = sum(w * (exit_px / px - 1 - cost) for px, w in buys) / total_w * 100
    return w_ret, total_w


def aggregate(sigs, plan, hold=14):
    xs = [sim_signal(s, plan, hold=hold) for s in sigs]
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None, 0.0
    tw = sum(x[1] for x in xs)
    wavg = sum(x[0] * x[1] for x in xs) / tw if tw else 0
    wwin = sum(x[1] for x in xs if x[0] > 0) / tw * 100 if tw else 0
    return round(wavg, 2), round(wwin, 1), round(sum(x[1] for x in xs) / len(xs), 1)


def one_shot(sigs, weight, hold=14, cost=0.02):
    xs = []
    for s in sigs:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        h = min(hold, len(fwd))
        r = (fwd[h - 1] / s["entry_price"] - 1 - cost) * 100
        xs.append((weight, r))
    if not xs:
        return None, None
    tw = sum(w for w, _ in xs)
    wavg = sum(w * r for w, r in xs) / tw
    wwin = sum(w for w, r in xs if r > 0) / tw * 100
    return round(wavg, 2), round(wwin, 1)


def in_window(date, w):
    if w == "full":
        return True
    if w == "pre123":
        return date <= "2026-01-22"
    if w == "feb":
        return "2026-01-23" <= date <= "2026-02-12"
    if w == "post_feb":
        return date > "2026-02-12"
    if w == "mar":
        return "2026-03-01" <= date <= "2026-03-31"
    if w == "jul":
        return date >= "2026-07-01"
    return False


# ---------------- 拟合 ----------------
PLANS = {
    "C(10,-10:20,-15:30)": [10, (10, 20), (15, 30)],
    "DV1(5,-5:10,-10:15)": [5, (5, 10), (10, 15)],
    "DV2(10,-5:20,-10:30)": [10, (5, 20), (10, 30)],
    "DV3(5,-5:15,-10:25)": [5, (5, 15), (10, 25)],
    "DV4(10,-8:20,-15:30)": [10, (8, 20), (15, 30)],
    "DV5(8,-5:15,-10:25)": [8, (5, 15), (10, 25)],
}


def do_fit():
    d = json.load(io.open(SAVE, encoding="utf-8"))
    sigs = d["signals"]
    print(f"total signals: {len(sigs)}")
    from collections import Counter
    print("position_limit:", dict(Counter(s.get("position_limit") for s in sigs)))
    deep = [s for s in sigs if s.get("position_limit") == 0.10 or "深值" in (s.get("action_label") or "")]
    print("deep_value signals:", len(deep))
    if not deep:
        print("no deep_value signals -> abort")
        return
    for hold in (14, 30):
        print(f"\n===== hold={hold} deep_value 层 =====")
        os, ww = one_shot(deep, 0.10, hold=hold)
        print(f"  一次性 0.10: wavg={os:+.2f}% win={ww:.1f}%")
        rows = []
        for name, plan in PLANS.items():
            a, w, avgw = aggregate(deep, plan, hold=hold)
            rows.append((name, a, w, avgw))
        rows.sort(key=lambda x: x[1], reverse=True)
        for name, a, w, avgw in rows:
            print(f"  {name:28s} wavg={a:+7.2f}% win={w:5.1f}% avg_total={avgw}%")
    # 稳健性：最优方案 vs 一次性，去极值/中间60%/分窗口
    print("\n===== 稳健性（hold14） =====")
    base_os, _ = one_shot(deep, 0.10, hold=14)
    best_name, best_plan = max(PLANS.items(), key=lambda kv: aggregate(deep, kv[1], hold=14)[0] or -99)
    print(f"最优方案: {best_name}")
    n = len(deep)
    by_net = sorted(deep, key=lambda s: s.get("net14") if s.get("net14") is not None else -99)
    k = max(1, n // 10)
    mid = by_net[k:-k] if n > 2 * k else deep
    def show(tag, subset):
        a, w, _ = aggregate(subset, best_plan, hold=14)
        os2, _ = one_shot(subset, 0.10, hold=14)
        print(f"  {tag:22s} n={len(subset):3d} 一次性={os2:+7.2f}% -> {best_name} {a:+7.2f}% (diff {a-os2:+.2f}pp)")
    show("全量", deep)
    show("中间60%", mid)
    show("pre-1/23", [s for s in deep if in_window(s["date"], "pre123")])
    show("1/23~2/12", [s for s in deep if in_window(s["date"], "feb")])
    show("post-2/12", [s for s in deep if in_window(s["date"], "post_feb")])
    show("3月", [s for s in deep if in_window(s["date"], "mar")])
    show("7月", [s for s in deep if in_window(s["date"], "jul")])
    # 尾部
    xs = sorted([(sim_signal(s, best_plan, hold=14) or (0, 0))[0] for s in deep], reverse=True)
    print("  最优方案最差5笔:", [round(x, 1) for x in xs[-5:]])
    xs1 = sorted([one_shot([s], 0.10, hold=14)[0] for s in deep])
    print("  一次性最差5笔:", [round(x, 1) for x in xs1[-5:]])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--limit", default="")
    args = ap.parse_args()
    if args.replay:
        limit = [x.strip() for x in args.limit.split(";") if x.strip()] or None
        do_replay(limit)
    elif args.fit:
        do_fit()
    else:
        ap.print_help()