import time
from .domain import BLOCKED, TERMINAL, MAX_ATTEMPTS, NotFound, ProviderResult
from .service import audit, update


class Engine:
    def __init__(self, db, gateway, clock=time.time, retry_base=2):
        self.db, self.gateway, self.clock, self.retry_base = db, gateway, clock, retry_base

    def tick(self, ident):
        with self.db.transaction() as s:
            order = s.order(ident)
            if not order:
                raise NotFound(ident)
            if order["status"] in TERMINAL | BLOCKED:
                return self.snapshot(order)
            now = self.clock()
            if order["next_attempt"] > now:
                return self.snapshot(order)
            phase = order["phase"]
            kind = {"PAYMENT": "payment", "INSURER": "insurer", "ROADTAX": "roadtax",
                    "REFUND": "refund", "NOTIFY_PHOTOS": "notification"}[phase]
            # Include only semantic input revisions, not attempts, in the operation key.
            revision = (order["photos_received"] if kind == "insurer" else
                        order["owner_corrected"] if kind == "roadtax" else 0)
            key = f"{ident}:{kind}:v{revision}"
            result = self.gateway.call(kind, order, key)
            if result.code == "SUCCESS" and not result.reference:
                result = ProviderResult("INVALID_RESPONSE", message="Successful response is missing its operation reference")
            update(s, order, attempt=order["attempt"] + 1)
            audit(s, order, "provider." + kind + ".response",
                  {"code": result.code, "reference": result.reference, "message": result.message,
                   "idempotency_key": key, "attempt": order["attempt"]}, now=now)
            if result.code == "TIMEOUT":
                if order["attempt"] >= MAX_ATTEMPTS:
                    update(s, order, status="MANUAL_REVIEW", reason="RETRIES_EXHAUSTED", next_attempt=0)
                    audit(s, order, "recovery.retries_exhausted", {"phase": phase}, now=now)
                else:
                    delay = self.retry_base * 2 ** (order["attempt"] - 1)
                    update(s, order, status="RETRYING", reason="TRANSIENT_FAILURE", next_attempt=now + delay)
                    audit(s, order, "recovery.retry_scheduled", {"delay_seconds": delay}, now=now)
            elif result.code == "SUCCESS":
                changes = dict(attempt=0, next_attempt=0, reason="", status="RUNNING")
                if phase == "PAYMENT":
                    changes.update(phase="INSURER")
                elif phase == "INSURER":
                    changes.update(phase="ROADTAX", policy_ref=result.reference)
                elif phase == "ROADTAX":
                    changes.update(status="COMPLETED", roadtax_ref=result.reference)
                elif phase == "REFUND":
                    changes.update(status="ROADTAX_REFUNDED", refund_ref=result.reference)
                elif phase == "NOTIFY_PHOTOS":
                    changes.update(status="WAITING_PHOTOS", reason="VEHICLE_PHOTOS_REQUIRED", phase="INSURER")
                update(s, order, **changes)
                audit(s, order, "workflow." + order["status"].lower(), {"phase": order["phase"]}, now=now)
            elif result.code == "VEHICLE_PHOTOS_REQUIRED" and phase == "INSURER":
                update(s, order, status="RUNNING", phase="NOTIFY_PHOTOS", attempt=0, next_attempt=0,
                       reason=result.code)
                audit(s, order, "recovery.request_photos", {"documents": ["front_vehicle_photo", "rear_vehicle_photo"]}, now=now)
            elif result.code == "OWNER_DATA_MISMATCH" and phase == "ROADTAX":
                update(s, order, status="WAITING_CORRECTION", reason=result.code, next_attempt=0)
                audit(s, order, "recovery.automatic_retry_disabled", {"reason": result.code}, now=now)
            elif result.code == "JPJ_BLACKLIST" and phase == "ROADTAX":
                update(s, order, status="REFUND_REQUIRED", reason=result.code, next_attempt=0)
                audit(s, order, "refund.approval_required", {"amount_cents": order["roadtax_cents"],
                      "currency": order["currency"], "scope": "roadtax_only", "insurance_remains_active": True}, now=now)
            else:
                update(s, order, status="MANUAL_REVIEW", reason=result.code, next_attempt=0)
                audit(s, order, "recovery.unknown_response", {"code": result.code}, now=now)
            return self.snapshot(order)

    @staticmethod
    def snapshot(order):
        return {k: order[k] for k in ("id", "status", "phase", "next_attempt", "version")}
