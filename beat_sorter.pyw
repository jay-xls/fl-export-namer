"""Beat Sorter - drop old exports in, get BPM + key, rename and file them. See README.txt."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sorter_app import main  # noqa: E402

if __name__ == "__main__":
    main()
