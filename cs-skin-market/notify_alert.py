# -*- coding: utf-8 -*-
"""Alert notifier: push health-check FAIL / collect errors to DingTalk robot webhook (optional).

Usage:
    python notify_alert.py --monitor             # run health monitor, push on FAIL (no pipe encoding issues)
    python notify_alert.py --title "CS alert" --text "collect FAIL: check network"

Config: NOTIFY_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx  in root .env
Exit codes: 0 = no push needed / pushed / webhook not configured (non-blocking); 2 = push failed
"""
import sys, os, json, argparse, urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENV_PATH = BASE / ".env"


def load_webhook_url():
    if "NOTIFY_WEBHOOK_URL" in os.environ:
        return os.environ["NOTIFY_WEBHOOK_URL"].strip()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NOTIFY_WEBHOOK_URL="):
                return line.split("=", 1)[1].strip()
    return ""


def send(title, text, url, timeout=10):
    payload = json.dumps({
        "msgtype": "text",
        "text": {"content": f"{title}\n{text}"},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def monitor_mode():
    """Run health monitor directly (no stdin pipe -> no encoding issues on Windows)."""
    try:
        import run_health_monitor as rhm
        summary = rhm.run_monitor()
    except Exception as exc:
        return _push("CS health monitor error", f"monitor itself failed: {exc}")
    if summary.get("status") != "fail":
        return 0
    fails = [c for c in summary.get("checks", []) if c.get("level") == "FAIL"]
    text = "\n".join(f"- {c.get('name')}: {c.get('detail', '')}" for c in fails[:10])
    title = f"CS health FAIL ({summary.get('date', '')}, {len(fails)} item(s))"
    return _push(title, text)


def _push(title, text):
    url = load_webhook_url()
    if not url:
        print("notify: NOTIFY_WEBHOOK_URL not configured, skipped (add to .env for alerts)")
        return 0
    try:
        status = send(title, text, url)
        print(f"notify: pushed HTTP {status}")
        return 0
    except Exception as exc:
        print(f"notify: push failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="CS alert")
    ap.add_argument("--text", default="")
    ap.add_argument("--monitor", action="store_true", help="run health monitor and push on FAIL")
    args = ap.parse_args()
    sys.exit(monitor_mode() if args.monitor else _push(args.title, args.text))