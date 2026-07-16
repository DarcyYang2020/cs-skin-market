import urllib.request, urllib.parse, json, http.cookiejar

handler = urllib.request.ProxyHandler({"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"})
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(handler, urllib.request.HTTPCookieProcessor(cj))

name = "Five-SeveN | Monkey Business (Factory New)"
encoded = urllib.parse.quote(name)

# Visit listing first
listing_url = "https://steamcommunity.com/market/listings/730/" + encoded
print("Step 1: Listing page...")
req = urllib.request.Request(listing_url, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})
with opener.open(req, timeout=15) as resp:
    print("  " + str(resp.status) + ", " + str(len(resp.read())) + " bytes")

# priceoverview
ov_url = "https://steamcommunity.com/market/priceoverview/?appid=730&currency=23&market_hash_name=" + encoded
print("\nStep 2: priceoverview (currency=CNY)...")
req = urllib.request.Request(ov_url, headers={
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
})
try:
    with opener.open(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(json.dumps(data, indent=2, ensure_ascii=False))
except Exception as e:
    print("  Error: " + str(e))

# itemordershistogram
hist_url = "https://steamcommunity.com/market/itemordershistogram?country=CN&language=schinese&currency=23&item_nameid=0&two_factor=0&norender=1&appid=730&market_hash_name=" + encoded
print("\nStep 3: itemordershistogram...")
req = urllib.request.Request(hist_url, headers={
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
})
try:
    with opener.open(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
except Exception as e:
    print("  Error: " + str(e))
