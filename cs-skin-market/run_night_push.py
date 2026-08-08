# -*- coding: utf-8 -*-
"""晚间推送独立任务（21:30 计划任务，2026-08-08 采集/推送解耦）。

背景：每日全量采集提前至 18:00，收尾仅生成监控事件+日报（push=False）；
本任务在 21:30 完整重跑 run_daily_monitor(slot="night")——事件按 slot 前缀幂等去重不重复，
日报覆盖写，钉钉推送保持「12:00 午间 + 21:30 晚间」两时段不变。

用法: python run_night_push.py
"""
import sys, io, os, json
from datetime import datetime, timezone, timedelta

if sys.stdout is sys.__stdout__:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TZ_BJ = timezone(timedelta(hours=8))
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "night_push.log")


def log(msg: str):
    line = f"[{datetime.now(TZ_BJ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main():
    log("=== 晚间推送开始 ===")
    from pipeline.monitor import run_daily_monitor
    try:
        _mon = run_daily_monitor(slot="night")
        log(f"监控事件: 生成 {_mon['generated']} / 新增 {_mon['saved']} 条 "
            f"(大盘 {_mon['bucket']}, 分析 {_mon['analyzed']} 品)")
        log(f"推送: {_mon.get('pushed')}")
    except Exception as e:
        log(f"晚间推送异常: {e}")
    log("=== 晚间推送完成 ===")


if __name__ == "__main__":
    main()
