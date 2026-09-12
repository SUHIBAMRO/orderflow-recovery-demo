import json
import re
import time
import uuid
from .db import encoded
from .domain import BLOCKED, TERMINAL, POLICY_VERSION, Conflict, NotFound, Scenario


def uid():
    return uuid.uuid4().hex


def audit(s, order, kind, details, actor="workflow", now=None):
    s.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", (
        uid(), order["id"], time.time() if now is None else now, actor, kind,
        encoded(details), POLICY_VERSION, order["version"]))


def wake(s, order_id):
    s.execute("INSERT INTO wakeups VALUES (?,?,0,?)", (uid(), order_id, time.time()))


def update(s, order, **changes):
    changes.update(version=order["version"] + 1, updated_at=time.time())
    s.execute("UPDATE orders SET " + ",".join(k + "=?" for k in changes) + " WHERE id=?",
              (*changes.values(), order["id"]))
    order.update(changes)


def public(order):
    return {k: v for k, v in order.items() if k not in {"request_key", "request_body"}}


class OrderService:
    def __init__(self, db):
        self.db = db

    def create(self, payload, key, actor="operator"):
        if not key or len(key) > 128:
            raise ValueError("A unique Idempotency-Key of at most 128 characters is required")
        allowed = {"scenario", "customer", "vehicle", "owner_last4", "roadtax_cents"}
        if set(payload) - allowed:
            raise ValueError("Unexpected order fields")
        scenario = str(Scenario(payload.get("scenario", "success")))
        customer = str(payload.get("customer", "Synthetic customer"))
        vehicle = str(payload.get("vehicle", "DEMO • Toyota Corolla"))
        last4 = str(payload.get("owner_last4", "4321"))
        amount = payload.get("roadtax_cents", 9000)
        if not 1 <= len(customer) <= 80 or not 1 <= len(vehicle) <= 80:
            raise ValueError("Customer and vehicle must contain 1–80 characters")
        if not re.fullmatch(r"\d{4}", last4):
            raise ValueError("Use four synthetic identity digits only")
        if type(amount) is not int or not 100 <= amount <= 1000000:
            raise ValueError("Roadtax amount must be 100–1,000,000 integer cents")
        body = encoded(dict(scenario=scenario, customer=customer, vehicle=vehicle,
                            owner_last4=last4, roadtax_cents=amount))
        with self.db.transaction() as s:
            if s.one("SELECT COUNT(*) AS n FROM orders")["n"] >= 1000:
                raise Conflict("Demo order limit reached. Reset the sandbox before adding more.")
            # Unique constraint is the final defense against concurrent creates.
            ident = "OF-" + uid()[:12].upper()
            now = time.time()
            s.execute("""INSERT INTO orders
                (id,scenario,customer,vehicle,owner_last4,status,phase,roadtax_cents,currency,
                 created_at,updated_at,request_key,request_body)
                VALUES (?,?,?,?,?,'RUNNING','PAYMENT',?,'MYR',?,?,?,?)
                ON CONFLICT(request_key) DO NOTHING""",
                (ident, scenario, customer, vehicle, last4, amount, now, now, key, body))
            order = s.one("SELECT * FROM orders WHERE request_key=?", (key,))
            if order["request_body"] != body:
                raise Conflict("Idempotency key already used for different order data")
            if order["id"] == ident:
                audit(s, order, "order.created", {"scenario": scenario, "synthetic": True}, actor)
                wake(s, ident)
            return public(order)

    def list(self):
        with self.db.transaction() as s:
            return [public(o) for o in s.all("SELECT * FROM orders ORDER BY created_at DESC LIMIT 500")]

    def detail(self, ident):
        with self.db.transaction() as s:
            order = s.one("SELECT * FROM orders WHERE id=?", (ident,))
            if not order:
                raise NotFound(ident)
            events = s.all("SELECT * FROM events WHERE order_id=? ORDER BY order_version,occurred_at,id", (ident,))
            for event in events:
                event["details"] = json.loads(event["details"])
            return dict(order=public(order), events=events)

    def action(self, ident, action, payload, key, actor, role):
        if not key or len(key) > 128:
            raise ValueError("Idempotency-Key is required (max 128 characters)")
        if role not in {"operator", "supervisor", "demo"}:
            raise PermissionError("Read-only role")
        if action == "approve_refund" and role not in {"supervisor", "demo"}:
            raise PermissionError("Supervisor approval is required")
        if set(payload) - {"note", "owner_last4", "expected_version"}:
            raise ValueError("Unexpected action fields")
        note = str(payload.get("note", "")).strip()
        if not 8 <= len(note) <= 500:
            raise ValueError("An audit note of 8–500 characters is required")
        body = encoded(dict(action=action, payload=payload, actor=actor))
        with self.db.transaction() as s:
            order = s.order(ident)
            if not order:
                raise NotFound(ident)
            prev = s.one("SELECT * FROM actions WHERE request_key=?", (key,))
            if prev:
                if prev["order_id"] != ident or prev["request_body"] != body:
                    raise Conflict("Action idempotency key has different content")
                return json.loads(prev["result"])
            if payload.get("expected_version") != order["version"]:
                raise Conflict("This order changed. Refresh before acting.")
            status = order["status"]
            changes = dict(status="RUNNING", reason="", attempt=0, next_attempt=0)
            if action == "confirm_photos" and status == "WAITING_PHOTOS":
                changes.update(photos_received=1, phase="INSURER")
            elif action == "correct_owner" and status == "WAITING_CORRECTION":
                last4 = str(payload.get("owner_last4", ""))
                if not re.fullmatch(r"\d{4}", last4):
                    raise ValueError("Enter four corrected synthetic identity digits")
                changes.update(owner_corrected=1, owner_last4=last4, phase="ROADTAX")
            elif action == "approve_refund" and status == "REFUND_REQUIRED":
                changes.update(phase="REFUND")
            elif action == "retry" and status == "MANUAL_REVIEW" and order["reason"] == "RETRIES_EXHAUSTED":
                pass
            elif action == "escalate" and status in BLOCKED:
                changes.update(status="MANUAL_REVIEW", reason="ESCALATED")
            else:
                raise Conflict("Action is not permitted in the current state")
            update(s, order, **changes)
            audit(s, order, "operator." + action, {"note": note, "role": role}, actor)
            result = public(order)
            s.execute("INSERT INTO actions VALUES (?,?,?,?)", (key, ident, body, encoded(result)))
            wake(s, ident)
            return result
