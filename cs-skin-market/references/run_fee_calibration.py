# -*- coding: utf-8 -*-
"""Wave4 E2 · 历史回测按 买0/卖1 重跑校准（2026-08-27，roadmap v82 卡）。

目标（§5.5 费率口径修正，2026-08-26 已拍板 买0/卖1）：
  ① 回测引擎费率参数改为 买0/卖1（config 化）——pipeline/config.py BACKTEST_FEES，
     回放脚本（run_item_backtest_full.py / run_item_backtest_fullpool_parallel.py）从 config 读取。
  ② 重跑现有基线/候选回放，输出新旧期望差异。
  ③ 滑点模型随盘口数据（D2）积累后补（本卡仅费率）。

关键事实（诚实标注）：费率只影响回放产物的 net14/net30（net = fwd − roundtrip_cost），
**不影响信号判定**（backtest_item 中 cost 仅用于 net 计算，信号发射/去重/闸门与费率无关）。
因此对现有 v2-T13 全池产物（`data/_exp_current_engine_fullpool_2026-08-27.json`，376 信号）
按新费率重算 net 与「用新费率重跑引擎」数学等价（同一信号集合，net 线性平移）。
本脚本采用重算路径 + 小样本真重跑对照验证，避免不必要的 1 小时全池重跑。

产出：
  data/_exp_v2t13_fee_cal_2026-08-27.json    —— 校准后产物（fees 标注，net 按买0/卖1 重算）
  data/_exp_fee_calibration_2026-08-27.json  —— 新旧期望差异表（2% 双边 vs 买0/卖1）
用法：python references/run_fee_calibration.py
"""
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# E2 回放库（replay_cycle_win.db，3 年窗口；R3 零漂移对照同源）。
# 必须在 import pipeline.config 之前设置——config.DB_PATH 在 import 时确定，
# 否则 verify 会连到生产库（365 天）导致信号集合不同（R3 教训同源：name 桥）。
os.environ.setdefault("CS_MODEL_DB", str(ROOT / "data" / "replay_cycle_win.db"))

from pipeline.config import BACKTEST_FEES, backtest_roundtrip_cost, SIGNAL_FAMILY_TAXONOMY  # noqa: E402

SRC = ROOT / "data" / "_exp_current_engine_fullpool_2026-08-27.json"
OUT_CAL = ROOT / "data" / "_exp_v2t13_fee_cal_2026-08-27.json"
OUT_DIFF = ROOT / "data" / "_exp_fee_calibration_2026-08-27.json"

OLD_ROUNDTRIP = 2.0  # 旧回放假设 2% 双边（round-trip cost ×100）
NEW_ROUNDTRIP = backtest_roundtrip_cost()  # = 买0 + 卖1 = 1.0


def _wilson_ci(k, n, z=1.96):
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (round(100.0 * max(0.0, center - half), 1), round(100.0 * min(1.0, center + half), 1))


def _stats(sigs, field="net14"):
    ok = [s for s in sigs if s.get(field) is not None]
    if not ok:
        return {"n": 0, "win": None, "avg": None, "ci": None}
    wins = sum(1 for s in ok if s[field] > 0)
    return {"n": len(ok), "win": round(100.0 * wins / len(ok), 1),
            "avg": round(sum(s[field] for s in ok) / len(ok), 2),
            "ci": _wilson_ci(wins, len(ok))}


def _display_key(label):
    lab = label or ""
    for fine in SIGNAL_FAMILY_TAXONOMY["fine_order"]:
        kw = SIGNAL_FAMILY_TAXONOMY["fine_keywords"].get(fine)
        if kw and kw in lab:
            return SIGNAL_FAMILY_TAXONOMY["fine_to_display"][fine]
    return "accumulate"


def build_diff_table(old_sigs, new_sigs):
    """新旧期望差异：按展示键（panic/deep_value/accumulate）+ 全量。"""
    rows = []
    keys = list(SIGNAL_FAMILY_TAXONOMY["display_keys"]) + ["ALL"]
    for key in keys:
        os_ = old_sigs if key == "ALL" else [s for s in old_sigs if _display_key(s.get("action_label") or "") == key]
        ns_ = new_sigs if key == "ALL" else [s for s in new_sigs if _display_key(s.get("action_label") or "") == key]
        o14, n14 = _stats(os_, "net14"), _stats(ns_, "net14")
        o30, n30 = _stats(os_, "net30"), _stats(ns_, "net30")
        rows.append({
            "key": key,
            "label": ("全量" if key == "ALL" else SIGNAL_FAMILY_TAXONOMY["display_labels"][key]),
            "n": len(ns_),
            "old_win14": o14["win"], "new_win14": n14["win"],
            "old_avg14": o14["avg"], "new_avg14": n14["avg"],
            "old_win30": o30["win"], "new_win30": n30["win"],
            "old_avg30": o30["avg"], "new_avg30": n30["avg"],
            "ci14_lo": (n14["ci"] or (None, None))[0],
            "ci14_hi": (n14["ci"] or (None, None))[1],
            "delta_avg14": round((n14["avg"] or 0) - (o14["avg"] or 0), 2),
            "delta_win14_pp": round((n14["win"] or 0) - (o14["win"] or 0), 1),
        })
    return rows


