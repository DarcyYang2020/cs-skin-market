import os, sys, traceback

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TEST_DIR))

passed = 0
failed = 0
skipped = 0
failures = []

SKIP_NET = os.environ.get('CS_MODEL_SKIP_NET', '') == '1'

def check(name, fn, skip=False):
    global passed, failed, skipped
    if skip:
        skipped += 1
        print(f'  SKIP: {name}')
        return
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
print('[Database: schema 版本化]')
def t_schema_version():
    from pipeline import db
    conn = db.get_conn()
    try:
        tables = [t0[0] for t0 in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert 'schema_version' in tables, tables
        row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        assert row is not None and row[0] == db.SCHEMA_VERSION, row
        assert not hasattr(db, 'MIGRATIONS')
    finally:
        conn.close()
check('schema_version 表记录当前版本', t_schema_version)

print('[API: Market Index]')
def t_idx():
    from pipeline import collector
    idx = collector.fetch_market_index()
    assert idx is not None
    assert idx.value > 0, f'idx.value={idx.value}'
check('market index API returns valid value', t_idx, skip=SKIP_NET)

print('[API: Index K-line]')
def t_kline():
    from pipeline import collector
    kline = collector.fetch_index_kline()
    assert len(kline) > 30, f'Only {len(kline)} points'
check('index K-line returns >30 points', t_kline, skip=SKIP_NET)

print('[Analysis: Index]')
def t_ianalysis():
    from pipeline import index_analysis, collector
    kline = collector.fetch_index_kline()
    result = index_analysis.analyze_index_full(kline)
    assert result.get('has_data')
    assert 'market_trend_health' in result
    assert 'market_fusion_decision' in result
    assert isinstance(result['market_trend_health'].get('score'), int)
    assert 'buy_distance' not in result, "F-3.8 大盘距买点展示模块已移除"
check('index analysis produces complete output', t_ianalysis, skip=SKIP_NET)

print('[API: Item Search]')
def t_search():
    from pipeline import collector
    results = collector.search_items('AK-47')
    # New suggest API: must return real items with valid good_id (hard dependency check)
    assert isinstance(results, list) and len(results) > 0, f'empty search results: {results}'
    assert results[0].good_id > 0, f'bad good_id: {results[0].good_id}'
    assert results[0].name, 'missing item name'
check('item search returns real items (suggest API)', t_search, skip=SKIP_NET)

print('[API: MarketHash -> good_id]')
def t_hash():
    from pipeline import collector
    gid = collector.get_good_id_by_market_hash('AK-47 | Elite Build (Battle-Scarred)')
    assert gid > 0, f'resolve failed: {gid}'
check('market hash resolves to good_id (getPriceByMarketHashName)', t_hash, skip=SKIP_NET)

print('[API: Item Detail]')
def t_detail():
    from pipeline import collector
    det = collector.fetch_item_detail(good_id=30)
    assert det is not None and det.good_id == 30, f'detail missing: {det}'
    assert det.name and det.price_rmb > 0, f'incomplete fields: name={det.name} price={det.price_rmb}'
check('item detail via info/good returns fields', t_detail, skip=SKIP_NET)

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
    kw = dict(name='Test', market_pct_90d=5.0,
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
    kw = dict(name='Test', market_pct_90d=5.0,
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
    kw = dict(name='Test', prices=[60.0] * 86 + [58.0, 57.0, 56.0, 58.0], market_pct_90d=5.0,
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
    def mk(pct=15.0, z=-1.0, th=45, phase='consolidation', price_zones=None, fusion='hold'):
        pos = SimpleNamespace(percentile_90d=pct, zscore_90d=z)
        return SimpleNamespace(
            position=pos,
            trend_health={'score': th},
            cycle=SimpleNamespace(phase=phase),
            fusion_decision={'action': fusion},
            value=SimpleNamespace(score=5.0, grade='C'),
            risk_level='D',
            price_zones=price_zones,
        )
    # 深度低估+趋势及格+大盘配合+融合buy → 可分批补仓 (P1: 需融合决策放行)
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45, fusion='buy'), market_th=50, sentiment_score=60)
    assert a['action'] == '可分批补仓', a['action']
    # 半山腰 pct 25~40 → 暂缓补仓
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=30, z=-0.6, th=45), market_th=50, sentiment_score=60)
    assert a['action'] == '暂缓补仓', a['action']
    # 市场贪婪 sent<=30 → 禁止补仓
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45), market_th=50, sentiment_score=20)
    assert a['action'] == '禁止补仓', a['action']
    # 深跌恐慌提前补(2026-08-05): sent>=80 + 大盘30日跌幅<=-15% + pct<=20 + z<=-1 → 不等确认
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=25, fusion='watch'), market_th=30, sentiment_score=85, market_30d_change=-18.0)
    assert a['action'] == '可分批补仓', a['action']
    assert 'V型底指纹' in a['reason'], a['reason']
    # 中跌恐慌暂缓(2026-08-05): sent>=80 + 大盘30日跌幅5~15% → 阴跌中继风险
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45), market_th=50, sentiment_score=85, market_30d_change=-8.0)
    assert a['action'] == '暂缓补仓', a['action']
    assert '阴跌中继' in a['reason'], a['reason']
    # 深度低估但大盘TH<45 → 暂缓补仓
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45), market_th=40, sentiment_score=60)
    assert a['action'] == '暂缓补仓', a['action']
    # P1(2026-08-04): 条件满足但融合决策未放行(watch) → 暂缓补仓(回测: watch子集14d均值-0.3%)
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45, fusion='watch'), market_th=50, sentiment_score=60)
    assert a['action'] == '暂缓补仓', a['action']
    assert '融合决策未放行' in a['reason'], a['reason']
    # 趋势走弱 → 止损
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=25), market_th=50, sentiment_score=60)
    assert a['action'] == '趋势走弱，考虑止损', a['action']
    # A方向(2026-08-03): 带 price_zones 买入区间时给出补仓价位与摊薄成本
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45, fusion='buy', price_zones={'entry': {'low': 60.0, 'high': 75.0}, 'current': 80.0}), market_th=50, sentiment_score=60)
    assert a['action'] == '可分批补仓', a['action']
    assert len(a.get('add_positions', [])) == 3, a
    assert a['add_positions'][0]['price'] == 75.0 and a['add_positions'][2]['price'] == 60.0
    assert a['entry_zone'] == {'low': 60.0, 'high': 75.0}
    assert a['avg_cost_after'] > 0, a
    assert '批1' in a['suggest'] and '摊薄成本' in a['suggest'], a['suggest']
    # 持仓: signal_guidance 传 expectancy -> type_label 覆盖为分层标签(2026-08-04 修复)
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45, fusion='buy', price_zones={'entry': {'low': 60.0, 'high': 75.0}, 'expectancy': {'label': '深值企稳'}}), market_th=50, sentiment_score=60)
    assert a['type_label'] == '深值企稳', a['type_label']
    # 非持仓: suggest 给出距建仓参考线的距离
    a = _portfolio_advice(False, 0, 0, 80.0, mk(pct=35, z=-0.8, th=45))
    assert a['action'] == '持有观察', a['action']
    assert '距低估线30%还差5pp' in a['suggest'], a['suggest']
    assert '摩擦带(35-54)' in a['suggest'], a['suggest']
    # 非持仓 buy 信号: 建议给出分批建仓方案（方案C, 回测最优）
    a = _portfolio_advice(False, 0, 0, 80.0, mk(pct=15, z=-1.2, th=60, fusion='buy', price_zones={'entry': {'low': 60.0, 'high': 75.0}}))
    assert a['action'] == '可分批建仓', a['action']
    assert '首仓10%' in a['suggest'] and '跌10%加20%' in a['suggest'] and '跌15%加30%' in a['suggest'], a['suggest']
check('portfolio advice 补仓分级 works', t_advice)

def t_p08_deep_value_tranche():
    from types import SimpleNamespace
    import pipeline.item_analysis as ia
    pos = SimpleNamespace(percentile_90d=15.0, zscore_90d=-0.8, high_90d=100.0,
                          low_90d=50.0, mean_90d=80.0, median_90d=82.0,
                          current_price=57.0, data_points=90, valuation_tier='undervalued')
    orig = (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
            ia.event_risk_coefficient, ia.compute_micro_th, ia.compute_fusion_decision)
    ia._analyze_position = lambda prices: pos
    ia.compute_sentiment_score = lambda: 50          # 40<=sent<=65
    ia.compute_sentiment_factor = lambda: 0.0
    ia.event_risk_coefficient = lambda: 1.0
    ia.compute_micro_th = lambda prices: 45          # 单品TH>=35
    def fake_fd(*a, **k):
        return SimpleNamespace(action='watch', action_label='🟡 观望', action_detail='',
                               deduction_sources=[], zone='undervalued', zone_label='低估',
                               liquidity_filtered=False, percentile_90d=15.0,
                               raw_th_score=45, corrected_th_score=45, position_limit=0.0)
    ia.compute_fusion_decision = fake_fd
    kw = dict(name='Test', market_pct_90d=15.0,
              market_cycle='consolidation', market_zscore=-0.8, market_th_score=45,
              market_30d_change=-3.0, market_drop21=-3.0, recent_buy_dates=[], signal_date='2026-07-03')
    # 先跌后恢复: 单品TH真实计算>=35, 触发 P0-8 深值企稳
    prices = [60.0]*80 + [58.0, 56.0, 55.0, 56.0, 57.0, 58.0, 58.5, 59.0, 59.5, 60.0]
    try:
        res = ia.run_item_analysis(prices=prices, **kw)
        fd = res.fusion_decision
        assert fd['action'] == 'buy', fd['action']
        assert 'deep_value_stable_market' in fd['deduction_sources'], fd['deduction_sources']
        assert '深值' in fd['action_label'], fd['action_label']
        assert fd['position_limit'] == 0.10, fd['position_limit']
        # 2026-08-04 分批落地: action_detail 带档位与加权期望
        assert '分批' in fd['action_detail'] and '跌10%加20%' in fd['action_detail'], fd['action_detail']
    finally:
        (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
         ia.event_risk_coefficient, ia.compute_micro_th, ia.compute_fusion_decision) = orig
check('P0-8 deep-value buy carries tranche advice (2026-08-04)', t_p08_deep_value_tranche)

def t_p09_panic_easing_deep_bottom():
    from types import SimpleNamespace
    import pipeline.item_analysis as ia
    pos = SimpleNamespace(percentile_90d=10.0, zscore_90d=-1.5, high_90d=100.0,
                          low_90d=50.0, mean_90d=80.0, median_90d=82.0,
                          current_price=55.0, data_points=90, valuation_tier='undervalued')
    orig = (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
            ia.event_risk_coefficient, ia.compute_micro_th, ia.compute_fusion_decision)
    ia._analyze_position = lambda prices: pos
    ia.compute_sentiment_score = lambda: 60          # 55<=sent<=80 恐慌退潮区
    ia.compute_sentiment_factor = lambda: 0.0
    ia.event_risk_coefficient = lambda: 1.0
    ia.compute_micro_th = lambda prices: 30          # microTH 弱, 基础/P0-5 均不触发
    def fake_fd(*a, **k):
        return SimpleNamespace(action='watch', action_label='🟡 观望', action_detail='',
                               deduction_sources=[], zone='undervalued', zone_label='低估',
                               liquidity_filtered=False, percentile_90d=10.0,
                               raw_th_score=30, corrected_th_score=30, position_limit=0.0)
    ia.compute_fusion_decision = fake_fd
    kw = dict(name='Test', market_pct_90d=10.0,
              market_cycle='consolidation', market_zscore=-1.5, market_th_score=30,
              market_30d_change=-18.0, market_drop21=-18.0, recent_buy_dates=[], signal_date='2026-05-28')
    # 1) 深跌 + 恐慌退潮 + 止跌(55,54,55) -> P0-9 触发
    prices = [60.0]*80 + [57.0, 56.0, 55.0, 54.0, 55.0]
    try:
        res = ia.run_item_analysis(prices=prices, **kw)
        fd = res.fusion_decision
        assert fd['action'] == 'buy', fd['action']
        assert 'panic_easing_deep_bottom' in fd['deduction_sources'], fd['deduction_sources']
        assert '恐慌退潮' in fd['action_label'], fd['action_label']
        assert fd['position_limit'] == 0.10, fd['position_limit']
    finally:
        pass
    # 2) 7天去重: 5/25 已 buy -> 5/28 不触发
    kw2 = dict(kw, recent_buy_dates=['2026-05-25'])
    res = ia.run_item_analysis(prices=prices, **kw2)
    assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
    # 3) 未止跌(55,54,53 继续创新低) -> 不触发
    prices2 = [60.0]*80 + [57.0, 56.0, 55.0, 54.0, 53.0]
    res = ia.run_item_analysis(prices=prices2, **kw)
    assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
    # 4) 大盘30日跌幅不够深(-10) -> 不触发(阴跌中继)
    kw3 = dict(kw, market_30d_change=-10.0)
    res = ia.run_item_analysis(prices=prices, **kw3)
    assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
    (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
     ia.event_risk_coefficient, ia.compute_micro_th, ia.compute_fusion_decision) = orig
check('P0-9 panic-easing deep-drop buy + 7d dedup (2026-08-05)', t_p09_panic_easing_deep_bottom)

def t_p1_supply_accumulation():
    from types import SimpleNamespace
    import pipeline.item_analysis as ia
    pos = SimpleNamespace(percentile_90d=45.0, zscore_90d=-0.3, high_90d=100.0,
                          low_90d=50.0, mean_90d=80.0, median_90d=82.0,
                          current_price=60.0, data_points=90, valuation_tier='fair')
    orig = (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
            ia.event_risk_coefficient, ia.compute_micro_th, ia.compute_fusion_decision)
    ia._analyze_position = lambda prices: pos
    ia.compute_sentiment_score = lambda: 50          # 中性, P1-0 门控放行(禁 贪婪+弱TH)
    ia.compute_sentiment_factor = lambda: 0.0
    ia.event_risk_coefficient = lambda: 1.0
    ia.compute_micro_th = lambda prices: 30          # microTH 弱, 基础/P0-5 不触发
    def fake_fd(*a, **k):
        return SimpleNamespace(action='watch', action_label='🟡 观望', action_detail='',
                               deduction_sources=[], zone='fair', zone_label='合理',
                               liquidity_filtered=False, percentile_90d=45.0,
                               raw_th_score=40, corrected_th_score=40, position_limit=0.0)
    ia.compute_fusion_decision = fake_fd
    supply = [100] * 23 + [60] * 7        # 30日均量90.7 -> 7日均量60 (0.66x < 0.85, 收缩)
    prices = [60.0] * 83 + [59.5, 60.2, 60.8, 60.0, 60.5, 60.3, 60.7]  # 7日|涨跌|<=3%
    kw = dict(name='Test', supply_hist=supply, market_pct_90d=50.0,
              market_cycle='volatile', market_zscore=0.0, market_th_score=50,
              market_30d_change=-5.0, market_drop21=-3.0, recent_buy_dates=[], signal_date='2026-03-01')
    # 1) 供给收缩+价格平稳+门控放行 -> P1-0 buy(轻仓0.10)
    res = ia.run_item_analysis(prices=prices, **kw)
    fd = res.fusion_decision
    assert fd['action'] == 'buy', fd['action']
    assert 'supply_contraction_accumulation' in fd['deduction_sources'], fd['deduction_sources']
    assert '吸筹' in fd['action_label'], fd['action_label']
    assert fd['position_limit'] == 0.10, fd['position_limit']
    # 2) 门控拦截: 贪婪(sent=30) + 大盘弱TH(40) -> 不触发
    ia.compute_sentiment_score = lambda: 30
    kw2 = dict(kw, market_th_score=40)
    res = ia.run_item_analysis(prices=prices, **kw2)
    assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
    ia.compute_sentiment_score = lambda: 50
    # 3) 供给未收缩(7日均100 = 30日均100) -> 不触发
    supply2 = [100] * 30
    res = ia.run_item_analysis(prices=prices, **dict(kw, supply_hist=supply2))
    assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
    # 4) 7天去重: 2/26 已 buy -> 3/1 不触发
    kw3 = dict(kw, recent_buy_dates=['2026-02-26'])
    res = ia.run_item_analysis(prices=prices, **kw3)
    assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
    # 5) 价格不稳(7日涨8%) -> 不触发
    prices2 = [60.0] * 83 + [62.0, 63.0, 63.5, 64.0, 64.5, 64.8, 64.8]
    res = ia.run_item_analysis(prices=prices2, **kw)
    assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
    # 6) 存世量过低(<3000) -> 不触发
    res = ia.run_item_analysis(prices=prices, **dict(kw, survive_count=500))
    assert res.fusion_decision['action'] == 'watch', res.fusion_decision['action']
    # 7) 强牛段放行（I-8 边界，2026-08-06 回放 sent<40+TH>=60 -> 30d +46.3%）:
    #    贪婪(sent=30) + 大盘强TH(60) 不满足禁入(sent<40 AND th<45) -> 仍触发
    ia.compute_sentiment_score = lambda: 30
    res7 = ia.run_item_analysis(prices=prices, **dict(kw, market_th_score=60))
    fd7 = res7.fusion_decision
    assert fd7['action'] == 'buy', fd7['action']
    assert fd7['position_limit'] == 0.10, fd7['position_limit']
    ia.compute_sentiment_score = lambda: 50
    (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
     ia.event_risk_coefficient, ia.compute_micro_th, ia.compute_fusion_decision) = orig
