# -*- coding: utf-8 -*-
"""BUY-1 数据质量闸门：10 品口径验证探针（只读，只进研究层，不写 bid_history）。

范围/红线基准 = references/optimization-initiation-2026-08-15.md（外审立项基线）。
本探针对比「直连 period=1095」与「现有 bid_history（直连 90d）」：
  - buy_price / buy_num 日级一致率（逐品，含小基数 buy_num 单独标注）
  - bid_30d_chg 直连口径的中位数 + 与售价 30d 涨跌 sign 一致率（定量「是否还背离」）
产出 data/_exp_buy1_gate.json。不通过才丢临时结果；通过/有条件通过也不写库，由后续全量回填阶段写。

选样准则（自动选，不写死）：
  5 品 = bid_history 中 buy_price 30d 变化最极端负值（曾「不可信/背离」候选）
  3 品 = replay 中 panic/supply_accum 信号贡献 top3
  2 品 = buy_price_last 最高价 ×1 + 最低价 ×1
"""
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db  # noqa: E402
from pipeline.collector import _api_call  # noqa: E402
from pipeline.config import TZ_BJ, SIGNAL_FAMILY_TAXONOMY  # noqa: E402

OUT = ROOT / "data" / "_exp_buy1_gate.json"
REPLAY = ROOT / "data" / "_exp_v2t9_win_replay.json"

CONSIST_TOL = 0.05      # 日级偏差 <5% 计「一致」
GATE_GLOBAL = 95.0      # 全局一致率门槛
GATE_PER_ITEM = 80.0    # 任一品低于此 → 不通过
SMALL_BASE = 10         # buy_num 中位数 <10 视为小基数（日间跳变噪声大）


def log(msg: str):
    print(msg, flush=True)


def fetch_1095(good_id: int, key: str):
    resp = _api_call("POST", "/info/chart", {
        "good_id": str(good_id), "key": key, "platform": 2,
        "period": "1095", "style": "all_style",
    })
    if resp.get("code") != 200 or not isinstance(resp.get("data"), dict):
        return None, f"code={resp.get('code')}"
    return resp["data"], None


def daily_last(data: dict) -> dict:
    """main_data -> {date: last_value}（按 timestamp 升序，同日后者覆盖前者=末点）。"""
    out = {}
    ts = data.get("timestamp") or []
    vals = data.get("main_data") or []
    for i in range(min(len(ts), len(vals))):
        try:
            t = int(ts[i])
            if t < 10 ** 11:
                t *= 1000
            v = float(vals[i])
        except (TypeError, ValueError):
            continue
        if t <= 0 or v <= 0:
            continue
        day = datetime.fromtimestamp(t / 1000, tz=TZ_BJ).strftime("%Y-%m-%d")
        out[day] = v
    return out


def chg30(series: dict) -> float | None:
    """series={date:last} -> 30 日前末点相对最新末点的变化 %。"""
    days = sorted(series)
    if not days:
        return None
    latest_day = days[-1]
    latest_val = series[latest_day]
    target = (datetime.fromisoformat(latest_day) - timedelta(days=30)).isoformat()
    base_day = None
    for d in days:
        if d <= target:
            base_day = d
        else:
            break
    if base_day is None:
        base_day = days[0]
    base_val = series[base_day]
    if not base_val:
        return None
    return round((latest_val - base_val) / base_val * 100.0, 2)


