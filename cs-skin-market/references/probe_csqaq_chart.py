# -*- coding: utf-8 -*-
"""csQAQ chart 数据服务恢复探测（2026-08-11 起，每小时计划任务）。

背景：8/10 csQAQ 故障后 /info/chart 一度空数据。2026-08-11 16:11 修正探测参数：
真实浏览器 body 为 {good_id, key:'sell_price', platform:1, period:'30', style:'all_style'}
（此前探测误用 style='1day' 导致误报 empty；style 必须为 'all_style'）。
本脚本每小时直连探测 3 品，任一品任一平台 main_data 有效点数 >= 30 判恢复。
留痕：data/csqaq_chart_probe.jsonl；恢复时写 data/csqaq_chart_recovery.json。
"""
import io, sys, os, json, time, datetime, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.config import CSQAQ_BASE, API_TOKEN

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
PROBE_LOG = os.path.join(DATA_DIR, 'csqaq_chart_probe.jsonl')
RECOVERY_JSON = os.path.join(DATA_DIR, 'csqaq_chart_recovery.json')

PROBE_GIDS = [279, 999148, 6]

def probe_chart(good_id, platform):
    req = urllib.request.Request(CSQAQ_BASE + '/info/chart', method='POST')
    if API_TOKEN:
        req.add_header('ApiToken', API_TOKEN)
    req.add_header('Content-Type', 'application/json')
    body = {'good_id': str(good_id), 'key': 'sell_price', 'platform': platform,
            'period': '90', 'style': 'all_style'}
    try:
        with urllib.request.urlopen(req, data=json.dumps(body).encode('utf-8'), timeout=25) as resp:
            d = json.loads(resp.read().decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as e:
        return None, f'HTTP {e.code}'
    except Exception as e:
        return None, f'ERR {type(e).__name__}'
    data = d.get('data')
    if d.get('code') == 200 and isinstance(data, dict):
        price = data.get('main_data') or []
        num = data.get('num_data') or []
        n_price = sum(1 for p in price if p is not None and float(p) > 0)
        n_num = sum(1 for v in num if v is not None and float(v) > 0)
        return (n_price, n_num), ''
    return None, f"code={d.get('code')} msg={str(d.get('msg'))[:40]}"

def main():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    samples = {}
    recovered = False
    for gid in PROBE_GIDS:
        res = {}
        for plat in (1, 2):
            r, note = probe_chart(gid, plat)
            if r is not None:
                res[f'p{plat}'] = {'price': r[0], 'num': r[1]}
                if r[0] >= 30:
                    recovered = True
            else:
                res[f'p{plat}'] = {'err': note}
            time.sleep(1.2)
        samples[gid] = res
        if recovered:
            break
    status = 'recovered' if recovered else 'empty'
    line = json.dumps({'ts': now, 'status': status, 'samples': samples}, ensure_ascii=False)
    with io.open(PROBE_LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    if recovered:
        with io.open(RECOVERY_JSON, 'w', encoding='utf-8') as f:
            json.dump({'recovered_at': now, 'samples': samples}, f, ensure_ascii=False, indent=1)
        print(f'[RECOVERED] {now} chart 数据已恢复')
    else:
        print(f'[{status}] {now} chart 数据仍为空: ' + json.dumps(samples, ensure_ascii=False)[:200])

if __name__ == '__main__':
    main()