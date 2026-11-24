import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Keep tests away from the real %APPDATA%\FL Export Namer.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="fen-test-")
