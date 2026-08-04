# -*- coding: utf-8 -*-
"""批量采集样本：箱子下级皮肤（csqaq 90日K线 + 悠悠真实成交量）落库。

用法: python collect_sample_items.py [--start N] [--end N]
结果写入 data/sample_collect_report.txt（UTF-8）。
"""
import sys, io, asyncio, argparse, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import collector_csqaq, collector_youpin, db

REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample_collect_report.txt")

# (箱子, 显示名, [搜索串变体])
CANDIDATES = [
    ("伽玛武器箱", "M4A1消音版 | 机械工业 (崭新出厂)", ["M4A1消音版 机械工业 (崭新出厂)", "M4A1 消音版 机械工业 (崭新出厂)"]),
    ("伽玛武器箱", "Tec-9 | 冰冠 (崭新出厂)", ["Tec-9 冰冠 (崭新出厂)"]),
    ("伽玛2号", "AK-47 | 霓虹革命 (崭新出厂)", ["AK-47 霓虹革命 (崭新出厂)"]),
    ("伽玛2号", "MP9 | 气密 (崭新出厂)", ["MP9 气密 (崭新出厂)"]),
    ("伽玛2号", "沙漠之鹰 | 指挥 (崭新出厂)", ["沙漠之鹰 指挥 (崭新出厂)"]),
    ("手套箱", "SSG 08 | 炎龙之焰 (崭新出厂)", ["SSG 08 炎龙之焰 (崭新出厂)"]),
    ("手套箱", "法玛斯 | 机械工业 (崭新出厂)", ["法玛斯 机械工业 (崭新出厂)"]),
    ("九头蛇箱", "AWP | 鬼退治 (崭新出厂)", ["AWP 鬼退治 (崭新出厂)"]),
    ("九头蛇箱", "M4A4 | 地狱烈焰 (崭新出厂)", ["M4A4 地狱烈焰 (崭新出厂)"]),
    ("九头蛇箱", "AK-47 | 轨道 Mk01 (崭新出厂)", ["AK-47 轨道 Mk01 (崭新出厂)", "AK-47 轨道MK01 (崭新出厂)"]),
    ("九头蛇箱", "M4A1消音版 | 闪回 (崭新出厂)", ["M4A1消音版 闪回 (崭新出厂)", "M4A1 消音版 闪回 (崭新出厂)"]),
    ("九头蛇箱", "加利尔 AR | 黑砂 (崭新出厂)", ["加利尔 AR 黑砂 (崭新出厂)", "加利尔AR 黑砂 (崭新出厂)"]),
    ("梦魇箱", "MP9 | 星使 (崭新出厂)", ["MP9 星使 (崭新出厂)"]),
    ("梦魇箱", "法玛斯 | 目皆转睛 (崭新出厂)", ["法玛斯 目皆转睛 (崭新出厂)", "法玛斯 目转睛 (崭新出厂)"]),
    ("梦魇箱", "USP 消音版 | 地狱门票 (崭新出厂)", ["USP 消音版 地狱门票 (崭新出厂)", "USP消音版 地狱门票 (崭新出厂)"]),
    ("激流箱", "SSG 08 | 速度激情 (崭新出厂)", ["SSG 08 速度激情 (崭新出厂)", "SSG 08 速度与激情 (崭新出厂)"]),
    ("激流箱", "M4A4 | 彼岸花 (崭新出厂)", ["M4A4 彼岸花 (崭新出厂)"]),
    ("收藏品", "AWP | CMYK (崭新出厂)", ["AWP CMYK (崭新出厂)"]),
    ("收藏品", "USP 消音版 | 银装素裹 (崭新出厂)", ["USP 消音版 银装素裹 (崭新出厂)", "USP消音版 银装素裹 (崭新出厂)"]),
    ("收藏品", "AWP | 复古流行 (崭新出厂)", ["AWP 复古流行 (崭新出厂)"]),
    ("收藏品", "AK-47 | X 射线 (崭新出厂)", ["AK-47 X 射线 (崭新出厂)"]),
    ("收藏品", "AWP | 锦虎 (崭新出厂)", ["AWP 锦虎 (崭新出厂)"]),
    ("收藏品", "沙漠之鹰 | 午夜凶匪 (崭新出厂)", ["沙漠之鹰 午夜凶匪 (崭新出厂)"]),
    ("收藏品", "沙漠之鹰 | 翡翠巨蟒 (崭新出厂)", ["沙漠之鹰 翡翠巨蟒 (崭新出厂)"]),
    ("收藏品", "M4A1消音版 | 控制台 (崭新出厂)", ["M4A1消音版 控制台 (崭新出厂)", "M4A1 消音版 控制台 (崭新出厂)"]),
    ("收藏品", "MP7 | 渐变之色 (崭新出厂)", ["MP7 渐变之色 (崭新出厂)"]),
    ("收藏品", "沙漠之鹰 | 炽烈之炎 (崭新出厂)", ["沙漠之鹰 炽烈之炎 (崭新出厂)"]),
    ("收藏品", "M4A4 | 波塞冬 (崭新出厂)", ["M4A4 波塞冬 (崭新出厂)"]),
    ("收藏品", "M4A1消音版 | 伊卡洛斯殒落 (崭新出厂)", ["M4A1消音版 伊卡洛斯殒落 (崭新出厂)", "M4A1 消音版 伊卡洛斯殒落 (崭新出厂)"]),
    ("收藏品", "AK-47 | 水栽竹 (崭新出厂)", ["AK-47 水栽竹 (崭新出厂)"]),
    ("收藏品", "M4A1消音版 | 赤红新星 (崭新出厂)", ["M4A1消音版 赤红新星 (崭新出厂)", "M4A1 消音版 赤红新星 (崭新出厂)"]),
    ("蛇噬箱", "M4A4 | 活色生香 (崭新出厂)", ["M4A4 活色生香 (崭新出厂)"]),
    ("蛇噬箱", "沙漠之鹰 | 后发制人 (崭新出厂)", ["沙漠之鹰 后发制人 (崭新出厂)"]),
    ("狂牙箱", "M4A1消音版 | 印花集 (崭新出厂)", ["M4A1消音版 印花集 (崭新出厂)", "M4A1 消音版 印花集 (崭新出厂)"]),
    ("狂牙箱", "M4A4 | 赛博 (崭新出厂)", ["M4A4 赛博 (崭新出厂)"]),
    ("棱彩2号", "M4A1消音版 | 二号玩家 (崭新出厂)", ["M4A1消音版 二号玩家 (崭新出厂)", "M4A1 消音版 二号玩家 (崭新出厂)"]),
    ("棱彩2号", "AK-47 | 幻影破坏者 (崭新出厂)", ["AK-47 幻影破坏者 (崭新出厂)"]),
    ("棱彩箱", "M4A4 | 皇帝 (崭新出厂)", ["M4A4 皇帝 (崭新出厂)"]),
    ("棱彩箱", "沙漠之鹰 | 轻轨 (崭新出厂)", ["沙漠之鹰 轻轨 (崭新出厂)"]),
    ("地平线箱", "AK-47 | 霓虹骑士 (崭新出厂)", ["AK-47 霓虹骑士 (崭新出厂)"]),
    ("地平线箱", "M4A1消音版 | 梦魇 (崭新出厂)", ["M4A1消音版 梦魇 (崭新出厂)", "M4A1 消音版 梦魇 (崭新出厂)"]),
    ("地平线箱", "AWP | 猫猫狗狗 (崭新出厂)", ["AWP 猫猫狗狗 (崭新出厂)"]),
    ("幻彩箱", "AWP | 无畏战神 (略有磨损)", ["AWP 无畏战神 (略有磨损)"]),
    ("幻彩箱", "沙漠之鹰 | 纳迦蛇神 (崭新出厂)", ["沙漠之鹰 纳迦蛇神 (崭新出厂)"]),
    ("光谱2号", "AK-47 | 皇后 (崭新出厂)", ["AK-47 皇后 (崭新出厂)"]),
    ("突围箱", "M4A1消音版 | 次时代 (崭新出厂)", ["M4A1消音版 次时代 (崭新出厂)", "M4A1 消音版 次时代 (崭新出厂)"]),
    ("突围箱", "沙漠之鹰 | 阴谋者 (崭新出厂)", ["沙漠之鹰 阴谋者 (崭新出厂)"]),
    ("弯曲猎手", "AK-47 | 深海复仇 (崭新出厂)", ["AK-47 深海复仇 (崭新出厂)"]),
    ("弯曲猎手", "格洛克 18 型 | 本生灯 (崭新出厂)", ["格洛克 18 型 本生灯 (崭新出厂)", "格洛克18型 本生灯 (崭新出厂)"]),
    ("先锋箱", "M4A4 | 狮鹫 (崭新出厂)", ["M4A4 狮鹫 (崭新出厂)"]),
    ("英勇箱", "沙漠之鹰 | 黄金锦鲤 (崭新出厂)", ["沙漠之鹰 黄金锦鲤 (崭新出厂)"]),
    ("猎杀者箱", "AK-47 | 火神 (崭新出厂)", ["AK-47 火神 (崭新出厂)", "AK-47 火蛇 (崭新出厂)"]),
    ("猎杀者箱", "M4A1消音版 | 原子合金 (崭新出厂)", ["M4A1消音版 原子合金 (崭新出厂)", "M4A1 消音版 原子合金 (崭新出厂)"]),
    ("猎杀者箱", "M4A4 | 沙漠精英 (崭新出厂)", ["M4A4 沙漠精英 (崭新出厂)"]),
    ("幻彩2号", "M4A1消音版 | 暴怒野兽 (崭新出厂)", ["M4A1消音版 暴怒野兽 (崭新出厂)", "M4A1 消音版 暴怒野兽 (崭新出厂)"]),
    ("反恐精英箱", "AK-47 | 表面淬火 (崭新出厂)", ["AK-47 表面淬火 (崭新出厂)"]),
    ("反恐精英箱", "格洛克 18 型 | 黑龙纹身 (崭新出厂)", ["格洛克 18 型 黑龙纹身 (崭新出厂)", "格洛克18型 黑龙纹身 (崭新出厂)"]),
]

