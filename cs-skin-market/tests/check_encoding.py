# -*- coding: utf-8 -*-
"""Encoding health check for repo text files.

Checks every .md/.py/.html/.css/.js/.json/.txt under the repo for:
  1. valid UTF-8 (catches GBK-miswritten files)
  2. no UTF-8 BOM
  3. no U+FFFD replacement character
  4. suspicious long runs of '?' (PowerShell pipe damage: Chinese -> '?')
  5. C0 control characters (PowerShell here-string escapes: `b/`t/`a/`f/`v/`r -> control chars)

Usage:
    python tests/check_encoding.py            # scan + report
    python tests/check_encoding.py --fix-bom  # strip UTF-8 BOM from files
Exit code: 1 when hard issues found (invalid utf-8 / BOM / U+FFFD).
"""
import os
import re
import sys

HARD = ("invalid_utf8", "bom", "replacement_char")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             ".idea", ".vscode", "data", "backup"}
EXTENSIONS = {".md", ".py", ".html", ".css", ".js", ".json", ".txt"}
QUESTION_RUN = re.compile(r"\?{3,}")
# C0 control chars (excluding tab/LF/CR) = PowerShell here-string escape damage
CONTROL_CHAR = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def repo_root(start=None):
    p = os.path.abspath(start or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    while True:
        if os.path.isdir(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return p
        p = parent


def _iter_text_files(root):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for f in files:
            if os.path.splitext(f)[1].lower() in EXTENSIONS:
                yield os.path.join(dirpath, f)


def check_file(path):
    """Return (hard_issues: list[str], warnings: list[str])."""
    hard, warn = [], []
    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        hard.append("bom")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ["invalid_utf8"], []
    if "\ufffd" in text:
        hard.append("replacement_char")
    m = QUESTION_RUN.search(text)
    if m:
        warn.append("long '?' run (x%d) at col %d" % (len(m.group()), m.start() + 1))
    m = CONTROL_CHAR.search(text)
    if m:
        n = text.count(m.group())
        warn.append("control char %r (x%d) at col %d" % (m.group(), n, m.start() + 1))
    return hard, warn


def scan(root):
    hard_total, warn_total = [], []
    for p in _iter_text_files(root):
        hard, warn = check_file(p)
        rel = os.path.relpath(p, root)
        for h in hard:
            hard_total.append((rel, h))
        for w in warn:
            warn_total.append((rel, w))
    return hard_total, warn_total


def fix_bom(root):
    fixed = []
    for p in _iter_text_files(root):
        raw = open(p, "rb").read()
        if raw.startswith(b"\xef\xbb\xbf"):
            open(p, "wb").write(raw[3:])
            fixed.append(os.path.relpath(p, root))
    return fixed


def main():
    root = repo_root()
    if "--fix-bom" in sys.argv:
        fixed = fix_bom(root)
        print("BOM stripped from %d file(s):" % len(fixed))
        for f in fixed:
            print("  -", f)
        return 0 if not fixed else 0
    hard, warn = scan(root)
    print("=== Encoding check: %s ===" % root)
    print("hard issues: %d, warnings: %d" % (len(hard), len(warn)))
    for rel, h in hard:
        print("  [HARD] %s: %s" % (h, rel))
    for rel, w in warn:
        print("  [WARN] %s: %s" % (w, rel))
    if hard:
        print("RESULT: FAIL (fix files, then re-run)")
        return 1
    if warn:
        print("RESULT: PASS (with warnings; inspect '?' runs manually)")
        return 0
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
