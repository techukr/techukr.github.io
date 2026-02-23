#!/usr/bin/env python3
"""
fix_frontmatter.py — One-time (and safe-to-rerun) cleanup of Hugo content files.
Fixes:
  1. Markdown link syntax [url](url) → plain url in frontmatter
  2. Reserved Hugo 'url:' and 'link:' fields → 'external_url:'
"""

import re
from pathlib import Path

CONTENT_DIR = Path("content/news")

# Match [anything](url) and extract plain url
MD_LINK_RE = re.compile(r'^\[.*?\]\((https?://[^)]+)\)$')

def clean_url(value: str) -> str:
    value = value.strip().strip('"')
    match = MD_LINK_RE.match(value)
    return match.group(1) if match else value

def fix_file(fpath: Path) -> bool:
    text = fpath.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    new_lines = []
    changed = False

    for line in lines:
        # Fix: url: "..." or url: [...](...)  → external_url: "plain_url"
        m = re.match(r'^(url|link):\s*"?(\[.*?\]\(https?://[^)]+\)|https?://[^\s"]+)"?\s*$', line)
        if m:
            plain = clean_url(m.group(2))
            new_line = f'external_url: "{plain}"\n'
            new_lines.append(new_line)
            changed = True
            continue

        # Fix: external_url: "[url](url)" → external_url: "plain_url"
        m2 = re.match(r'^(external_url|source):\s*"(\[.*?\]\(https?://[^)]+\))"\s*$', line)
        if m2:
            plain = clean_url(m2.group(2))
            new_line = f'{m2.group(1)}: "{plain}"\n'
            new_lines.append(new_line)
            changed = True
            continue

        new_lines.append(line)

    if changed:
        fpath.write_text("".join(new_lines), encoding="utf-8")

    return changed

def main():
    if not CONTENT_DIR.exists():
        print("No content/news directory found.")
        return

    files = list(CONTENT_DIR.glob("*.md"))
    fixed = sum(1 for f in files if fix_file(f))
    print(f"✅ Scanned {len(files)} files, fixed {fixed}.")

if __name__ == "__main__":
    main()
