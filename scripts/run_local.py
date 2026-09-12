"""Launch the SQLite verification runner using generated .env tokens."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
env = root / ".env"
if not env.exists():
    raise SystemExit("Run python scripts/setup_env.py first.")
for line in env.read_text().splitlines():
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)
from orderflow.local import run
run(data=str(root / "data"))
