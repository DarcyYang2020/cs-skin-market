# -*- coding: utf-8 -*-
"""P-2 定向扩池脚本：csQAQ get_rank_list 高价×低在售候选 → 入库分析（2026-08-11）
目标：
  1) P-2 样本桶（价格>=1000 × 悠悠在售 100-200）增量
  2) B 通道覆盖面（items/price_history 增加活跃品，每日采集自动覆盖）
纪律：数据层采集入库，引擎参数零改动。产物 data/_exp_p2_pool_candidates.json
"""
import asyncio, json, sys, io, time, logging
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import db
from pipeline.collector_csqaq import _get_browser
from webapp.analysis_service import (
    KLINE_FRESH_DISCOVER, resolve_item, kline_db_fallback,
    save_analysis_result, save_item_snapshot, market_snapshot,
)
from pipeline import item_analysis

_log = logging.getLogger("pool_expand_p2")
RANK_URL = "https://csqaq.com/rank"
MAX_PAGES = 4  # 每档最多 4 页 x 100

TIERS = [
    {"label": "P2_hi", "price_lo": 1000, "price_hi": None, "sale_lo": 100, "sale_hi": 200},
    {"label": "mid", "price_lo": 300, "price_hi": 1000, "sale_lo": 100, "sale_hi": 200},
]

def _exclude(name: str) -> bool:
    n = name or ""
    if "StatTrak" in n or "纪念品" in n:
        return True
    if n.startswith("印花") or n.startswith("音乐盒") or n.startswith("收藏品"):
        return True
    return False

async def fetch_tier(page, tier):
    """route 改写 get_rank_list，翻页拉候选。返回 [(good_id, name, buff_sell, yyyp_sell, price)]"""
    out, seen = [], set()
    for pidx in range(1, MAX_PAGES + 1):
        captured = {}
        async def _on_resp(resp):
            if "get_rank_list" in resp.url:
                try:
                    captured["body"] = await resp.text()
                except Exception:
                    pass
        page.on("response", _on_resp)
        async def _modify(route, request):
            try:
                body = json.loads(request.post_data or "{}")
                f = {}
                if tier["sale_lo"]:
                    f["在售最少"] = tier["sale_lo"]
                if tier["sale_hi"]:
                    f["在售最多"] = tier["sale_hi"]
                if tier["price_lo"]:
                    f["价格最低价"] = tier["price_lo"]
                if tier["price_hi"]:
                    f["价格最高价"] = tier["price_hi"]
                f["类别"] = ["★", "普通"]
                f["排序"] = ["价格_价格下降(百分比)_近1天"]
                body["filter"] = f
                body["page_index"] = pidx
                body["page_size"] = 100
                body["show_recently_price"] = False
                await route.continue_(post_data=json.dumps(body))
            except Exception:
                await route.continue_()
        await page.route("**/info/get_rank_list", _modify)
        try:
            await page.goto(RANK_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3500)
        except Exception as e:
            print(f"  [{tier['label']}] 第{pidx}页 goto 失败: {str(e)[:60]}")
        page.remove_listener("response", _on_resp)
        await page.unroute("**/info/get_rank_list")
        body = captured.get("body")
        if not body:
            print(f"  [{tier['label']}] 第{pidx}页未捕获（限流/慢），尝试重载 1 次")
            await page.wait_for_timeout(2500)
            continue
        try:
            d = json.loads(body)
            items = (d.get("data") or {}).get("data") or []
        except Exception:
            items = []
        if not items:
            print(f"  [{tier['label']}] 第{pidx}页空，停止翻页")
            break
        for x in items:
            gid = int(x.get("id") or 0)
            nm = x.get("name") or ""
            if gid <= 0 or not nm or gid in seen:
                continue
            if _exclude(nm):
                continue
            seen.add(gid)
            out.append((gid, nm, x.get("buff_sell_num") or 0, x.get("yyyp_sell_num") or 0, x.get("buff_sell_price") or 0))
        print(f"  [{tier['label']}] 第{pidx}页: {len(items)} 条，累计 {len(out)}")
        if len(items) < 100:
            break
        await page.wait_for_timeout(2000)
    return out

