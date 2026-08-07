# -*- coding: utf-8 -*-
"""J-2 重拟合三通道监测（2026-08-07 J-2 修订落地，展示层）。

读 item_backtest_full_2025.json（370 信号）+ signal_event_counts.json（事件计数），
计算三通道状态：
  A. 独立恐慌市场事件 >=3（自然积累，不阻塞）
  B. 冻结后新数据累计 >=260 天（约 2027-04-25，与 PARAM_FREEZE.oos_revalidate_after 一致）
  C. 胜率监测：buy 连续 2 月 14d<70% 或月度 14d<80%/30d<55%
输出 data/j2_channel_status.json，dashboard 数据积累进度卡渲染。
口径注意：C 通道当前为「去量 v2 370 信号回放」近似（生产实盘信号跟踪尚未建立）；
5 月恐慌单事件簇退出集中在 6 月，低胜率月度须按事件簇纪律（±3~7 天簇限次）复核。
"""
import io
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPLAY = BASE / "data" / "item_backtest_full_2025.json"
SIGNAL_EVENTS = BASE / "data" / "signal_event_counts.json"
OUT = BASE / "data" / "j2_channel_status.json"

FROZEN_AT = "2026-08-07"
OOS_AFTER = "2027-04-25"
A_THRESHOLD = 3
B_THRESHOLD_DAYS = 260
C14_MONTH = 80.0
C30_MONTH = 55.0
C14_2M = 70.0
CLUSTER_GAP = 4  # 同簇定义：距上一保留信号 <4 天则跳过（±3 天簇，与 j1_event_counts 一致）


def _load(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def _cluster_dedup(recs):
    kept = []
    last = None
    for s in sorted(recs, key=lambda x: x["date"]):
        if last is None:
            kept.append(s)
            last = s["date"]
        else:
            d0 = date.fromisoformat(last)
            d1 = date.fromisoformat(s["date"])
            if (d1 - d0).days >= CLUSTER_GAP:
                kept.append(s)
                last = s["date"]
    return kept


def _wr(recs, field):
    v = [s[field] for s in recs if isinstance(s.get(field), (int, float))]
    if not v:
        return None, 0
    return round(100.0 * sum(1 for x in v if x > 0) / len(v), 1), len(v)


def _monthly(sigs):
    by_month = defaultdict(list)
    for s in sigs:
        by_month[s.get("date", "")[:7]].append(s)
    out = {}
    for m in sorted(by_month):
        grp = by_month[m]
        dg = _cluster_dedup(grp)
        w14, n14 = _wr(grp, "fwd14")
        w30, n30 = _wr(grp, "fwd30")
        d14, dn14 = _wr(dg, "fwd14")
        d30, dn30 = _wr(dg, "fwd30")
        out[m] = {
            "n": len(grp), "win14": w14, "win30": w30,
            "dedup_n": len(dg), "dedup_win14": d14, "dedup_win30": d30,
        }
    return out


def _channel_c(sigs):
    monthly = _monthly(sigs)
    rows = []
    months = sorted(monthly)
    for m in months:
        r = monthly[m]
        flags = []
        if r["n"] >= 10:
            if r["win14"] is not None and r["win14"] < C14_MONTH:
                flags.append("14d " + str(r["win14"]) + "% < " + str(int(C14_MONTH)) + "%")
            if r["win30"] is not None and r["win30"] < C30_MONTH:
                flags.append("30d " + str(r["win30"]) + "% < " + str(int(C30_MONTH)) + "%")
        if r["dedup_n"] >= 10:
            if r["dedup_win14"] is not None and r["dedup_win14"] < C14_MONTH:
                flags.append("去簇14d " + str(r["dedup_win14"]) + "% < " + str(int(C14_MONTH)) + "%")
            if r["dedup_win30"] is not None and r["dedup_win30"] < C30_MONTH:
                flags.append("去簇30d " + str(r["dedup_win30"]) + "% < " + str(int(C30_MONTH)) + "%")
        rows.append({"month": m, "n": r["n"], "win14": r["win14"], "win30": r["win30"],
                     "dedup_n": r["dedup_n"], "dedup_win14": r["dedup_win14"],
                     "dedup_win30": r["dedup_win30"], "flags": flags})
    two_month = []
    for i in range(1, len(months)):
        m1, m2 = months[i - 1], months[i]
        w1, w2 = monthly[m1]["win14"], monthly[m2]["win14"]
        if w1 is not None and w2 is not None and w1 < C14_2M and w2 < C14_2M:
            two_month.append(m1 + "+" + m2 + " 连续2月14d " + str(w1) + "%/" + str(w2) + "% < " + str(int(C14_2M)) + "%")
    return {"monthly": rows, "two_month_flags": two_month}


def compute():
    replay = _load(REPLAY)
    events = _load(SIGNAL_EVENTS)
    sigs = replay["signals"]

    panic_events = (events.get("display_keys") or {}).get("panic", {}).get("events", 0)
    a_pct = round(100.0 * panic_events / A_THRESHOLD, 1)

    today = date.today()
    frozen = date.fromisoformat(FROZEN_AT)
    days = max(0, (today - frozen).days)
    b_pct = round(100.0 * days / B_THRESHOLD_DAYS, 1)

    c = _channel_c(sigs)

    channels = {
        "A": {
            "label": "独立恐慌市场事件",
            "value": panic_events, "threshold": A_THRESHOLD,
            "progress_pct": a_pct,
            "status": "已达标" if panic_events >= A_THRESHOLD else "积累中",
            "note": "事件不可控，自然积累不阻塞；当前 2025-10 五合一 / 2026-05 恐慌深跌 2 个独立事件",
        },
        "B": {
            "label": "冻结后新数据积累",
            "value_days": days, "threshold_days": B_THRESHOLD_DAYS,
            "progress_pct": b_pct, "target_date": OOS_AFTER,
            "status": "已达标" if days >= B_THRESHOLD_DAYS else "积累中",
            "note": "自冻结起点 " + FROZEN_AT + " 起累计新数据；满 " + str(B_THRESHOLD_DAYS) +
                    " 天（约 " + OOS_AFTER + "）即真 OOS 复验点",
        },
        "C": {
            "label": "胜率监测（月度 14d/30d vs 阈值）",
            "monthly": c["monthly"],
            "two_month_flags": c["two_month_flags"],
            "thresholds": {"14d_month": C14_MONTH, "30d_month": C30_MONTH, "14d_2m": C14_2M},
            "status": "已触发" if (c["two_month_flags"] or any(r["flags"] for r in c["monthly"])) else "未触发",
            "note": "口径=去量 v2 370 信号回放（生产实盘信号跟踪未建立）；月度 n>=10 才判定；去簇(±3天) n>=10 才判定；"
                    "5 月恐慌单事件簇退出集中在 6 月，低胜率月度须按事件簇纪律复核后再定",
        },
    }

    triggered = [k for k, v in channels.items() if v["status"] in ("已达标", "已触发")]
    return {
        "generated": today.isoformat(),
        "frozen_at": FROZEN_AT,
        "oos_revalidate_after": OOS_AFTER,
        "channels": channels,
        "overall": {
            "triggered": bool(triggered),
            "triggered_channels": triggered,
            "note": "J-2 三通道任一满足即解锁重拟合：A 事件>=3 / B 新数据>=260 天 / C 胜率监测触发",
        },
    }


def main():
    d = compute()
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("written:", OUT)


if __name__ == "__main__":
    main()