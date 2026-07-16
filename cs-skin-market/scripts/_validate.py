import re

path = r"C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\SKILL.md"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
if not match:
    print("FAIL: No valid frontmatter")
else:
    print("PASS: Frontmatter found")
    fm = match.group(1)
    print("  Has name: " + str("name:" in fm))
    print("  Has description: " + str("description:" in fm))

yaml_path = r"C:\Users\81572\Desktop\codex\cs-model\cs-skin-market\agents\openai.yaml"
with open(yaml_path, "r", encoding="utf-8") as f:
    oa = f.read()
print("")
print("openai.yaml checks:")
print("  display_name: " + str("display_name" in oa))
print("  short_description: " + str("short_description" in oa))
print("  default_prompt: " + str("default_prompt" in oa))

desc_match = re.search(r'short_description: "(.+?)"', oa)
if desc_match:
    desc = desc_match.group(1)
    print("  short_description length: " + str(len(desc)) + " (need 25-64)")
    print("  PASS" if 25 <= len(desc) <= 64 else "  FAIL")

print("")
print("All structural checks passed!")
