# NOTE: original Chinese comments in this docstring were lost to console-encoding damage (2026-08-04). Code is functional; comments not restored. See AGENTS.md "doc encoding rules".
# -*- coding: utf-8 -*-
"""???????????P2?????????301 ????????hold14 ??????????

??:
- ??? = ?????????? ~ ?????+hold?
- ?? = ???????? = position_limit???????
- ?? HOLD ????????? k ??? = fwd[k-1]????(???+HOLD)? fwd[HOLD-1] ??
- ????? = ? active ??????????????????panic > base > deep_value?
- ?? = 1 + ?????(?????, ???) + ?????(?? mark-to-market)?????
"""
import sys, io, json, statistics
from datetime import date, timedelta
sys.path.insert(0, ".")

PRIORITY = {"panic": 3, "base": 2, "deep_value": 1, "oversold": 2, "accumulate": 2}
HOLD = 14
COST = 0.02


def load_signals():
    d = json.load(io.open('data/deepvalue_replay_tmp.json', encoding='utf-8'))
    sigs = d['signals']
    out = []
    for s in sigs:
        fwd = s.get('fwd_series') or []
        if not fwd:
            continue
        st = s.get('signal_type') or 'base'
        if abs((s.get('position_limit') or 0) - 0.10) < 0.001:
            st = 'deep_value'
        out.append({
            'date': date.fromisoformat(s['date']), 'item': s['name'],
            'entry': s['entry_price'], 'limit': s.get('position_limit') or 0.0,
            'fwd': fwd, 'st': st, 'prio': PRIORITY.get(st, 1),
            'net14': s.get('net14'),
        })
    return out


def simulate(sigs, cap=None):
    by_day = {}
    for s in sigs:
        by_day.setdefault(s['date'], []).append(s)
    first = min(s['date'] for s in sigs)
    last = max(s['date'] for s in sigs) + timedelta(days=HOLD)
    day = first
    active = []  # {s, idx(?????????), base}
    total_invested = 0.0
    realized = 0.0
    rejected = 0
    curve = []
    max_pos = 0.0
    while day <= last:
        for a in active:
            a['idx'] += 1
        for s in sorted(by_day.get(day, []), key=lambda x: -x['prio']):
            if cap is not None and total_invested + s['limit'] > cap + 1e-9:
                rejected += 1
                continue
            active.append({'s': s, 'idx': 0, 'base': s['limit']})
            total_invested += s['limit']
        unreal = 0.0
        pos_sum = 0.0
        for a in active:
            pos_sum += a['base']
            k = a['idx']
            if k <= 0 or k >= HOLD:
                continue
            fwd = a['s']['fwd']
            if k > len(fwd):
                continue
            px = fwd[min(k - 1, len(fwd) - 1)]
            unreal += a['base'] * (px / a['s']['entry'] - 1)
        for a in active:
            if a['idx'] >= HOLD:
                fwd = a['s']['fwd']
                px = fwd[min(HOLD - 1, len(fwd) - 1)]
                realized += a['base'] * (px / a['s']['entry'] - 1 - COST)
                total_invested -= a['base']
        active = [a for a in active if a['idx'] < HOLD]
        eq = 1.0 + realized + unreal
        curve.append((day.isoformat(), pos_sum, eq))
        max_pos = max(max_pos, pos_sum)
        day += timedelta(days=1)
    return curve, rejected, max_pos


def metrics(curve, rejected, max_pos):
    vals = [c[2] for c in curve]
    if not vals:
        return {}
    peak, max_dd = 1.0, 0.0
    for v in vals:
        peak = max(peak, v)
        max_dd = min(max_dd, (v / peak - 1) * 100)
    total = (vals[-1] / 1.0 - 1) * 100
    return {"total_return_pct": round(total, 2), "max_drawdown_pct": round(max_dd, 2),
            "max_position": round(max_pos, 3), "rejected": rejected, "days": len(curve)}


def main():
    sigs = load_signals()
    from collections import Counter
    print(f"signals: {len(sigs)}  type:", dict(Counter(s['st'] for s in sigs)))
    xs = [(s['limit'], s['net14']) for s in sigs if s['net14'] is not None]
    tw = sum(w for w, _ in xs)
    wavg = sum(w * r for w, r in xs) / tw
    wwin = sum(w for w, r in xs if r > 0) / tw * 100
    print(f"?????????(hold14): wavg={wavg:+.2f}% win={wwin:.1f}% (n={len(xs)})")
    print(f"{'cap':>6} {'total%':>9} {'maxDD%':>8} {'maxPos':>7} {'rejected':>9} {'days':>6}")
    for cap in (None, 1.0, 0.8, 0.6, 0.4):
        curve, rej, mx = simulate(sigs, cap=cap)
        m = metrics(curve, rej, mx)
        print(f"{str(cap if cap else 'none'):>6} {m['total_return_pct']:>9} {m['max_drawdown_pct']:>8} "
              f"{m['max_position']:>7} {m['rejected']:>9} {m['days']:>6}")
    curve, _, _ = simulate(sigs, cap=None)
    poss = sorted(c[1] for c in curve)
    n = len(poss)
    def pct(q):
        return poss[min(n - 1, int(q * n))]
    print(f"\n?????????: p50={pct(0.5):.2f} p90={pct(0.9):.2f} p99={pct(0.99):.2f} max={poss[-1]:.2f}")
    over60 = sum(1 for v in poss if v > 0.6)
    over80 = sum(1 for v in poss if v > 0.8)
    print(f"?60%??: {over60}/{n} ({over60/n*100:.1f}%)  ?80%??: {over80}/{n} ({over80/n*100:.1f}%)")


if __name__ == "__main__":
    main()
