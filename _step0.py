path = r'C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\pipeline\collector_csqaq.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find ItemData class (starts around line 27)
start = None
end = None
for i, line in enumerate(lines):
    if 'class ItemData:' in line:
        start = i
    if start is not None and 'class OrderBook:' in line:
        end = i
        break

print(f'ItemData: lines {start+1}-{end}')

new_class = '''class ItemData:
    def __init__(self):
        self.name = self.steam_name = self.weapon = self.skin = self.wear = \"\"
        self.price_rmb = self.volume_day = self.volume_total = 0
        self.trend = \"\"
        self.order_book = None
        self.kline_90d = []
        self._daily_bars = []
        self._kline_raw = []
        self.good_id = 0
        self.sector = \"\"
        self.rarity_name = self.exterior_name = \"\"
        self.sell_price_rate_1 = self.sell_price_rate_7 = self.sell_price_rate_15 = 0.0
        self.sell_price_rate_30 = self.sell_price_rate_90 = self.sell_price_rate_180 = 0.0
        self.type_name = \"\"
        self.quality_name = \"\"
        self.group_hash_name = \"\"
        self.case_name = \"\"
        self.case_discontinued = False
        self.case_created = \"\"
        self.rank_num = 0
        self.rank_change = 0
        self.statistic_variants = []

'''

result = lines[:start] + [new_class] + lines[end:]
with open(path, 'w', encoding='utf-8') as f:
    f.writelines(result)
print('Done')
