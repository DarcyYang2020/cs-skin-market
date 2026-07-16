path = r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\pipeline\collector_csqaq.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add new field extraction after rarity_name/exterior_name
old = '''                item.rarity_name = gi.get(\"rarity_localized_name\", \"\")
                item.exterior_name = gi.get(\"exterior_localized_name\", \"\")
                
                buff_sell'''

new = '''                item.rarity_name = gi.get(\"rarity_localized_name\", \"\")
                item.exterior_name = gi.get(\"exterior_localized_name\", \"\")
                item.type_name = gi.get(\"type_localized_name\", \"\")
                item.quality_name = gi.get(\"quality_localized_name\", \"\")
                item.group_hash_name = gi.get(\"group_hash_name\", \"\")
                item.rank_num = int(gi.get(\"rank_num\", 0))
                item.rank_change = int(gi.get(\"rank_num_change\", 0))
                
                # Container/case info
                container = data[\"data\"].get(\"container\", [])
                if container and isinstance(container, list) and len(container) > 0:
                    c = container[0]
                    item.case_name = c.get(\"name\", \"\")
                    item.case_discontinued = c.get(\"comment\", \"\") == \"\\u7edd\\u7248\"
                    item.case_created = c.get(\"created_at\", \"\")
                
                # Statistic variants (same skin, different wears)
                sl = data[\"data\"].get(\"statistic_list\", [])
                if isinstance(sl, list):
                    item.statistic_variants = sl
                
                buff_sell'''

content = content.replace(old, new)
print(f'Replaced: {old in content} -> {new in content}')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('collector_csqaq.py detail parsing updated')
