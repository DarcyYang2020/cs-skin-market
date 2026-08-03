import os, sys, traceback

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TEST_DIR))

passed = 0
failed = 0
failures = []

def check(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f'  PASS: {name}')
    except Exception as e:
        failed += 1
        msg = f'  FAIL: {name} - {e}'
        print(msg)
        failures.append((name, str(e), traceback.format_exc()))

print('=== CS-Market Smoke Tests ===')
print()

print('[Config]')
def t_config():
    from pipeline import config
    assert hasattr(config, 'CSQAQ_BASE')
    assert config.CSQAQ_BASE.startswith('https://')
    assert hasattr(config, 'API_TOKEN')
    assert len(config.API_TOKEN) > 10
check('config loads with csQAQ settings', t_config)

print('[Database]')
def t_db():
    from pipeline import db
    conn = db.get_conn()
    try:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = [t[0] for t in tables]
        for r in ['items', 'price_history', 'snapshots', 'market_index', 'settings']:
            assert r in names, f'Missing: {r} (have {names})'
    finally:
        conn.close()
check('all required tables exist', t_db)

print('[API: Market Index]')
def t_idx():
    from pipeline import collector
    idx = collector.fetch_market_index()
    assert idx is not None
    assert idx.value > 0, f'idx.value={idx.value}'
check('market index API returns valid value', t_idx)

print('[API: Index K-line]')
def t_kline():
    from pipeline import collector
    kline = collector.fetch_index_kline()
    assert len(kline) > 30, f'Only {len(kline)} points'
check('index K-line returns >30 points', t_kline)

print('[Analysis: Index]')
def t_ianalysis():
    from pipeline import index_analysis, collector
    kline = collector.fetch_index_kline()
    result = index_analysis.analyze_index_full(kline)
    assert result.get('has_data')
    assert 'market_trend_health' in result
    assert 'market_fusion_decision' in result
    assert isinstance(result['market_trend_health'].get('score'), int)
check('index analysis produces complete output', t_ianalysis)

print('[API: Item Search]')
def t_search():
    from pipeline import collector
    # csQAQ search API requires properly formatted names
    # Verify function exists and handles errors gracefully
    assert hasattr(collector, 'search_items')
    results = collector.search_items('AK-47')
    # API may return empty for certain queries, but function should not crash
    assert isinstance(results, list)
check('item search function works (no crash)', t_search)

print('[Analysis: Item]')
def t_ia():
    from pipeline.item_analysis import run_item_analysis
    assert callable(run_item_analysis)
check('item_analysis imports cleanly', t_ia)

print('[Analysis: Item P0-4 falling-knife filter]')
def t_knife():
    from types import SimpleNamespace
    import pipeline.item_analysis as ia
    pos = SimpleNamespace(percentile_90d=5.0, zscore_90d=-2.8, high_90d=100.0,
                          low_90d=50.0, mean_90d=80.0, median_90d=82.0,
                          current_price=55.0, data_points=90, valuation_tier='undervalued')
    orig_pos, orig_sent, orig_factor, orig_risk, orig_fd, orig_micro = (
        ia._analyze_position, ia.compute_sentiment_score,
        ia.compute_sentiment_factor, ia.event_risk_coefficient,
        ia.compute_fusion_decision, ia.compute_micro_th)
    ia._analyze_position = lambda prices: pos
    ia.compute_sentiment_score = lambda: 60
    ia.compute_sentiment_factor = lambda: 0.0
    ia.event_risk_coefficient = lambda: 1.0
    ia.compute_micro_th = lambda prices: 70
    def fake_fd(*a, **k):
        return SimpleNamespace(action='buy', action_label='\u5468\u671f\u5438\u7b79\u00b7\u5206\u6279\u5efa\u4ed3',
                               action_detail='', deduction_sources=[], zone='undervalued',
                               zone_label='\u4f4e\u4f30', liquidity_filtered=False,
                               percentile_90d=5.0, raw_th_score=55, corrected_th_score=55,
                               position_limit=None)
    ia.compute_fusion_decision = fake_fd
    kw = dict(name='Test', volumes=[0] * 90, market_pct_90d=5.0,
              market_cycle='consolidation', market_zscore=-2.8, market_th_score=55,
              market_30d_change=-5.0, market_drop21=-25.0, recent_buy_dates=[], signal_date='2026-07-03')
    try:
        # falling knife: last day new low + 3d still down -> downgraded to watch
        prices = [60.0] * 86 + [58.0, 57.0, 56.0, 55.0]
        res = ia.run_item_analysis(prices=prices, **kw)
        fd = res.fusion_decision
        assert fd['action'] == 'watch', fd['action']
        assert 'falling_knife_filter' in fd['deduction_sources'], fd['deduction_sources']
        # stabilized: not making new low -> buy preserved
        prices2 = [60.0] * 86 + [58.0, 57.0, 55.0, 57.0]
        res2 = ia.run_item_analysis(prices=prices2, **kw)
        fd2 = res2.fusion_decision
        assert fd2['action'] == 'buy', fd2['action']
        assert 'falling_knife_filter' not in fd2['deduction_sources'], fd2['deduction_sources']
    finally:
        ia._analyze_position, ia.compute_sentiment_score = orig_pos, orig_sent
        ia.compute_sentiment_factor, ia.event_risk_coefficient = orig_factor, orig_risk
        ia.compute_fusion_decision, ia.compute_micro_th = orig_fd, orig_micro