def select_items(conn):
    """按选样准则自动选 10 品 -> list[dict(good_id, name, tag)]。"""
    picked = {}

    # 5 品：bid_history buy_price 30d 变化最极端负值
    rows = conn.execute(
        "SELECT good_id, item_name, date, buy_price_last FROM bid_history "
        "WHERE buy_price_last IS NOT NULL ORDER BY good_id, date").fetchall()
    by_good = {}
    for r in rows:
        by_good.setdefault(r["good_id"], {"name": r["item_name"], "series": {}})
        by_good[r["good_id"]]["series"][r["date"]] = r["buy_price_last"]
    chgs = []
    for gid, info in by_good.items():
        c = chg30(info["series"])
        if c is not None:
            chgs.append((c, gid, info["name"]))
    chgs.sort()
    for c, gid, name in chgs[:5]:
        picked[gid] = {"good_id": gid, "name": name, "tag": "bid30_极端负值", "bid30_bh": c}

    # 3 品：replay panic/supply_accum 高贡献
    data = json.load(open(REPLAY, encoding="utf-8"))
    cnt = Counter()
    for s in data["signals"]:
        lbl = s.get("action_label") or ""
        for fine in SIGNAL_FAMILY_TAXONOMY["fine_order"]:
            kw = SIGNAL_FAMILY_TAXONOMY["fine_keywords"].get(fine)
            if kw and kw in lbl:
                if fine in ("panic_resonance", "panic_easing", "supply_accum"):
                    cnt[s.get("name")] += 1
                break
    for name, n in cnt.most_common():
        if len([p for p in picked.values() if p["tag"] == "panic/supply_accum"]) >= 3:
            break
        row = conn.execute("SELECT good_id, name FROM items WHERE name=? LIMIT 1", (name,)).fetchone()
        if row and row["good_id"] not in picked:
            picked[row["good_id"]] = {"good_id": row["good_id"], "name": row["name"], "tag": "panic/supply_accum"}

    # 2 品：高价 ×1 + 低价 ×1（按 bid_history 最新日期的 buy_price_last）
    hi = conn.execute("SELECT good_id, item_name FROM bid_history "
                      "WHERE date=(SELECT MAX(date) FROM bid_history) AND buy_price_last IS NOT NULL "
                      "ORDER BY buy_price_last DESC LIMIT 1").fetchone()
    lo = conn.execute("SELECT good_id, item_name FROM bid_history "
                      "WHERE date=(SELECT MAX(date) FROM bid_history) AND buy_price_last IS NOT NULL AND buy_price_last>0 "
                      "ORDER BY buy_price_last ASC LIMIT 1").fetchone()
    if hi and hi["good_id"] not in picked:
        picked[hi["good_id"]] = {"good_id": hi["good_id"], "name": hi["item_name"], "tag": "高价"}
    if lo and lo["good_id"] not in picked:
        picked[lo["good_id"]] = {"good_id": lo["good_id"], "name": lo["item_name"], "tag": "低价"}

    return [picked[g] for g in sorted(picked, key=lambda x: -x)]


def load_bid_history(conn, good_id: int):
    rows = conn.execute("SELECT date, buy_price_last, buy_num_last FROM bid_history "
                        "WHERE good_id=? AND buy_price_last IS NOT NULL", (good_id,)).fetchall()
    return {r["date"]: {"bp": r["buy_price_last"], "bn": r["buy_num_last"]} for r in rows}


def load_sell(conn, good_id: int):
    rows = conn.execute(
        "SELECT p.date, p.price_rmb FROM price_history p JOIN items i ON p.item_id=i.id "
        "WHERE i.good_id=? AND p.price_rmb IS NOT NULL AND p.price_rmb>0 ORDER BY p.date", (good_id,)).fetchall()
    return {r["date"]: r["price_rmb"] for r in rows}


