# -*- coding: utf-8 -*-
"""J-2 C 通道事件簇纪律复核（只读）。

背景：j2_channel_status.json C 通道已触发（replay 口径 14d 多月 <80%、30d 2026-03/06 <55%），
note 明确「5 月恐慌单事件簇退出集中在 6 月须按事件簇纪律复核」。
本脚本在 v2-T4 标准产物（317 信号）上：
1) 复现月度口径统计（对照 j2 monthly）
2) 按 ±3 天事件簇聚合，给出每簇 n/win14/avg14/win30/avg30
3) 拆分恐慌簇（2026-05-28 附近）与其余簇，判断劣化是否单一事件主导

产物：data/_exp_c_channel_cluster_review.json
"""
import json, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPLAY = ROOT / "data" / "item_backtest_full_2025.json"
OUT = ROOT / "data" / "_exp_c_channel_cluster_review.json"
PANIC_DATE = "2026-05-28"  # j2/决策日志中的恐慌日

def mstat(rows):
    n = len(rows)
    if n == 0:
        return {"n": 0}
    w14 = sum(1 for r in rows if r.get("net14") is not None and r["net14"] > 0)
    w30 = sum(1 for r in rows if r.get("net30") is not None and r["net30"] > 0)
    a14 = [r["net14"] for r in rows if r.get("net14") is not None]
    a30 = [r["net30"] for r in rows if r.get("net30") is not None]
    return {
        "n": n,
        "win14": round(100.0 * w14 / len(a14), 1) if a14 else None,
        "avg14": round(statistics.mean(a14), 2) if a14 else None,
        "win30": round(100.0 * w30 / len(a30), 1) if a30 else None,
        "avg30": round(statistics.mean(a30), 2) if a30 else None,
        "filled14": len(a14), "filled30": len(a30),
    }

def main():
    d = json.load(open(REPLAY, encoding="utf-8"))
    sigs = d["signals"]
    win = [s for s in sigs if "2026-04-01" <= s["date"] <= "2026-07-31"]
    out = {"source": "item_backtest_full_2025.json (v2-T4 317)", "window": ["2026-04-01", "2026-07-31"],
           "n_in_window": len(win)}

    # 1) 月度口径（与 j2 monthly 对照）
    monthly = {}
    for m in sorted(set(s["date"][:7] for s in win)):
        rows = [s for s in win if s["date"][:7] == m]
        st = mstat(rows)
        st["flags"] = [f for f, v in (("14d", st["win14"]), ("30d", st["win30"])) if v is not None and (v < 80 if f == "14d" else v < 55)]
        monthly[m] = st
    out["monthly"] = monthly

    # 2) 事件簇聚合（±3 天）
    dates = sorted(set(s["date"] for s in win))
    clusters = []
    for dt in dates:
        if not clusters or (__import__("datetime").date.fromisoformat(dt) - __import__("datetime").date.fromisoformat(clusters[-1]["end"])).days > 3:
            clusters.append({"start": dt, "end": dt})
        else:
            clusters[-1]["end"] = dt
    for c in clusters:
        rows = [s for s in win if c["start"] <= s["date"] <= c["end"]]
        st = mstat(rows)
        st["is_panic_cluster"] = c["start"] <= PANIC_DATE <= c["end"]
        st["month"] = c["start"][:7]
        c.update(st)
    out["clusters"] = clusters

    # 3) 恐慌簇 vs 非恐慌簇（5 月恐慌簇退出集中在 6 月 = 5/28 簇 fwd30 在 6/27 到期）
    panic_clusters = [c for c in clusters if c["is_panic_cluster"]]
    panic_rows = []
    for pc in panic_clusters:
        panic_rows += [s for s in win if pc["start"] <= s["date"] <= pc["end"]]
    panic_keys = set((s["name"], s["date"]) for s in panic_rows)
    non_panic = [s for s in win if (s["name"], s["date"]) not in panic_keys]
    out["panic_vs_non"] = {
        "panic_cluster": mstat(panic_rows),
        "non_panic_rest": mstat(non_panic),
    }

    # 4) 6 月信号内部分解：是否仍有独立劣化（去 5 月恐慌簇后）
    jun = [s for s in win if s["date"][:7] == "2026-06"]
    jun_nonpanic = [s for s in jun if (s["name"], s["date"]) not in panic_keys]
    out["june_split"] = {"june_all": mstat(jun), "june_excl_panic_entry": mstat(jun_nonpanic)}

    # 5) 结论判定
    j6 = out["june_split"]["june_all"]; j6x = out["june_split"]["june_excl_panic_entry"]
    concl = []
    if j6.get("win30") is not None and j6["win30"] < 55:
        concl.append("6 月 30d 胜率 <55% 触发 flag")
    if j6x.get("n", 0) <= 0:
        concl.append("6 月信号全部来自恐慌簇相关时段，无法独立判定")
    elif j6x.get("win30") is not None and j6x["win30"] >= 55:
        concl.append("剔除恐慌簇入场后 6 月 30d 胜率恢复 >=55% → 劣化由恐慌事件簇主导（事件级外推性存疑，非全月系统性劣化）")
    else:
        concl.append("剔除恐慌簇后 6 月 30d 仍 <55%（n=" + str(j6x.get("n")) + "）→ 存在非恐慌簇劣化，需继续观察")
    out["conclusion"] = "; ".join(concl)

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])

if __name__ == "__main__":
    main()