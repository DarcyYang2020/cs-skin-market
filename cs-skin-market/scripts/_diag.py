import socket
import ssl
import urllib.request

print("=== Network Diagnostics ===")

# Test 1: DNS
try:
    ip = socket.gethostbyname("steamcommunity.com")
    print(f"DNS OK: steamcommunity.com -> {ip}")
except Exception as e:
    print(f"DNS FAIL: {e}")

# Test 2: TCP connect
try:
    sock = socket.create_connection(("steamcommunity.com", 443), timeout=10)
    sock.close()
    print("TCP OK: steamcommunity.com:443 reachable")
except Exception as e:
    print(f"TCP FAIL: {e}")

# Test 3: HTTPS with proper SSL
try:
    ctx = ssl.create_default_context()
    sock = socket.create_connection(("steamcommunity.com", 443), timeout=10)
    ssock = ctx.wrap_socket(sock, server_hostname="steamcommunity.com")
    print(f"SSL OK: {ssock.version()}")
    ssock.close()
except Exception as e:
    print(f"SSL FAIL: {e}")

# Test 4: Simple HTTPS request
try:
    req = urllib.request.Request(
        "https://steamcommunity.com/market/",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"HTTP OK: {resp.status}, {len(resp.read())} bytes")
except Exception as e:
    print(f"HTTP FAIL: {e}")

# Test 5: Alternate API approach
try:
    url = "https://steamcommunity.com/market/priceoverview/?appid=730&currency=1&market_hash_name=AK-47%20%7C%20Redline%20%28Field-Tested%29"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read().decode("utf-8")
        print(f"Price Overview OK: {data[:200]}")
except Exception as e:
    print(f"Price Overview FAIL: {e}")

print("\n=== Done ===")
