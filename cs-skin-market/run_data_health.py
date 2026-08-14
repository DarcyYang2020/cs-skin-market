# -*- coding: utf-8 -*-
"""数据源健康检查脚本：纯 SQLite 只读校验各数据源基线，不触发任何采集。

用法:
    python run_data_health.py            # 人类可读输出
    python run_data_health.py --json     # JSON 输出（供自动化/日志）

退出码:
    0 = 全部通过（可含 WARN）
    2 = 存在 FAIL（数据异常，需人工核查）

基线依据: references/data-source-health.md（2026-08-04 建立）
触发场景: 每周一次 / 批量扫描结果异常 / 用户反馈数据不对时
"""
import sys, io, os, json, sqlite3, argparse
from datetime import date, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "market.db")
LOG_PATH = os.path.join(BASE, "data", "health_check.log")
TODAY = date.today().isoformat()

MOODS = ("恐惧", "中性", "贪婪")

ACTIVE_ITEM_COND = """
    (i.in_watchlist=1 OR i.holding=1
     OR COALESCE(i.notes, '') NOT LIKE '%存世量过低%'
        AND COALESCE(i.notes, '') NOT LIKE '%活跃池淘汰%'
        AND COALESCE(i.notes, '') NOT LIKE '%贴纸模块停采%')
"""


def _q(c, sql, args=()):
    try:
        return c.execute(sql, args).fetchall()
    except sqlite3.OperationalError as e:
        return [("__ERR__", str(e))]


def _cnt(c, sql, args=()):
    """COUNT 查询包装：表缺失/查询失败按 0 处理（避免 __ERR__ 字符串参与比较）。"""
    r = _q(c, sql, args)
    if not r or r[0][0] == "__ERR__":
        return 0
    return r[0][0]


def _days_since(dstr):
    if not dstr:
        return 999
    try:
        return (date.today() - datetime.strptime(dstr, "%Y-%m-%d").date()).days
    except ValueError:
        return 999


