# === Step 0: Update collector_csqaq.py to extract new fields from good_detail ===
import re

path = r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\pipeline\collector_csqaq.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the line where good_detail response is parsed and add extraction code
# Look for the section that parses captured["detail"]
# Find: "# 2. Parse detail data" or similar
idx = content.find('# 2. Parse detail data')
if idx < 0:
    # Try to find where captured detail is used
    idx = content.find('if captured.get("detail")')
if idx < 0:
    idx = content.find('captured[\"detail\"]')

if idx > 0:
    # Find the end of this parsing block - next major comment or end of try block
    end_idx = content.find('return item', idx)
    if end_idx > idx:
        parse_block = content[idx:end_idx]
        print(f'Parse block at offset {idx}, length {len(parse_block)}')
        print(parse_block[:500])
    else:
        print(f'Found at {idx} but no return item after')
else:
    print('Could not find detail parsing block')
    # Let me find what's after the chart parsing
    idx_chart = content.find('kline_90d = item._daily_bars[:]')
    if idx_chart > 0:
        print(f'kline_90d assignment at offset {idx_chart}')
        print(content[idx_chart:idx_chart+500])
