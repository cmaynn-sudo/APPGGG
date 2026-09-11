from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from http.cookies import SimpleCookie
from typing import Any


SESSION_COOKIE = "recepcion_session"
SESSION_MAX_AGE = 60 * 60 * 12


def _secret() -> bytes:
    value = os.environ.get("SESSION_SECRET") or os.environ.get("SECRET_KEY") or "recepcion-local-session-secret"
    return value.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign(value: str) -> str:
    return hmac.new(_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def configured_user() -> dict[str, str]:
    return {
        "username": os.environ.get("ADMIN_USERNAME", "admin"),
        "password": os.environ.get("ADMIN_PASSWORD", "admin"),
        "role": "superuser",
    }


def authenticate(username: str, password: str) -> dict[str, str] | None:
    configured = configured_user()
    if hmac.compare_digest(username, configured["username"]) and hmac.compare_digest(password, configured["password"]):
        return {"username": configured["username"], "role": configured["role"]}
    return None


def create_session(user: dict[str, str]) -> str:
    payload = {
        "username": user["username"],
        "role": user.get("role", "user"),
        "iat": int(time.time()),
        "exp": int(time.time()) + SESSION_MAX_AGE,
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{encoded}.{_sign(encoded)}"


def verify_session(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    encoded, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(encoded)):
        return None
    try:
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    if payload.get("role") != "superuser":
        return None
    return payload


def user_from_cookie(cookie_header: str | None) -> dict[str, Any] | None:
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return None
    morsel = cookie.get(SESSION_COOKIE)
    return verify_session(morsel.value if morsel else None)


def session_cookie_header(token: str, secure: bool = False) -> str:
    parts = [
        f"{SESSION_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={SESSION_MAX_AGE}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie_header() -> str:
    return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