def run_checks(db_path=None):
    """运行全部健康检查，返回 [(检查名, PASS/FAIL, 详情)]。

    db_path: 可指定数据库路径（默认 data/market.db），供 run_health_monitor/测试复用。
    """
    conn = sqlite3.connect(db_path or DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    rows = []

    # 1. 大盘指数
    idx = _q(c, "SELECT date, value, mood FROM market_index ORDER BY date DESC LIMIT 1")
    if idx and idx[0][0] != "__ERR__":
        d, v, m = idx[0]
        bad = []
        if not (v and v > 1000):
            bad.append(f"value={v}")
        if m not in MOODS:
            bad.append(f"mood={m!r}")
        age = _days_since(d)
        if age > 4:
            bad.append(f"latest={d} 距今{age}天")
        rows.append(("大盘指数", "FAIL" if bad else "PASS",
                     f"{d} value={v:.2f} mood={m}" + (f" | 异常: {'; '.join(bad)}" if bad else "")))
    else:
        rows.append(("大盘指数", "FAIL", "market_index 无数据或查询失败"))

    # 2. 单品 K 线（2026-08-07 Phase 1b: 基线从自选品改为"历史有在售量的品"，曾漏检非自选品停更）
    #    2026-08-13 起基线改为活跃池品：自选/持仓豁免 + 排除存世量过低/活跃池淘汰/贴纸模块停采。
    #    贴纸停采后历史在售量仍留在 price_history，若仍按"历史有在售量"统计会把已停采贴纸计入分母。
    #    低于此即提示当日抓取不完整（如 2026-08-03 回归 92→23，本检查应 FAIL 告警）
    expect = _cnt(c, f"SELECT COUNT(*) FROM items i WHERE i.good_id>0 AND {ACTIVE_ITEM_COND}")
    kline = _q(c, f"""SELECT p.date, COUNT(DISTINCT p.item_id) n
                      FROM price_history p JOIN items i ON i.id=p.item_id
                      WHERE i.good_id>0 AND {ACTIVE_ITEM_COND}
                        AND p.date>=date('now','-7 day')
                      GROUP BY p.date ORDER BY p.date DESC LIMIT 1""")
    if kline and kline[0][0] != "__ERR__":
        d, n = kline[0]
        age = _days_since(d)
        bad = []
        if n < expect * 0.85:
            bad.append(f"覆盖{n}<预期{expect}*0.85")
        if age > 1:
            bad.append(f"latest={d} 距今{age}天")
        # B-5（2026-08-10）失败品清单：当日未覆盖的基线品逐品列出，便于排查
        miss = _q(c, f"""SELECT i.name FROM items i
            WHERE i.good_id > 0 AND {ACTIVE_ITEM_COND}
              AND i.id NOT IN (SELECT DISTINCT p.item_id FROM price_history p WHERE p.date = ?) ORDER BY i.id""", (d,))
        miss = [m[0] for m in miss if m[0] != "__ERR__"]
        if miss:
            bad.append(f"缺{len(miss)}品" + (f": {', '.join(miss[:10])}" + ("…" if len(miss) > 10 else "")))
        rows.append(("单品K线", "FAIL" if bad else "PASS",
                     f"{d} 覆盖{n}/{expect}品" + (f" | 异常: {'; '.join(bad)}" if bad else "")))
    else:
        rows.append(("单品K线", "FAIL", "近7日无 price_history"))

    # 3. 在售量覆盖（2026-08-07 去量：原悠悠成交量检查改为 in_sale_count）
    sup = _q(c, f"""SELECT p.date, COUNT(*) n
                    FROM price_history p JOIN items i ON i.id=p.item_id
                    WHERE i.good_id>0 AND {ACTIVE_ITEM_COND}
                      AND p.in_sale_count>0 AND p.in_sale_count IS NOT NULL
                      AND p.date>=date('now','-7 day')
                    GROUP BY p.date ORDER BY p.date DESC LIMIT 1""")
    if sup and sup[0][0] != "__ERR__":
        d, n = sup[0]
        age = _days_since(d)
        bad = []
        if n < expect * 0.85:
            bad.append(f"有在售量{n}<预期{expect}*0.85")
        if age > 1:
            bad.append(f"latest={d} 距今{age}天")
        # B-5（2026-08-10）失败品清单：当日无在售量的基线品逐品列出
        miss = _q(c, f"""SELECT i.name FROM items i
            WHERE i.good_id > 0 AND {ACTIVE_ITEM_COND}
              AND i.id NOT IN (SELECT DISTINCT p.item_id FROM price_history p WHERE p.date = ? AND p.in_sale_count > 0) ORDER BY i.id""", (d,))
        miss = [m[0] for m in miss if m[0] != "__ERR__"]
        if miss:
            bad.append(f"缺{len(miss)}品" + (f": {', '.join(miss[:10])}" + ("…" if len(miss) > 10 else "")))
        rows.append(("在售量", "FAIL" if bad else "PASS",
                     f"{d} 有在售量{n}/{expect}品" + (f" | 异常: {'; '.join(bad)}" if bad else "")))
    else:
        rows.append(("在售量", "FAIL", "近7日无 in_sale_count>0（需每日 K 线/在售量刷新）"))

    # 4. 贪婪/卡价
    g = _cnt(c, "SELECT COUNT(*) FROM macro_history WHERE greedy_index IS NOT NULL")
    k = _cnt(c, "SELECT COUNT(*) FROM macro_history WHERE card_price IS NOT NULL")
    bad = []
    if g < 55:
        bad.append(f"greedy={g}")
    if k < 170:
        bad.append(f"card={k}")
    rows.append(("贪婪/卡价", "FAIL" if bad else "PASS",
                 f"greedy={g}点 card={k}点" + (f" | 异常: {'; '.join(bad)}" if bad else "")))

    # 5. 全市场快照（基线 2026-08-04 过滤后 1468 品）
    # B-5（2026-08-10）修复：原 MAX(date)+全表 COUNT(*) 口径混用，多日累计后行数虚增
    # （3 天 x1468=4404 触发 >3500 误报连续 3 天）；改为统计最新日快照行数
    snap = _q(c, """SELECT s.date d, COUNT(*) n FROM market_snapshot s
                    WHERE s.date = (SELECT MAX(date) FROM market_snapshot)""")
    if snap and snap[0][0] != "__ERR__":
        d, n = snap[0]
        age = _days_since(d)
        bad = []
        if n < 1400:
            bad.append(f"行数{n}<1400")
        if n > 3500:
            bad.append(f"行数{n}>3500（疑似未过滤，基线1468）")
        if age > 8:  # 全市场快照/大户集中度改每周采集(2026-08-08), 阈值放宽到 8 天
            bad.append(f"latest={d} 距今{age}天")
        st = _cnt(c, "SELECT COUNT(*) FROM market_snapshot WHERE name LIKE '%StatTrak%' OR name LIKE '%纪念品%'")
        if st:
            bad.append(f"StatTrak/纪念品残留{st}")
        rows.append(("全市场快照", "FAIL" if bad else "PASS",
                     f"{d} {n}行 StatTrak残留={st}" + (f" | 异常: {'; '.join(bad)}" if bad else "")))
    else:
        rows.append(("全市场快照", "FAIL", "market_snapshot 无数据"))

    # 6. 大户集中度
    mon = _q(c, "SELECT date, COUNT(DISTINCT item_id) items, COUNT(*) rows_ FROM monitor_rank_snapshot GROUP BY date ORDER BY date DESC LIMIT 1")
    if mon and mon[0][0] != "__ERR__":
        d, items, rn = mon[0]
        age = _days_since(d)
        bad = []
        if items < 90:
            bad.append(f"覆盖{items}品<90")
        if rn < 4000:
            bad.append(f"行数{rn}<4000")
        if age > 8:  # 全市场快照/大户集中度改每周采集(2026-08-08), 阈值放宽到 8 天
            bad.append(f"latest={d} 距今{age}天")
        rows.append(("大户集中度", "FAIL" if bad else "PASS",
                     f"{d} {items}品/{rn}行" + (f" | 异常: {'; '.join(bad)}" if bad else "")))
    else:
        rows.append(("大户集中度", "FAIL", "monitor_rank_snapshot 无数据"))

    # 7. items 元数据
    no_good = _cnt(c, "SELECT COUNT(*) FROM items WHERE good_id<=0 AND in_watchlist=1")
    dupe = _cnt(c, "SELECT COUNT(*) FROM (SELECT good_id FROM items WHERE good_id>0 GROUP BY good_id HAVING COUNT(*)>1)")
    bad = []
    if no_good:
        bad.append(f"持仓品缺good_id×{no_good}")
    if dupe:
        bad.append(f"重复good_id×{dupe}")
    rows.append(("items元数据", "FAIL" if bad else "PASS",
                 f"缺good_id={no_good} 重复good_id={dupe}" + (f" | 异常: {'; '.join(bad)}" if bad else "")))

    conn.close()
    return rows


def main():
    if sys.stdout is sys.__stdout__:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = run_checks()
    n_fail = sum(1 for _, lv, _ in rows if lv == "FAIL")
    n_pass = sum(1 for _, lv, _ in rows if lv == "PASS")

    if args.json:
        print(json.dumps({"ok": n_fail == 0, "date": TODAY,
                          "checks": [{"name": n, "level": lv, "detail": dt} for n, lv, dt in rows]},
                         ensure_ascii=False, indent=2))
    else:
        for name, lv, dt in rows:
            mark = {"PASS": "[PASS]", "FAIL": "[FAIL]"}[lv]
            print(f"{mark} {name}: {dt}")
        print(f"\n== {n_pass}/{len(rows)} 通过, FAIL={n_fail} ==")

    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ok={n_fail==0} pass={n_pass}/{len(rows)} fail={n_fail}\n")
    except Exception:
        pass

    return 2 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