async def analyze_one(good_id, name, ms):
    """分析+落库（复用 discover 链路：串品防护→upsert→price_history→分析→报告）。返回 dict 或 error dict"""
    try:
        item = await resolve_item(good_id, name, KLINE_FRESH_DISCOVER)
        if item is None:
            return {"error": "详情获取失败"}
        exact_name = item.name or name
        daily_bars = item.kline_90d if hasattr(item, "kline_90d") and item.kline_90d else []
        if not daily_bars:
            _db_bars, _stale, _stale_date = kline_db_fallback(good_id, exact_name)
            if _db_bars:
                daily_bars = _db_bars
        # 串品防护：悠悠锚 vs kline 最新
        anchor_price = getattr(item, "price_rmb", 0) or 0
        anchor_sell = getattr(item, "sell_num_yyyp", 0) or 0
        if daily_bars:
            _closes = [k.close for k in daily_bars if k.close and k.close > 0]
            _last_sale = 0
            for k in reversed(daily_bars):
                if getattr(k, "in_sale_count", 0) or 0:
                    _last_sale = k.in_sale_count
                    break
            _bad = (
                (anchor_price > 0 and _closes and abs(_closes[-1] / anchor_price - 1) > 0.20)
                or (anchor_sell > 0 and _last_sale > 0 and abs(_last_sale / anchor_sell - 1) > 0.30)
            )
            if _bad:
                _item2 = await resolve_item(good_id, exact_name, KLINE_FRESH_DISCOVER)
                if _item2 and _item2.kline_90d:
                    item = _item2
                    daily_bars = item.kline_90d
        # 落库（新品入库 = 扩池；DB 复用品跳过写入）
        if daily_bars and not getattr(item, "from_db", False):
            try:
                conn_p = db.get_conn()
                try:
                    _pid = db.upsert_item(conn_p, name=exact_name, good_id=good_id,
                                          yyyp_id=getattr(item, "yyyp_id", "") or "", in_watchlist=None)
                    db.save_price_history_batch(conn_p, _pid, daily_bars)
                    conn_p.commit()
                finally:
                    conn_p.close()
            except Exception as _pe:
                print(f"  落库失败 {exact_name}: {_pe}")
        prices = [k.close for k in daily_bars if k.close > 0] if daily_bars else [anchor_price]
        if len(prices) < 14:
            return {"name": exact_name, "skip": "K线不足14天"}
        supply_hist = [k.in_sale_count for k in daily_bars] if daily_bars else []
        analysis = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: item_analysis.run_item_analysis(
                name=exact_name, prices=prices, supply_hist=supply_hist or None,
                order_book=item.order_book,
                index_change_7d=ms["chg7"], market_history=ms["history"],
                market_pct_90d=ms["pct"], market_zscore=ms["z"],
                market_cycle=ms["cycle"], market_th_score=ms["th"],
                market_30d_change=ms["chg30"], market_drop21=ms.get("drop21", 0),
                recent_buy_dates=[], signal_date=time.strftime("%Y-%m-%d"),
                price_anchor=anchor_price, survive_count=getattr(item, "survive_count", 0),
            ),
        )
        # 报告落库
        try:
            save_analysis_result(analysis)
            _conn_d = db.get_conn()
            try:
                _pid_d = db.upsert_item(_conn_d, name=exact_name, good_id=good_id)
                _conn_d.commit()
            finally:
                _conn_d.close()
            _conn_s = db.get_conn()
            try:
                save_item_snapshot(_conn_s, _pid_d, analysis, analysis.price_rmb or 0)
            finally:
                _conn_s.close()
        except Exception as _se:
            print(f"  报告落库失败 {exact_name}: {_se}")
        return {
            "name": exact_name, "good_id": good_id, "price_rmb": analysis.price_rmb or anchor_price,
            "grade": analysis.value.grade, "score": analysis.value.score,
            "data_quality": getattr(analysis, "data_quality", "low"),
            "fd_action": (analysis.fusion_decision or {}).get("action", "") if isinstance(analysis.fusion_decision, dict) else "",
            "percentile_90d": getattr(analysis.position, "percentile_90d", 50) if hasattr(analysis, "position") else 50,
            "in_sale_latest": (supply_hist[-1] if supply_hist else 0),
        }
    except Exception as e:
        return {"name": name, "error": str(e)[:150]}

