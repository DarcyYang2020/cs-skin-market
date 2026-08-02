"""Event calendar manager (P1): maintain risk-event windows that dampen buy signals.

Events are V社活动 / 新箱 / Major 等短窗口风险事件，
在日程窗口内通过 event_risk_coefficient() 抑制大盘与单品的 buy 信号。
系数范围 0.5~1.0，越低风险越大，同日多个事件取最低系数。

Usage:
  python manage_events.py list
  python manage_events.py add "新箱发布" 2026-08-05 2026-08-20 0.85 "补充说明"
  python manage_events.py del 3
"""
import sys, argparse
sys.path.insert(0, ".")
from pipeline import db


def main():
    p = argparse.ArgumentParser(description="事件日历管理")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出所有事件")
    a = sub.add_parser("add", help="新增事件")
    a.add_argument("name")
    a.add_argument("start_date")
    a.add_argument("end_date")
    a.add_argument("coefficient", type=float, default=1.0)
    a.add_argument("note", nargs="?", default="")
    d = sub.add_parser("del", help="删除事件")
    d.add_argument("event_id", type=int)
    args = p.parse_args()

    conn = db.get_conn()
    try:
        if args.cmd == "list":
            rows = db.list_events(conn)
            if not rows:
                print("(暂无事件)")
            for r in rows:
                print("#%d  %s  %s ~ %s  coeff=%s  note=%s" % (r["id"], r["name"], r["start_date"], r["end_date"], r["coefficient"], r["note"]))
        elif args.cmd == "add":
            eid = db.add_event(conn, args.name, args.start_date, args.end_date, args.coefficient, args.note)
            conn.commit()
            print(f"added #{eid}: {args.name} {args.start_date}~{args.end_date} coeff={max(0.5, min(1.0, args.coefficient))}")
        elif args.cmd == "del":
            db.delete_event(conn, args.event_id)
            conn.commit()
            print(f"deleted #{args.event_id}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
