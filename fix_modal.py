# -*- coding: utf-8 -*-
"""Fix modal popup issues."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ============================================================
# Fix 1: watchlist.html - add onclick to report button
# ============================================================
fp = r"C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\webapp\templates\watchlist.html"
with open(fp, "r", encoding="utf-8") as f:
    w = f.read()

old = 'hx-get="/api/watchlist/{{ item.id }}/report" hx-target="#modal-body" hx-swap="innerHTML">📋 查看报告</button>'
new = 'hx-get="/api/watchlist/{{ item.id }}/report" hx-target="#modal-body" hx-swap="innerHTML" onclick="openModal(\'analysis-modal\')">📋 查看报告</button>'
if old in w:
    w = w.replace(old, new)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(w)
    print("Fixed: watchlist.html report button onclick")
else:
    print("WARNING: report button pattern not found in watchlist.html")

# ============================================================
# Fix 2: style.css - modal z-index above loading overlay
# ============================================================
fp2 = r"C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\webapp\static\css\style.css"
with open(fp2, "r", encoding="utf-8") as f:
    css = f.read()

# Modal overlay z-index: 200 -> 300 (above scan overlay at 250)
css = css.replace(
    "position: fixed; inset: 0; z-index: 200;",
    "position: fixed; inset: 0; z-index: 300;"
)
with open(fp2, "w", encoding="utf-8") as f:
    f.write(css)
print("Fixed: style.css modal z-index 200 -> 300")

# ============================================================
# Fix 3: app.js - auto-open modal when content loads into #modal-body
# ============================================================
fp3 = r"C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\webapp\static\js\app.js"
with open(fp3, "r", encoding="utf-8") as f:
    js = f.read()

# Add htmx:afterSettle handler to ensure modal is open after content swap
extra_handler = """
// ---- Auto-open modal when content loads into #modal-body ----
document.addEventListener('htmx:afterSettle', function(evt) {
  if (evt.detail.target && evt.detail.target.id === 'modal-body') {
    openModal('analysis-modal');
  }
});
"""
if 'modal-body' not in js.lower() or 'afterSettle' not in js:
    # Insert before the last event listener or at the end
    js = js.rstrip() + "\n" + extra_handler + "\n"
    with open(fp3, "w", encoding="utf-8") as f:
        f.write(js)
    print("Fixed: app.js added htmx:afterSettle auto-open")
else:
    print("app.js already has modal-body handler")

print("Done - all 3 fixes applied")
