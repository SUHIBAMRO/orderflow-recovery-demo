import os
import secrets
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI, Header, HTTPException
from .db import Database
from .domain import Conflict, Scenario
from .providers import MockGateway

db = Database(os.environ.get("MOCK_DATABASE_URL", "sqlite:///data/providers.db"))
gateway = MockGateway(db)


@asynccontextmanager
async def lifespan(app):
    if len(os.environ.get("PROVIDER_TOKEN", "")) < 24:
        raise RuntimeError("PROVIDER_TOKEN must contain at least 24 characters")
    db.initialize()
    yield


app = FastAPI(title="Synthetic insurer / JPJ / payment / notifications", lifespan=lifespan)


@app.get("/healthz")
def health():
    return {"status": "ok", "synthetic": True}


@app.post("/mock/{kind}")
def operation(kind: str, payload: dict, authorization: Annotated[str, Header()],
              idempotency_key: Annotated[str, Header()]):
    if not secrets.compare_digest(authorization, "Bearer " + os.environ["PROVIDER_TOKEN"]):
        raise HTTPException(401, "Invalid provider token")
    try:
        required = {"id", "scenario", "owner_last4", "roadtax_cents", "currency", "photos_received", "owner_corrected"}
        if set(payload) != required or len(idempotency_key) > 160:
            raise ValueError("Invalid provider payload")
        Scenario(payload["scenario"])
        if payload["currency"] != "MYR" or type(payload["roadtax_cents"]) is not int:
            raise ValueError("Invalid money fields")
        return gateway.call(kind, payload, idempotency_key).__dict__
    except Conflict as exc:
        raise HTTPException(409, str(exc))
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc))
