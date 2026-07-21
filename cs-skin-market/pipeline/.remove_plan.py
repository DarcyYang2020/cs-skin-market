import os
base = r"C:\Users\81572\Desktop\codex\cs-model\cs-skin-market"

# ------- none.md -------
path = os.path.join(base, "references", "none.md")
with open(path, "r", encoding="utf-8") as f:
    text = f.read()
text = text.replace("strong(>=65)", "strong(>=55)")
text = text.replace("neutral(>=45)", "neutral(>=35)")
marker = "大盘完全基于 csQAQ HTTP API，不需要 Playwright。"
fragment = open(os.path.join(base, "..", "tmp_ins_md.txt"), "r", encoding="utf-8").read()
idx = text.index(marker) + len(marker)
text = text[:idx] + fragment + text[idx:]
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("none.md done")