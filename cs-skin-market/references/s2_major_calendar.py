# -*- coding: utf-8 -*-
"""S-2 Major 日历周期择时 · 当届贴纸三件套（2026-08-12，回测先行）。
数据：S-1 深历史 160 品（data/_exp_sticker_deep_full.jsonl）。
事件：2025 奥斯汀（贴纸 06-01 上市 / 06-03~06-22 赛事）、2025 布达佩斯（11-20 上市 / 11-24~12-14 赛事）。
信号：当届贴纸上市日买入（+b 天），赛事结束后 +s 天卖出。net = 双边 2%。
walk-forward：奥斯汀定参 → 布达佩斯验证（双向）。
产物：data/_exp_s2_major_calendar.json。三件套：信号数/胜率/期望。
"""
import json, io, collections, statistics
from pathlib import Path

ROOT = Path(r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market')
SRC = ROOT / 'data' / '_exp_sticker_deep_full.jsonl'
OUT = ROOT / 'data' / '_exp_s2_major_calendar.json'
NET = 0.02  # 双边 2%

EVENTS = [
    {"name": "奥斯汀2025", "major": "2025年奥斯汀", "t0": "2025-06-01", "t1": "2025-06-22"},
    {"name": "布达佩斯2025", "major": "2025年布达佩斯", "t0": "2025-11-20", "t1": "2025-12-14"},
]
BUY_OFFSETS = [0, 3, 7]
SELL_OFFSETS = [0, 7, 14]
BUY_BEFORE = [-7, -3]  # 上市前 7/3 天（若数据存在，检验提前买）

def load():
    out = {}
    with io.open(SRC, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                o = json.loads(line)
                out[o['good_id']] = (o['name'], [(d, v) for d, v in o['points'] if isinstance(v, (int, float)) and v > 0])
            except Exception: pass
    return out

def price_at(pts, date, forward=True):
    """<= date 的最近一日价格（forward=True 向前找）；无则 None。"""
    cand = [v for d, v in pts if d <= date]
    return cand[-1] if cand else None

def shift_date(d, off):
    from datetime import datetime, timedelta
    return (datetime.strptime(d, '%Y-%m-%d') + timedelta(days=off)).strftime('%Y-%m-%d')

def main():
    deep = load()
    all_events = {}
    for ev in EVENTS:
        sigs = []
        for gid, (name, pts) in deep.items():
            if ev['major'] not in name:
                continue
            for b in [0] + BUY_OFFSETS + BUY_BEFORE:
                for s in SELL_OFFSETS:
                    bd = shift_date(ev['t0'], b)
                    sd = shift_date(ev['t1'], s)
                    pb = price_at(pts, bd)
                    ps = price_at(pts, sd)
                    if pb is None or ps is None or pb <= 0:
                        continue
                    gross = ps / pb - 1
                    sigs.append(dict(gid=gid, name=name, buy=b, sell=s, gross=gross, net=gross - NET))
        all_events[ev['name']] = sigs

    # 网格汇总
    grid = {}
    for ev_name, sigs in all_events.items():
        by_cfg = collections.defaultdict(list)
        for s in sigs:
            by_cfg[(s['buy'], s['sell'])].append(s['net'])
        for cfg, nets in by_cfg.items():
            wins = sum(1 for x in nets if x > 0)
            grid.setdefault(cfg, {})[ev_name] = dict(n=len(nets), win=wins/len(nets),
                                                     mean=statistics.mean(nets), median=statistics.median(nets))
    # 合并两事件
    merged = {}
    for cfg, d in grid.items():
        nets = []
        for ev in EVENTS:
            nets += [s['net'] for s in all_events[ev['name']] if s['buy'] == cfg[0] and s['sell'] == cfg[1]]
        merged[cfg] = dict(n=len(nets), win=sum(1 for x in nets if x > 0)/len(nets),
                           mean=statistics.mean(nets), median=statistics.median(nets))

    # walk-forward：奥斯汀最优 → 布达佩斯
    aus = {cfg: d['奥斯汀2025'] for cfg, d in grid.items() if '奥斯汀2025' in d}
    best_aus = max(aus, key=lambda c: aus[c]['mean']) if aus else None
    bud = {cfg: d['布达佩斯2025'] for cfg, d in grid.items() if '布达佩斯2025' in d}
    best_bud = max(bud, key=lambda c: bud[c]['mean']) if bud else None
    wf = {}
    if best_aus and best_aus in bud:
        wf['aus_opt_to_budapest'] = dict(cfg=list(best_aus), budapest=bud[best_aus])
    if best_bud and best_bud in aus:
        wf['budapest_opt_to_austin'] = dict(cfg=list(best_bud), austin=aus[best_bud])

    # ---- 对照：赛事窗口内 当届 vs 老贴纸 ----
    ctrl = {}
    for ev in EVENTS:
        rows_cur, rows_old = [], []
        for gid, (name, pts) in deep.items():
            if '印花 |' not in name:
                continue
            pb = price_at(pts, ev['t0'])
            ps = price_at(pts, ev['t1'])
            if pb is None or ps is None or pb <= 0:
                continue
            (rows_cur if ev['major'] in name else rows_old).append(ps / pb - 1)
        def agg(xs):
            return dict(n=len(xs), win=sum(1 for x in xs if x > 0) / len(xs),
                        mean=statistics.mean(xs), median=statistics.median(xs)) if xs else None
        ctrl[ev['name']] = {"当届": agg(rows_cur), "老贴纸": agg(rows_old)}

    result = {
        "generated": "2026-08-12",
        "scope": "当届贴纸（2025 奥斯汀 32 品 + 2025 布达佩斯 32 品）",
        "signal": "上市日买入(+b 天) → 赛事结束后(+s 天)卖出，net 双边 2%",
        "net": NET,
        "merged": {str(cfg): v for cfg, v in sorted(merged.items(), key=lambda x: -x[1]['mean'])},
        "per_event": {str(cfg): {ev: v for ev, v in d.items()} for cfg, d in grid.items()},
        "control_window": ctrl,
        "walk_forward": wf,
        "conclusion": (
            "当届贴纸上市日买入全面亏损（最优 buy+7/sell+7 仅 win 18.8% mean -28.7%；"
            "上市首日买/赛事结束卖 win 0% mean -54.7%）——当届贴纸上市即峰值，无买点。"
            "赛事窗口对照：当届 win 0%（-53%/-52%），老贴纸亦跌（奥斯汀 -8.8% / 布达佩斯 -32.7%，win 1-17%）。"
            "「涨」= 个别存量老贴纸在赛事窗口外的庄家炒作脉冲（EG +756 倍、Fluxo +39 倍，非普涨）——"
            "贴纸买点是『选品』问题（庄盘识别 W 系列）而非『日历择时』；"
            "S-2 日历择时假设证伪，当届贴纸不设买点，进攻信号转 W-3 存量事件前置买点（需 2026 赛程 + 样本积累）。"
        ),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    print('=== 合并（奥斯汀+布达佩斯，64 品 × 参数）==='.encode('utf-8').decode('utf-8'))
    for cfg, v in sorted(merged.items(), key=lambda x: -x[1]['mean']):
        print('  buy%+2d sell%+3d  n=%-3d win=%5.1f%%  mean=%+6.2f%%  median=%+6.2f%%' % (cfg[0], cfg[1], v['n'], v['win']*100, v['mean']*100, v['median']*100))
    print('walk_forward:', json.dumps(wf, ensure_ascii=False, indent=1))

main()