async def main():
    ms = market_snapshot()
    print("大盘 TH =", ms["th"], "chg30 =", ms["chg30"])
    conn = db.get_conn()
    try:
        known = set(r[0] for r in conn.execute("SELECT good_id FROM items WHERE good_id>0").fetchall())
        retired = set(r[0] for r in conn.execute("SELECT good_id FROM items WHERE good_id>0 AND notes LIKE '%活跃池淘汰%'").fetchall())
    finally:
        conn.close()
    print("在库 good_id:", len(known), "| 淘汰:", len(retired))

    pw, browser = await _get_browser()
    if not browser:
        print("浏览器不可用"); return
    page = await browser.new_page()
    candidates = []
    for tier in TIERS:
        print(f"== 档位 {tier['label']}（价>={tier['price_lo']}, buff在售 {tier['sale_lo']}-{tier['sale_hi']}）==")
        cand = await fetch_tier(page, tier)
        print(f"  {tier['label']} 候选 {len(cand)} 条")
        candidates.extend(cand)
    await page.close()
    # 不 close 浏览器：collector 的 _get_browser 单例会复用该实例，
    # close 后 resolve_item 会拿到已关闭的浏览器（browser has been closed）

    # 去重 + 过滤在库
    seen, fresh = set(), []
    for gid, nm, buff_sell, yyyp_sell, price in candidates:
        if gid in seen or gid in known or gid in retired:
            continue
        seen.add(gid)
        fresh.append({"good_id": gid, "name": nm, "buff_sell": buff_sell, "yyyp_sell": yyyp_sell, "price_ref": price})
    print(f"过滤后库外候选: {len(fresh)} 条")
    if not fresh:
        print("无新候选，结束"); return

    results, errors, skips = [], [], []
    for i, c in enumerate(fresh):
        print(f"[{i+1}/{len(fresh)}] {c['name']} (good={c['good_id']}, buff在售={c['buff_sell']})")
        r = await analyze_one(c["good_id"], c["name"], ms)
        if "error" in r:
            errors.append(r)
            print(f"  -> 失败: {r['error']}")
        elif "skip" in r:
            skips.append(r)
            print(f"  -> 跳过: {r['skip']}")
        else:
            r["buff_sell_ref"] = c["buff_sell"]
            r["yyyp_sell_ref"] = c["yyyp_sell"]
            results.append(r)
            print(f"  -> ok: {r['grade']} score={r['score']} 实测在售={r['in_sale_latest']}")

    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "csQAQ get_rank_list (filter: 价格>=1000 或 300-1000, buff在售100-200)",
        "candidates_total": len(candidates),
        "new_added": len(results), "errors": len(errors), "skips": len(skips),
        "results": results, "errors_list": errors, "skips_list": skips,
    }
    outp = ROOT / "data" / "_exp_p2_pool_candidates.json"
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    p2 = [r for r in results if r.get("price_rmb", 0) >= 1000 and 100 <= (r.get("in_sale_latest") or 0) <= 200]
    print(f"== 汇总：新增 {len(results)} / 失败 {len(errors)} / 跳过 {len(skips)}")
    print(f"P-2 样本增量（价>=1000 × 实测悠悠在售100-200）: {len(p2)} 品")
    print(f"产物: {outp}")

if __name__ == "__main__":
    asyncio.run(main())
