# -*- coding: utf-8 -*-
"""运维 CLI（Wave6 O1–O4，2026-08-27）：kill switch / 审计 / 告警 / 交易监控。

独立于 webapp（直接读写状态文件/台账），webapp 卡死时仍可触发 —— O2「独立于业务链」判据。

用法:
    python ops_tool.py kill-switch status
    python ops_tool.py kill-switch on global  --by <who> --reason <原因> [--ref <decision-log 条目>]
    python ops_tool.py kill-switch off paper  --by <who> --reason <原因>
    python ops_tool.py audit [--limit 50] [--key kill_switch.paper]
    python ops_tool.py monitor [--db PATH] [--status-path PATH]
    python ops_tool.py alert --level trade --title "标题" --text "正文" [--dry-run]

参数/配置变更请走 config_audit（kill switch 命令已自动落审计台账）；告警分级走 O4 路由。
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

if sys.stdout is sys.__stdout__:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _cmd_kill(args):
    from pipeline.ops import kill_switch_state, set_kill_switch
    if args.action == "status":
        st = kill_switch_state()
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return 0
    scope = args.scope
    if scope not in ("global", "paper", "notify"):
        print(f"scope 必须为 global/paper/notify，收到 {scope!r}", file=sys.stderr)
        return 2
    blocked = args.action == "on"
    if not args.reason:
        print("--reason 必填（审计留痕）", file=sys.stderr)
        return 2
    st = set_kill_switch(scope, blocked, by=args.by or "cli", reason=args.reason,
                         decision_log_ref=args.ref)
    print(json.dumps(st, ensure_ascii=False, indent=1))
    return 0


def _cmd_audit(args):
    from pipeline.ops import list_audit
    rows = list_audit(limit=args.limit, key=args.key)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    print(f"-- {len(rows)} 条 --")
    return 0


def _cmd_monitor(args):
    from pipeline.ops import run_ops_monitor
    res = run_ops_monitor(db_path=args.db, status_path=args.status_path)
    for c in res["checks"]:
        mark = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]"}.get(c["level"], f"[{c['level']}]")
        print(f"{mark} {c['name']}: {c['detail']}")
    print(f"== status={res['status']} FAIL={res['fail_count']} auto_killed={res['auto_killed'] or '无'} ==")
    for a in res.get("alerts", []):
        print(f"  告警[{a['level']}] {a['title']}: {a['text']}")
    return 2 if res["fail_count"] else 0


def _cmd_alert(args):
    from notify_alert import route_alert
    r = route_alert(level=args.level, title=args.title, text=args.text, dry_run=args.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("pushed") else 2


def main():
    ap = argparse.ArgumentParser(description="CS-Market 运维 CLI（Wave6 O1–O4）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_kill = sub.add_parser("kill-switch", help="O2 kill switch（全局/策略级，自动落审计）")
    p_kill.add_argument("action", choices=["on", "off", "status"])
    p_kill.add_argument("scope", nargs="?", default=None, help="global/paper/notify（status 可省略）")
    p_kill.add_argument("--by", default=None, help="操作人（默认 cli）")
    p_kill.add_argument("--reason", default=None, help="原因（必填，审计留痕）")
    p_kill.add_argument("--ref", default=None, help="decision-log 条目引用")
    p_kill.set_defaults(fn=_cmd_kill)

    p_audit = sub.add_parser("audit", help="O3 操作审计台账查询")
    p_audit.add_argument("--limit", type=int, default=50)
    p_audit.add_argument("--key", default=None)
    p_audit.set_defaults(fn=_cmd_audit)

    p_mon = sub.add_parser("monitor", help="O1 交易级监控（手动跑）")
    p_mon.add_argument("--db", default=None)
    p_mon.add_argument("--status-path", default=None)
    p_mon.set_defaults(fn=_cmd_monitor)

    p_alert = sub.add_parser("alert", help="O4 告警分级推送")
    p_alert.add_argument("--level", choices=["collect", "quality", "trade"], default="collect")
    p_alert.add_argument("--title", required=True)
    p_alert.add_argument("--text", default="")
    p_alert.add_argument("--dry-run", action="store_true")
    p_alert.set_defaults(fn=_cmd_alert)

    args = ap.parse_args()
    try:
        sys.exit(args.fn(args))
    except Exception as e:
        print(f"ops_tool 错误: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