check('P1-0 supply-contraction accumulation buy + gate/dedup/survive', t_p1_supply_accumulation)

print('[Batch Scan: 信号提取]')
def t_extract_signals():
    from pipeline.batch_scan import extract_signals
    results = [
        dict(name="A", holding=0, buy_distance={"gap_pct": -1.0}, portfolio_advice={"action": "观望等待机会", "suggest": "x"}),
        dict(name="B", holding=1, buy_distance={"gap_pct": 4.0}, portfolio_advice={"action": "可分批补仓", "suggest": "可分3批补仓"}),
        dict(name="C", holding=1, buy_distance={"gap_pct": 2.0}, portfolio_advice={"action": "趋势走弱，考虑止损", "suggest": "y"}),
        dict(name="D", holding=0, buy_distance={"gap_pct": 12.0}, portfolio_advice={"action": "观望等待机会", "suggest": "z"}),
        dict(name="E", holding=0, buy_distance={"gap_pct": 0.0}, portfolio_advice={"action": "可分批建仓", "suggest": "w"}),
        dict(name="F", holding=0, error="价格校验未通过"),
    ]
    sigs = extract_signals(results)
    # 补仓优先 > 止损 > 已到买点；D(远离)与F(错误)不产生信号
    assert [s["name"] for s in sigs] == ["B", "C", "A", "E"], [s["name"] for s in sigs]
    assert sigs[0]["action"] == "可分批补仓" and sigs[0]["holding"] == 1
    assert sigs[2]["action"] == "已到买点" and sigs[2]["gap_pct"] == -1.0
    assert sigs[3]["action"] == "已到买点" and sigs[3]["gap_pct"] == 0.0
    # 无信号场景
    assert extract_signals([dict(name="X", holding=0, buy_distance={"gap_pct": 20.0}, portfolio_advice={"action": "观望等待机会"})]) == []
check('batch scan 信号提取(补仓/止损/已到买点)', t_extract_signals)

print('[Batch Scan: 距买点摘要/排序/HTML]')
def t_batch_scan_display():
    from pipeline.batch_scan import summarize_buy_distance, sort_results, build_scan_html
    from pipeline.buy_distance import tranche_plan_text
    bd = {"scenario": "bottom", "scenario_label": "抄底/下跌中继", "current_price": 111.0,
          "target_price": 106.6, "gap_pct": 4.0, "bar_pct": 20.0, "summary": "再跌 4.0% 到 ¥106.60 触发买点"}
    s = summarize_buy_distance(bd)
    assert s["target_price"] == 106.6 and s["gap_pct"] == 4.0 and s["bar_pct"] == 20.0, s
    assert summarize_buy_distance(None) is None
    assert summarize_buy_distance({}) is None
    assert tranche_plan_text() == '首仓10% → 跌10%加20% → 跌15%加30%', tranche_plan_text()
    # 排序(2026-08-04): 统一按距买点 gap 升序（最接近买点在前）——持仓不再按浮亏排
    held = [dict(holding=1, avg_cost=100.0, price_rmb=130.0, name="赚", buy_distance={"gap_pct": 3.0}),
            dict(holding=1, avg_cost=100.0, price_rmb=70.0, name="亏", buy_distance={"gap_pct": 8.0})]
    unheld = [dict(holding=0, avg_cost=0, price_rmb=100.0, name="远", buy_distance={"gap_pct": 8.0}),
              dict(holding=0, avg_cost=0, price_rmb=100.0, name="近", buy_distance={"gap_pct": 2.0})]
    out = sort_results(held + unheld)
    assert [r["name"] for r in out] == ["赚", "亏", "近", "远"], [r["name"] for r in out]
    # 同层级(止损层)时浮亏大在前（次级排序）
    held_tie = [dict(holding=1, avg_cost=100.0, price_rmb=70.0, name="亏", buy_distance={"gap_pct": 5.0},
                     portfolio_advice={"action": "趋势走弱，考虑止损"}),
                dict(holding=1, avg_cost=100.0, price_rmb=130.0, name="赚", buy_distance={"gap_pct": 5.0},
                     portfolio_advice={"action": "趋势走弱，考虑止损"})]
    assert [r["name"] for r in sort_results(held_tie)] == ["亏", "赚"]
    # 无 buy_distance 的品排最后
    held_no = [dict(holding=1, avg_cost=100.0, price_rmb=130.0, name="A", buy_distance={"gap_pct": 3.0}),
               dict(holding=1, avg_cost=100.0, price_rmb=70.0, name="B")]
    assert [r["name"] for r in sort_results(held_no)] == ["A", "B"]
    # HTML 冒烟：市场条 + 距买点列 + 汇总统计
    results = [
        dict(name="A", holding=0, price_rmb=100.0, grade="A", score=4.0, valuation_tier="低估", percentile_90d=12.0,
             buy_distance={"scenario_label": "抄底/下跌中继", "target_price": 96.0, "gap_pct": 4.0, "bar_pct": 20.0},
             portfolio_advice={"action": "观望等待机会", "suggest": "再跌 4.0%", "hold_guidance": ""}, error=None),
        dict(name="B", holding=0, price_rmb=90.0, grade="B", score=3.0, valuation_tier="低估", percentile_90d=5.0,
             buy_distance={"scenario_label": "已到买点", "target_price": 90.0, "gap_pct": 0.0, "bar_pct": 100.0},
             portfolio_advice={"action": "可分批建仓", "suggest": "已到建仓区，可分批建仓：首仓10% → 跌10%加20% → 跌15%加30%", "hold_guidance": ""}, error=None),
    ]
    html = build_scan_html(results, 2, {"th": 55, "sentiment": 70, "cycle": "bear", "index": 1566}, now_str="12:00:00")
    assert "市场环境" in html and "大盘TH=55" in html, html
    assert "距买点" in html
    assert "1 个已到买点" in html, html
    assert "跌10%加20%" in html, html
    assert "¥96.00" in html and "¥90.00" in html
    assert "批量扫描完成" in html and "成功 2/2" in html
    # P2(2026-08-04): 并发建议仓位超上限 → 预警提示(展示层)
    results_cap = [
        dict(name="A", holding=0, price_rmb=100.0, grade="A", score=4.0, valuation_tier="低估", percentile_90d=12.0,
             buy_distance={}, position_limit=0.3,
             portfolio_advice={"action": "可分批建仓", "suggest": "", "hold_guidance": ""}, error=None),
        dict(name="B", holding=0, price_rmb=90.0, grade="A", score=4.0, valuation_tier="低估", percentile_90d=10.0,
             buy_distance={}, position_limit=0.3,
             portfolio_advice={"action": "可分批建仓", "suggest": "", "hold_guidance": ""}, error=None),
        dict(name="C", holding=1, avg_cost=100.0, price_rmb=85.0, grade="A", score=4.0, valuation_tier="低估", percentile_90d=12.0,
             buy_distance={}, position_limit=0.3,
             portfolio_advice={"action": "可分批补仓", "suggest": "", "hold_guidance": ""}, error=None),
    ]
    html_cap = build_scan_html(results_cap, 3, {"th": 55, "sentiment": 70, "cycle": "bear", "index": 1566}, now_str="12:00:00")
    assert "并发建议仓位 90%" in html_cap, html_cap
    assert "上限 80%" in html_cap, html_cap
check('batch scan 距买点摘要/排序/HTML works', t_batch_scan_display)

def t_advice_buy_distance_passthrough():
    from pipeline.batch_scan import _portfolio_advice
    from types import SimpleNamespace
    pos = SimpleNamespace(percentile_90d=35.0, zscore_90d=-0.8)
    bd = {"scenario": "bottom", "scenario_label": "抄底/下跌中继", "current_price": 80.0,
          "target_price": 74.0, "gap_pct": 7.5, "bar_pct": 37.5, "summary": "再跌 7.5% 到 ¥74.00 触发买点"}
    a = SimpleNamespace(position=pos, trend_health={"score": 45}, cycle=SimpleNamespace(phase="consolidation"),
                        fusion_decision={"action": "watch", "action_label": "🟡 观望"}, value=SimpleNamespace(score=3.0, grade="B"),
                        risk_level="C", price_zones=None, buy_distance=bd)
    adv = _portfolio_advice(False, 0, 0, 80.0, a)
    assert adv["buy_distance"] is not None and adv["buy_distance"]["target_price"] == 74.0, adv
    assert adv["buy_distance"]["gap_pct"] == 7.5, adv
    # 无 buy_distance 属性兼容（旧对象）
    a2 = SimpleNamespace(position=pos, trend_health={"score": 45}, cycle=SimpleNamespace(phase="consolidation"),
                         fusion_decision={"action": "watch", "action_label": "🟡 观望"}, value=SimpleNamespace(score=3.0, grade="B"),
                         risk_level="C", price_zones=None)
    adv2 = _portfolio_advice(False, 0, 0, 80.0, a2)
    assert adv2["buy_distance"] is None, adv2
check('portfolio advice 透传距买点摘要', t_advice_buy_distance_passthrough)

print('[Guidance]')
def t_guidance():
    from pipeline.batch_scan import signal_guidance
    g = signal_guidance("🟢 恐慌共振·分批建仓")
    assert g["signal_type"] == "panic", g
    assert "14日" in g["hold_guidance"], g
    g2 = signal_guidance("🟢 周期吸筹·分批建仓")
    assert g2["signal_type"] == "accumulate", g2
    g3 = signal_guidance("🟢 超跌反弹·分批建仓")
    assert g3["signal_type"] == "oversold", g3
    g4 = signal_guidance("🟢 分批建仓")
    assert g4["signal_type"] == "base", g4
    g5 = signal_guidance("🟢 分批建仓", {"label": "周期吸筹"})
    assert g5["type_label"] == "周期吸筹", g5
check('signal guidance classifies buy types', t_guidance)
print('[Buy Distance]')
def t_buy_distance_prices():
    from types import SimpleNamespace
    from pipeline.buy_distance import compute_buy_distance
    import statistics
    prices = list(range(11, 101))  # 90 points, current=100
    pos = SimpleNamespace(percentile_90d=80.0, zscore_90d=1.5)
    bd = compute_buy_distance(prices, pos, 40.0, price_zones={'entry': {'low': 30, 'high': 45}})
    assert bd is not None
    # 目标 = 买入区上沿
    assert bd['drop_to_entry_pct'] == 55.0, bd
    assert bd['drop_price'] == 45.0, bd
    assert bd['in_entry_zone'] is False
    # pct30 反推价格: 30% 分位
    assert bd['pct30_price'] == 38.0, bd
    # z=-1.5 反推价格: 用同口径 MAD 公式验证
    med = statistics.median(prices)
    mad = statistics.median([abs(v - med) for v in prices])
    z_at = (bd['z15_price'] - med) / (mad * 1.4826)
    assert abs(z_at + 1.5) < 0.01, z_at
    # z gap 方向: z=1.5 距 -1.5 还差 3.0
    assert bd['z_gap'] == 3.0, bd
    assert bd['th_gap'] == 15.0, bd
check('buy_distance quantifies drop% to entry zone', t_buy_distance_prices)

def t_buy_distance_in_zone():
    from types import SimpleNamespace
    from pipeline.buy_distance import compute_buy_distance
    prices = [100.0] * 40 + [105.0] * 50   # current=105, stable
    pos = SimpleNamespace(percentile_90d=25.0, zscore_90d=-1.6)
    bd = compute_buy_distance(prices, pos, 58.0, price_zones={'entry': {'low': 100, 'high': 106}})
    assert bd['in_entry_zone'] is True, bd
    assert bd['bar_pct'] == 100, bd
    assert bd['scenario'] == 'done' and bd['target_price'] == bd['current_price'], bd
    assert bd['pct_gap'] == 0.0 and bd['z_gap'] == 0.0 and bd['th_gap'] == 0.0, bd
    assert bd.get('tranche_plan') and '首仓10%' in bd['tranche_plan'] and '跌10%加20%' in bd['tranche_plan'], bd
check('buy_distance marks in-zone with full bar', t_buy_distance_in_zone)

def t_buy_distance_scenarios():
    from types import SimpleNamespace
    from pipeline.buy_distance import compute_buy_distance
    # 下跌寻底: current=111 已过 pct30 -> 目标=z-1.5(仍低于现价)
    prices = [200.0]
    c = 200.0
    for _ in range(89):
        c *= 0.994
        prices.append(round(c, 2))
    prices[-1] = 111.0
    pos = SimpleNamespace(percentile_90d=5.0, zscore_90d=-1.8)
    bd = compute_buy_distance(prices, pos, 32.0, price_zones={'entry': {'low': 0, 'high': 0}}, cycle_phase='distribution')
    assert bd is not None and bd['scenario'] == 'bottom', bd
    assert bd['target_price'] < bd['current_price'], bd          # 目标价永不高于现价
    assert bd['gap_pct'] > 0 and bd['gap_rmb'] > 0, bd
    assert bd['z15_price'] and bd['z15_price'] < bd['current_price'], bd
    # 强势回踩: 目标=MA支撑(低于现价)
    bd2 = compute_buy_distance(prices, pos, 65.0, price_zones={'entry': {'low': 0, 'high': 0}}, cycle_phase='accumulation')
    assert bd2['scenario'] in ('breakout', 'pullback'), bd2
    assert bd2['target_price'] <= bd2['current_price'], bd2
    # 已到买点: 目标=现价
    bd3 = compute_buy_distance(prices, pos, 32.0, price_zones={'entry': {'low': 0, 'high': 0}}, cycle_phase='distribution', action='buy')
    assert bd3['scenario'] == 'done' and bd3['target_price'] == bd3['current_price'], bd3
    assert '首仓10%' in bd3.get('tranche_plan', ''), bd3
check('buy_distance scenario targets never exceed current price', t_buy_distance_scenarios)

