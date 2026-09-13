import sys
from pathlib import Path

# Lets `pytest` work on a fresh clone before `uv sync` has run.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
