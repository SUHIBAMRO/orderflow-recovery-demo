from dataclasses import dataclass
from enum import StrEnum


class Scenario(StrEnum):
    SUCCESS = "success"
    PHOTOS = "missing_photos"
    MISMATCH = "owner_mismatch"
    BLACKLIST = "blacklist"
    TIMEOUT = "insurer_timeout"
    AMBIGUOUS = "timeout_after_issue"
    OUTAGE = "persistent_outage"


TERMINAL = {"COMPLETED", "ROADTAX_REFUNDED"}
BLOCKED = {"WAITING_PHOTOS", "WAITING_CORRECTION", "REFUND_REQUIRED", "MANUAL_REVIEW"}
MAX_ATTEMPTS = 3
POLICY_VERSION = "demo-1.0"


@dataclass(frozen=True)
class ProviderResult:
    code: str
    reference: str = ""
    message: str = ""


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


def classify_text(text: str) -> dict:
    """Conservative rule baseline, intentionally NOT presented as an LLM."""
    if len(text) > 4000:
        raise ValueError("Text exceeds 4000 characters")
    s = text.lower()
    if "photo" in s and any(w in s for w in ("required", "provide", "request")):
        reason = "VEHICLE_PHOTOS_REQUIRED"
    elif "owner" in s and "mismatch" in s:
        reason = "OWNER_DATA_MISMATCH"
    else:
        reason = "UNCLASSIFIED"
    return {"classifier": "deterministic-baseline", "suggested_reason": reason,
            "requires_human_confirmation": True, "executes_actions": False}
