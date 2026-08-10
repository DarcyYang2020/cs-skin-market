# -*- coding: utf-8 -*-
"""B-3 在售量三口径对比（2026-08-10，需联网/Playwright，SKIP_NET 时跳过）。

问题：_chart_to_daily_ohlc 对日内 10 分钟点取「当日最后一个 in_sale_count」（末点口径）；
8/9 审计发现 31 品 SALE 系统性偏差 30-500%。本脚本对抽样品重采原始 chart（num_data），
对最近 N 天做「末点 vs 中位数 vs 均值」三口径对比，验证聚合规则是否需统一。

用法: python references/sale_caliber_compare.py [good_id ...]（默认抽样 5 品）
输出: data/sale_caliber_compare.json
"""
import io
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "sale_caliber_compare.json"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

SAMPLE_IDS = [1147, 2, 4, 6, 8]  # 抽样：火卫一/蓝层压板等持仓品 good_id 由调用方校验


async def fetch_raw_chart(good_id):
    """重采原始 chart JSON（复用 collector 浏览器单例与路由拦截）。"""
    from pipeline import collector_csqaq as cc
    pw, browser = await cc._get_browser()
    page = await browser.new_page()
    captured = {"charts": []}

    async def on_response(response):
        if "info/chart" in response.url and response.ok:
            try:
                body = await response.text()
                if len(captured["charts"]) < 2:
                    captured["charts"].append(body)
            except Exception:
                pass

    async def modify_chart(route, request):
        if "info/chart" in request.url:
            try:
                body = json.loads(request.post_data)
                body["period"] = "90"
                body["key"] = "sell_price"
                body["platform"] = 2
                await route.continue_(post_data=json.dumps(body))
            except Exception:
                await route.continue_()
        else:
            await route.continue_()

    try:
        page.on("response", on_response)
        await page.route("**/info/chart**", modify_chart)
        await page.goto(f"{cc.CSQAQ_WEB}/goods/{good_id}", wait_until="domcontentloaded", timeout=15000)
        await cc._wait_chart(page, captured, key="charts", timeout=5.0)
        for body in captured["charts"]:
            try:
                d = json.loads(body)
                if d.get("code") == 200 and d.get("data"):
                    return d["data"]
            except Exception:
                continue
        return None
    finally:
        await page.close()


def three_calibers(cd, days=30):
    """按日三口径：末点/中位数/均值（num_data 与 timestamp 对齐）。"""
    ts_arr = cd.get("timestamp", [])
    num_arr = cd.get("num_data", [])
    by_day = {}
    for i in range(min(len(ts_arr), len(num_arr))):
        v = num_arr[i]
        if v is None:
            continue
        try:
            val = float(v)
        except (TypeError, ValueError):
            continue
        ts = int(ts_arr[i]) // 1000 if ts_arr[i] else 0
        if not ts:
            continue
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(val)
    out = []
    for day in sorted(by_day)[-days:]:
        vals = by_day[day]
        if not vals:
            continue
        last = vals[-1]
        med = statistics.median(vals)
        avg = sum(vals) / len(vals)
        out.append({
            "date": day, "n_points": len(vals),
            "last": round(last, 0), "median": round(med, 0), "mean": round(avg, 0),
            "last_vs_median_pct": round((last / med - 1) * 100, 1) if med else None,
            "last_vs_mean_pct": round((last / avg - 1) * 100, 1) if avg else None,
        })
    return out


def main():
    import asyncio
    ids = [int(a) for a in sys.argv[1:]] or SAMPLE_IDS
    results = {}
    async def _run():
        from pipeline import db
        conn = db.get_conn()
        for gid in ids:
            row = conn.execute("SELECT name FROM items WHERE good_id=?", (gid,)).fetchone()
            name = row["name"] if row else f"good_{gid}"
            cd = await fetch_raw_chart(gid)
            if not cd:
                results[gid] = {"name": name, "error": "chart 未捕获（限流/超时）"}
                continue
            days = three_calibers(cd)
            dev = [d for d in days if d["last_vs_median_pct"] is not None and abs(d["last_vs_median_pct"]) > 20]
            results[gid] = {"name": name, "days": days,
                            "n_days": len(days), "dev>20%_days": len(dev),
                            "worst_last_vs_median": max((d["last_vs_median_pct"] or 0 for d in days), default=0)}
            print(f"[{gid}] {name}: {len(days)} 天, 末点vs中位偏差>20% 天数={len(dev)}", flush=True)
        conn.close()
    asyncio.run(_run())
    out = {"meta": "在售量三口径对比(B-3, 2026-08-10)：末点(现行) vs 中位数 vs 均值；偏差>20% 计为口径敏感日。",
           "generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "items": results}
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written:", OUT)


if __name__ == "__main__":
    main()
