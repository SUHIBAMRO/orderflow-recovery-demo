"""Single-process public demo entrypoint: SQLite and synthetic HTTP APIs."""
import os
import secrets
from pathlib import Path
from .local import run


def main():
    os.environ["PUBLIC_DEMO"] = "1"
    os.environ.setdefault("PROVIDER_TOKEN", secrets.token_urlsafe(36))
    port = int(os.environ.get("PORT", "8080"))
    run(port=port, provider_port=int(os.environ.get("PROVIDER_PORT", str(port + 1))),
        data=os.environ.get("DATA_DIR", str(Path.cwd() / "data")))


if __name__ == "__main__":
    main()
