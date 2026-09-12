import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from .config import identity, validate_tokens
from .db import Database
from .domain import Conflict, NotFound, classify_text
from .service import OrderService

db = Database(os.environ.get("DATABASE_URL", "sqlite:///data/orders.db"))
service = OrderService(db)
STATIC = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app):
    validate_tokens()
    db.initialize()
    yield


app = FastAPI(title="OrderFlow Recovery API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def protect(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        try:
            request.state.role, request.state.actor = identity(request.headers.get("authorization", ""))
        except PermissionError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=401)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 16384:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    return response


@app.exception_handler(Conflict)
async def conflict(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(NotFound)
async def notfound(request, exc):
    return JSONResponse({"detail": "Order not found"}, status_code=404)


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(PermissionError)
async def forbidden(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=403)


@app.get("/healthz")
def health():
    with db.transaction() as s:
        s.execute("SELECT 1")
    return {"status": "ok", "component": "api", "synthetic": True}


@app.get("/api/session")
def session(request: Request):
    return {"role": request.state.role, "actor": request.state.actor,
            "public_demo": os.environ.get("PUBLIC_DEMO") == "1", "mode": "PostgreSQL + Temporal",
            "providers": "synthetic", "classifier": "deterministic baseline"}


@app.get("/api/orders")
def orders():
    return service.list()


@app.post("/api/orders", status_code=201)
def create(request: Request, payload: dict, idempotency_key: Annotated[str, Header()]):
    if request.state.role == "viewer":
        raise PermissionError("Read-only role")
    return service.create(payload, idempotency_key, request.state.actor)


@app.get("/api/orders/{ident}")
def detail(ident: str):
    return service.detail(ident)


@app.post("/api/orders/{ident}/actions/{action}")
def action(request: Request, ident: str, action: str, payload: dict,
           idempotency_key: Annotated[str, Header()]):
    return service.action(ident, action, payload, idempotency_key, request.state.actor, request.state.role)


@app.post("/api/classify")
def classify(payload: dict):
    return classify_text(str(payload.get("text", "")))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
