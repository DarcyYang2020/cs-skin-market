path = r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\pipeline\item_analysis.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find run_item_analysis function signature
for i, line in enumerate(lines):
    if 'def run_item_analysis(' in line:
        print(f'Signature at line {i+1}')
        # Print next 10 lines
        for j in range(i, min(i+15, len(lines))):
            print(f'{j+1}: {lines[j].rstrip()[:120]}')
        break