def t_buy_distance_anchor():
    from types import SimpleNamespace
    from pipeline.buy_distance import compute_buy_distance
    # 锚定价仅作展示：场景/目标/距离按 chart K线口径（与百分位同源），
    # 悠悠价 90 vs K线收盘 111 偏差 -19% → anchor_note 提示，不再混源得出「已低于90日低」
    prices = [200.0]
    c = 200.0
    for _ in range(89):
        c *= 0.994
        prices.append(round(c, 2))
    prices[-1] = 111.0
    pos = SimpleNamespace(percentile_90d=5.0, zscore_90d=-1.8)
    bd = compute_buy_distance(prices, pos, 32.0, price_zones={'entry': {'low': 0, 'high': 0}},
                              cycle_phase='distribution', anchor_price=90.0)
    assert bd is not None and bd['current_price'] == 111.0, bd          # K线口径
    assert bd['target_price'] <= bd['current_price'], bd
    assert bd['anchor_price'] == 90.0, bd                                # 悠悠锚价仅展示
    assert bd['anchor_note'] and '偏差' in bd['anchor_note'], bd
    assert bd['scenario'] != 'extreme', bd
    # 无锚定价时仅展示当前价回退窗口最后价
    bd2 = compute_buy_distance(prices, pos, 32.0, price_zones={'entry': {'low': 0, 'high': 0}},
                               cycle_phase='distribution')
    assert bd2['current_price'] == 111.0 and bd2.get('anchor_price') is None, bd2
check('buy_distance anchor_price is display-only (chart-consistent)', t_buy_distance_anchor)

def t_buy_distance_v3():
    # 距买点 v3（2026-08-07 去量理念）：下跌中继不追跌 / 供给吸筹就近 / 恐慌黄金坑
    from pipeline.buy_distance import compute_buy_distance
    # 连跌创新低（下跌中继）→ 等企稳不追跌：target 为 MA/ATR 支撑而非一路下探
    prices = [200 - i for i in range(90)]
    class _P:
        percentile_90d = 25
        zscore_90d = -1.0
    bd = compute_buy_distance(prices, _P(), th_score=26)
    assert bd and bd["scenario"] == "bottom" and bd["stabilizing"] is False, bd
    assert "下跌中继" in bd["scenario_label"], bd["scenario_label"]
    assert 0 < bd["target_price"] < bd["current_price"], bd
    # 供给吸筹（supply_risk=hoarding）→ 买点就近 MA 支撑
    bd2 = compute_buy_distance(prices, _P(), th_score=26,
                               supply={"supply_risk": "hoarding", "supply_trend": "contracting"})
    assert bd2 and bd2["scenario"] == "accumulate" and bd2["supply_signal"] == "hoarding", bd2
    assert bd2["target_price"] < bd2["current_price"], bd2
check('buy_distance v3: 下跌中继不追跌/供给吸筹就近/恐慌黄金坑', t_buy_distance_v3)

print('[Data Sane: K线脏价校验]')
def t_kline_price_sane():
    from types import SimpleNamespace
    from webapp.analysis_service import kline_price_sane
    def bars(last):
        # 平滑序列（无大跳变），只改最后一天 → 专测「整体口径偏移」漏检场景
        b = [SimpleNamespace(date="2026-08-%02d" % (d + 1), close=640.0) for d in range(4)]
        b[-1].close = last
        return b
    # 死寂空间场景：chart 883 vs 悠悠锚 614 → 应拦截（整体偏移、序列平滑）
    ok, msg = kline_price_sane(bars(883.28), 999999, anchor_price=614.0)
    assert not ok and "悠悠锚" in msg, (ok, msg)
    # 正常：chart 614 vs 锚 614 → 通过
    ok, _ = kline_price_sane(bars(614.0), 999999, anchor_price=614.0)
    assert ok
    # 正常小偏差：chart 618 vs 锚 614（0.7%）→ 通过
    ok, _ = kline_price_sane(bars(618.0), 999999, anchor_price=614.0)
    assert ok
    # 新品无历史（item_id 不存在）+ 无锚 → 原逻辑不误伤
    ok, _ = kline_price_sane(bars(640.0), 999999)
    assert ok
check('kline dirty-price anchor rule blocks offset series', t_kline_price_sane)


def t_item_result_buy_distance():
    from types import SimpleNamespace
    import pipeline.item_analysis as ia
    pos = SimpleNamespace(percentile_90d=5.0, zscore_90d=-2.8, high_90d=100.0,
                          low_90d=50.0, mean_90d=80.0, median_90d=82.0,
                          current_price=55.0, data_points=90, valuation_tier='undervalued')
    orig = (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
            ia.event_risk_coefficient, ia.compute_fusion_decision, ia.compute_micro_th)
    ia._analyze_position = lambda prices: pos
    ia.compute_sentiment_score = lambda: 60
    ia.compute_sentiment_factor = lambda: 0.0
    ia.event_risk_coefficient = lambda: 1.0
    ia.compute_micro_th = lambda prices: 70
    def fake_fd(*a, **k):
        return SimpleNamespace(action='buy', action_label='周期吸筹·分批建仓',
                               action_detail='', deduction_sources=[], zone='undervalued',
                               zone_label='低估', liquidity_filtered=False,
                               percentile_90d=5.0, raw_th_score=55, corrected_th_score=55,
                               position_limit=None)
    ia.compute_fusion_decision = fake_fd
    kw = dict(name='Test', market_pct_90d=5.0,
              market_cycle='consolidation', market_zscore=-2.8, market_th_score=55,
              market_30d_change=-5.0, market_drop21=-25.0, recent_buy_dates=[], signal_date='2026-07-03')
    try:
        prices = [60.0] * 86 + [58.0, 57.0, 55.0, 57.0]
        res = ia.run_item_analysis(prices=prices, **kw)
        assert res.buy_distance, res
        assert res.buy_distance['kind'] == 'item', res.buy_distance
        assert res.buy_distance['drop_price'] > 0, res.buy_distance
        assert res.buy_distance['current_price'] == res.price_rmb, res.buy_distance
    finally:
        (ia._analyze_position, ia.compute_sentiment_score, ia.compute_sentiment_factor,
         ia.event_risk_coefficient, ia.compute_fusion_decision, ia.compute_micro_th) = orig
check('item analysis result carries buy_distance', t_item_result_buy_distance)

print('[Market Cycle Sync]')
def t_market_cycle_sync():
    from pipeline.backtest_common import build_market_context
    from pipeline.market_th import derive_market_cycle
    ctx = build_market_context("2025-11-02")
    if not ctx:
        return
    cycles = {v["cycle"] for v in ctx.values()}
    assert cycles and cycles != {"unknown"}, cycles
    valid = ("bull", "bear", "volatile", "sideways", "distribution", "accumulation")
    assert cycles <= set(valid), cycles
    # 手工牛市段：30日涨幅>5% 且 7日>1%
    vals = [100.0] * 30 + [100 + 0.5 * i for i in range(1, 31)]
    assert derive_market_cycle(vals, len(vals) - 1) in ("bull", "volatile"), derive_market_cycle(vals, len(vals) - 1)
check('backtest market cycle is live-consistent (not unknown)', t_market_cycle_sync)

def t_live_snapshot_sync():
    from pipeline.backtest_common import build_market_context
    from webapp.analysis_service import market_snapshot
    ctx = build_market_context("2025-11-02")
    if not ctx:
        return
    today = max(ctx)
    live = market_snapshot()
    assert live["cycle"] == ctx[today]["cycle"], (live["cycle"], ctx[today]["cycle"])
    assert live["th"] == ctx[today]["th"], (live["th"], ctx[today]["th"])
    assert abs(live["pct"] - ctx[today]["pct"]) < 1.0, (live["pct"], ctx[today]["pct"])
    assert abs(live["z"] - ctx[today]["z"]) < 0.05, (live["z"], ctx[today]["z"])
check('live _market_snapshot matches backtest context (pct/z/th/cycle)', t_live_snapshot_sync)

print('[Executions: P0-2 执行记录与自动复盘]')
def t_exec_crud():
    from pipeline import db
    conn = db.get_conn()
    eids = []
    try:
        eid = db.add_execution(conn, 0, '__smoke_test_item__', 'buy', '2026-07-01', 100.0, 2,
                               advice_signal='已到买点', advice_price=95.0)
        eids.append(eid)
        rows = [r for r in db.list_executions(conn) if r['id'] == eid]
        assert len(rows) == 1, rows
        r = rows[0]
        assert r['name'] == '__smoke_test_item__' and r['action'] == 'buy'
        assert r['advice_date'] == '2026-07-01' and abs(r['exec_price'] - 100.0) < 1e-6 and r['qty'] == 2
        assert r['settle_14'] is None and r['pnl_14'] is None
        db.settle_execution(conn, eid, settle_14=110.0, pnl_14=8.0)
        r2 = [r for r in db.list_executions(conn) if r['id'] == eid][0]
        assert abs(r2['settle_14'] - 110.0) < 1e-6 and abs(r2['pnl_14'] - 8.0) < 1e-6
    finally:
        for eid in eids:
            try:
                db.delete_execution(conn, eid)
            except Exception:
                pass
        conn.close()
check('executions CRUD (add/list/settle/delete)', t_exec_crud)

def t_closing_price():
    from pipeline import db
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT item_id, MAX(date) d, MIN(date) d0 FROM price_history GROUP BY item_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        if not row:
            return
        item_id, dmax, dmin = row['item_id'], row['d'], row['d0']
        assert dmin <= dmax
        mid = (dmin[:8] + dmax[:8]) if len(dmin) >= 8 else dmax
        px = db.closing_price_on(conn, item_id, dmax)
        assert px is not None and px > 0, px
        px_future = db.closing_price_on(conn, item_id, '2999-12-31')
        assert px_future == px, (px_future, px)
    finally:
        conn.close()
check('closing_price_on returns latest close for future date', t_closing_price)

