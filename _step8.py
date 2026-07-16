path = r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\pipeline\item_analysis.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the run_item_analysis function body
idx_func = content.find('def run_item_analysis(')
idx_next_func = content.find('\ndef ', idx_func + 50)

func_body = content[idx_func:idx_next_func]

# Find probability call within function body
idx = func_body.find('probability = analyze_probability')
if idx > 0:
    end = func_body.find('\n', idx + 100)
    print(f'Probability call: {func_body[idx:end]}')
    
    # Find trend health compute call
    idx_th = func_body.find('th = compute_trend_health(')
    if idx_th > 0:
        end_th = func_body.find('\n', idx_th + 100)
        print(f'Trend health call: {func_body[idx_th:end_th]}')
        
    # Check order
    print(f'Probability at offset {idx}, TH at offset {idx_th}')
    print(f'Probability comes first: {idx < idx_th}')
else:
    print('Probability call not found in function body')
    # Search with different pattern
    for pat in ['analyze_probability', 'ProbPrediction']:
        i = func_body.find(pat)
        if i > 0:
            print(f'{pat} at offset {i}: {func_body[i:i+100]}')