def main():
    conn = db.get_conn()
    items = select_items(conn)
    log(f"selected {len(items)} items")

    results = []
    for it in items:
        gid, name = it["good_id"], it["name"]
        bp, e1 = fetch_1095(gid, "buy_price")
        bn, e2 = fetch_1095(gid, "buy_num")
        bp_d = daily_last(bp) if bp else {}
        bn_d = daily_last(bn) if bn else {}
        bh = load_bid_history(conn, gid)
        sell = load_sell(conn, gid)

        # 重叠日一致率（buy_price / buy_num）
        overlap = sorted(set(bp_d) & set(bh))
        bp_ok = bp_bad = 0
        bn_ok = bn_bad = 0
        for d in overlap:
            v = bp_d[d]; base = bh[d]["bp"]
            if base and base > 0 and abs(v - base) / base < CONSIST_TOL:
                bp_ok += 1
            else:
                bp_bad += 1
            nv = bn_d.get(d); nbase = bh[d]["bn"]
            if nbase and nbase > 0 and nv is not None and abs(nv - nbase) / nbase < CONSIST_TOL:
                bn_ok += 1
            else:
                bn_bad += 1
        bp_rate = round(100.0 * bp_ok / (bp_ok + bp_bad), 1) if (bp_ok + bp_bad) else None
        bn_rate = round(100.0 * bn_ok / (bn_ok + bn_bad), 1) if (bn_ok + bn_bad) else None
        bn_vals = [bh[d]["bn"] for d in overlap if bh[d]["bn"] is not None]
        bn_median = sorted(bn_vals)[len(bn_vals) // 2] if bn_vals else None
        small_base = bn_median is not None and bn_median < SMALL_BASE

        bid30_direct = chg30(bp_d)
        bid30_bh = chg30({d: bh[d]["bp"] for d in bh if bh[d]["bp"]})
        sell30 = chg30(sell)
        sign_agree = None
        if bid30_direct is not None and sell30 is not None:
            sign_agree = (bid30_direct > 0) == (sell30 > 0)

        results.append({
            "good_id": gid, "name": name, "tag": it["tag"],
            "overlap_days": len(overlap),
            "buy_price_rate": bp_rate, "buy_price_ok": bp_ok, "buy_price_bad": bp_bad,
            "buy_num_rate": bn_rate, "buy_num_ok": bn_ok, "buy_num_bad": bn_bad,
            "buy_num_median": bn_median, "small_base": small_base,
            "bid30_direct": bid30_direct, "bid30_bh": bid30_bh, "sell30": sell30,
            "bid_sell_sign_agree": sign_agree,
            "fetch_err": (e1 or "") + ((";" + e2) if e2 else ""),
        })
        log(f"  good={gid:>6} bp_rate={bp_rate} bn_rate={bn_rate} small_base={small_base} "
            f"bid30_direct={bid30_direct} sell30={sell30} sign_agree={sign_agree} {name[:20]}")

    # 三档结论
    tot_ok = sum(r["buy_price_ok"] for r in results)
    tot_bad = sum(r["buy_price_bad"] for r in results)
    global_rate = round(100.0 * tot_ok / (tot_ok + tot_bad), 1) if (tot_ok + tot_bad) else None
    any_below_80 = any(r["buy_price_rate"] is not None and r["buy_price_rate"] < GATE_PER_ITEM for r in results)
    divergent = [r for r in results if r["bid_sell_sign_agree"] is False]
    price_ok = global_rate is not None and global_rate >= GATE_GLOBAL and not any_below_80
    bid_ok = len(divergent) == 0
    if price_ok and bid_ok:
        tier = "通过"
    elif price_ok and not bid_ok:
        tier = "有条件通过"
    else:
        tier = "不通过"

    bid30_direct_vals = [r["bid30_direct"] for r in results if r["bid30_direct"] is not None]
    bid30_direct_median = round(sorted(bid30_direct_vals)[len(bid30_direct_vals) // 2], 1) if bid30_direct_vals else None
    agree = [r for r in results if r["bid_sell_sign_agree"] is not None]
    sign_agree_rate = round(100.0 * sum(1 for r in agree if r["bid_sell_sign_agree"]) / len(agree), 1) if agree else None

    out = {
        "probe": "BUY-1 10品口径验证探针",
        "generated": datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "baseline_doc": "references/optimization-initiation-2026-08-15.md",
        "ruler": "直连 period=1095 vs bid_history（直连 90d）；一致=日级偏差<5%；gate=全局>=95% 且任一品>=80%；bid_30d_chg 定量=中位数 + 与售价 sign 一致率",
        "global": {
            "buy_price_rate": global_rate, "any_item_below_80": any_below_80,
            "bid30_direct_median": bid30_direct_median, "sign_agree_rate": sign_agree_rate,
            "divergent_count": len(divergent),
        },
        "conclusion": tier,
        "items": results,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"\n=== 三档结论：{tier} ===")
    log(f"global buy_price_rate={global_rate}% any_below_80={any_below_80} "
        f"bid30_direct_median={bid30_direct_median} sign_agree_rate={sign_agree_rate} divergent={len(divergent)}")
    log(f"wrote {OUT}")
    conn.close()


if __name__ == "__main__":
    main()