def t_auto_settle():
    from datetime import date, timedelta
    from pipeline import db
    from webapp.main import _settle_expired_executions
    conn = db.get_conn()
    eids = []
    try:
        today = date(2026, 8, 4)
        due = (today - timedelta(days=40)).isoformat()   # 14d 与 30d 均已到期
        fresh = (today - timedelta(days=5)).isoformat()  # 未到期
        e1 = db.add_execution(conn, 0, '__smoke_settle_due__', 'buy', due, 100.0, 1)
        e2 = db.add_execution(conn, 0, '__smoke_settle_fresh__', 'buy', fresh, 100.0, 1)
        eids += [e1, e2]
        _settle_expired_executions(conn, today.isoformat())
        r1 = [r for r in db.list_executions(conn) if r['id'] == e1][0]
        r2 = [r for r in db.list_executions(conn) if r['id'] == e2][0]
        # 无价格历史的 item_id=0: 到期记录跳过(不报错), 未到期保持 None
        assert r1['settle_14'] is None and r1['settle_30'] is None
        assert r2['settle_14'] is None and r2['settle_30'] is None
        # 有价格历史时: 结算价<=到期日, pnl 口径=(px/exec-1)*100-2
        row = conn.execute("SELECT item_id, MAX(date) d FROM price_history GROUP BY item_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        if row:
            e3 = db.add_execution(conn, row['item_id'], '__smoke_settle_px__', 'buy', (today - timedelta(days=40)).isoformat(), 100.0, 1)
            eids.append(e3)
            _settle_expired_executions(conn, today.isoformat())
            r3 = [r for r in db.list_executions(conn) if r['id'] == e3][0]
            assert r3['settle_14'] is not None and r3['settle_30'] is not None, r3
            expected = round((r3['settle_14'] / 100.0 - 1) * 100 - 2.0, 2)
            assert abs(r3['pnl_14'] - expected) < 1e-6, (r3['pnl_14'], expected)
    finally:
        for eid in eids:
            try:
                db.delete_execution(conn, eid)
            except Exception:
                pass
        conn.close()
check('_settle_expired_executions settles due records only', t_auto_settle)

def t_exec_btn_display():
    from pipeline.batch_scan import _exec_btn
    assert '按建议执行' in _exec_btn('测试|AK', {'action': '可分批补仓'}, 55.5)
    assert 'data-action="add"' in _exec_btn('x', {'action': '可分批补仓'}, 1.0)
    assert 'data-action="buy"' in _exec_btn('x', {'action': '可分批建仓'}, 1.0)
    assert 'data-action="reduce"' in _exec_btn('x', {'action': '建议止盈减仓'}, 1.0)
    assert 'data-action="sell"' in _exec_btn('x', {'action': '趋势走弱，考虑止损'}, 1.0)
    assert _exec_btn('x', {'action': '持有观察'}, 1.0) == ''  # F-1.3: 观望类无按钮（没操作不记录）
check('batch scan exec button maps actionable advice only', t_exec_btn_display)


print('[Dashboards: P0-3 数据积累 / P0-4 组合仓位]')
def t_data_progress():
    from pipeline import db, dashboards
    conn = db.get_conn()
    try:
        d = dashboards.data_progress(conn)
        if d['index']['rows'] == 0:
            return
        assert d['index']['rows'] > 0, d['index']
        assert d['price']['items'] > 0 and d['price']['median_days'] >= 0
        assert 0.0 <= d['price']['pct_90d'] <= 100.0
        assert d['supply']['rows'] >= 0 and d['supply']['avg_days_per_item'] >= 0
        assert d['supply']['pct_items'] >= 0.0
        assert d['market_snapshot']['days'] >= 0 and d['market_snapshot']['latest'] is not None
        assert d['monitor_rank']['days'] >= 0 and d['monitor_rank']['n'] >= 0
        # J-3 信号族样本深度: signal_event_counts.json 必须存在且与回放展示键同源
        fam = d.get('families')
        assert fam and fam.get('display_keys'), 'families 缺失（signal_event_counts.json 未生成）'
        import json as _J
        from pathlib import Path as _P
        replay = _J.loads(_P(__file__).resolve().parent.parent.joinpath('data', 'item_backtest_full_2025.json').read_text(encoding='utf-8'))
        from collections import Counter as _C
        def _dk(lab):
            lab = lab or ''
            if '恐慌' in lab: return 'panic'
            if '深值' in lab: return 'deep_value'
            return 'accumulate'
        cnt = _C(_dk(s.get('action_label', '')) for s in replay['signals'])
        for k, n in cnt.items():
            assert fam['display_keys'][k]['n'] == n, f"进度卡 {k} n={fam['display_keys'][k]['n']} 与回放 {n} 不一致"
        assert fam['total_signals'] == len(replay['signals']), 'total_signals 与回放不一致'
    finally:
        conn.close()
check('data_progress reports index/price/supply coverage + J-3 families 同源', t_data_progress)

def t_portfolio_dash():
    from pipeline import db, dashboards
    conn = db.get_conn()
    try:
        d = dashboards.portfolio_dashboard(conn)
        assert d['total_assets'] >= 0 and d['holding_value'] >= 0
        assert isinstance(d['holdings'], list)
        assert 0.0 <= d['position_ratio'] <= 100.0
        assert d['max_single'] >= 0.0 and d['top3'] >= 0.0
        s = d['scan']
        assert s['cap'] > 0 and s['demand'] >= 0.0
        assert isinstance(s['over_cap'], bool)
        # holdings 按市值降序
        vals = [h['value'] for h in d['holdings']]
        assert vals == sorted(vals, reverse=True), vals
    finally:
        conn.close()
check('portfolio_dashboard reports holdings and concurrent cap', t_portfolio_dash)


print('[DB: 全市场快照 + 历史回填 (2026-08-04)]')
def t_market_snapshot():
    from pipeline import db
    conn = db.get_conn()
    try:
        db.save_market_snapshot(conn, "2099-01-01", [
            {"good_id": 900001, "name": "测试品A", "exterior_localized_name": "崭新出厂",
             "rarity_localized_name": "隐秘", "yyyp_sell_price": 12.34, "yyyp_sell_num": 56},
            {"good_id": 900002, "name": "测试品B", "yyyp_sell_price": 0},
        ])
        rows = conn.execute("SELECT * FROM market_snapshot WHERE date='2099-01-01' ORDER BY good_id").fetchall()
        assert len(rows) == 2, len(rows)
        assert rows[0]["yyyp_sell_price"] == 12.34 and rows[0]["yyyp_sell_num"] == 56
        assert rows[0]["exterior_localized_name"] == "崭新出厂"
        # 幂等覆盖
        db.save_market_snapshot(conn, "2099-01-01", [{"good_id": 900001, "name": "测试品A2", "yyyp_sell_price": 99.0}])
        rows2 = conn.execute("SELECT * FROM market_snapshot WHERE date='2099-01-01' AND good_id=900001").fetchall()
        assert len(rows2) == 1 and rows2[0]["name"] == "测试品A2"
    finally:
        conn.execute("DELETE FROM market_snapshot WHERE date='2099-01-01'")
        conn.commit()
        conn.close()
check('save_market_snapshot upsert rows', t_market_snapshot)

def t_backfill_missing():
    from pipeline import db
    conn = db.get_conn()
    item_id = None
    date = None
    orig = None
    try:
        # 找一个已有 volume_day 的真实品，验证回填不覆盖量
        item = conn.execute("SELECT item_id, date FROM price_history WHERE volume_day IS NOT NULL AND volume_day>0 ORDER BY date DESC LIMIT 1").fetchone()
        if not item:
            return
        item_id, date = item["item_id"], item["date"]
        orig = conn.execute("SELECT * FROM price_history WHERE item_id=? AND date=?", (item_id, date)).fetchone()
        # 清掉该行，模拟“缺失日期”，再回填价格
        conn.execute("DELETE FROM price_history WHERE item_id=? AND date=?", (item_id, date))
        conn.commit()
        db.backfill_price_missing(conn, item_id, [(date, 888.88)])
        row = conn.execute("SELECT price_rmb, volume_day FROM price_history WHERE item_id=? AND date=?", (item_id, date)).fetchone()
        assert row is not None and abs(row["price_rmb"] - 888.88) < 0.01
        assert row["volume_day"] is None  # 原 volume 已被删, 回填不伪造量
        start = db.item_history_start(conn, item_id)
        assert start and len(start) == 10
    finally:
        if item_id is not None and date is not None and orig is not None:
            # 完整恢复原始行，避免污染生产数据
            conn.execute("DELETE FROM price_history WHERE item_id=? AND date=?", (item_id, date))
            cols = [d[1] for d in conn.execute("PRAGMA table_info(price_history)").fetchall() if d[1] != "id"]
            conn.execute("INSERT INTO price_history ({}) VALUES ({})".format(",".join(cols), ",".join("?" * len(cols))), [orig[k] for k in cols])
            conn.commit()
        conn.close()
check('backfill_price_missing fills price only, keeps volume', t_backfill_missing)


def t_monitor_rank_snapshot():
    from pipeline import db
    conn = db.get_conn()
    try:
        db.save_monitor_rank_snapshot(conn, "2099-01-02", 9001, 12345, [
            {"steam_name": "\u5927\u6237A", "steam_id": "s1", "num": 100},
            {"steam_name": "\u5927\u6237B", "steam_id": "s2", "num": 50},
            {"steam_name": "\u5927\u6237C", "steam_id": "s3", "num": 0},
        ])
        rows = conn.execute("SELECT * FROM monitor_rank_snapshot WHERE date='2099-01-02' ORDER BY rank").fetchall()
        assert len(rows) == 2, len(rows)  # num=0 行不存
        assert rows[0]["rank"] == 1 and rows[0]["num"] == 100
        assert rows[1]["rank"] == 2 and rows[1]["steam_id"] == "s2"
        # 幂等覆盖
        db.save_monitor_rank_snapshot(conn, "2099-01-02", 9001, 12345, [{"steam_name": "X", "steam_id": "s9", "num": 7}])
        rows2 = conn.execute("SELECT COUNT(*) c FROM monitor_rank_snapshot WHERE date='2099-01-02'").fetchone()["c"]
        assert rows2 == 1, rows2
    finally:
        conn.execute("DELETE FROM monitor_rank_snapshot WHERE date='2099-01-02'")
        conn.commit()
        conn.close()
check('save_monitor_rank_snapshot upsert rows', t_monitor_rank_snapshot)

def t_exec_sync_position():
    # 执行记录同步持仓 (2026-08-05): buy/add 摊薄均价+累计买入; reduce/sell 减数量
    from pipeline import db
    conn = db.get_conn()
    TEST = "__TEST_EXEC_SYNC__"
    try:
        conn.execute("DELETE FROM items WHERE name=?", (TEST,))
        conn.commit()
        iid = db.upsert_item(conn, TEST, in_watchlist=1)
        conn.execute("UPDATE items SET holding=1, avg_cost=10.0, quantity=5, total_bought=50.0 WHERE id=?", (iid,))
        conn.commit()
        # buy: 数量+=, 均价=(10*5+15*5)/10=12.5, 累计=50+75=125
        r = db.apply_execution_to_position(conn, iid, "buy", 15.0, 5)
        row = conn.execute("SELECT holding, avg_cost, quantity, total_bought FROM items WHERE id=?", (iid,)).fetchone()
        assert row["quantity"] == 10 and row["avg_cost"] == 12.5 and row["total_bought"] == 125.0 and row["holding"] == 1, dict(row)
        assert r == {"holding": 1, "quantity": 10, "avg_cost": 12.5, "total_bought": 125.0}, r
        # add: 同 buy
        db.apply_execution_to_position(conn, iid, "add", 17.5, 2)
        row = conn.execute("SELECT avg_cost, quantity, total_bought FROM items WHERE id=?", (iid,)).fetchone()
        assert row["quantity"] == 12 and row["avg_cost"] == 13.33 and row["total_bought"] == 160.0, dict(row)
        # reduce: 数量减, 均价/累计不变
        db.apply_execution_to_position(conn, iid, "reduce", 20.0, 4)
        row = conn.execute("SELECT holding, avg_cost, quantity, total_bought FROM items WHERE id=?", (iid,)).fetchone()
        assert row["quantity"] == 8 and row["avg_cost"] == 13.33 and row["total_bought"] == 160.0 and row["holding"] == 1, dict(row)
        # sell 清仓: quantity=0, holding=0
        db.apply_execution_to_position(conn, iid, "sell", 20.0, 99)
        row = conn.execute("SELECT holding, avg_cost, quantity FROM items WHERE id=?", (iid,)).fetchone()
        assert row["quantity"] == 0 and row["holding"] == 0, dict(row)
        # 再买: 均价=成交价, 累计延续
        db.apply_execution_to_position(conn, iid, "buy", 20.0, 3)
        row = conn.execute("SELECT holding, avg_cost, quantity, total_bought FROM items WHERE id=?", (iid,)).fetchone()
        assert row["quantity"] == 3 and row["avg_cost"] == 20.0 and row["total_bought"] == 220.0 and row["holding"] == 1, dict(row)
        # item_id=0 / 不存在 -> None 不崩
        assert db.apply_execution_to_position(conn, 0, "buy", 10.0, 1) is None
        assert db.apply_execution_to_position(conn, 99999999, "buy", 10.0, 1) is None
    finally:
        conn.execute("DELETE FROM items WHERE name=?", (TEST,))
        conn.commit()
        conn.close()
check('execution syncs position (avg cost/qty/total bought)', t_exec_sync_position)


def t_upsert_space_dedup():
    # 回归防复发 (2026-08-06): USP 守护者空格变体重复条目两次被 health 检出（id=162 删、id=209 再犯）。
    # upsert_item 必须按「忽略半角/全角空格」归一匹配，命中复用原行并保留规范名。
    import sqlite3 as _sq
    from pipeline import db
    conn = _sq.connect(":memory:")
    conn.row_factory = _sq.Row
    db._init_schema(conn)
    try:
        canonical = "USP消音版 | 守护者 (崭新出厂)"
        id1 = db.upsert_item(conn, canonical, good_id=6554, in_watchlist=1)
        id2 = db.upsert_item(conn, "USP 消音版 | 守护者 (崭新出厂)", good_id=6554, in_watchlist=1)
        id3 = db.upsert_item(conn, "USP\u3000消音版 | 守护者 (崭新出厂)", good_id=6554, in_watchlist=1)
        assert id1 == id2 == id3, (id1, id2, id3)
        n = conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
        assert n == 1, f"空格变体应复用同一行, 实际 {n} 行"
        name = conn.execute("SELECT name FROM items WHERE id=?", (id1,)).fetchone()["name"]
        assert name == canonical, f"应保留规范名, 实际 {name}"
        # 真正不同的品不应误合并
        id4 = db.upsert_item(conn, "AK-47 | 精英之作 (战痕累累)", good_id=30)
        assert id4 != id1
    finally:
        conn.close()
check('upsert_item 空格变体去重 (半角/全角复用规范名)', t_upsert_space_dedup)




def t_kline_daily():
    # 回归防护 (2026-08-07 去量 P3): K 线全量刷新（含在售量）每日无条件执行，
    # 不再依赖 is_sunday 条件（旧守卫：is_sunday 先赋值再定义 _playwright_tasks）。
    src = open(os.path.join(TEST_DIR, "..", "run_daily_collect.py"), encoding="utf-8").read()
    assert "is_sunday" not in src, "去量后不应再依赖 is_sunday 条件刷新"
    i_pw = src.index("async def _playwright_tasks")
    i_kline = src.index("await collect_kline_all()")
    assert i_pw < i_kline, "collect_kline_all 必须在 _playwright_tasks 内调用"
    assert "P3 (2026-08-07" in src, "缺少 P3 日更注释"
check('run_daily_collect K线每日无条件刷新', t_kline_daily)


def t_keep_wear():
    from pipeline.collector_snapshot import _keep_wear
    # 枪皮仅尝新；手套仅略磨+久经；无磨损品保留
    assert _keep_wear("AWP | 火卫一 (崭新出厂)", "崭新出厂") is True
    assert _keep_wear("AWP | 火卫一 (略有磨损)", "略有磨损") is False
    assert _keep_wear("运动手套（★） | 迈阿密风云 (略有磨损)", "略有磨损") is True
    assert _keep_wear("运动手套（★） | 迈阿密风云 (崭新出厂)", "崭新出厂") is False
    assert _keep_wear("印花 | 麻将·百中", None) is True
check('collector_snapshot _keep_wear 磨损过滤', t_keep_wear)


def t_survive_filter():
    from pipeline.item_analysis import run_item_analysis
    prices = [100 - i for i in range(90)]
    prices = prices[::-1]  # 升序回升
    # 存世量过低（194<3000）不给 buy
    a = run_item_analysis(
        name="法玛斯 | 对比涂装 (崭新出厂)",
        prices=prices, supply_hist=[5]*90,
        index_change_7d=-1, market_history=[1000]*60, market_pct_90d=20,
        market_zscore=-1.0, market_cycle="bear", market_th_score=50,
        market_30d_change=-5, market_drop21=-20, survive_count=194,
    )
    fd = a.fusion_decision
    if fd.get("action") == "buy":
        assert "survive_too_low" in fd.get("deduction_sources", []), fd
    # 存世量足够（67256）不触发过滤
    b = run_item_analysis(
        name="FN57 | 神祗 (崭新出厂)",
        prices=prices, supply_hist=[500]*90,
        index_change_7d=-1, market_history=[1000]*60, market_pct_90d=20,
        market_zscore=-1.0, market_cycle="bear", market_th_score=50,
        market_30d_change=-5, market_drop21=-20, survive_count=67256,
    )
    assert "survive_too_low" not in (b.fusion_decision or {}).get("deduction_sources", [])
check('item_analysis 存世量<3000 不建仓过滤', t_survive_filter)




def t_encoding():
    # 文档编码健康检查（防乱码，2026-08-04）：仓库文本文件必须为 UTF-8 无 BOM、
    # 无 U+FFFD；'?' 长串仅警告（如 decision-log 中 AK-47 | ??? 1337 为刻意记录）。
    sys.path.insert(0, TEST_DIR)
    import check_encoding
    root = check_encoding.repo_root()
    hard, warn = check_encoding.scan(root)
    assert not hard, f"encoding hard issues: {hard}"
check('repo text files encoding health', t_encoding)



def t_buy_distance_plain():
    # ??? summary ???(2026-08-05): ?? pct30/z-1.5 ??, ???/????; stage ?????
    from pipeline.buy_distance import compute_buy_distance
    prices = [200 - i for i in range(90)]
    class _P:
        percentile_90d = 25
        zscore_90d = -1.0
    bd = compute_buy_distance(prices, _P(), th_score=26)
    assert bd and bd["scenario"] == "bottom", bd
    s = bd["summary"]
    assert "pct30" not in s and "z-1.5" not in s, s
    assert "\u4f4e\u4f30" in s, s  # ????
    assert bd["stage"] in (2, 3), bd
    assert bd["pct_ok"] is True and bd["th_ok"] is False, bd
check('buy_distance summary ???+stage', t_buy_distance_plain)


def t_action_level_sort():
    # 信号层级排序(2026-08-07): 可分批补仓 > 趋势走弱止损 > 持有观察 > 观望等待机会(最低)
    # 观望组内按下跌最严重: 持仓浮亏大在前 / 非持仓 percentile 低(深跌)在前
    from pipeline.batch_scan import sort_results
    def mk(name, action, holding=0, pnl=None, pct=50.0, gap=5.0):
        return dict(name=name, holding=holding, avg_cost=(100.0 if holding else 0),
                    price_rmb=((100.0 + pnl) if holding and pnl is not None else 100.0),
                    percentile_90d=pct, buy_distance={"gap_pct": gap},
                    portfolio_advice={"action": action, "suggest": "", "hold_guidance": ""})
    results = [
        mk("观望B", "观望等待机会", pct=30.0),
        mk("观望A", "观望等待机会", pct=60.0),
        mk("补仓", "可分批补仓", holding=1, pnl=-12.0),
        mk("持有", "持有观察", holding=1, pnl=-5.0),
        mk("止损", "趋势走弱，考虑止损", holding=1, pnl=-20.0),
        mk("观望持仓2", "观望等待机会", holding=1, pnl=-8.0),
        mk("观望持仓", "观望等待机会", holding=1, pnl=-25.0),
    ]
    names = [r["name"] for r in sort_results(results)]
    # 持仓区块: 补仓(0) > 止损(1) > 持有(5) > 观望持仓(7, 浮亏大在前)
    assert names[:5] == ["补仓", "止损", "持有", "观望持仓", "观望持仓2"], names
    # 非持仓区块: 观望组内深跌(pct 低)在前
    assert names[5:] == ["观望B", "观望A"], names


def t_proximity_sort():
    # ???????(2026-08-05): ????????, ????????
    from pipeline.batch_scan import _proximity_key
    def mk(gap, pct_gap=5.6, z_gap=1.12, th_gap=29.0, scenario="bottom"):
        return {"buy_distance": {"gap_pct": gap, "scenario": scenario,
                                 "pct_gap": pct_gap, "z_gap": z_gap, "th_gap": th_gap}}
    a = mk(1.0)                                  # ???????(?????)
    b = mk(1.7, pct_gap=0.0, z_gap=0.11)         # ????, ??? 0.11
    c = mk(5.7, pct_gap=0.0, z_gap=0.0)          # ????+??
    ka, kb, kc = _proximity_key(a), _proximity_key(b), _proximity_key(c)
    assert kc < kb < ka, (ka, kb, kc)
check('batch_scan 信号层级排序 (2026-08-07)', t_action_level_sort)
check('batch_scan ???????', t_proximity_sort)


def t_bd_cell_badges():
    # ??????????(2026-08-05): ???? ?, ????? ? X
    from pipeline.batch_scan import _bd_cell
    bd = {"scenario": "bottom", "gap_pct": 1.7, "bar_pct": 8,
          "scenario_label": "\u4e0b\u8dcc\u5bfb\u5e95", "target_price": 100.0,
          "pct_gap": 0.0, "z_gap": 0.11, "th_gap": 29.0}
    html = _bd_cell(bd)
    assert "\u2713" in html, html  # ???? ?
    assert "\u5dee" in html, html  # ??? ? X
check('batch_scan ??????????', t_bd_cell_badges)


def t_cluster_report():
    from pipeline.backtest_methodology import signal_cluster_report
    # adjacent dates (within +-3d) form one event cluster; duplicates count as signals
    dates = ["2026-05-22", "2026-05-23", "2026-05-24",
             "2026-06-15", "2026-06-16", "2026-07-01", "2026-07-02"]
    r = signal_cluster_report(dates, window=3)
    assert r["signal_count"] == 7
    assert r["cluster_count"] == 3 and r["event_count"] == 3
    assert r["unique_dates"] == 7
    # effective event days 3 < 5 -> warning
    assert r["flagged"] is True
    assert any("有效事件日" in w for w in r["warnings"]), r["warnings"]
    # same date repeated 4x: signal count 5, still 2 clusters
    r2 = signal_cluster_report(["2026-05-22"] * 4 + ["2026-06-15"], window=3)
    assert r2["signal_count"] == 5 and r2["cluster_count"] == 2
    # single cluster share > 50% -> warning
    r3 = signal_cluster_report(["2026-05-22"] * 4 + ["2026-06-15", "2026-06-16"], window=3)
    assert r3["max_cluster_share"] > 0.5
    assert any("50%" in w for w in r3["warnings"]), r3["warnings"]
check('backtest_methodology 信号时间聚类', t_cluster_report)


def t_walkforward():
    import random
    from datetime import date, timedelta
    from pipeline.backtest_methodology import walk_forward_split
    base = date(2026, 1, 1)
    recs = []
    for i in range(100):
        d = (base + timedelta(days=i)).isoformat()
        rng = random.Random(i)
        win = 0.9 if i < 70 else 0.5
        recs.append({"date": d, "fwd14": 5.0 if rng.random() < win else -3.0})
    r = walk_forward_split(recs, anchor_ratio=0.7)
    assert r["valid"] is True and r["strict_after"] is True
    assert r["train"]["n"] == 70 and r["test"]["n"] == 30
    # test segment strictly after train segment
    assert r["test"]["date_range"][0] > r["train"]["date_range"][1]
    assert r["train"]["win_rate"] > 0.8 and r["test"]["win_rate"] < 0.7
    # same-date boundary -> split moves forward to keep strict ordering
    recs2 = [{"date": "2026-01-01", "fwd14": 1.0}] * 8 + [{"date": "2026-01-02", "fwd14": -1.0}] * 2
    r2 = walk_forward_split(recs2, anchor_ratio=0.7, min_samples=2)
    assert r2["train"]["n"] == 8 and r2["test"]["n"] == 2
    assert r2["strict_after"] is True and r2["valid"] is True
check('backtest_methodology walk-forward 切分', t_walkforward)


def t_permutation():
    import random
    from pipeline.backtest_methodology import permutation_baseline
    # all positive returns -> observed win rate 100%, tiny p-value
    r = permutation_baseline([1.0] * 20, n_perm=200, seed=42)
    assert r["observed_win_rate"] == 1.0 and r["p_value"] < 0.01
    # random signs -> observed win rate near 50%, large p-value
    rng = random.Random(1)
    rets = [1.0 if rng.random() < 0.5 else -1.0 for _ in range(100)]
    r2 = permutation_baseline(rets, n_perm=200, seed=42)
    assert 0.3 < r2["observed_win_rate"] < 0.7
    assert r2["p_value"] > 0.05
    # same seed is reproducible
    a = permutation_baseline([1.0, -2.0, 3.0] * 10, n_perm=100, seed=7)
    b = permutation_baseline([1.0, -2.0, 3.0] * 10, n_perm=100, seed=7)
    assert a["p_value"] == b["p_value"]
    # None values are dropped
    r3 = permutation_baseline([1.0, None, 2.0, -1.0], n_perm=50, seed=1)
    assert r3["n"] == 3
check('backtest_methodology 置换检验 p 值', t_permutation)


print('[Health Monitor: A1 自动校验告警 (2026-08-05)]')
def t_health_monitor():
    # run_health_monitor 复用 run_data_health 检查 → health_checks 表 upsert + status 判定。
    # 用临时 DB 构造 pass（基线齐全）与 fail（空表）两例，不触碰线上 data/market.db。
    from datetime import date, timedelta
    import tempfile, shutil, sqlite3
    from run_health_monitor import run_monitor
    from pipeline import db as _db

    def build(path, ok):
        """构造健康检查基线数据；ok=True 全通过，ok=False 空表触发 FAIL。"""
        conn = sqlite3.connect(path)
        try:
            _db._init_schema(conn)
            c = conn.cursor()
            if not ok:
                return  # 空表：除 items 元数据（无持仓品）外全部 FAIL
            today = date.today().isoformat()
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            # 1. 大盘指数（value>1000、mood 三态、近 4 日内）
            c.execute("INSERT INTO market_index (date, value, change_7d, mood) VALUES (?, 1551.82, -1.2, ?)",
                      (today, "恐惧"))
            # 2/3. 单品 K 线 + 在售量（10 品全量覆盖/有在售量）
            for i in range(1, 11):
                c.execute("INSERT INTO items (id, good_id, name, in_watchlist) VALUES (?, ?, ?, 1)",
                          (i, 900000 + i, "测试品%d" % i))
                c.execute("INSERT INTO price_history (item_id, date, price_rmb, in_sale_count) VALUES (?, ?, 100.0, 120)",
                          (i, today))
                c.execute("INSERT INTO price_history (item_id, date, price_rmb, in_sale_count) VALUES (?, ?, 99.0, 110)",
                          (i, yesterday))
            # 4. 贪婪/卡价（greedy>=55 点、card>=170 点）
            for k in range(200):
                dd = (date.today() - timedelta(days=400 - k)).isoformat()
                c.execute("INSERT INTO macro_history (date, greedy_index, card_price) VALUES (?, 60.0, 179.0)", (dd,))
            # 5. 全市场快照（1400~3500 行，无 StatTrak/纪念品）
            c.executemany("INSERT INTO market_snapshot (date, good_id, name) VALUES (?, ?, ?)",
                          [(today, 800000 + i, "快照品%d" % i) for i in range(1500)])
            # 6. 大户集中度（>=90 品、>=4000 行）
            rows = [(today, it, 900000 + it, r, "大户%d" % r, "", 100)
                    for it in range(1, 96) for r in range(1, 45)]
            c.executemany(
                "INSERT INTO monitor_rank_snapshot (date, item_id, good_id, rank, steam_name, steam_id, num) VALUES (?,?,?,?,?,?,?)",
                rows)
            conn.commit()
        finally:
            conn.close()

    tmp = tempfile.mkdtemp()
    try:
        pass_db = os.path.join(tmp, "pass.db")
        fail_db = os.path.join(tmp, "fail.db")
        build(pass_db, ok=True)
        build(fail_db, ok=False)
        # pass 例：status=pass、无 FAIL
        r1 = run_monitor(db_path=pass_db, check_date="2099-01-01")
        assert r1["status"] == "pass" and r1["fail_count"] == 0, r1
        # fail 例：status=fail、有 FAIL
        r2 = run_monitor(db_path=fail_db, check_date="2099-01-02")
        assert r2["status"] == "fail" and r2["fail_count"] > 0, r2
        # 表写入验证：pass 行内容正确；同日重复运行 upsert 不新增行
        conn = sqlite3.connect(pass_db)
        try:
            row = conn.execute("SELECT date, status, checks_json FROM health_checks WHERE date='2099-01-01'").fetchone()
            assert row and row[1] == "pass", row
            assert "大盘指数" in row[2] and "PASS" in row[2], row[2]
            n1 = conn.execute("SELECT COUNT(*) FROM health_checks").fetchone()[0]
            run_monitor(db_path=pass_db, check_date="2099-01-01")
            n2 = conn.execute("SELECT COUNT(*) FROM health_checks").fetchone()[0]
            assert n1 == n2, (n1, n2)
        finally:
            conn.close()
        # fail 行同时写入
        conn = sqlite3.connect(fail_db)
        try:
            row = conn.execute("SELECT status FROM health_checks WHERE date='2099-01-02'").fetchone()
            assert row and row[0] == "fail", row
        finally:
            conn.close()

        # 部分覆盖例（Phase 1b 回归防护）：基线=历史曾有在售量品(10)，今日仅 5 品有数据 → 必须 FAIL
        part_db = os.path.join(tmp, 'part.db')
        build(part_db, ok=True)
        conn = sqlite3.connect(part_db)
        try:
            conn.execute("DELETE FROM price_history WHERE item_id > 5 AND date = ?", (date.today().isoformat(),))
            conn.commit()
        finally:
            conn.close()
        r3 = run_monitor(db_path=part_db, check_date='2099-01-03')
        assert r3['status'] == 'fail', r3
        names = [c['name'] for c in r3['checks'] if c['level'] == 'FAIL']
        assert '单品K线' in names and '在售量' in names, f'部分覆盖未检出: {names}'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
check('health_monitor 检查→upsert→status 判定', t_health_monitor)

print('[I-1 市场状态标注]')
def t_regime():
    from pipeline.batch_scan import market_regime
    # 贪婪禁入
    l, c, _ = market_regime(25, -5, 50)
    assert l == '贪婪禁入' and c == 'regime-greedy', (l, c)
    # V型底区：恐慌 + 深跌
    l, c, _ = market_regime(85, -18, 35)
    assert l == 'V型底区' and c == 'regime-vbottom', (l, c)
    # 阴跌中继区：恐慌 + 中跌
    l, c, _ = market_regime(85, -7.6, 35)
    assert l == '阴跌中继区' and c == 'regime-risky', (l, c)
    # 恐慌浅跌
    l, c, _ = market_regime(85, -2, 35)
    assert l == '恐慌浅跌' and c == 'regime-panic', (l, c)
    # 中性企稳：非恐慌 + TH>=45
    l, c, _ = market_regime(60, -5, 50)
    assert l == '中性企稳' and c == 'regime-ok', (l, c)
    # 弱市观望：非恐慌 + TH<45
    l, c, _ = market_regime(60, -5, 40)
    assert l == '弱市观望' and c == 'regime-weak', (l, c)
    # 边界：chg30 恰好 -15 属 V型底；-5 属阴跌中继（> -15 且 <= -5）
    assert market_regime(85, -15, 35)[0] == 'V型底区'
    assert market_regime(85, -5, 35)[0] == '阴跌中继区'
    # None 兜底
    assert market_regime(None, None, None)[0] == '中性企稳'
check('market_regime 六态判定', t_regime)

print('[B1 风险预算层]')
def t_b1_risk():
    from pipeline.portfolio_risk import drawdown_from_curve, single_position_exposure
    from pipeline.batch_scan import _portfolio_advice
    from types import SimpleNamespace
    # 回撤 5% -> 未触发；15% -> 触发；数据不足 -> None
    base = [('2026-01-01', 100.0)]
    assert drawdown_from_curve(base) is None
    d5 = drawdown_from_curve([('2026-01-01', 100.0), ('2026-01-02', 95.0)], threshold=0.10)
    assert d5['drawdown_pct'] == -5.0 and d5['breaker_active'] is False, d5
    d15 = drawdown_from_curve([('2026-01-01', 100.0), ('2026-01-02', 85.0)], threshold=0.10)
    assert d15['drawdown_pct'] == -15.0 and d15['breaker_active'] is True, d15
    assert d15['threshold_pct'] == 10.0 and d15['days'] == 2
    # 收复峰值 -> 解除
    drec = drawdown_from_curve([('2026-01-01', 100.0), ('2026-01-02', 85.0), ('2026-01-03', 100.0)], threshold=0.10)
    assert drec['breaker_active'] is False, drec
    # 单票敞口：超阈值提示、未超不提示、资产为 0 返回 None
    e1 = single_position_exposure(30000, 20000, 100000)
    assert e1['after_pct'] == 50.0 and e1['over'] is True and e1['over_pct'] == 20.0, e1
    e2 = single_position_exposure(20000, 5000, 100000)
    assert e2['after_pct'] == 25.0 and e2['over'] is False, e2
    assert single_position_exposure(10000, 0, 0) is None
    # _portfolio_advice 带 total_assets：补仓建议超单票敞口时给出警示（纯展示不改 action）
    pos = SimpleNamespace(percentile_90d=15.0, zscore_90d=-1.2)
    mk = SimpleNamespace(
        position=pos, trend_health={'score': 45},
        cycle=SimpleNamespace(phase='consolidation'),
        fusion_decision={'action': 'buy'},
        value=SimpleNamespace(score=5.0, grade='C'),
        risk_level='D',
        price_zones={'entry': {'low': 60.0, 'high': 75.0}, 'current': 80.0},
    )
    # 浮亏(avg=100, cur=80, qty=100): 市值8000(8%) + 补仓约6682 -> 敞口约14.7% 不超 30%
    a = _portfolio_advice(True, 100.0, 100, 80.0, mk, market_th=50, sentiment_score=60, total_assets=100000.0)
    assert a['action'] == '可分批补仓', a['action']
    assert 'exposure' not in a, a.get('exposure')
    # 浮亏但市值占资产 40%: 补仓后敞口超 30% -> 提示（纯展示不改 action）
    a2 = _portfolio_advice(True, 100.0, 500, 80.0, mk, market_th=50, sentiment_score=60, total_assets=100000.0)
    assert a2['action'] == '可分批补仓', a2['action']
    assert 'exposure' in a2 and a2['exposure']['over'] is True, a2.get('exposure')
    assert '单票敞口警示' in a2['suggest'], a2['suggest']
check('B1 熔断状态 + 单票敞口提示', t_b1_risk)

print('[数据对接: 信号复盘 + 期望统计 (2026-08-06, K-2 引擎)]')
def t_replay_source():
    import json as _J
    from pathlib import Path
    from collections import Counter
    base = Path(TEST_DIR).parent
    p = base / 'data' / 'item_backtest_full_2025.json'
    assert p.exists(), f'replay 数据源缺失: {p}'
    d = _J.loads(p.read_text(encoding='utf-8'))
    sigs = d.get('signals', [])
    assert 250 < len(sigs) < 600, f'回放信号数异常: {len(sigs)}'
    assert all(s.get('fwd_series') for s in sigs), 'fwd_series 缺失'
    assert all(s.get('net14') is not None for s in sigs), 'net14 缺失'
    from pipeline.config import ITEM_EXPECTANCY_STATS
    def _fam(lab):
        lab = lab or ''
        if '恐慌' in lab: return 'panic'
        if '深值' in lab: return 'deep_value'
        return 'accumulate'
    cnt = Counter(_fam(s.get('action_label', '')) for s in sigs)
    for k, n in cnt.items():
        assert ITEM_EXPECTANCY_STATS[k]['n'] == n, \
            f"{k} 期望n={ITEM_EXPECTANCY_STATS[k]['n']} 与回放信号 {n} 不一致"
check('replay 数据源 + 期望统计对接新版引擎', t_replay_source)

def t_event_calendar():
    from pipeline.market_macro import historical_event_impact
    assert '五合一崩盘' in historical_event_impact('2025-10-16', horizon_days=30), '10-16 未命中五合一崩盘'
    assert '黄盾' in historical_event_impact('2025-07-10', horizon_days=30), '07-10 未命中黄盾'
    assert '纪念品炼金' in historical_event_impact('2025-05-28', horizon_days=30), '05-28 未命中纪念品炼金'
    assert historical_event_impact('2026-01-01') == [], '无事件日期误命中'
    assert historical_event_impact('bad-date') == [], '非法日期应返回空'
check('事件日历: 黑天鹅 impact 窗口标注', t_event_calendar)

print('[期望统计单一事实源 + 基准对照 + 参数冻结 (2026-08-07)]')
def t_expectancy_sync():
    import importlib.util
    from pathlib import Path
    from pipeline.config import ITEM_EXPECTANCY_STATS
    base = Path(TEST_DIR).parent
    ref = base / 'references' / 'sync_expectancy_config.py'
    spec = importlib.util.spec_from_file_location('sync_expectancy_config', ref)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stats, _total, _comp = mod.compute_display_stats(str(base / 'data' / 'item_backtest_full_2025.json'))
    assert set(stats) == set(ITEM_EXPECTANCY_STATS), f'展示键不一致: {sorted(stats)} vs {sorted(ITEM_EXPECTANCY_STATS)}'
    for k, v in stats.items():
        c = ITEM_EXPECTANCY_STATS[k]
        for f in ('n', 'events', 'win14', 'avg14', 'ci14_lo', 'ci14_hi', 'win30', 'avg30'):
            assert c[f] == v[f], (
                f'{k}.{f} 漂移: config={c[f]} 回放计算={v[f]}；'
                f'改回放产物后必须重跑 references/sync_expectancy_config.py')
check('期望统计单一事实源: config == 回放计算值（全字段）', t_expectancy_sync)

def t_benchmark():
    import json as _J
    from pathlib import Path
    base = Path(TEST_DIR).parent
    p = base / 'data' / 'benchmark_compare.json'
    assert p.exists(), 'benchmark_compare.json 缺失（运行 references/benchmark_compare.py 生成）'
    d = _J.loads(p.read_text(encoding='utf-8'))
    for wname, w in d['windows'].items():
        assert w['range'][0] < w['range'][1], f'{wname} 窗口倒置'
        for leg in ('strategy', 'pool_buy_hold', 'market_index'):
            m = w[leg]
            assert isinstance(m['total_return_pct'], (int, float)), f'{wname}.{leg} total 缺失'
            assert m['max_drawdown_pct'] <= 0, f'{wname}.{leg} maxDD 应为非正'
            assert m['days'] > 0, f'{wname}.{leg} days 异常'
    full = d['windows']['full']
    assert full['strategy']['total_return_pct'] > full['market_index']['total_return_pct'], '策略应相对大盘超额'
    assert full['strategy']['max_drawdown_pct'] > full['pool_buy_hold']['max_drawdown_pct'], '策略回撤应小于池内等权持有'
check('基准对照 JSON 内部一致性', t_benchmark)

def t_param_freeze():
    from pipeline.config import PARAM_FREEZE
    assert PARAM_FREEZE['frozen_at'] == '2026-08-07', '冻结起点日期漂移'
    assert any('去量引擎' in s for s in PARAM_FREEZE['frozen_set']), '冻结集缺少去量引擎 v2'
    assert PARAM_FREEZE['oos_revalidate_after'] > '2027-01-01', 'OOS 复验窗口过近'
    assert len(PARAM_FREEZE['triggers']) >= 3, '复验触发条件缺失'
check('参数冻结条款 (OOS 纪律) 存在且完整', t_param_freeze)

def t_j2_channel_status():
    import json as _J
    from datetime import date
    from pathlib import Path
    base = Path(TEST_DIR).parent
    p = base / 'data' / 'j2_channel_status.json'
    assert p.exists(), 'j2_channel_status.json 缺失（运行 references/j2_channel_monitor.py 生成）'
    d = _J.loads(p.read_text(encoding='utf-8'))
    ch = d['channels']
    for k in ('A', 'B', 'C'):
        assert k in ch, f'J-2 通道 {k} 缺失'
    from pipeline.config import PARAM_FREEZE, J2_THRESHOLDS, ENGINE_VERSION
    assert ch['A']['threshold'] == J2_THRESHOLDS['a_events'], 'A 通道阈值与 config 不同源'
    assert ch['B']['threshold_days'] == J2_THRESHOLDS['b_days'], 'B 通道阈值与 config 不同源'
    assert ch['B']['target_date'] > '2027-01-01', 'B 通道复验点异常'
    assert ch['C']['thresholds']['14d_month'] == J2_THRESHOLDS['c14_month'], 'C 通道 14d 阈值与 config 不同源'
    assert ch['C']['thresholds']['30d_month'] == J2_THRESHOLDS['c30_month'], 'C 通道 30d 阈值与 config 不同源'
    assert ch['C']['thresholds']['14d_2m'] == J2_THRESHOLDS['c14_2m'], 'C 通道连续2月阈值与 config 不同源'
    assert d.get('engine_version') == ENGINE_VERSION, 'J-2 状态缺少引擎版本标识'
    assert set(ch['C']) >= {'replay_alert', 'production_gate', 'production_triggered', 'trigger_state'}, 'C 通道缺少 Phase 2b 字段'
    ra = ch['C']['replay_alert']
    assert 'triggered' in ra and 'since' in ra, 'replay_alert 结构缺失'
    assert ch['C']['production_gate']['min_filled14'] == 20, '实盘判定门槛漂移'
    assert d['overall'].get('trigger_action'), 'overall 缺少 trigger_action'
    assert isinstance(ch['C']['monthly'], list) and ch['C']['monthly'], 'C 通道月度数据缺失'
    ev = _J.loads((base / 'data' / 'signal_event_counts.json').read_text(encoding='utf-8'))
    assert ch['A']['value'] == ev['display_keys']['panic']['events'], 'A 通道事件数与事件计数不同源'
    from pipeline.config import PARAM_FREEZE
    frozen = date.fromisoformat(PARAM_FREEZE['frozen_at'])
    days = max(0, (date.today() - frozen).days)
    assert ch['B']['value_days'] == days, 'B 通道天数与冻结起点不一致'
    assert d['overall']['triggered'] in (True, False), '总体触发标记缺失'
check('J-2 三通道监测 JSON 完整且与冻结条款同源', t_j2_channel_status)

def t_signal_tracking():
    import sqlite3
    from pipeline import db as _db
    conn = _db.get_conn()
    try:
        r = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signal_tracking'").fetchone()
        assert r, 'signal_tracking 表缺失'
    finally:
        conn.close()
    from pipeline import signal_tracking as _st
    m = sqlite3.connect(':memory:')
    m.row_factory = sqlite3.Row
    _st.ensure_schema(m)
    m.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)')
    m.execute('CREATE TABLE price_history (item_id INTEGER, date TEXT, price_rmb REAL)')
    assert _st.record_buy_signal(m, item_id=1, item_name='AWP', signal_date='2026-07-01',
                                 action='buy', action_label='🟢 分批建仓', entry_price=100.0, source='analyze') is True
    assert _st.record_buy_signal(m, item_id=1, item_name='AWP', signal_date='2026-07-01',
                                 action='buy', action_label='🟢 分批建仓', entry_price=100.0) is False, '重复信号未去重'
    assert _st.record_buy_signal(m, item_id=1, item_name='AWP', signal_date='2026-07-01',
                                 action='watch', action_label='观望', entry_price=100.0) is False, '非 buy 信号不应记录'
    row_v = m.execute('SELECT engine_version FROM signal_tracking').fetchone()
    assert row_v['engine_version'] == _st.ENGINE_VERSION, 'engine_version 未按 config 记录'
    for i in range(1, 31):
        d = '2026-07-{:02d}'.format(i + 1) if i < 30 else '2026-08-01'
        m.execute('INSERT INTO price_history VALUES (1,?,?)', (d, 100 + i))
    m.commit()
    assert _st.backfill_signal_tracking(m) == 1, '回填应更新 1 条'
    row = m.execute('SELECT fwd14, net14, fwd30, net30 FROM signal_tracking').fetchone()
    assert abs(row['fwd14'] - 14.0) < 0.01 and abs(row['fwd30'] - 30.0) < 0.01, 'fwd 计算口径漂移'
    s = _st.tracking_summary(m)
    assert s['n_total'] == 1 and s['n_filled30'] == 1 and s['net30']['avg'] == 28.0, '统计口径漂移'
    m.close()
