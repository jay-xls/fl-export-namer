import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
# Keep tests away from the real %APPDATA%\DAW Export Fixer.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="fen-test-")
