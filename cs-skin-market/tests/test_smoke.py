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
    assert 'buy_distance' in result, list(result.keys())
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
    assert '距55还差10分' in a['suggest'], a['suggest']
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
    kw = dict(name='Test', volumes=[0] * 90, market_pct_90d=15.0,
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
    # 排序：持仓浮亏大在前，非持仓 gap 小在前
    held = [dict(holding=1, avg_cost=100.0, price_rmb=130.0, name="赚"),
            dict(holding=1, avg_cost=100.0, price_rmb=70.0, name="亏")]
    unheld = [dict(holding=0, avg_cost=0, price_rmb=100.0, name="远", buy_distance={"gap_pct": 8.0}),
              dict(holding=0, avg_cost=0, price_rmb=100.0, name="近", buy_distance={"gap_pct": 2.0})]
    out = sort_results(held + unheld)
    assert [r["name"] for r in out] == ["亏", "赚", "近", "远"], [r["name"] for r in out]
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

print('[Data Sane: K线脏价校验]')
def t_kline_price_sane():
    from types import SimpleNamespace
    from webapp.main import _kline_price_sane
    def bars(last):
        # 平滑序列（无大跳变），只改最后一天 → 专测「整体口径偏移」漏检场景
        b = [SimpleNamespace(date="2026-08-%02d" % (d + 1), close=640.0) for d in range(4)]
        b[-1].close = last
        return b
    # 死寂空间场景：chart 883 vs 悠悠锚 614 → 应拦截（整体偏移、序列平滑）
    ok, msg = _kline_price_sane(bars(883.28), 999999, anchor_price=614.0)
    assert not ok and "悠悠锚" in msg, (ok, msg)
    # 正常：chart 614 vs 锚 614 → 通过
    ok, _ = _kline_price_sane(bars(614.0), 999999, anchor_price=614.0)
    assert ok
    # 正常小偏差：chart 618 vs 锚 614（0.7%）→ 通过
    ok, _ = _kline_price_sane(bars(618.0), 999999, anchor_price=614.0)
    assert ok
    # 新品无历史（item_id 不存在）+ 无锚 → 原逻辑不误伤
    ok, _ = _kline_price_sane(bars(640.0), 999999)
    assert ok
check('kline dirty-price anchor rule blocks offset series', t_kline_price_sane)

print('[Expectancy: 资金加权期望]')
def t_weighted_expectancy():
    from run_item_backtest import summarize, _weighted_stats
    # 三笔信号：仓位 0.1/0.2/0.3，收益 +10/-5/+5
    sigs = [
        {"position_limit": 0.1, "fwd14": 12.0, "net14": 10.0, "fwd30": 15.0, "net30": 12.0},
        {"position_limit": 0.2, "fwd14": -3.0, "net14": -5.0, "fwd30": -8.0, "net30": -10.0},
        {"position_limit": 0.3, "fwd14": 7.0, "net14": 5.0, "fwd30": 9.0, "net30": 8.0},
    ]
    wavg, wwin = _weighted_stats(sigs, "net14")
    # 等权 avg = (10-5+5)/3 = 3.33；加权 avg = (1 - 1 + 1.5)/0.6 = 2.50
    assert abs(wavg - 2.50) < 0.01, wavg
    assert wwin == 66.7, wwin  # 赢仓位 0.1+0.3 / 0.6
    rows, agg = summarize([{"name": "T", "days": 10, "signals": sigs}])
    assert agg["wavg14"] == 2.50 and abs(agg["avg14"] - 3.33) < 0.01, agg
    assert agg["wavg14"] != agg["avg14"], agg
    assert "wavg14" in rows[0] and "wavg30" in rows[0]
check('expectancy is position-weighted not signal-equal', t_weighted_expectancy)

def t_portfolio_wexpectancy():
    from run_portfolio_backtest import compute_metrics
    trades = [
        {"contrib_pct": 4.38, "limit": 0.2},  # 大赢，低仓
        {"contrib_pct": 0.49, "limit": 0.3},
        {"contrib_pct": -0.89, "limit": 0.3},
    ]
    m = compute_metrics(trades, ["2026-01-01", "2026-01-02"], [100000.0, 100000.0])
    # 等权 = (4.38+0.49-0.89)/3 = 1.327；加权 = (4.38+0.49-0.89)/(0.2+0.3+0.3) = 4.975
    assert abs(m["expectancy_pct"] - 1.327) < 0.01, m["expectancy_pct"]
    assert abs(m["wexpectancy_pct"] - 4.975) < 0.01, m["wexpectancy_pct"]
check('portfolio expectancy is position-weighted', t_portfolio_wexpectancy)

def t_market_buy_distance():
    from pipeline.buy_distance import compute_market_buy_distance
    prices = list(range(11, 101))
    mbd = compute_market_buy_distance(prices, pct=45.0, z=0.8, th_score=40.0, regime='bear', action='watch')
    assert mbd is not None
    assert mbd['line_price'] == 38.0, mbd          # min(pct30=38, z0=55.5)
    assert mbd['drop_to_line_pct'] == 62.0, mbd
    assert mbd['th_target'] == 55, mbd
    assert mbd['scenario'] == 'bottom' and mbd['target_price'] == 38.0, mbd
    assert mbd['gap_pct'] == 62.0 and mbd['gap_rmb'] == 62.0, mbd
    mbd2 = compute_market_buy_distance(prices, pct=20.0, z=-0.5, th_score=60.0, regime='bear', action='buy', action_label='低估区间·分批建仓')
    assert mbd2['bar_pct'] == 100 and '已到买点' in mbd2['summary'], mbd2
    mbd3 = compute_market_buy_distance(prices, pct=45.0, z=0.8, th_score=20.0, regime='bull', action='watch')
    assert mbd3['th_target'] == 30, mbd3
check('market buy_distance prices the reference line', t_market_buy_distance)

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
    kw = dict(name='Test', volumes=[0] * 90, market_pct_90d=5.0,
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
    from webapp.main import _market_snapshot
    ctx = build_market_context("2025-11-02")
    today = max(ctx)
    live = _market_snapshot()
    assert live["cycle"] == ctx[today]["cycle"], (live["cycle"], ctx[today]["cycle"])
    assert live["th"] == ctx[today]["th"], (live["th"], ctx[today]["th"])
    assert abs(live["pct"] - ctx[today]["pct"]) < 1.0, (live["pct"], ctx[today]["pct"])
    assert abs(live["z"] - ctx[today]["z"]) < 0.05, (live["z"], ctx[today]["z"])
check('live _market_snapshot matches backtest context (pct/z/th/cycle)', t_live_snapshot_sync)

print()
print(f'=== Results: {passed} passed, {failed} failed ===')
if failures:
    print()
    for name, msg, tb in failures:
        print(f'  FAIL: {name}')
        for l in tb.strip().split(chr(10))[-2:]:
            print(f'    {l}')
sys.exit(0 if failed == 0 else 1)
