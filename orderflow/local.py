"""Dependency-free verification server. NOT a substitute for the Temporal deployment."""
import argparse
import json
import logging
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .config import identity, validate_tokens
from .db import Database, encoded
from .domain import Conflict, NotFound, classify_text
from .engine import Engine
from .providers import HttpGateway, MockGateway
from .service import OrderService


def run(port=8080, provider_port=8081, data="data", host="127.0.0.1"):
    validate_tokens()
    provider_token = os.environ.setdefault("PROVIDER_TOKEN", secrets.token_urlsafe(32))
    db = Database("sqlite:///" + str(Path(data) / "orders.db"))
    provider_db = Database("sqlite:///" + str(Path(data) / "providers.db"))
    db.initialize()
    provider_db.initialize()
    service, gateway = OrderService(db), MockGateway(provider_db)
    engine = Engine(db, HttpGateway(f"http://127.0.0.1:{provider_port}", provider_token))
    web = Path(__file__).resolve().parent.parent / "web"
    stopped = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # Do not log authorization or customer payloads.

        def send(self, code, data, mime="application/json"):
            raw = data if isinstance(data, bytes) else encoded(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            try:
                path = urlsplit(self.path).path
                if self.command == "GET" and path == "/healthz":
                    return self.send(200, {"status": "ok", "mode": "portable-verification", "synthetic": True})
                length = int(self.headers.get("Content-Length", "0"))
                if length > 16384 or length < 0:
                    return self.send(413, {"detail": "Request too large"})
                payload = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(payload, dict):
                    raise ValueError("JSON object required")
                key = self.headers.get("Idempotency-Key", "")
                if self.server.server_port == provider_port:
                    if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + provider_token):
                        return self.send(401, {"detail": "Invalid provider token"})
                    if self.command != "POST" or not path.startswith("/mock/"):
                        raise NotFound(path)
                    return self.send(200, gateway.call(path.split("/")[-1], payload, key).__dict__)
                if path.startswith("/api/"):
                    try:
                        role, actor = identity(self.headers.get("Authorization", ""))
                    except PermissionError as exc:
                        return self.send(401, {"detail": str(exc)})
                    if path == "/api/session" and self.command == "GET":
                        return self.send(200, {"role": role, "actor": actor,
                                              "public_demo": os.environ.get("PUBLIC_DEMO") == "1", "mode": "SQLite verification runner",
                                              "providers": "synthetic HTTP APIs", "classifier": "deterministic baseline"})
                    if path == "/api/orders" and self.command == "GET":
                        return self.send(200, service.list())
                    if path == "/api/orders" and self.command == "POST":
                        if role == "viewer":
                            raise PermissionError("Read-only role")
                        return self.send(201, service.create(payload, key, actor))
                    parts = path.strip("/").split("/")
                    if len(parts) == 3 and parts[:2] == ["api", "orders"] and self.command == "GET":
                        return self.send(200, service.detail(parts[2]))
                    if len(parts) == 5 and parts[:2] == ["api", "orders"] and parts[3] == "actions" and self.command == "POST":
                        return self.send(200, service.action(parts[2], parts[4], payload, key, actor, role))
                    if path == "/api/classify" and self.command == "POST":
                        return self.send(200, classify_text(str(payload.get("text", ""))))
                    raise NotFound(path)
                static = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/assets/app.js": ("app.js", "text/javascript"),
                          "/assets/styles.css": ("styles.css", "text/css"),
                          "/assets/readability.css": ("readability.css", "text/css"),
                          "/assets/favicon.svg": ("favicon.svg", "image/svg+xml")}
                if self.command != "GET" or path not in static:
                    raise NotFound(path)
                file, mime = static[path]
                self.send(200, (web / file).read_bytes(), mime)
            except Conflict as exc:
                self.send(409, {"detail": str(exc)})
            except NotFound:
                self.send(404, {"detail": "Not found"})
            except PermissionError as exc:
                self.send(403, {"detail": str(exc)})
            except (ValueError, KeyError) as exc:
                self.send(422, {"detail": str(exc)})
            except Exception:
                logging.exception("Request failed")
                self.send(500, {"detail": "Internal error; no sensitive details exposed"})

    def pump():
        while not stopped.wait(0.25):
            try:
                for order in service.list():
                    if order["status"] in {"RUNNING", "RETRYING"}:
                        engine.tick(order["id"])
            except Exception:
                logging.exception("Tick failed; persisted state will be retried")

    providers = ThreadingHTTPServer(("127.0.0.1", provider_port), Handler)
    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=providers.serve_forever, daemon=True).start()
    threading.Thread(target=pump, daemon=True).start()
    print(f"OrderFlow verification server listening on {host}:{port} (synthetic only)", flush=True)
    try:
        server.serve_forever()
    finally:
        stopped.set()
        providers.shutdown()
        server.server_close()
        providers.server_close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--provider-port", type=int, default=8081)
    p.add_argument("--data", default="data")
    a = p.parse_args()
    run(a.port, a.provider_port, a.data)
