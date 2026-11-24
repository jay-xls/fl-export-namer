"""DAW Export Fixer - watches FL Studio renders and names them. See README.txt."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from namer_core import main  # noqa: E402

if __name__ == "__main__":
    main()
