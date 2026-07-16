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

print()
print(f'=== Results: {passed} passed, {failed} failed ===')
if failures:
    print()
    for name, msg, tb in failures:
        print(f'  FAIL: {name}')
        for l in tb.strip().split(chr(10))[-2:]:
            print(f'    {l}')
sys.exit(0 if failed == 0 else 1)