check('生产实盘信号跟踪: 表/记录去重/回填口径', t_signal_tracking)

def t_cost_sensitivity():
    import json as _J
    from pathlib import Path
    p = Path(TEST_DIR).parent / 'data' / 'cost_sensitivity.json'
    assert p.exists(), 'cost_sensitivity.json 缺失（运行 references/cost_sensitivity.py 生成）'
    d = _J.loads(p.read_text(encoding='utf-8'))
    be = d['breakeven_cost_pct']
    assert be['14d'] > 10 and be['30d'] > 15, f'盈亏平衡成本异常: {be}'
    r2 = next(r for r in d['rows'] if r['cost_pct'] == 2.0)
    assert r2['14d_all']['win_pct'] == 71.1, f'2% 14d 胜率漂移: {r2["14d_all"]["win_pct"]}'
    assert abs(r2['14d_all']['avg'] - 16.7) < 0.01, f'2% 14d 期望漂移: {r2["14d_all"]["avg"]}'
check('成本敏感性: 盈亏平衡>10% 且 2% 基准行与回放一致', t_cost_sensitivity)

def t_portfolio_backtest():
    import json as _J
    from pathlib import Path
    base = Path(TEST_DIR).parent
    p = base / 'data' / 'portfolio_backtest.json'
    b = base / 'data' / 'benchmark_compare.json'
    assert p.exists(), 'portfolio_backtest.json 缺失（运行 references/portfolio_backtest.py 生成）'
    d = _J.loads(p.read_text(encoding='utf-8'))
    v = d['variants']
    assert set(v) == {'cap0_8', 'cap0_8_cluster5', 'nocap_ref'}, f'组合变体缺失: {sorted(v)}'
    c08 = v['cap0_8']
    assert c08['n_trades'] > 0 and c08['portfolio_win_rate_pct'] is not None, 'cap0.8 无平仓记录'
    assert c08['max_drawdown_pct'] > v['nocap_ref']['max_drawdown_pct'], 'cap 应降低回撤'
    assert c08['sharpe'] is not None and c08['calmar'] is not None and c08['sortino'] is not None, '组合风险指标缺失'
    assert c08['monthly_returns'], '月度收益缺失'
    assert v['cap0_8_cluster5']['n_trades'] <= c08['n_trades'], '簇限次信号数应<=现行'
    assert d['consistency_with_benchmark'].get('consistent') is True, '与 benchmark_compare 不一致'
    bj = _J.loads(b.read_text(encoding='utf-8'))
    assert abs(c08['total_return_pct'] - bj['windows']['full']['strategy']['total_return_pct']) < 0.5, '组合总收益与基准漂移'
