# -*- coding: utf-8 -*-
"""推送→执行归因（D-3，2026-08-10，纯查询脚本）。

目标：度量「监控推送建议 → 用户执行」的转化，为 F-7（钉钉卡片一键执行）攒前置数据。

口径：
- 推送事件 = monitor_events 中可操作类型（new_buy_signal / near_buy / stop_loss / decision_flip），
  事件按 date 分组（与 M2 推送同源；推送幂等键 monitor_push_{date}_{slot}）。
- 执行 = executions.advice_date 同日、同 item_name 的记录（手动录入默认 source=manual；
  未来前端带 push:{push_id} 后可精确关联，本脚本先按 日期+品名 近似匹配）。
- 转化率 = 有执行匹配的推送品数 / 当日推送可操作品数。

输出: data/push_exec_attribution.json；样例数据少时给出「样本不足」提示。
"""
import io
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "push_exec_attribution.json"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
ACTIONABLE = {"new_buy_signal", "near_buy", "stop_loss", "decision_flip"}


def main(days=14):
    from pipeline import db
    conn = db.get_conn()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    ev = conn.execute(
        "SELECT date, item_name, event_type FROM monitor_events "
        "WHERE date >= ? AND event_type IN ('new_buy_signal','near_buy','stop_loss','decision_flip') "
        "ORDER BY date", (cutoff,)).fetchall()
    ex = conn.execute(
        "SELECT advice_date, name FROM executions WHERE advice_date >= ?", (cutoff,)).fetchall()
    conn.close()

    push = defaultdict(set)
    for r in ev:
        push[r["date"]].add(r["item_name"] or "")
    exec_by_day = defaultdict(set)
    for r in ex:
        exec_by_day[r["advice_date"]].add(r["name"] or "")

    days_out = []
    total_push = total_exec = total_matched = 0
    for d in sorted(push):
        pushed = {p for p in push[d] if p}
        done = exec_by_day.get(d, set())
        matched = pushed & done
        days_out.append({
            "date": d,
            "pushed_items": len(pushed),
            "exec_items": len(done),
            "matched_items": len(matched),
            "matched_names": sorted(matched)[:10],
            "conversion_pct": round(100.0 * len(matched) / len(pushed), 1) if pushed else None,
        })
        total_push += len(pushed)
        total_exec += len(done)
        total_matched += len(matched)

    out = {
        "meta": "推送→执行归因(D-3, 2026-08-10)：monitor_events 可操作事件 vs executions 同日同品近似匹配；"
                "精确归因待前端带 push:{push_id} 后启用（executions.source 列已就绪）。",
        "generated": date.today().isoformat(),
        "window_days": days,
        "daily": days_out,
        "totals": {
            "pushed_items": total_push, "exec_items": total_exec, "matched_items": total_matched,
            "conversion_pct": round(100.0 * total_matched / total_push, 1) if total_push else None,
        },
        "note": "样本不足时转化率仅作参考；executions 累积 >=20 条后再做置信统计。",
    }
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written:", OUT)
    print("totals:", out["totals"])


if __name__ == "__main__":
    main()
