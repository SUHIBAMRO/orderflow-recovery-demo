import json
import socket
import time
import urllib.error
import urllib.request
from .db import encoded
from .domain import Conflict, ProviderResult
from .service import uid


class MockGateway:
    """Durable provider-side deduplication, independent from the order transaction."""
    def __init__(self, db):
        self.db = db

    def call(self, kind, order, key):
        if kind not in {"payment", "insurer", "roadtax", "refund", "notification"}:
            raise ValueError("Unknown provider operation")
        body = encoded({k: order[k] for k in ("id", "scenario", "owner_last4", "roadtax_cents",
                                            "currency", "photos_received", "owner_corrected")})
        with self.db.transaction() as s:
            # Serialize equal provider keys on PostgreSQL even before an operation row exists.
            if s.postgres:
                s.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", (key,))
            saved = s.one("SELECT * FROM provider_operations WHERE request_key=?", (key,))
            if saved:
                if saved["request_body"] != body or saved["kind"] != kind:
                    raise Conflict("Provider idempotency payload mismatch")
                result = ProviderResult(**json.loads(saved["response"]))
            else:
                count = s.one("SELECT COUNT(*) AS n FROM provider_calls WHERE request_key=?", (key,))["n"]
                result = self._result(kind, order, count)
                if result.code == "SUCCESS":
                    s.execute("INSERT INTO provider_operations VALUES (?,?,?,?,?)",
                              (key, kind, order["id"], body, encoded(result.__dict__)))
                    if kind == "insurer" and order["scenario"] == "timeout_after_issue":
                        # Side effect committed but acknowledgement lost. Same key reconciles it.
                        result = ProviderResult("TIMEOUT", message="Acknowledgement lost after issuance")
            s.execute("INSERT INTO provider_calls VALUES (?,?,?,?,?,?)",
                      (uid(), key, kind, order["id"], result.code, time.time()))
            return result

    @staticmethod
    def _result(kind, order, count):
        scenario = order["scenario"]
        if kind == "insurer":
            if scenario == "persistent_outage" or (scenario == "insurer_timeout" and count < 2):
                return ProviderResult("TIMEOUT", message="Synthetic insurer timeout")
            if scenario == "missing_photos" and not order["photos_received"]:
                return ProviderResult("VEHICLE_PHOTOS_REQUIRED", message="Provide front and rear vehicle photos for underwriting review.")
        if kind == "roadtax":
            if scenario == "owner_mismatch" and not order["owner_corrected"]:
                return ProviderResult("OWNER_DATA_MISMATCH", message="Owner verification rejected by synthetic JPJ gateway")
            if scenario == "blacklist":
                return ProviderResult("JPJ_BLACKLIST", message="Synthetic blacklist rejection. Do not retry.")
        return ProviderResult("SUCCESS", reference="DEMO-" + kind.upper() + "-" + uid()[:10])


class HttpGateway:
    def __init__(self, base_url, token):
        self.base_url, self.token = base_url.rstrip("/"), token

    def call(self, kind, order, key):
        data = {k: order[k] for k in ("id", "scenario", "owner_last4", "roadtax_cents",
                                     "currency", "photos_received", "owner_corrected")}
        req = urllib.request.Request(self.base_url + "/mock/" + kind,
              data=encoded(data).encode(), method="POST",
              headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token,
                       "Idempotency-Key": key})
        try:
            with urllib.request.urlopen(req, timeout=4) as response:
                raw = json.loads(response.read(65536))
            return ProviderResult(**raw)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                return ProviderResult("TIMEOUT", message="Provider temporarily unavailable")
            return ProviderResult("PROVIDER_REJECTED", message="Provider HTTP " + str(exc.code))
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            return ProviderResult("TIMEOUT", message="Provider response not received")
        except (ValueError, TypeError):
            return ProviderResult("INVALID_RESPONSE", message="Provider returned an invalid response")