check('组合层回测: 变体/风险指标/胜率/一致性', t_portfolio_backtest)



def t_replay_snapshot():
    import json as _J, sys as _sys
    from pathlib import Path
    base = Path(TEST_DIR).parent
    p = base / 'data' / 'item_backtest_full_2025.json'
    snap = base / 'tests' / 'snapshots' / 'replay_v2.json'
    assert p.exists(), '回放产物缺失 item_backtest_full_2025.json'
    assert snap.exists(), '回放口径快照缺失 tests/snapshots/replay_v2.json（运行 references/sync_replay_snapshot.py 生成）'
    d = _J.loads(p.read_text(encoding='utf-8'))
    expected = _J.loads(snap.read_text(encoding='utf-8'))
    ag = d['aggregate']
    for k, v in expected['aggregate'].items():
        assert k in ag, f'aggregate.{k} 缺失'
        assert abs(ag[k] - v) < 1e-6, (
            f'aggregate.{k} 漂移: 当前={ag[k]} 快照={v}；改动回放产物/成本口径后须重跑 '
            f'references/sync_replay_snapshot.py 并人工确认')
    _sys.path.insert(0, str(base / 'references'))
    import j2_channel_monitor as _j2
    monthly = _j2._monthly(d['signals'])
    assert set(monthly) == set(expected['monthly']), f'月度集合漂移: {sorted(monthly)} vs {sorted(expected["monthly"])}'
    for m, exp in expected['monthly'].items():
        cur = monthly[m]
        for f in ('n', 'win14', 'win30', 'dedup_n', 'dedup_win14', 'dedup_win30'):
            assert cur.get(f) == exp[f], f'monthly.{m}.{f} 漂移: 当前={cur.get(f)} 快照={exp[f]}'
check('回放口径快照: aggregate+月度(含去簇) 无漂移', t_replay_snapshot)

def t_progress_schema():
    from pipeline import db as _db, dashboards as _dash
    conn = _db.get_conn()
    try:
        d = _dash.data_progress(conn)
    finally:
        conn.close()
    assert set(d) == {'index', 'price', 'supply', 'market_snapshot', 'monitor_rank', 'families', 'j2'}, (
        f'/api/data/progress 顶层字段漂移: {sorted(d)}')
    assert set(d['supply']) == {'rows', 'items_with_supply', 'pct_items', 'avg_days_per_item', 'latest'}
    assert set(d['index']) == {'rows', 'start', 'end'}
    assert set(d['price']) == {'rows', 'items', 'start', 'end', 'median_days', 'pct_90d', 'pct_180d'}
    assert set(d['market_snapshot']) == {'days', 'n', 'latest'}
    assert set(d['monitor_rank']) == {'days', 'n', 'latest'}
    assert set(d['families']) >= {'generated', 'window', 'total_signals', 'display_keys'}
    j2 = d['j2']
    assert j2 is not None, 'j2 状态缺失'
    assert set(j2) == {'generated', 'frozen_at', 'oos_revalidate_after', 'engine_version', 'channels', 'overall'}, (
        f'j2 字段漂移: {sorted(j2)}')
    assert set(j2['channels']) == {'A', 'B', 'C'}
    assert set(j2['channels']['A']) == {'label', 'value', 'threshold', 'progress_pct', 'status', 'note'}
    assert set(j2['channels']['B']) == {'label', 'value_days', 'threshold_days', 'progress_pct', 'target_date', 'status', 'note'}
    assert set(j2['channels']['C']) == {'label', 'monthly', 'two_month_flags', 'thresholds', 'production', 'production_gate', 'production_triggered', 'replay_alert', 'status', 'trigger_state', 'note'}
    assert set(j2['overall']) == {'triggered', 'triggered_channels', 'note', 'trigger_action'}
check('数据积累进度接口结构契约 (字段快照)', t_progress_schema)




print()
print('[Phase 3: 重拟合流水线]')
def t_refit_pipeline():
    import json as _J, sys as _sys
    _sys.path.insert(0, os.path.join(TEST_DIR, '..', 'references'))
    import refit_pipeline as _rp
    rep = _rp.compute(mode='simulate', frozen_at=_rp.PARAM_FREEZE['frozen_at'])
    assert set(rep) == {'generated', 'engine_version', 'mode', 'frozen_at', 'replay_generated',
                        'input', 'walk_forward', 'cluster', 'permutation', 'gate', 'action'}, sorted(rep)
    wf = rep['walk_forward']
    assert wf['train'] is not None and wf['test'] is not None, wf
    assert 'win_rate' in wf['test'] and wf['test']['n_with_return'] >= 10, wf['test']
    assert 'p_value' in rep['permutation'] and 'flagged' in rep['cluster']
    assert set(rep['gate']) >= {'valid', 'samples_ok', 'p_ok', 'cluster_ok', 'winrate_ok', 'passed', 'reasons'}
