path = r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\pipeline\collector_csqaq.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

idx = content.find('# 2. Parse detail data')
# Print 2000 chars from this point
print(content[idx:idx+2000])
