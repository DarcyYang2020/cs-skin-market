# -*- coding: utf-8 -*-
"""O1 干净数据仓位网格重跑（2026-08-15，做厚收益端第 1 步）。

背景：旧 P-B 仓位网格（supply_accum 0.15/0.20「恶化」、deep_value 0.20 未测）建立在伪零污染的
290 信号上。伪零清零后 supply_accum 被 P2 证实为「稳」族（干净 23 条 +13.18）。本探针在
cycle 186（3 年干净日线回放）上重跑仓位变体。

预注册判定：
- 变体 total 或 Calmar 显著改善（≥2pp / ≥0.5）且 maxDD 不破 −20%；
- 前后半段（按 2025-08-10 walk-forward 切点分窗）方向一致；
- 全过 → 落地 bump v2-T10；否则维持 v2-T9。
"""
import io
import json
import sys
from datetime import date
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "references"))

CYCLE = ROOT / "data" / "_exp_cycle_replay_2026.json"
OUT = ROOT / "data" / "_exp_o1_position_grid_clean.json"
SPLIT = date(2025, 8, 10)  # walk-forward 切点（拟合/验证）


def fine_classify(label):
    lab = label or ""
    if "恐慌" in lab:
        return "panic"
    if "深值" in lab:
        return "deep_value"
    if "供给收缩" in lab:
        return "supply_accum"
    return "other"


def load_cycle():
    d = json.load(io.open(CYCLE, encoding="utf-8"))
    sigs = []
    for s in d["signals"]:
        fwd = s.get("fwd_series") or []
        if not fwd:
            continue
        sigs.append({
            "date": date.fromisoformat(s["date"]), "item": s["name"],
            "entry": s["entry_price"], "limit": s.get("position_limit") or 0.0,
            "fwd": fwd,
            "fam": fine_classify(s.get("action_label")),
            "prio": {"panic": 3, "deep_value": 1, "supply_accum": 2, "other": 2}[fine_classify(s.get("action_label"))],
        })
    return sigs, d.get("args", {})


def with_limits(sigs, supply_accum=None, deep_value=None):
    out = []
    for s in sigs:
        c = dict(s)
        if s["fam"] == "supply_accum" and supply_accum is not None:
            c["limit"] = supply_accum
        elif s["fam"] == "deep_value" and deep_value is not None:
            c["limit"] = deep_value
        out.append(c)
    return out


def run(sigs, cap=0.8):
    # 动态导入 simulate（b1_risk_backtest_v2 使用自己的 date/limit/fwd 字段名）
    _spec = spec_from_file_location("b1v2", str(ROOT / "references" / "b1_risk_backtest_v2.py"))
    b1v2 = module_from_spec(_spec)
    _spec.loader.exec_module(b1v2)
    converted = [{
        "date": s["date"], "item": s["item"], "entry": s["entry"],
        "limit": s["limit"], "fwd": s["fwd"],
        "st": "panic" if s["fam"] == "panic" else ("deep_value" if s["fam"] == "deep_value" else "accumulate"),
        "prio": s["prio"],
    } for s in sigs]
    sim = b1v2.simulate(converted, cap=cap)
    curve = sim["curve"]  # [(date, idx, equity)?] —— 确认结构
    # b1v2.simulate 的 curve 元素结构：以 probe_core_sat_1 中 (c[0], c[2]) 为准 = (date, equity)
    pts = [(c[0], c[2]) for c in curve]
    m = metrics(pts)
    # 前后半段
    split_iso = SPLIT.isoformat()
    front = [(d, v) for d, v in pts if d < split_iso]
    back = [(d, v) for d, v in pts if d >= split_iso]
    m["front"] = metrics(front)
    m["back"] = metrics(back)
    m["n_signals"] = len(sigs)
    return m


def metrics(pts):
    if not pts:
        return {"total_return_pct": None, "max_drawdown_pct": None, "calmar": None}
    vals = [v for _, v in pts]
    total = (vals[-1] / vals[0] - 1) * 100
    peak = vals[0]
    mdd = 0.0
    for v in vals:
        if v > peak:
            peak = v
        dd = (v / peak - 1) * 100
        if dd < mdd:
            mdd = dd
    days = max(1, len(vals))
    ann = ((vals[-1] / vals[0]) ** (365.0 / days) - 1) * 100
    calmar = round(abs(total / mdd), 2) if mdd < 0 else None
    return {"total_return_pct": round(total, 2), "max_drawdown_pct": round(mdd, 2),
            "annualized_pct": round(ann, 2), "calmar": calmar}


def main():
    sigs, args = load_cycle()
    print("信号数:", len(sigs))
    from collections import Counter
    print("族分布:", dict(Counter(s['fam'] for s in sigs)))
    print("当前 position_limit 样例:", {f: [s['limit'] for s in sigs if s['fam'] == f][:3] for f in sorted(set(s['fam'] for s in sigs))})

    variants = {
        "baseline": run(sigs),
        "supply_accum_0.15": run(with_limits(sigs, supply_accum=0.15)),
        "deep_value_0.20": run(with_limits(sigs, deep_value=0.20)),
        "both": run(with_limits(sigs, supply_accum=0.15, deep_value=0.20)),
    }
    out = {"probe": "O1 干净数据仓位网格", "generated": date.today().isoformat(),
           "window": [args.get("start"), args.get("end")], "variants": variants}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n=== O1 干净仓位网格（cycle 186, cap0.8）===")
    for k, v in variants.items():
        print(f"  {k:18s} total={str(v['total_return_pct']):>9s} maxDD={str(v['max_drawdown_pct']):>8s} calmar={v['calmar']} "
              f"front_total={v['front']['total_return_pct']} front_mdd={v['front']['max_drawdown_pct']} "
              f"back_total={v['back']['total_return_pct']} back_mdd={v['back']['max_drawdown_pct']}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