check('Phase 3 refit_pipeline 结构契约 (simulate)', t_refit_pipeline)


print()

print('[M1 监控模式]')
def t_monitor_events():
    """8 类事件生成逻辑（合成数据，纯函数级，不落库）。"""
    import sqlite3
    from pipeline import monitor as _mon

    class _FA:
        pass

    item = {"id": 1, "name": "测试品", "holding": 1, "avg_cost": 100.0}
    a = _FA()
    a.fusion_decision = {"action": "watch", "action_label": "观望·等待买点",
                         "proximity": {"score": 72, "nearest": "供给收缩吸筹"}}
    a.supply_analysis = {"supply_change_7d": -25.0}
    res = {"analysis": a, "prices": [100.0, 70.0], "latest": 70.0}
    evs = _mon._gen_item_events("2026-08-08", item, res, prev_action="")
    types = {e["event_type"] for e in evs}
    assert {"near_buy", "supply_shift", "price_spike", "stop_loss"} <= types, types
    assert len(evs) == 4, evs

    a2 = _FA()
    a2.fusion_decision = {"action": "buy", "action_label": "🟢 分批建仓", "proximity": {"score": 90, "nearest": "x"}}
    a2.supply_analysis = {}
    res2 = {"analysis": a2, "prices": [100.0, 101.0], "latest": 101.0}
    evs2 = _mon._gen_item_events("2026-08-08", item, res2, prev_action="avoid")
    assert any(e["event_type"] == "decision_flip" and e["level"] == "danger" for e in evs2), evs2

    m = sqlite3.connect(':memory:')
    m.row_factory = sqlite3.Row
    m.execute("""CREATE TABLE monitor_events (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT,
        item_id INTEGER, item_name TEXT, event_type TEXT, level TEXT, detail TEXT,
        dedup_key TEXT UNIQUE, created_at TEXT)""")
    evs3 = _mon._gen_market_events(m, "2026-08-08", "阴跌中继区")
    assert any(e["event_type"] == "market_state" and e["level"] == "info" for e in evs3)
    assert not any("切换" in e["detail"] for e in evs3), "无历史不应触发切换"
    m.execute("INSERT INTO monitor_events (date, item_id, item_name, event_type, level, detail, dedup_key) "
              "VALUES ('2026-08-07', NULL, NULL, 'market_state', 'info', '大盘状态：中性企稳', '2026-08-07||market_state')")
    evs4 = _mon._gen_market_events(m, "2026-08-08", "阴跌中继区")
    assert any("切换" in e["detail"] and e["level"] == "warn" for e in evs4), evs4

    m.execute("CREATE TABLE executions (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, name TEXT, "
              "action TEXT, advice_date TEXT, advice_signal TEXT, exec_price REAL, qty INTEGER, "
              "settle_14 REAL, settle_30 REAL, created_at TEXT, advice_price REAL)")
    m.execute("INSERT INTO executions (item_id, name, action, advice_date, exec_price, qty) "
              "VALUES (1, '测试品', 'buy', '2026-07-25', 100.0, 1)")
    evs5 = _mon._gen_exec_events(m, "2026-08-08")
    assert any(e["event_type"] == "exec_due" and e["level"] == "info" for e in evs5), evs5

    m.execute("CREATE TABLE signal_tracking (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, "
              "item_name TEXT, signal_date TEXT, action TEXT, action_label TEXT, entry_price REAL, "
              "position_limit REAL, source TEXT, fwd14 REAL, fwd30 REAL, net14 REAL, net30 REAL, "
              "checked14_at TEXT, checked30_at TEXT, created_at TEXT, engine_version TEXT)")
    m.execute("INSERT INTO signal_tracking (item_id, item_name, signal_date, action, action_label, entry_price) "
              "VALUES (1, '测试品', '2026-08-08', 'buy', '🟢 分批建仓', 99.0)")
    evs6 = _mon._gen_new_buy_events(m, "2026-08-08")
    assert any(e["event_type"] == "new_buy_signal" and e["level"] == "danger" for e in evs6), evs6
check('M1 监控事件 8 类生成逻辑', t_monitor_events)


def t_monitor_run_guard():
    """空库守卫：monitor_events 表存在 + 空市场数据返回默认大盘上下文（不抛异常）。"""
    import sqlite3
    from pipeline import monitor as _mon, db as _db
    conn = _db.get_conn()
    try:
        r = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='monitor_events'").fetchone()
        assert r, 'monitor_events 表缺失'
    finally:
        conn.close()
    m = sqlite3.connect(':memory:')
    m.row_factory = sqlite3.Row
    _db._init_schema(m)
    ctx = _mon._market_ctx_from_db(m)
    assert ctx["bucket"] in ("中性企稳", "弱市观望", "贪婪禁入", "恐慌浅跌", "阴跌中继区", "V型底区"), ctx
    assert ctx["th"] == 50.0 and ctx["chg30"] == 0.0
check('M1 监控空库守卫 + 默认大盘上下文', t_monitor_run_guard)



def t_monitor_push():
    """M2 推送：正文组装（danger 明细 + warn/info 计数）+ 无 webhook 跳过（不写幂等 key）。"""
    import os
    from pipeline import monitor as _mon
    summary = {"date": "2099-01-01", "bucket": "阴跌中继区", "analyzed": 25, "skipped": 0}
    events = [
        {"item_id": 1, "item_name": "AWP | 火卫一", "event_type": "stop_loss", "level": "danger",
         "detail": "现价 ¥70.28 ≤ 成本-25% ¥72.75，建议止损"},
        {"item_id": 2, "item_name": "AK-47 | 抽象派", "event_type": "near_buy", "level": "warn",
         "detail": "买点接近度 80%"},
        {"item_id": None, "item_name": None, "event_type": "market_state", "level": "info",
         "detail": "大盘状态：阴跌中继区"},
    ]
    title, text = _mon._build_push_text(summary, events, "night")
    assert "🚨1危险" in title and "破位止损" in text and "买点接近" in text, (title, text)
    assert "127.0.0.1" not in text and ":8000" not in text, "推送必须纯文字自包含，不得引用内网地址"
    os.environ["NOTIFY_WEBHOOK_URL"] = ""
    try:
        r = _mon.push_daily(summary, events, "night")
        assert r == {"pushed": False, "reason": "no_webhook"}, r
    finally:
        os.environ.pop("NOTIFY_WEBHOOK_URL", None)
    from pipeline import db as _db
    conn = _db.get_conn()
    try:
        k = conn.execute("SELECT value FROM settings WHERE key='monitor_push_2099-01-01_night'").fetchone()
        assert k is None, "无 webhook 不应写幂等 key"
    finally:
        conn.close()
check('M2 监控推送组装 + 无 webhook 跳过', t_monitor_push)

def t_monitor_slots():
    """M3 双时段：标题区分午间/晚间；推送幂等 key 按 slot 独立；事件 dedup 前缀区分并存。"""
    from pipeline import monitor as _mon
    summary = {"date": "2099-01-03", "bucket": "阴跌中继区", "analyzed": 25, "skipped": 0}
    events = [{"item_id": 1, "item_name": "AWP | 火卫一", "event_type": "stop_loss", "level": "danger",
               "detail": "现价 ≤ 成本-25%"}]
    t_n, _ = _mon._build_push_text(summary, events, "noon")
    t_d, _ = _mon._build_push_text(summary, events, "night")
    assert "午间" in t_n and "晚间" in t_d, (t_n, t_d)
    import os
    os.environ["NOTIFY_WEBHOOK_URL"] = ""
    try:
        r1 = _mon.push_daily(summary, events, "noon")
        r2 = _mon.push_daily(summary, events, "night")
        assert r1 == r2 == {"pushed": False, "reason": "no_webhook"}, (r1, r2)
    finally:
        os.environ.pop("NOTIFY_WEBHOOK_URL", None)
    from pipeline import db as _db
    conn = _db.get_conn()
    try:
        for k in ("monitor_push_2099-01-03_noon", "monitor_push_2099-01-03_night"):
            assert conn.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone() is None, k
        evs = [
            {"item_id": None, "item_name": None, "event_type": "market_state", "level": "info",
             "detail": "大盘状态：阴跌中继区", "dedup_key": f"noon::{summary['date']}||market_state"},
            {"item_id": None, "item_name": None, "event_type": "market_state", "level": "info",
             "detail": "大盘状态：阴跌中继区", "dedup_key": f"night::{summary['date']}||market_state"},
        ]
        _db.save_monitor_events(conn, summary["date"], evs)
        conn.commit()
        rows = _db.list_monitor_events(conn, days=400)
        got = {(r["date"], r["slot"]) for r in rows
               if r["date"] == summary["date"] and r["event_type"] == "market_state"}
        assert ("2099-01-03", "noon") in got and ("2099-01-03", "night") in got, got
        conn.execute("DELETE FROM monitor_events WHERE date=?", (summary["date"],))
        conn.commit()
    finally:
        conn.close()
check('M3 双时段 noon/night slot 区分', t_monitor_slots)

def t_monitor_push_idempotent():
    """M2 修复：推送成功后幂等 key 持久化(commit)，同日重跑返回 already_pushed 不重复推。"""
    from unittest import mock
    from pipeline import monitor as _mon, db as _db
    summary = {"date": "2099-01-04", "bucket": "阴跌中继区", "analyzed": 25, "skipped": 0}
    events = [{"item_id": 1, "item_name": "AWP | 火卫一", "event_type": "stop_loss", "level": "danger",
               "detail": "现价 ≤ 成本-25%"}]
    key = "monitor_push_2099-01-04_noon"
    conn = _db.get_conn()
    try:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))
        conn.commit()
    finally:
        conn.close()
    try:
        with mock.patch("notify_alert.send", return_value=200):
            r1 = _mon.push_daily(summary, events, "noon")
            assert r1 == {"pushed": True}, r1
        r2 = _mon.push_daily(summary, events, "noon")
        assert r2 == {"pushed": False, "reason": "already_pushed"}, r2
        conn = _db.get_conn()
        try:
            v = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            assert v and v["value"] == "1", v
        finally:
            conn.close()
    finally:
        conn = _db.get_conn()
        try:
            conn.execute("DELETE FROM settings WHERE key=?", (key,))
            conn.commit()
        finally:
            conn.close()
check('M2 推送幂等 key 持久化 + 重跑不重复', t_monitor_push_idempotent)

def t_notify_send_errcode():
    """M2 hardening: send() must check dingtalk errcode, 310000 raises not fake-success."""
    from unittest import mock
    from notify_alert import send

    class FakeResp:
        def __init__(self, body, status=200):
            self.status = status
            self._body = body.encode("utf-8")
        def read(self):
            return self._body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    with mock.patch("urllib.request.urlopen", return_value=FakeResp('{"errcode":310000,"errmsg":"keywords not match"}')):
        try:
            send("t", "x", "http://fake")
        except RuntimeError as exc:
            assert "310000" in str(exc), str(exc)
        else:
            raise AssertionError("errcode!=0 must raise, not fake-success")
    with mock.patch("urllib.request.urlopen", return_value=FakeResp('{"errcode":0,"errmsg":"ok"}')):
        assert send("t", "x", "http://fake") == 200
check('M2 send() dingtalk errcode guard', t_notify_send_errcode)

def t_snapshot_bid_cols():
    """快照持久化求购(bid/spread)字段：数据储备，供后续版本迭代验证求购因子（决策零改动）。"""
    from pipeline import db
    from webapp.analysis_service import save_item_snapshot

    class _V:
        score = 8.0; grade = "A"; scarcity = 10; volume = 0
        market_sentiment = 60; liquidity = 80
    class _P:
        valuation_tier = "低估"; percentile_90d = 25; zscore_90d = 0.0
        current_price = 100.0; data_points = 90
    class _C:
        phase = "accumulation"; phase_label = "吸筹期"; phase_confidence = 70
        phase_description = "低位"; phase_strategy = "分批建仓"
    class _A:
        name = "测试求购品"; price_rmb = 100.0
        value = _V(); position = _P(); cycle = _C()
        fusion_decision = {"action": "watch"}
        supply_analysis = {}; aux = None; liquidity = None; probability = None
        whale = None; data_quality = "good"; trend_health = {}
        price_zones = {}; buy_distance = {}

    conn = db.get_conn()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(snapshots)")]
        for c in ("bid_highest", "bid_7d_chg", "bid_30d_chg", "spread_pct", "spread_avg"):
            assert c in cols, c
        conn.execute("INSERT OR IGNORE INTO items (id, name) VALUES (999001, '测试求购品')")
        conn.commit()
        save_item_snapshot(conn, 999001, _A(), 100.0, today="2099-01-01",
                           order_book={"highest_buy": 98.0, "bid_7d_chg": 1.5, "bid_30d_chg": -30.0,
                                       "spread_pct": 2.0, "spread_avg": 2.5})
        row = conn.execute("SELECT bid_highest, bid_7d_chg, bid_30d_chg, spread_pct, spread_avg "
                           "FROM snapshots WHERE item_id=999001 AND date='2099-01-01'").fetchone()
        assert row and abs(row["bid_highest"] - 98.0) < 1e-9
        assert abs(row["bid_7d_chg"] - 1.5) < 1e-9 and abs(row["spread_pct"] - 2.0) < 1e-9
        # 幂等覆盖：无 order_book 时求购列置 NULL
        save_item_snapshot(conn, 999001, _A(), 101.0, today="2099-01-01", order_book=None)
        row2 = conn.execute("SELECT bid_highest, spread_pct FROM snapshots WHERE item_id=999001 AND date='2099-01-01'").fetchone()
        assert row2["bid_highest"] is None and row2["spread_pct"] is None, dict(row2)
    finally:
        conn.execute("DELETE FROM snapshots WHERE item_id=999001")
        conn.execute("DELETE FROM items WHERE id=999001")
        conn.commit(); conn.close()
check('snapshot 持久化求购 bid/spread 字段', t_snapshot_bid_cols)

def t_market_401_rebind_retry():
    """大盘 401（出口 IP 轮换）→ bind_local_ip 重新绑定 → 重试成功。"""
    from pipeline import collector
    calls = {"n": 0, "bind": 0}
    def fake_get(path):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"code": 401, "data": None, "msg": "IP mismatch"}
        return {"code": 200, "data": {"sub_index_data": [
            {"name_key": "init", "market_index": 1586.0, "chg_rate": 0.0}],
            "greedy_status": {"level": "medium"}}}
    def fake_bind():
        calls["bind"] += 1
        return "ok"
    orig_get, orig_bind = collector._api_get, collector.bind_local_ip
    collector._api_get, collector.bind_local_ip = fake_get, fake_bind
    try:
        idx = collector.fetch_market_index()
        assert idx is not None and abs(idx.value - 1586.0) < 1e-6, idx
        assert calls["n"] == 2 and calls["bind"] == 1, calls
        # kline 解析函数直接可用
        pts = collector._parse_kline_points([{"t": 1723104000000, "c": 1500.5}, {"bad": 1}])
        assert len(pts) == 1 and pts[0][0] == "2024-08-08", pts
    finally:
        collector._api_get, collector.bind_local_ip = orig_get, orig_bind
check('大盘 401 后 bind 重试成功', t_market_401_rebind_retry)