def calibrate():
    if not SRC.exists():
        raise SystemExit("缺少源产物: %s（先跑 R3 全池回放）" % SRC)
    data = json.load(io.open(SRC, encoding="utf-8"))
    old_sigs = data["signals"]
    new_sigs = []
    for s in old_sigs:
        ns = dict(s)
        if s.get("fwd14") is not None:
            ns["net14"] = round(s["fwd14"] - NEW_ROUNDTRIP, 2)
        if s.get("fwd30") is not None:
            ns["net30"] = round(s["fwd30"] - NEW_ROUNDTRIP, 2)
        ns["_fee_roundtrip"] = NEW_ROUNDTRIP
        ns["_fee_note"] = "E2 买0/卖1 不对称费率（旧 2% 双边）"
        new_sigs.append(ns)

    # 校准后产物（保留原 args + 费率标注）
    cal = {k: v for k, v in data.items() if k != "signals"}
    cal["args"] = dict(data.get("args") or {})
    cal["args"]["fees"] = {
        "buy_pct": BACKTEST_FEES["buy_pct"], "sell_pct": BACKTEST_FEES["sell_pct"],
        "roundtrip_pct": NEW_ROUNDTRIP,
        "note": "E2 不对称费率 config 化（pipeline.config.BACKTEST_FEES）；net = fwd − roundtrip；"
                "费率不影响信号判定，重算与重跑等价（见脚本 docstring）",
    }
    cal["generated"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
    cal["signals"] = new_sigs

    diff = build_diff_table(old_sigs, new_sigs)
    out_diff = {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="minutes"),
        "source": str(SRC),
        "calibrated": str(OUT_CAL),
        "old_roundtrip_pct": OLD_ROUNDTRIP,
        "new_roundtrip_pct": NEW_ROUNDTRIP,
        "fees": BACKTEST_FEES,
        "note": "E2 新旧期望差异：旧=2% 双边（net=fwd−2.0），新=买0/卖1（net=fwd−1.0）。"
                "信号集合不变（费率不影响判定），win/avg 全体 +1.0pp 平移由 avg 体现；"
                "win 变化仅因符号翻转（阈值附近信号）。滑点模型待 D2 盘口积累后补。",
        "table": diff,
    }

    with io.open(OUT_CAL, "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=1)
    with io.open(OUT_DIFF, "w", encoding="utf-8") as f:
        json.dump(out_diff, f, ensure_ascii=False, indent=1)

    print("=== E2 费率校准（买0/卖1 round-trip=%.1f%% vs 旧 %.1f%%）===" % (NEW_ROUNDTRIP, OLD_ROUNDTRIP))
    print("源产物信号数:", len(old_sigs))
    print("%-12s %5s | %8s %8s -> %8s %8s | %8s %8s -> %8s %8s | dAvg14 dWin14" % (
        "key", "n", "oWin14", "oAvg14", "nWin14", "nAvg14", "oWin30", "oAvg30", "nWin30", "nAvg30"))
    for r in diff:
        print("%-12s %5d | %7s %8s -> %7s %8s | %7s %8s -> %7s %8s | %+5.2f %+4.1fpp" % (
            r["key"], r["n"],
            r["old_win14"], r["old_avg14"], r["new_win14"], r["new_avg14"],
            r["old_win30"], r["old_avg30"], r["new_win30"], r["new_avg30"],
            r["delta_avg14"], r["delta_win14_pp"]))
    print("written:", OUT_CAL, "|", OUT_DIFF)
    return cal, out_diff


def verify_small_replay(n=5):
    """小样本真重跑对照：随机取 n 品用 config 费率重跑，验证 net 与重算一致（数学等价实证）。"""
    import random
    import sqlite3
    import importlib.util
    # CS_MODEL_DB 已在模块顶部 setdefault 为回放库（config.DB_PATH 同源）
    from pipeline.backtest_common import build_market_context
    spec = importlib.util.spec_from_file_location(
        "rib", str(ROOT / "references" / "scripts-archive" / "run_item_backtest.py"))
    rib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rib)

    cal = json.load(io.open(OUT_CAL, encoding="utf-8"))
    by_name = {}
    for s in cal["signals"]:
        by_name.setdefault(s["name"], []).append(s)

    market_ctx = build_market_context("2023-11-17", end="2026-08-05")
    conn = sqlite3.connect(os.environ["CS_MODEL_DB"])
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT i.id, i.name FROM items i JOIN price_history p ON p.item_id=i.id "
                        "GROUP BY i.id").fetchall()
    conn.close()
    rng = random.Random(42)
    sample = rng.sample([r for r in rows if r["name"] in by_name], min(n, len(by_name)))
    mismatches = []
    for row in sample:
        # cost 参数为小数形式（0.01=1%），与 backtest_item 内 net=fwd−cost*100 对齐
        r = rib.backtest_item(row["id"], row["name"], "2023-11-17", "2026-08-05", 30,
                              market_ctx, cost=NEW_ROUNDTRIP / 100.0)
        for s in r.get("signals", []):
            if s.get("fwd14") is None or s.get("date") not in {x["date"] for x in by_name.get(row["name"], [])}:
                continue
            orig = next(x for x in by_name[row["name"]] if x["date"] == s["date"])
            if abs((s.get("net14") if s.get("net14") is not None else 0) -
                   (orig.get("net14") if orig.get("net14") is not None else 0)) > 0.02:
                mismatches.append((row["name"], s["date"], s.get("net14"), orig.get("net14")))
    print("小样本真重跑对照（%d 品，seed=42）：net14 不一致 %d 处" % (len(sample), len(mismatches)))
    for m in mismatches[:5]:
        print("  MISMATCH:", m)
    return len(mismatches) == 0


if __name__ == "__main__":
    cal, diff = calibrate()
    ok = verify_small_replay(n=5)
    print("verify_small_replay:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
