# -*- coding: utf-8 -*-
"""模拟盘生产初始化 + 历史信号补账（2026-08-17，一次性；幂等）。

背景：v2 模拟盘落地后 paper_* 表从未在生产库初始化（每日任务异常被静默吞掉，
日志仅剩「模拟盘执行异常」），前端也一直无展示。本脚本：
  1) ensure_schema 建 paper_account/positions/trades/baseline；
  2) 把 signal_tracking 现存历史 buy 信号按信号日补开仓（与 daily_run 同口径镜像）；
  3) 用当前价格结算三类出场（供给扩张全止损 > 止盈/止损 > 到期）；
  4) 更新等权基准腿 + 写 data/paper_trading_status.json。
幂等：已存在持仓/已镜像信号不重复开；可安全重跑。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db  # noqa: E402
from pipeline import paper_trading as pt  # noqa: E402
from pipeline.signal_tracking import family_key_for_label  # noqa: E402


def sc30_at(conn, item_id, signal_date):
    rows = conn.execute(
        "SELECT date, in_sale_count FROM price_history WHERE item_id=? AND in_sale_count IS NOT NULL "
        "AND date<=? ORDER BY date", (item_id, signal_date)).fetchall()
    if len(rows) < 60:
        return None
    s30 = sum(r["in_sale_count"] for r in rows[-30:]) / 30
    s30a = sum(r["in_sale_count"] for r in rows[-60:-30]) / 30
    return (s30 / s30a - 1) * 100 if s30a > 0 else None


def main():
    conn = db.get_conn()
    try:
        pt.ensure_schema(conn)
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT * FROM signal_tracking WHERE action IN ('buy','oversold_buy') "
            "AND signal_date<=? ORDER BY signal_date", (today,)).fetchall()
        mirrored = {r["item_name"] + r["signal_date"] + (r["action_label"] or "")
                    for r in conn.execute(
                        "SELECT item_name, signal_date, action_label FROM paper_positions")}
        opened = 0
        for s in rows:
            key = s["item_name"] + s["signal_date"] + (s["action_label"] or "")
            if key in mirrored:
                continue
            pid = pt.open_position(
                conn, item_id=s["item_id"], item_name=s["item_name"],
                family=family_key_for_label(s["action_label"] or ""),
                action_label=s["action_label"] or "",
                signal_date=s["signal_date"], entry_price=s["entry_price"],
                limit_pct=s["position_limit"] or 0.10,
                sentiment_score=s["sentiment"] if s["sentiment"] is not None else 50,
                sc30=sc30_at(conn, s["item_id"], s["signal_date"]))
            if pid:
                opened += 1
                print("opened:", s["item_name"], s["signal_date"], "limit=%.2f" % (s["position_limit"] or 0.10))
        closed = pt.settle_exits(conn, pt._latest_prices(conn), pt._sc30_now(conn))
        for c in closed:
            print("closed:", c)
        pt._baseline_update(conn)
        st = pt.status(conn)
        with open(pt.STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump({**st, "date": today, "closed_today": closed, "opened_today": opened},
                      f, ensure_ascii=False, indent=1)
        print("status:", json.dumps(st, ensure_ascii=False))
        print("wrote", pt.STATUS_PATH)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