print('[F-1/F-2: 一键执行录入 + 执行复盘对照 (2026-08-08)]')
def t_report_exec_btn():
    """F-1: 单品报告渲染含「按建议记录执行」按钮（决策动作默认映射 buy/hold/reduce/sell，watch 类信号→观望）。"""
    from webapp.main import templates
    def _render(action, label="已到买点"):
        return templates.get_template("partials/analysis.html").render(
            name="测试|AK", price_rmb=55.5,
            fusion_decision={"action": action, "action_label": label})
    h = _render("buy")
    assert "按建议记录执行" in h, h[:500]
    assert 'data-action="buy"' in h and 'data-name="测试|AK"' in h, h[:500]
    assert 'data-price="55.50"' in h, h[:500]
    assert 'data-action="reduce"' in _render("reduce")
    assert 'data-action="sell"' in _render("sell")
    assert 'data-action="hold"' not in _render("watch")
    assert "按建议记录执行" not in _render("watch")  # F-1.3: 观望类无按钮
    assert "无需记录" in _render("watch")  # 提示观望无需记录
    assert 'data-action="sell"' in _render("avoid")
    h2 = templates.get_template("partials/analysis.html").render(name="X", price_rmb=1.0)
    assert "按建议记录执行" not in h2  # 无决策不显示
check("F-1 单品报告按建议执行按钮渲染", t_report_exec_btn)

def t_exec_review():
    """F-2: 执行复盘对照聚合（真实 vs 纸面）口径。"""
    from pipeline import db, dashboards
    conn = db.get_conn()
    eids = []
    try:
        r0 = dashboards.execution_review(conn)["real"]  # 基线（库内可能已有执行记录，用增量断言）
        e1 = db.add_execution(conn, 0, "__smoke_review_a__", "buy", "2026-07-01", 100.0, 1,
                              advice_signal="x", advice_price=95.0)
        e2 = db.add_execution(conn, 0, "__smoke_review_b__", "buy", "2026-07-01", 100.0, 1)
        eids += [e1, e2]
        db.settle_execution(conn, e1, settle_14=110.0, pnl_14=8.0, settle_30=105.0, pnl_30=3.0)
        db.settle_execution(conn, e2, settle_30=90.0, pnl_30=-10.0)
        d = dashboards.execution_review(conn)
        r = d["real"]
        assert r["n"] == r0["n"] + 2 and r["n_settled"] == r0["n_settled"] + 2, (r, r0)
        assert r["pnl14"]["n"] == r0["pnl14"]["n"] + 1, (r, r0)
        assert r["pnl30"]["n"] == r0["pnl30"]["n"] + 2, (r, r0)
        assert r["slippage"]["n"] == r0["slippage"]["n"] + 1, (r, r0)
        if r0["pnl14"]["n"] == 0:
            assert r["pnl14"]["win"] == 100.0 and r["pnl14"]["avg"] == 8.0, r["pnl14"]
        if r0["pnl30"]["n"] == 0:
            assert r["pnl30"]["win"] == 50.0 and r["pnl30"]["avg"] == -3.5, r["pnl30"]
        if r0["slippage"]["n"] == 0:
            assert abs(r["slippage"]["avg"] - round((100.0 / 95.0 - 1) * 100, 2)) < 1e-6, r["slippage"]
        assert "paper" in d and d["paper"]["n_total"] >= 0, d.keys()
    finally:
        for eid in eids:
            try:
                db.delete_execution(conn, eid)
            except Exception:
                pass
        conn.close()
check("F-2 执行复盘对照聚合口径", t_exec_review)



print('[F-3: 采集复用优先 (2026-08-08)]')
def t_kline_fresh():
    """F-3: db_kline_fresh 判定——新鲜（<=max_stale_days）复用，过期/不足 14 行返回 None。"""
    from datetime import date, timedelta
    from webapp.analysis_service import db_kline_fresh
    from pipeline import db
    conn = db.get_conn()
    TEST = "__SMOKE_FRESH__"
    try:
        conn.execute("DELETE FROM price_history WHERE item_id IN (SELECT id FROM items WHERE name=?)", (TEST,))
        conn.execute("DELETE FROM items WHERE name=?", (TEST,))
        conn.commit()
        iid = db.upsert_item(conn, TEST, good_id=999999001)
        conn.commit()
        today = date.today()
        base = today - timedelta(days=90)
        for d in range(91):  # 含今天：最新日期 = today，stale=0
            dt = (base + timedelta(days=d)).isoformat()
            conn.execute(
                "INSERT INTO price_history (item_id, date, price_rmb, volume_day, volume_total, in_sale_count) VALUES (?,?,?,?,?,?)",
                (iid, dt, 100.0 + d * 0.1, 0, 0, 500))
        conn.commit()
        # 新鲜（最新=今天，stale=0）：3 天与 0 天阈值均命中
        f3 = db_kline_fresh(999999001, TEST, max_stale_days=3)
        assert f3 and len(f3["bars"]) == 90 and f3["stale"] == 0, f3
        assert f3["db_name"] == TEST and f3["item_id"] == iid
        f0 = db_kline_fresh(999999001, TEST, max_stale_days=0)
        assert f0 is not None, "stale=0 应命中"
        # 过期：删除最近 10 天行 -> 最新=07-29, stale=10, 3 天阈值不命中
        conn.execute("DELETE FROM price_history WHERE item_id=? AND date > ?",
                     (iid, (today - timedelta(days=10)).isoformat()))
        conn.commit()
        assert db_kline_fresh(999999001, TEST, max_stale_days=3) is None
        assert db_kline_fresh(999999001, TEST, max_stale_days=14) is not None
    finally:
        try:
            conn.execute("DELETE FROM price_history WHERE item_id IN (SELECT id FROM items WHERE name=?)", (TEST,))
            conn.execute("DELETE FROM items WHERE name=?", (TEST,))
            conn.commit()
        except Exception:
            pass
        conn.close()
check("F-3 db_kline_fresh 新鲜度判定", t_kline_fresh)

def t_resolve_item_reuse():
    """F-3: DB 新鲜时 resolve_item 直接复用，不触发网络采集。"""
    import asyncio
    from datetime import date, timedelta
    from pipeline import db
    from webapp import analysis_service
    from webapp.analysis_service import db_kline_fresh, item_from_db
    conn = db.get_conn()
    TEST = "__SMOKE_REUSE__"
    try:
        conn.execute("DELETE FROM price_history WHERE item_id IN (SELECT id FROM items WHERE name=?)", (TEST,))
        conn.execute("DELETE FROM items WHERE name=?", (TEST,))
        conn.commit()
        iid = db.upsert_item(conn, TEST, good_id=999999002)
        conn.commit()
        base = date.today() - timedelta(days=60)
        for d in range(60):
            dt = (base + timedelta(days=d)).isoformat()
            conn.execute(
                "INSERT INTO price_history (item_id, date, price_rmb, volume_day, volume_total, in_sale_count) VALUES (?,?,?,?,?,?)",
                (iid, dt, 50.0 + d * 0.2, 0, 0, 300))
        conn.commit()

        async def _run():
            orig = analysis_service.collector_csqaq.fetch_item_detail
            called = {"n": 0}
            async def fake_fetch(good_id):
                called["n"] += 1
                raise AssertionError("DB 新鲜时不应触发网络采集")
            analysis_service.collector_csqaq.fetch_item_detail = fake_fetch
            try:
                item = await analysis_service.resolve_item(999999002, TEST, max_stale_days=3)
            finally:
                analysis_service.collector_csqaq.fetch_item_detail = orig
            return item, called["n"]

        item, fetch_n = asyncio.run(_run())
        assert fetch_n == 0, "网络采集被触发"
        assert item is not None and getattr(item, "from_db", False), "未标记 from_db"
        assert item.name == TEST and item.price_rmb > 0 and len(item.kline_90d) == 60, (item.name, item.price_rmb, len(item.kline_90d))
        assert item.sell_num_yyyp == 300 and item.in_sale_count == 300
    finally:
        try:
            conn.execute("DELETE FROM price_history WHERE item_id IN (SELECT id FROM items WHERE name=?)", (TEST,))
            conn.execute("DELETE FROM items WHERE name=?", (TEST,))
            conn.commit()
        except Exception:
            pass
        conn.close()
check("F-3 resolve_item DB 复用不触发采集", t_resolve_item_reuse)

# ---- F-3.5 流动性深度闸门 (2026-08-08) ----
print('[F-3.5: 流动性闸门 supply_depth]')

def t_liquidity_depth_gate():
    """F-3.5: 最新在售量 0<supply_depth<15 时 buy 降级 watch（结构性无流动性，如渐变斑纹在售 13）；
    在售量充足时不受影响。"""
    import types
    from pipeline.trend_health import compute_fusion_decision
    th = types.SimpleNamespace(raw_score=80, score=80, deduction_sources=[])
    # 低在售：buy -> watch + liquidity_depth_gate
    fd = compute_fusion_decision(10, th, liquidity_score=63, zscore_90d=-1.0,
                                 market_cycle="consolidation", sentiment_score=50.0,
                                 supply_depth=13)
    assert fd.action == "watch", fd.action
    assert fd.liquidity_filtered is True
    assert "liquidity_depth_gate" in fd.deduction_sources
    # 充足在售：buy 保持
    fd2 = compute_fusion_decision(10, th, liquidity_score=63, zscore_90d=-1.0,
                                  market_cycle="consolidation", sentiment_score=50.0,
                                  supply_depth=80)
    assert fd2.action == "buy", fd2.action
    assert fd2.liquidity_filtered is False
    # 无数据（supply_depth=0）：不误伤
    fd3 = compute_fusion_decision(10, th, liquidity_score=63, zscore_90d=-1.0,
                                  market_cycle="consolidation", sentiment_score=50.0,
                                  supply_depth=0)
    assert fd3.action == "buy", fd3.action

check("F-3.5 流动性深度闸门 buy 降级", t_liquidity_depth_gate)


def t_liquidity_gate_e2e():
    """F-3.5 端到端：渐变斑纹（在售 13，avg7≈12）整链分析最终不得为 buy——
    决策层闸门 + 升级族禁升级（supply_contraction 不再把 watch 升回 buy）。"""
    from webapp.analysis_service import db_kline_fresh, item_from_db
    from pipeline import item_analysis as ia
    fresh = db_kline_fresh(1323, "M4A4 | 渐变斑纹 (崭新出厂)", max_stale_days=14)
    assert fresh is not None, "渐变斑纹 K 线缺失"
    it = item_from_db(fresh, 1323)
    prices = [k.close for k in it.kline_90d if k.close and k.close > 0]
    supply = [k.in_sale_count for k in it.kline_90d]
    an = ia.run_item_analysis(name=it.name, prices=prices, supply_hist=supply or None,
                              order_book=None, index_change_7d=0, market_cycle="bear",
                              market_th_score=37, market_30d_change=-6.7, market_drop21=0,
                              survive_count=0)
    fd = an.fusion_decision
    assert fd.get("action") != "buy", fd.get("action")
    assert fd.get("liquidity_filtered") is True

check("F-3.5 渐变斑纹端到端禁 buy", t_liquidity_gate_e2e)



print('[F-3.7: 补仓倒金字塔 + 止损评估矩阵 (2026-08-09)]')
def t_f37_stop_loss():
    from pipeline.batch_scan import _split_topup_qty, _stop_loss_plan, _portfolio_advice
    from types import SimpleNamespace
    # 3:2:1 分配：总和=持仓量，递减，零量剔除
    assert _split_topup_qty(10) == [5, 3, 2], _split_topup_qty(10)
    assert sum(_split_topup_qty(7)) == 7
    assert _split_topup_qty(1) == [1], _split_topup_qty(1)
    assert _split_topup_qty(2) == [1, 1], _split_topup_qty(2)
    assert _split_topup_qty(3) == [2, 1], _split_topup_qty(3)
    def mk(pct=15.0, z=-1.0, th=45, s30=0.0, low90=60.0, fusion='hold', price_zones=None):
        pos = SimpleNamespace(percentile_90d=pct, zscore_90d=z, low_90d=low90)
        return SimpleNamespace(
            position=pos,
            trend_health={'score': th},
            cycle=SimpleNamespace(phase='consolidation'),
            fusion_decision={'action': fusion},
            value=SimpleNamespace(score=5.0, grade='C'),
            risk_level='D',
            price_zones=price_zones,
            supply_analysis={'supply_change_30d': s30},
        )
    # 未触发：浮亏<15% 无止损评估
    assert _stop_loss_plan(100.0, 10, 90.0, mk()) is None
    # 供给扩张 -> 全止损 sell
    sp = _stop_loss_plan(100.0, 10, 80.0, mk(s30=8.0), market_30d_change=0.0)
    assert sp['state'] == '供给扩张' and sp['action'] == '全止损' and sp['sell_action'] == 'sell'
    assert sp['sell_qty'] == 10 and sp['ratio_pct'] == 100
    # 恐慌深跌 -> 不止损（转补仓）
    sp = _stop_loss_plan(100.0, 10, 80.0, mk(), market_30d_change=-18.0)
    assert sp['state'] == '恐慌深跌' and sp['sell_action'] is None
    # 阴跌中继 -> 减半止损 reduce
    sp = _stop_loss_plan(100.0, 10, 80.0, mk(), market_30d_change=-8.0)
    assert sp['state'] == '阴跌中继' and sp['action'] == '减半止损' and sp['sell_action'] == 'reduce'
    assert sp['sell_qty'] == 5 and sp['ratio_pct'] == 50
    # 大盘上涨段 -> 不止损
    sp = _stop_loss_plan(100.0, 10, 80.0, mk(), market_30d_change=8.0)
    assert sp['state'] == '大盘上涨段' and sp['sell_action'] is None
    # 中性 -> 不止损
    sp = _stop_loss_plan(100.0, 10, 80.0, mk(), market_30d_change=0.0)
    assert sp['state'] == '中性' and sp['sell_action'] is None
    # 止损参考价 = min(90日支撑, 现价)
    sp = _stop_loss_plan(100.0, 10, 80.0, mk(s30=8.0, low90=70.0), market_30d_change=0.0)
    assert sp['stop_price'] == 70.0, sp['stop_price']
    # 持仓建议：浮亏-20% 挂 stop_plan；补仓批量为 3:2:1
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45, fusion='buy',
                          price_zones={'entry': {'low': 60.0, 'high': 75.0}, 'current': 80.0}),
                          market_th=50, sentiment_score=60, market_30d_change=0.0)
    assert a['action'] == '可分批补仓', a['action']
    assert a['stop_plan']['state'] == '中性'
    qs = [p['qty'] for p in a['add_positions']]
    assert qs == [5, 3, 2], qs
    assert '倒金字塔3:2:1' in a['suggest'], a['suggest']
    # 供给扩张 -> 禁止补仓（即使深度低估+融合buy）
    a = _portfolio_advice(True, 100.0, 10, 80.0, mk(pct=15, z=-1.2, th=45, fusion='buy', s30=8.0,
                          price_zones={'entry': {'low': 60.0, 'high': 75.0}, 'current': 80.0}),
                          market_th=50, sentiment_score=60, market_30d_change=0.0)
    assert a['action'] == '禁止补仓', a['action']
    assert a['stop_plan']['state'] == '供给扩张'
check('F-3.7 补仓倒金字塔 + 止损评估矩阵', t_f37_stop_loss)

print(f'=== Results: {passed} passed, {failed} failed, {skipped} skipped ===')
if failures:
    print()
    for name, msg, tb in failures:
        print(f'  FAIL: {name}')
        for l in tb.strip().split(chr(10))[-2:]:
            print(f'    {l}')
sys.exit(0 if failed == 0 else 1)
