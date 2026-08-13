import json
import math
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from pipeline.backtest_common import approx_sentiment
from pipeline.market_macro import greedy_to_sentiment

REPLAY = BASE / 'data' / 'item_backtest_full_2025.json'
DB = BASE / 'data' / 'market.db'
OUT = BASE / 'data' / '_exp_panic_alignment.json'


def pearson(xs, ys):
    if not xs or len(xs) != len(ys):
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def spearman(xs, ys):
    if not xs or len(xs) != len(ys):
        return None

    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    return pearson(ranks(xs), ranks(ys))


def load_market_index(con):
    rows = con.execute('SELECT date, value FROM market_index ORDER BY date').fetchall()
    dates = [r[0] for r in rows]
    values = [r[1] for r in rows]
    return dates, values


def load_real_sentiment(con):
    rows = con.execute('SELECT date, greedy_index FROM macro_history WHERE greedy_index IS NOT NULL ORDER BY date').fetchall()
    return {d: greedy_to_sentiment(float(v)) for d, v in rows}, {d: float(v) for d, v in rows}


def threshold_table(real, approx, cut):
    a = {'real_pos': 0, 'real_neg': 0, 'approx_pos': 0, 'approx_neg': 0, 'agree': 0, 'n': 0}
    for r, p in zip(real, approx):
        rp = r >= cut
        pp = p >= cut
        a['real_pos'] += rp
        a['real_neg'] += not rp
        a['approx_pos'] += pp
        a['approx_neg'] += not pp
        a['agree'] += (rp == pp)
        a['n'] += 1
    a['agree_pct'] = round(a['agree'] / a['n'] * 100, 1) if a['n'] else None
    return a


def main():
    replay = json.load(open(REPLAY, encoding='utf-8'))
    sigs = [s for s in replay['signals'] if s.get('fwd_series')]
    panic = [s for s in sigs if s.get('signal_type') == 'panic']

    con = sqlite3.connect(DB)
    dates, values = load_market_index(con)
    real_sent, real_raw = load_real_sentiment(con)

    idx_by_date = {d: i for i, d in enumerate(dates)}
    panic_checks = []
    for s in panic:
        idx = idx_by_date.get(s['date'])
        approx = approx_sentiment(values, idx) if idx is not None else None
        stored = s.get('sentiment')
        diff = (stored - approx) if stored is not None and approx is not None else None
        panic_checks.append({
            'date': s['date'],
            'name': s['name'],
            'stored_sentiment': stored,
            'recomputed_approx': round(approx, 2) if approx is not None else None,
            'diff': round(diff, 2) if diff is not None else None,
            'real_available': s['date'] in real_sent,
        })
    diffs = [abs(c['diff']) for c in panic_checks if c['diff'] is not None]
    replay_panic = {
        'n': len(panic),
        'date_range': [min(s['date'] for s in panic), max(s['date'] for s in panic)],
        'month_counts': dict(sorted(Counter(s['date'][:7] for s in panic).items())),
        'stored_sentiment_ge75': sum(1 for s in panic if s.get('sentiment') is not None and s['sentiment'] >= 75),
        'stored_sentiment_buckets': dict(sorted(Counter(round(float(s['sentiment'])) for s in panic if s.get('sentiment') is not None).items())),
        'real_sentiment_available': sum(1 for s in panic if s['date'] in real_sent),
        'recomputed_mean_abs_diff': round(statistics.mean(diffs), 3) if diffs else None,
        'recomputed_max_abs_diff': round(max(diffs), 3) if diffs else None,
        'samples': panic_checks[:12],
    }

    overlap_real, overlap_approx, overlap_raw, overlap_dates = [], [], [], []
    for d in sorted(real_sent):
        idx = idx_by_date.get(d)
        if idx is None or idx < 14:
            continue
        approx = approx_sentiment(values, idx)
        overlap_dates.append(d)
        overlap_real.append(real_sent[d])
        overlap_raw.append(real_raw[d])
        overlap_approx.append(approx)

    alignment = {
        'n': len(overlap_dates),
        'date_range': [overlap_dates[0], overlap_dates[-1]] if overlap_dates else None,
        'pearson_sent_vs_approx': round(pearson(overlap_real, overlap_approx), 3) if overlap_real else None,
        'spearman_sent_vs_approx': round(spearman(overlap_real, overlap_approx), 3) if overlap_real else None,
        'pearson_raw_vs_approx': round(pearson(overlap_raw, overlap_approx), 3) if overlap_raw else None,
        'spearman_raw_vs_approx': round(spearman(overlap_raw, overlap_approx), 3) if overlap_raw else None,
        'mae_sent_vs_approx': round(statistics.mean([abs(r - p) for r, p in zip(overlap_real, overlap_approx)]), 2) if overlap_real else None,
        'bias_real_minus_approx': round(statistics.mean([r - p for r, p in zip(overlap_real, overlap_approx)]), 2) if overlap_real else None,
        'threshold_75': threshold_table(overlap_real, overlap_approx, 75),
        'threshold_70': threshold_table(overlap_real, overlap_approx, 70),
        'threshold_50': threshold_table(overlap_real, overlap_approx, 50),
    }

    prod_rows = con.execute('SELECT item_name, signal_date, action_label, entry_price, position_limit, fwd14, fwd30, net14, net30, engine_version FROM signal_tracking ORDER BY signal_date').fetchall()
    production = []
    for r in prod_rows:
        label = r[2] or ''
        unreadable = bool(label) and all(ch in '? ' for ch in label)
        is_panic = None if unreadable else ('恐慌' in label or 'panic' in label.lower())
        idx = idx_by_date.get(r[1])
        production.append({
            'item_name': r[0],
            'signal_date': r[1],
            'action_label': label,
            'is_panic': is_panic,
            'label_unreadable': unreadable,
            'entry_price': r[3],
            'position_limit': r[4],
            'real_greedy_sentiment': real_sent.get(r[1]),
            'approx_sentiment': round(approx_sentiment(values, idx), 2) if idx is not None else None,
            'fwd14': r[5],
            'fwd30': r[6],
            'net14': r[7],
            'net30': r[8],
            'engine_version': r[9],
        })
    production_panic = [p for p in production if p['is_panic'] is True]
    production_unreadable = [p for p in production if p['label_unreadable']]
    con.close()

    out = {
        'generated': 'stage0',
        'replay_panic': replay_panic,
        'real_vs_approx_alignment': alignment,
        'production': {
            'n_total': len(production),
            'n_panic': len(production_panic),
            'n_unreadable': len(production_unreadable),
            'rows': production,
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('written', OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])


if __name__ == '__main__':
    main()
