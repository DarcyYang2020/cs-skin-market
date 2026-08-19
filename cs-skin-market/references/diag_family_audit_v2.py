# -*- coding: utf-8 -*-
"""诊断 v2（只读）：189 信号族划分 + 信号丢失 + 池子品类覆盖 三子题根因诊断。

产出 data/_exp_family_audit_2026-08-19.json（原始产物，交③审计独立判）。
不写生产库、不改任何引擎/展示代码。数据源：
  - data/_exp_cycle_replay_period_route.json（189 信号，v2-T13 官方 HQ）
  - data/replay_cycle_win.db（回放库，只读）
"""
import json
import sqlite3
import collections

ROOT = "data"
REPLAY = f"{ROOT}/_exp_cycle_replay_period_route.json"
DB = f"{ROOT}/replay_cycle_win.db"

d = json.load(open(REPLAY, encoding="utf-8"))
sigs = d["signals"]

out = {"meta": {"date": "2026-08-19", "role": "algorithm-research (read-only diagnosis)",
                "replay": REPLAY, "db": DB, "n_signals": len(sigs),
                "caliber": "v2-T13 official HQ, CS_ENGINE_PERIOD_ROUTE=1"}}

# ---------- 子题①：族划分三口径对照 ----------
by_al = collections.Counter(s["action_label"] for s in sigs)
by_st = collections.Counter(s.get("signal_type") or "?" for s in sigs)
by_tl = collections.Counter(s.get("type_label") or "?" for s in sigs)
out["family_distribution"] = {
    "by_action_label": dict(by_al.most_common()),
    "by_signal_type": dict(by_st.most_common()),
    "by_type_label": dict(by_tl.most_common()),
    "note": "signal_type 来自展示层 signal_guidance 关键字归类(恐慌→panic/超跌→oversold/长持→longhold/吸筹→accumulate/else→base)，与 config.SIGNAL_FAMILY_TAXONOMY 6细族+3展示键、引擎11族注册制 是互不一致的三套口径。",
}

# ---------- 子题②：按月信号 + 恐慌族时间 ----------
bym = collections.defaultdict(int)
for s in sigs:
    bym[s["date"][:7]] += 1
out["monthly_signal_count"] = {m: bym[m] for m in sorted(bym)}

panic = [s for s in sigs if (s.get("signal_type") or "").startswith("panic")]
out["panic_family"] = {
    "n": len(panic),
    "date_range": [min(s["date"] for s in panic), max(s["date"] for s in panic)],
    "note": "panic 族 73 条全部集中在 2026-04-23~05-30 两次事件簇；2025 年两次恐慌事件(5/14、7/21)零捕捉。",
}

# 大盘关键事件跌幅（21/30 交易日窗口）
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("SELECT date, value FROM market_index ORDER BY date")
rows = cur.fetchall()
dates = [r[0] for r in rows]
idx = {r[0]: r[1] for r in rows}
def _chg(day, n):
    i = dates.index(day)
    if i - n < 0:
        return None
    return round((idx[day] / rows[i - n][1] - 1) * 100, 2)

events = {}
for day in ["2025-05-14", "2025-07-21", "2026-05-22", "2026-04-23"]:
    if day in idx:
        events[day] = {"value": round(idx[day], 0),
                       "chg7": _chg(day, 7), "chg21": _chg(day, 21), "chg30": _chg(day, 30)}
out["market_panic_events"] = events
out["panic_trigger_thresholds"] = {
    "panic_resonance": "drop21<=-18 且 sent>=75 且 pct<=15 且 z<=-1.5 且 microTH>=60",
    "panic_easing": "mchg30<=-15 且 55<=sent<=80 且 pct<=20 且 z<=-1 且 stopped",
    "finding": "2025-05-14(chg7=-20%)/07-21(chg7=-12.7%) 为急跌快反弹型，chg21(-8.3%/-11.0%)不满足 drop21<=-18、chg30(-5.4%/-7.7%)不满足 mchg30<=-15 → 双双漏触发。恐慌族以大盘深度跌幅为前提，天然排除急跌型恐慌。",
}

# macro_history 覆盖
cur.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM macro_history")
mh = cur.fetchone()
out["macro_history_coverage"] = {"min": mh[0], "max": mh[1], "n": mh[2],
                                 "finding": "真实贪婪指数仅覆盖 2026-02 起，2025 年 sent 全为价格近似情绪(与 PANIC-ALIGN-1 阶段0一致)。"}

# ---------- 子题③：池子品类覆盖 ----------
cur.execute("SELECT name FROM items")
names = [r[0] for r in cur.fetchall()]
def _cat(n):
    return n.split("|", 1)[0].strip()
cats = collections.Counter(_cat(n) for n in names)
out["pool_category_distribution"] = dict(cats.most_common())
out["pool_singleton_categories"] = [k for k, v in cats.items() if v == 1]

# 孤品数据覆盖
out["singleton_items_coverage"] = {}
for name in ["运动手套（★） | 树篱迷宫 (久经沙场)", "德拉戈米尔 | 军刀勇士", "M4A4 | 合纵 (崭新出厂)"]:
    cur.execute("SELECT id FROM items WHERE name=?", (name,))
    r = cur.fetchone()
    if r:
        cur.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM price_history WHERE item_id=?", (r[0],))
        mn, mx, cnt = cur.fetchone()
        out["singleton_items_coverage"][name] = {"min": mn, "max": mx, "n": cnt}

# price_history 池子扩容节点
cur.execute("SELECT substr(date,1,7) m, COUNT(DISTINCT item_id) FROM price_history GROUP BY m ORDER BY m")
ph = cur.fetchall()
out["price_history_pool_growth"] = {m: n for m, n in ph}
conn.close()

# 信号物品覆盖
byn = collections.Counter(s["name"] for s in sigs)
out["signal_item_coverage"] = {
    "n_distinct_items": len(byn),
    "n_singleton_items": sum(1 for v in byn.values() if v == 1),
    "singleton_items": [k for k, v in byn.items() if v == 1],
    "no_glove_no_knife": "189 信号无手套(树篱迷宫)/匕首(德拉戈米尔)任何信号。",
}

json.dump(out, open(f"{ROOT}/_exp_family_audit_2026-08-19.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"saved {ROOT}/_exp_family_audit_2026-08-19.json")
print(json.dumps(out, ensure_ascii=False, indent=1))
