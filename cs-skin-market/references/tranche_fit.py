# -*- coding: utf-8 -*-
"""\u5206\u6279\u52a0\u4ed3\u6a21\u62df + \u8d44\u91d1\u52a0\u6743\u671f\u671b\u7f51\u683c\uff08\u542b\u4e00\u6b21\u6027\u5bf9\u7167\uff09
\u57fa\u51c6\uff1adata/item_backtest_latest.json (88 \u4fe1\u53f7, fwd_series = \u4fe1\u53f7\u65e5\u6b21\u65e5\u8d77\u9010\u65e5)
"""
import io, json, statistics

d = json.load(io.open('data/item_backtest_latest.json', encoding='utf-8'))
sigs = d['signals']
print('signals:', len(sigs), flush=True)

def sim_signal(sig, plan, cost=0.02, hold=14):
    entry = sig['entry_price']
    fwd = sig['fwd_series']
    n = len(fwd)
    if n == 0:
        return None
    h = min(hold, n)
    exit_px = fwd[h - 1]
    buys = [(entry, plan[0])]
    for k, (thr, w) in enumerate(plan[1:], start=1):
        thr_px = entry * (1 - thr / 100.0)
        idx = next((j for j in range(n) if fwd[j] <= thr_px), None)
        if idx is not None:
            buys.append((fwd[idx], w))
    total_w = sum(w for _, w in buys)
    w_ret = sum(w * (exit_px / px - 1 - cost) for px, w in buys) / total_w * 100
    return w_ret, total_w

def aggregate(plan, hold=14):
    xs = [sim_signal(s, plan, hold=hold) for s in sigs]
    xs = [x for x in xs if x is not None]
    tw = sum(x[1] for x in xs)
    wavg = sum(x[0] * x[1] for x in xs) / tw if tw else 0
    wwin = sum(x[1] for x in xs if x[0] > 0) / tw * 100 if tw else 0
    return round(wavg, 2), round(wwin, 1), round(sum(x[1] for x in xs) / len(xs), 1)

def baseline(hold=14):
    xs = [(s.get('position_limit') or 0.0, s.get('net14') if hold == 14 else s.get('net30')) for s in sigs]
    xs = [(w, r) for w, r in xs if r is not None]
    tw = sum(w for w, _ in xs)
    wavg = sum(w * r for w, r in xs) / tw
    wwin = sum(w for w, r in xs if r > 0) / tw * 100
    return round(wavg, 2), round(wwin, 1)

def one_shot(weight, hold=14):
    xs = []
    for s in sigs:
        entry = s['entry_price']; fwd = s['fwd_series']
        if not fwd: continue
        h = min(hold, len(fwd))
        r = (fwd[h-1]/entry - 1 - 0.02) * 100
        xs.append((weight, r))
    tw = sum(w for w, _ in xs)
    wavg = sum(w*r for w, r in xs)/tw
    wwin = sum(w for w, r in xs if r > 0)/tw*100
    return round(wavg, 2), round(wwin, 1)

for hold in (14, 30):
    b = baseline(hold)
    print(f'== hold={hold} \u57fa\u7ebf(\u4e00\u6b21\u6027\u6309 position_limit) == \u8d44\u91d1\u52a0\u6743={b[0]}% \u80dc\u7387={b[1]}%')

print()
print('== \u5bf9\u7167\uff1a\u4e00\u6b21\u6027\u4e0d\u540c\u4ed3\u4f4d (\u533a\u5206\u4ed3\u4f4d\u6548\u5e94) ==')
for hold in (14, 30):
    for w in (0.20, 0.30, 0.55):
        a, ww = one_shot(w, hold)
        print(f'  hold={hold} \u4e00\u6b21\u6027 {w:.0%}: wavg={a:+.2f}% win={ww:.1f}%')

PLANS = {
    '1\u6863(-10%,30)': [10, (10, 30)],
    '1\u6863(-8%,20)': [10, (8, 20)],
    '2\u6863(-8,-15):15/30': [10, (8, 15), (15, 30)],
    '2\u6863(-8,-15):10/20': [10, (8, 10), (15, 20)],
    '2\u6863(-5,-10):15/30': [10, (5, 15), (10, 30)],
    '3\u6863(-5,-10,-15):10/15/30': [10, (5, 10), (10, 15), (15, 30)],
    '3\u6863(-3,-6,-10):5/10/20': [10, (3, 5), (6, 10), (10, 20)],
}
print()
print('== \u5206\u6279\u7f51\u683c\u7ed3\u679c (\u8d44\u91d1\u52a0\u6743) ==')
for hold in (14, 30):
    print(f'--- hold={hold} ---')
    rows = []
    for name, plan in PLANS.items():
        a, w, avgw = aggregate(plan, hold=hold)
        rows.append((name, a, w, avgw))
    rows.sort(key=lambda x: x[1], reverse=True)
    for name, a, w, avgw in rows:
        print(f'  {name:22s} wavg={a:+7.2f}% win={w:5.1f}% \u5747\u603b\u4ed3\u4f4d={avgw}%')
