"""User-run setup: create fresh local-only secrets without printing them."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
target = root / ".env"
keys = ["POSTGRES_PASSWORD", "OPERATOR_TOKEN", "SUPERVISOR_TOKEN", "VIEWER_TOKEN", "PROVIDER_TOKEN"]
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; preserved without changes.")
with os.fdopen(fd, "w") as f:
    for key in keys:
        f.write(key + "=" + secrets.token_urlsafe(36) + "\n")
print("Created local .env. Use its operator/supervisor/viewer token to sign in. Do not share it.")