check('falling-knife filter (z<-2 new-low) downgrades buy', t_knife)

print('[Analysis: Item P0-5/P0-6 panic upgrade + micro-TH confirm]')
def t_panic():
    from types import SimpleNamespace
    import pipeline.item_analysis as ia
    pos = SimpleNamespace(percentile_90d=5.0, zscore_90d=-2.0, high_90d=100.0,
                          low_90d=50.0, mean_90d=80.0, median_90d=82.0,
                          current_price=55.0, data_points=90, valuation_tier='undervalued')
    orig = (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
            ia.event_risk_coefficient, ia.compute_fusion_decision, ia.compute_micro_th)
    ia._analyze_position = lambda prices: pos
    ia.compute_sentiment_score = lambda: 80
    ia.compute_sentiment_factor = lambda: 0.0
    ia.event_risk_coefficient = lambda: 1.0
    def fake_fd(action='watch'):
        return SimpleNamespace(action=action, action_label='', action_detail='',
                               deduction_sources=[], zone='undervalued', zone_label='\u4f4e\u4f30',
                               liquidity_filtered=False, percentile_90d=5.0, raw_th_score=40,
                               corrected_th_score=40, position_limit=None)
    ia.compute_fusion_decision = lambda *a, **k: fake_fd('watch')
    kw = dict(name='Test', volumes=[0] * 90, market_pct_90d=5.0,
              market_cycle='consolidation', market_zscore=-2.0, market_th_score=50,
              market_30d_change=-10.0, market_drop21=-25.0, recent_buy_dates=[], signal_date='2026-05-25')
    kw7 = dict(kw, recent_buy_dates=['2026-05-20'])
    try:
        # P0-5: extreme fear + deep oversold + short-term reversal -> buy
        ia.compute_micro_th = lambda prices: 65
        res = ia.run_item_analysis(prices=[60.0] * 90, **kw)
        fd = res.fusion_decision
        assert fd['action'] == 'buy', fd['action']
        assert 'panic_resonance_upgrade' in fd['deduction_sources'], fd['deduction_sources']
        # micro < 60 -> no upgrade
        ia.compute_micro_th = lambda prices: 55
        res = ia.run_item_analysis(prices=[60.0] * 90, **kw)
        assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
        # sentiment < 75 -> no upgrade
        ia.compute_micro_th = lambda prices: 65
        ia.compute_sentiment_score = lambda: 70
        res = ia.run_item_analysis(prices=[60.0] * 90, **kw)
        assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
        # 7-day cluster blocks repeat upgrade
        ia.compute_sentiment_score = lambda: 80
        res = ia.run_item_analysis(prices=[60.0] * 90, **kw7)
        assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
        # P0-6: buy with weak micro-TH (<45) downgraded
        ia.compute_micro_th = lambda prices: 40
        ia.compute_fusion_decision = lambda *a, **k: fake_fd('buy')
        res = ia.run_item_analysis(prices=[60.0] * 90, **kw)
        fd = res.fusion_decision
        assert fd['action'] == 'watch', fd['action']
        assert 'micro_th_weak' in fd['deduction_sources'], fd['deduction_sources']
        # buy with strong micro-TH kept
        ia.compute_micro_th = lambda prices: 60
        res = ia.run_item_analysis(prices=[60.0] * 90, **kw)
        assert res.fusion_decision['action'] == 'buy', res.fusion_decision['action']
    finally:
        (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
         ia.event_risk_coefficient, ia.compute_fusion_decision, ia.compute_micro_th) = orig
