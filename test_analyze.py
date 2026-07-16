import urllib.request, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Wait for server
time.sleep(2)

# Quick health check
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=5) as r:
        print(f"Server UP: {r.status}")
except Exception as e:
    print(f"Server DOWN: {e}")
    sys.exit(1)

# Trigger analysis
print("Triggering analysis for id=5 (FN57)...")
try:
    req = urllib.request.Request("http://127.0.0.1:8000/api/watchlist/5/analyze")
    with urllib.request.urlopen(req, timeout=90) as r:
        html = r.read().decode("utf-8")
    print(f"Analysis OK: {len(html)} bytes")
    # Check key content
    for key in ["analysis-result", "trend_health", "valuation_grid", "fusion_decision"]:
        print(f"  Has {key}: {key in html}")
    if "error" in html[:500]:
        idx = html.find("error")
        print(f"  ERROR section: {html[idx:idx+200]}")
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    body = e.read().decode("utf-8", errors="replace")
    print(f"Body: {body[:500]}")
except Exception as e:
    print(f"Error: {e}")
