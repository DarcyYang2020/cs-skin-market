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


def load_webhook_secret():
    """G-2（2026-08-10）钉钉加签 secret（可选）：.env NOTIFY_WEBHOOK_SECRET。"""
    if "NOTIFY_WEBHOOK_SECRET" in os.environ:
        return os.environ["NOTIFY_WEBHOOK_SECRET"].strip()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NOTIFY_WEBHOOK_SECRET="):
                return line.split("=", 1)[1].strip()
    return ""


def _level_webhook(level):
    """O4 告警分级路由：每级可选独立 webhook（env 覆盖），缺省走基础 NOTIFY_WEBHOOK_URL。

    路由规则在 config.OPS_RULES["alerts"]（单一事实源）。
    """
    try:
        from pipeline.config import OPS_RULES
        env_name = OPS_RULES["alerts"]["webhook_env"].get(level, "")
    except Exception:
        env_name = ""
    if env_name and os.environ.get(env_name, "").strip():
        return os.environ[env_name].strip()
    return load_webhook_url()


def route_alert(level="collect", title="", text="", dry_run=False, data_dir=None):
    """O4 告警三档路由：采集 collect → 质量 quality → 交易 trade，到钉钉（复用加签基建）。

    - 推送前检查 kill switch(notify)：拦截仍留痕 ops_log（分级不漏报的审计面）；
    - 未配置 webhook → 返回 no_webhook（非阻断），仍写 ops_log 留痕；
    - dry_run=True 不发起 HTTP（供冒烟/调试）；data_dir 覆盖状态文件目录（测试/多环境）。
    返回: {"pushed": bool, "reason": str, "level": str, "tag": str, ...}
    """
    try:
        from pipeline.config import OPS_RULES
        levels = OPS_RULES["alerts"]["levels"]
        tags = OPS_RULES["alerts"]["tags"]
    except Exception:
        levels = ["collect", "quality", "trade"]
        tags = {"collect": "采集", "quality": "质量", "trade": "交易"}
    if level not in levels:
        raise ValueError(f"告警级别必须为 {levels}，收到 {level!r}")
    tag = tags.get(level, level)
    # S3 关键词保证（2026-08-27）：钉钉自定义机器人安全设置按关键词校验（否则 310000 拒收）。
    # O4 三档告警统一加「CS」前缀（与 monitor_mode「CS 监控 …」格式一致），
    # 用户侧机器人关键词须含「CS」（或「意向单」）方能送达——见决策日志登记。
    title = f"CS【{tag}】{title}" if title else title

    # O2 联动：kill switch 闸停通知时，只留痕不推送
    try:
        from pipeline import ops as _ops
        if _ops.is_blocked("notify", data_dir):
            _ops.log_event("warn", "alert_route", f"kill switch 拦停通知 level={level}: {title}",
                           alert_level=level, title=title, data_dir=data_dir)
            return {"pushed": False, "reason": "kill_switch_notify", "level": level, "tag": tag}
    except Exception:
        pass

    url = _level_webhook(level)
    if not url:
        try:
            from pipeline import ops as _ops
            _ops.log_event("info", "alert_route", f"webhook 未配置，跳过 level={level}: {title}",
                           alert_level=level, title=title, data_dir=data_dir)
        except Exception:
            pass
        return {"pushed": False, "reason": "no_webhook", "level": level, "tag": tag}
    if dry_run:
        return {"pushed": True, "dry_run": True, "level": level, "tag": tag, "title": title, "url": url.split("?")[0]}
    try:
        status = send(title, text, url)
        try:
            from pipeline import ops as _ops
            _ops.log_event("info", "alert_route", f"推送成功 level={level}: {title}", alert_level=level, status=status, data_dir=data_dir)
        except Exception:
            pass
        return {"pushed": True, "level": level, "tag": tag, "status": status}
    except Exception as exc:
        try:
            from pipeline import ops as _ops
            _ops.log_event("error", "alert_route", f"推送失败 level={level}: {title}: {exc}",
                           alert_level=level, title=title, data_dir=data_dir)
        except Exception:
            pass
        print(f"notify: push failed: {exc}", file=sys.stderr)
        return {"pushed": False, "reason": f"push_failed: {exc}", "level": level, "tag": tag}


def sign_webhook_url(url, secret):
    """DingTalk 加签：timestamp + HMAC-SHA256(secret) + base64 -> url 参数。

    secret 为空时原样返回（兼容旧 access_token-only 配置）。
    """
    if not secret or not url:
        return url
    import base64, hashlib, hmac, time as _time
    timestamp = str(round(_time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}timestamp={timestamp}&sign={sign}"


def send(title, text, url, timeout=10):
    url = sign_webhook_url(url, load_webhook_secret())  # G-2（2026-08-10）钉钉加签（可选）
    payload = json.dumps({
        "msgtype": "text",
        "text": {"content": f"{title}\n{text}"},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.status
        body = resp.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(body)
    except Exception as exc:
        raise RuntimeError(f"non-JSON dingtalk response (HTTP {status}): {body[:200]}") from exc
    if data.get("errcode"):
        raise RuntimeError(f"dingtalk errcode={data.get('errcode')}: {data.get('errmsg')}")
    return status


def monitor_mode():
    """Run health monitor directly (no stdin pipe -> no encoding issues on Windows)."""
    try:
        import run_health_monitor as rhm
        summary = rhm.run_monitor()
    except Exception as exc:
        return _push("CS 监控 health monitor error", f"monitor itself failed: {exc}")
    if summary.get("status") != "fail":
        return 0
    fails = [c for c in summary.get("checks", []) if c.get("level") == "FAIL"]
    text = "\n".join(f"- {c.get('name')}: {c.get('detail', '')}" for c in fails[:10])
    title = f"CS 监控 health FAIL ({summary.get('date', '')}, {len(fails)} item(s))"
    return _push(title, text)


def _push(title, text):
    url = load_webhook_url()
    if not url:
        print("notify: NOTIFY_WEBHOOK_URL not configured, skipped (add to .env for alerts)")
        return 0
    try:
        from pipeline import ops as _ops
        if _ops.is_blocked("notify"):
            print("notify: kill switch 闸停通知（notify scope），跳过推送")
            _ops.log_event("warn", "alert_route", f"kill switch 拦停通知: {title}", title=title)
            return 0
    except Exception:
        pass
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
    ap.add_argument("--title", default="CS 监控 alert")
    ap.add_argument("--text", default="")
    ap.add_argument("--monitor", action="store_true", help="run health monitor and push on FAIL")
    ap.add_argument("--level", default="collect", choices=["collect", "quality", "trade"],
                    help="O4 告警三档路由级别（默认 collect=采集）")
    ap.add_argument("--dry-run", action="store_true", help="不发起 HTTP，仅打印路由结果（调试/冒烟）")
    args = ap.parse_args()
    if args.monitor:
        sys.exit(monitor_mode())
    if args.dry_run:
        _r = route_alert(args.level, args.title, args.text, dry_run=True)
        print(json.dumps(_r, ensure_ascii=False, indent=2))
        sys.exit(0)
    sys.exit(_push(args.title, args.text))