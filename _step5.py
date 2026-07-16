path = r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\pipeline\item_analysis.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add supply import
old_import = 'from .valuation import compute_valuation_grid, valuation_grid_summary'
new_import = 'from .valuation import compute_valuation_grid, valuation_grid_summary\nfrom .supply import analyze_supply, supply_summary'
content = content.replace(old_import, new_import)

# 2. Add supply_analysis field to ItemAnalysisResult
old_field = '    valuation_grid: dict = None\n    market_context: dict = None'
new_field = '    valuation_grid: dict = None\n    supply_analysis: dict = None\n    corr_label: str = \"\"\n    market_context: dict = None'
content = content.replace(old_field, new_field)

# 3. Update probability function with trend decay
# Find analyze_probability and add decay parameter
old_prob = '''def analyze_probability(prices: list, z: float, vol_14d: float,
                       vol_regime: str) -> ProbPrediction:'''
new_prob = '''def analyze_probability(prices: list, z: float, vol_14d: float,
                       vol_regime: str, trend_score: int = 50) -> ProbPrediction:'''

if old_prob in content:
    content = content.replace(old_prob, new_prob)

# Now add decay logic at the end of analyze_probability
# Find the return statement
old_prob_return = '''    return ProbPrediction('''
if old_prob_return in content:
    # Find the actual return block
    idx = content.find(old_prob_return)
    # Find where ProbPrediction instantiation ends
    end_idx = content.find('    )', idx)
    if end_idx > idx:
        old_block = content[idx:end_idx+6]
        new_block = '''    # ---- Trend decay: if trend is very weak, reduce up-probability ----
    if trend_score < 30:
        up_discount = 0.5 + (trend_score / 30) * 0.25
        prob_up_3d  = max(5, round(prob_up_3d * up_discount, 1))
        prob_up_7d  = max(5, round(prob_up_7d * up_discount, 1))
        prob_up_30d = max(5, round(prob_up_30d * up_discount, 1))
    elif trend_score > 70:
        dn_discount = 0.5 + ((100 - trend_score) / 30) * 0.25
        prob_down_3d  = max(5, round(prob_down_3d * dn_discount, 1))
        prob_down_7d  = max(5, round(prob_down_7d * dn_discount, 1))
        prob_down_30d = max(5, round(prob_down_30d * dn_discount, 1))

    return ProbPrediction('''
        content = content.replace(old_block, new_block)
        print('Probability decay added')

print('item_analysis.py imports and fields updated')
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