check('panic-resonance upgrade + micro-TH confirm', t_panic)

print('[Analysis: Item price_zones sentiment-adaptive stop/take]')
def t_zones():
    from types import SimpleNamespace
    import pipeline.item_analysis as ia
    pos = SimpleNamespace(percentile_90d=5.0, zscore_90d=-2.0, high_90d=100.0,
                          low_90d=50.0, mean_90d=80.0, median_90d=82.0,
                          current_price=55.0, data_points=90, valuation_tier='undervalued')
    orig = (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
            ia.event_risk_coefficient, ia.compute_fusion_decision, ia.compute_micro_th)
    ia._analyze_position = lambda prices: pos
    ia.compute_sentiment_factor = lambda: 0.0
    ia.event_risk_coefficient = lambda: 1.0
    ia.compute_micro_th = lambda prices: 65
    def fake_fd(*a, **k):
        return SimpleNamespace(action='buy', action_label='x', action_detail='', deduction_sources=[],
                               zone='undervalued', zone_label='low', liquidity_filtered=False,
                               percentile_90d=5.0, raw_th_score=40, corrected_th_score=40, position_limit=None)
    ia.compute_fusion_decision = fake_fd
    kw = dict(name='Test', prices=[60.0] * 86 + [58.0, 57.0, 56.0, 58.0], volumes=[0] * 90, market_pct_90d=5.0,
              market_cycle='consolidation', market_zscore=-2.0, market_th_score=50,
              market_30d_change=-10.0, market_drop21=-25.0, recent_buy_dates=[], signal_date='2026-05-25')
    try:
        # fear: stop -30% / take +40% (P1 fit), hold note present
        ia.compute_sentiment_score = lambda: 80
        pz = ia.run_item_analysis(**kw).price_zones
        assert abs(pz['stop_loss'] - 58.0 * 0.70) < 0.01, pz['stop_loss']
        # buy -> expectancy label present (accumulate bucket: label has no panic word)
        assert pz.get('expectancy') and pz['expectancy']['win14'] > 0, pz.get('expectancy')
        assert abs(pz['take_profit'] - 58.0 * 1.40) < 0.01, pz['take_profit']
        assert '\u6050\u614c' in pz['strategy'] or 'stop' in pz['strategy'], pz['strategy']
        assert '\u5efa\u8bae\u6301\u4ed3' in pz['strategy'], pz['strategy']
        # neutral: ATR stop kept, take +15%
        ia.compute_sentiment_score = lambda: 50
        pz = ia.run_item_analysis(**kw).price_zones
        assert '\u6050\u614c' not in pz['strategy'], pz['strategy']
        assert abs(pz['take_profit'] - 58.0 * 1.15) < 0.01, pz['take_profit']
        # greed: stop -8% / take 1.5xATR (unchanged risk rule)
        ia.compute_sentiment_score = lambda: 25
        pz = ia.run_item_analysis(**kw).price_zones
        assert abs(pz['stop_loss'] - 58.0 * 0.92) < 0.01, pz['stop_loss']
        assert '\u8d2a\u5a6a' in pz['strategy'], pz['strategy']
    finally:
        (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
         ia.event_risk_coefficient, ia.compute_fusion_decision, ia.compute_micro_th) = orig
check('price_zones sentiment-adaptive stop/take', t_zones)

