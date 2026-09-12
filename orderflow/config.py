import os
import secrets


def identity(header):
    if os.environ.get("PUBLIC_DEMO") == "1":
        return "demo", "public-demo"
    if not header.startswith("Bearer "):
        raise PermissionError("Sign in with a demo access token")
    supplied = header[7:]
    for role, env in (("supervisor", "SUPERVISOR_TOKEN"), ("operator", "OPERATOR_TOKEN"), ("viewer", "VIEWER_TOKEN")):
        expected = os.environ.get(env, "")
        if expected and secrets.compare_digest(supplied, expected):
            return role, "demo-" + role
    raise PermissionError("Invalid access token")


def validate_tokens():
    if os.environ.get("PUBLIC_DEMO") == "1":
        return
    values = [os.environ.get(k, "") for k in ("SUPERVISOR_TOKEN", "OPERATOR_TOKEN", "VIEWER_TOKEN")]
    if any(len(v) < 24 for v in values) or len(set(values)) != 3:
        raise RuntimeError("Configure three different access tokens of at least 24 characters")
