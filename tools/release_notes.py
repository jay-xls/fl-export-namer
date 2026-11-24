"""Print the CHANGELOG.md section for one version (used as GitHub release notes).

    python tools/release_notes.py 1.2.0
"""
import re
import sys
from pathlib import Path

version = sys.argv[1].lstrip("v")
text = Path(__file__).resolve().parent.parent.joinpath("CHANGELOG.md").read_text(encoding="utf-8")
m = re.search(rf"^## \[?{re.escape(version)}\]?.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
if not m or not m.group(1).strip():
    sys.exit(f"CHANGELOG.md has no section for {version} - add one before releasing.")
body = m.group(1).strip()
print(body)
print("\n---\n**Install:** download `DAW Export Fixer Setup " + version + ".exe` below and run it. "
      "Windows may say it's from an unknown publisher (the app isn't code-signed): *More info -> Run anyway*.\n"
      "Already installed? Running the new Setup updates it and keeps your settings.")