print('[Analysis: Trend Health]')
def t_th():
    from pipeline.trend_health import compute_trend_health
    prices = [100.0 + i * 0.5 for i in range(90)]
    th = compute_trend_health(prices)
    assert 0 <= th.score <= 100
    assert th.direction in ('up', 'flat', 'down')
check('trend_health computes on synthetic data', t_th)

print('[Analysis: Market TH]')
def t_mth():
    from pipeline.market_th import compute_market_trend_health, compute_market_fusion_decision
    prices = [1000.0 + i * 2 for i in range(90)]
    mth = compute_market_trend_health(prices)
    assert 0 <= mth.score <= 100
    mfd = compute_market_fusion_decision(percentile_90d=45.0, th=mth)
    assert mfd.action in ('buy', 'hold', 'watch', 'reduce', 'sell', 'avoid')
check('market TH + fusion compute correctly', t_mth)

print('[Analysis: Valuation]')
def t_val():
    from pipeline.valuation import compute_valuation_grid
    from pipeline.trend_health import compute_trend_health
    prices = [100.0 + i * 0.5 for i in range(90)]
    th = compute_trend_health(prices)
    result = compute_valuation_grid(pct_90d=15.0, trend_health=th)
    assert result.grid_label
    assert result.grid_action
check('valuation grid produces valid action', t_val)

print('[Portfolio Advice: 补仓分级]')
def t_advice():
    from pipeline.batch_scan import _portfolio_advice
    from types import SimpleNamespace
    def mk(pct=15.0, z=-1.0, th=45, phase='consolidation', price_zones=None):
        pos = SimpleNamespace(percentile_90d=pct, zscore_90d=z)
        return SimpleNamespace(
            position=pos,
            trend_health={'score': th},
            cycle=SimpleNamespace(phase=phase),
            fusion_decision={'action': 'hold'},
            value=SimpleNamespace(score=5.0, grade='C'),
            risk_level='D',
            price_zones=price_zones,
        )
    # 深度低估+趋势及格+大盘配合 → 可分批补仓
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45), market_th=50, sentiment_score=60)
    assert a['action'] == '可分批补仓', a['action']
    # 半山腰 pct 25~40 → 暂缓补仓
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=30, z=-0.6, th=45), market_th=50, sentiment_score=60)
    assert a['action'] == '暂缓补仓', a['action']
    # 市场贪婪 sent<=30 → 禁止补仓
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45), market_th=50, sentiment_score=20)
    assert a['action'] == '禁止补仓', a['action']
    # 深度低估但大盘TH<45 → 暂缓补仓
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45), market_th=40, sentiment_score=60)
    assert a['action'] == '暂缓补仓', a['action']
    # 趋势走弱 → 止损
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=25), market_th=50, sentiment_score=60)
    assert a['action'] == '趋势走弱，考虑止损', a['action']
    # A方向(2026-08-03): 带 price_zones 买入区间时给出补仓价位与摊薄成本
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45, price_zones={'entry': {'low': 60.0, 'high': 75.0}, 'current': 80.0}), market_th=50, sentiment_score=60)
    assert a['action'] == '可分批补仓', a['action']
    assert len(a.get('add_positions', [])) == 3, a
    assert a['add_positions'][0]['price'] == 75.0 and a['add_positions'][2]['price'] == 60.0
    assert a['entry_zone'] == {'low': 60.0, 'high': 75.0}
    assert a['avg_cost_after'] > 0, a
    assert '批1' in a['suggest'] and '摊薄成本' in a['suggest'], a['suggest']
    # 非持仓: suggest 给出距建仓参考线的距离
    a = _portfolio_advice(False, 0, 0, 80.0, mk(pct=35, z=-0.8, th=45))
    assert a['action'] == '持有观察', a['action']
    assert '距低估线30%还差5pp' in a['suggest'], a['suggest']
    assert '距55还差10分' in a['suggest'], a['suggest']
check('portfolio advice 补仓分级 works', t_advice)

