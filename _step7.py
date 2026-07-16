path = r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\pipeline\item_analysis.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Update function signature to add item_meta
old_sig = '''    market_history: list = None,
    market_cycle: str = "unknown",
    market_zscore: float = 0.0,
) -> ItemAnalysisResult:'''
new_sig = '''    market_history: list = None,
    market_cycle: str = "unknown",
    market_zscore: float = 0.0,
    item_meta: dict = None,
) -> ItemAnalysisResult:'''
content = content.replace(old_sig, new_sig)

# Find the probability call and add trend_score
old_prob_call = '''    probability = analyze_probability(prices, position.zscore_90d, vol_14d, vol_regime)'''
new_prob_call = '''    probability = analyze_probability(prices, position.zscore_90d, vol_14d, vol_regime, 
                                      trend_score=th.score if 'th' in dir() else 50)'''
# But th is not yet defined here. Let me find where probability is called relative to th
# Let me just add trend_score after th is computed

# Instead, let me find the exact call and update it to pass a default
# The call happens before th is computed, so use a placeholder
# Actually, let me restructure: compute th first, then probability

# Find the order in run_item_analysis
idx_prob = content.find('probability = analyze_probability(prices, position.zscore_90d')
idx_th = content.find('# ---- Trend Health v3')
print(f'Probability call at {idx_prob}')
print(f'Trend Health at {idx_th}')

# If probability is called before trend health, move probability after trend health
if idx_prob < idx_th and idx_prob > 0:
    # Extract the probability call
    prob_start = content.rfind('\n    probability', 0, idx_prob + 5)
    prob_end = content.find('\n\n', idx_prob)
    if prob_end < 0:
        prob_end = content.find('\n    #', idx_prob + 10)
    prob_call = content[prob_start:prob_end]
    print(f'Prob call: [{prob_call[:200]}]')
    
    # Remove from current position
    content = content[:prob_start] + content[prob_end:]
    
    # Insert after trend health computation (before value_score)
    idx_val = content.find('    value = analyze_value_score')
    if idx_val > 0:
        insert_point = content.rfind('\n', 0, idx_val)
        # Update the call to pass trend_score
        new_prob = prob_call.replace('vol_regime)', 'vol_regime, trend_score=th.score)')
        content = content[:insert_point] + '\n' + new_prob + content[insert_point:]
        print('Moved probability after trend health')

print('Function signature updated')
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
