
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Read main file
with open('pipeline/index_analysis.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Read new function
with open('pipeline/_sector_rec.py', 'r', encoding='utf-8') as f:
    new_func = f.read()

# Splice: replace old function with new
start = content.find('def analyze_cycle_sector_recommendation')
end = content.find('def analyze_index_full(index_history', start)

if start < 0 or end < 0:
    print('ERROR: boundaries not found')
    sys.exit(1)

content = content[:start] + new_func + '\n' + content[end:]
with open('pipeline/index_analysis.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK - function replaced')