print('[Youpin Volume Collector]')
def t_youpin_aggregation():
    import asyncio
    from pipeline import collector_youpin as cy
    rows = [
        {"time": 1, "price": "10.0", "localDate": "2026-07-25", "proportion": "1", "sourceType": 0},
        {"time": 2, "price": "10.1", "localDate": "2026-07-25", "proportion": "0.5", "sourceType": 0},
        {"time": 3, "price": "10.2", "localDate": "2026-07-26", "proportion": "0.5", "sourceType": 0},
        {"time": 4, "price": "10.3", "localDate": "2026-07-27", "proportion": "1", "sourceType": 0},
    ]
    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"code": 0, "data": {"tradeDataList": rows}}
    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None, headers=None):
            assert url == cy.API_URL
            assert headers.get('authorization') == 'test-token'
            assert json['templateId'] == '49533'
            assert json['day'] == '90'
            return FakeResp()
    orig_headers, orig_client = cy._api_headers, cy.httpx.AsyncClient
    cy._api_headers = lambda: {'authorization': 'test-token'}
    cy.httpx.AsyncClient = FakeClient
    try:
        result = asyncio.run(cy.fetch_youpin_volume('49533', days=90))
    finally:
        cy._api_headers, cy.httpx.AsyncClient = orig_headers, orig_client
    assert result == {'2026-07-25': 2, '2026-07-26': 1, '2026-07-27': 1}, result
check('youpin volume aggregates tradeDataList by day', t_youpin_aggregation)

def t_youpin_auth_error():
    import asyncio
    from pipeline import collector_youpin as cy
    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"code": -1, "msg": "system busy"}
    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None, headers=None):
            return FakeResp()
    orig_headers, orig_client = cy._api_headers, cy.httpx.AsyncClient
    cy._api_headers = lambda: {'authorization': 'expired'}
    cy.httpx.AsyncClient = FakeClient
    try:
        result = asyncio.run(cy.fetch_youpin_volume('49533'))
    finally:
        cy._api_headers, cy.httpx.AsyncClient = orig_headers, orig_client
    assert result == {}, result
check('youpin volume returns {} on auth error', t_youpin_auth_error)

def t_youpin_no_auth():
    import asyncio
    from pipeline import collector_youpin as cy
    orig = cy._api_headers
    cy._api_headers = lambda: {}
    try:
        result = asyncio.run(cy.fetch_youpin_volume('49533'))
    finally:
        cy._api_headers = orig
    assert result == {}, result
check('youpin volume returns {} without auth', t_youpin_no_auth)

def t_volume_map_fill():
    from webapp import main as webapp
    class Bar:
        def __init__(self, date):
            self.date = date
            self.volume = 0
    vol_map = {'2026-07-25': 2, '2026-07-26': 1}
    bars = [Bar('2026-07-24'), Bar('2026-07-25'), Bar('2026-07-26'), Bar('2026-07-27')]
    webapp._apply_volume_map(bars, vol_map)
    vols = [b.volume for b in bars]
    assert vols == [0, 2, 1, 0], vols
check('volume map fills matching daily bars', t_volume_map_fill)

print('[Guidance]')
def t_guidance():
    from pipeline.batch_scan import signal_guidance
    g = signal_guidance("🟢 恐慌共振·分批建仓")
    assert g["signal_type"] == "panic", g
    assert "30日" in g["hold_guidance"], g
    g2 = signal_guidance("🟢 周期吸筹·分批建仓")
    assert g2["signal_type"] == "accumulate", g2
    g3 = signal_guidance("🟢 超跌反弹·分批建仓")
    assert g3["signal_type"] == "oversold", g3
    g4 = signal_guidance("🟢 分批建仓")
    assert g4["signal_type"] == "base", g4
    g5 = signal_guidance("🟢 分批建仓", {"label": "周期吸筹"})
    assert g5["type_label"] == "周期吸筹", g5
check('signal guidance classifies buy types', t_guidance)

print()
print(f'=== Results: {passed} passed, {failed} failed ===')
if failures:
    print()
    for name, msg, tb in failures:
        print(f'  FAIL: {name}')
        for l in tb.strip().split(chr(10))[-2:]:
            print(f'    {l}')
sys.exit(0 if failed == 0 else 1)
