"""Not My Debt application entrypoint. Created with assistance from OpenAI Codex."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from not_my_debt.ui import main

main()