def parse_name_parts(name: str):
    """'AK-47 | 霓虹革命 (崭新出厂)' -> (weapon, skin, wear)"""
    weapon = skin = wear = ""
    body = name
    if "(" in body:
        body, wear = body.rsplit("(", 1)
        wear = wear.strip(" )")
    if "|" in body:
        weapon, skin = [p.strip() for p in body.split("|", 1)]
        skin = skin.replace("（★）", "").replace("(★)", "").strip()
    else:
        skin = body.strip()
    return weapon, skin, wear


async def collect_one(case, display, queries, out):
    gid, title = 0, ""
    for q in queries:
        try:
            gid, title = await collector_csqaq.search_good_id(q)
        except Exception as e:
            out.append(f"  [search err] {q}: {e}")
            continue
        if gid:
            break
    if not gid:
        out.append(f"  FAIL 搜索不到: {display}")
        return
    try:
        item = await collector_csqaq.fetch_item_detail(gid)
    except Exception as e:
        out.append(f"  FAIL 详情 gid={gid}: {e}")
        return
    if item is None:
        out.append(f"  FAIL 详情为空 gid={gid} ({display})")
        return
    try:
        bars, _raw = await collector_csqaq.fetch_kline_90d(gid)
    except Exception as e:
        out.append(f"  FAIL K线 gid={gid}: {e}")
        return
    if not bars:
        out.append(f"  FAIL K线为空 gid={gid} ({display})")
        return
    vol_map = {}
    if item.yyyp_id:
        try:
            vol_map = await collector_youpin.fetch_youpin_volume(item.yyyp_id)
        except Exception as e:
            out.append(f"  [youpin err] {e}")
    if vol_map:
        for b in bars:
            d = getattr(b, "date", "")
            v = vol_map.get(d, 0)
            b.volume = int(v) if v and v > 0 else 0
    weapon, skin, wear = parse_name_parts(item.name)
    conn = db.get_conn()
    try:
        pid = db.upsert_item(conn, item.name, weapon=weapon, skin=skin, wear=wear,
                             source="case", good_id=gid, in_watchlist=0)
        db.save_price_history_batch(conn, pid, bars)
        conn.commit()
    except Exception as e:
        out.append(f"  FAIL 落库 {item.name}: {e}")
        return
    finally:
        conn.close()
    dates = sorted(vol_map.keys())
    vol_days = sum(1 for b in bars if getattr(b, "volume", 0) and b.volume > 0)
    closes = [b.close for b in bars if getattr(b, "close", 0) and b.close > 0]
    lo, hi = (min(closes), max(closes)) if closes else (0, 0)
    span = f"{bars[0].date}~{bars[-1].date}" if len(bars) >= 2 else bars[0].date
    vol_range = f"{dates[0]}~{dates[-1]}" if dates else "-"
    out.append(f"  OK [{case}] {item.name} | price={item.price_rmb} yyyp={item.yyyp_id} bars={len(bars)} [{span}] range={lo}~{hi} | vol_days={vol_days}/{len(dates)} [{vol_range}]")
    out.append(f"    -> item_id={pid} 入库完成")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=len(CANDIDATES))
    args = ap.parse_args()
    lines = []
    lines.append(f"== 批量采集 {args.start}~{args.end} / {len(CANDIDATES)} ==")
    ok = 0
    for i in range(args.start, min(args.end, len(CANDIDATES))):
        case, display, queries = CANDIDATES[i]
        lines.append(f"[{i+1}/{len(CANDIDATES)}] {case}: {display}")
        before = len(lines)
        await collect_one(case, display, queries, lines)
        if any("OK" in l for l in lines[before:]):
            ok += 1
    lines.append(f"== 完成: {ok}/{args.end - args.start} 成功 ==")
    with io.open(REPORT, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    for l in lines:
        print(l)


if __name__ == "__main__":
    asyncio.run(main())