"""Signed session cookies (JWT, HS256).

The browser holds an opaque, tamper-evident token. Role and patient scope live INSIDE it, signed by
a secret only the server knows, so editing the cookie (or the UI dropdown) can't escalate privileges.
The cookie is HttpOnly (JavaScript can't read it, which limits XSS damage) and SameSite=Lax (the
browser won't attach it to cross-site POSTs, which blocks CSRF).
"""
import logging
import secrets
import time
import uuid

import jwt

from app.auth.access import ROLES, Access
from app.config import settings

COOKIE_NAME = "hc_session"
ALGORITHM = "HS256"

log = logging.getLogger("auth")

_secret = settings.session_secret
if not _secret:
    _secret = secrets.token_urlsafe(48)
    log.warning("SESSION_SECRET not set: using a random one; all sessions reset when the server restarts.")


def issue_token(access: Access, session_id: str | None = None) -> str:
    now = int(time.time())
    claims = {"sid": session_id or uuid.uuid4().hex, "role": access.role, "subject": access.subject,
              "label": access.label, "iat": now, "exp": now + settings.session_hours * 3600}
    return jwt.encode(claims, _secret, algorithm=ALGORITHM)


def read_token(token: str | None) -> tuple[Access, str] | None:
    """Return (Access, session_id) or None if missing, tampered with, or expired."""
    if not token:
        return None
    try:
        c = jwt.decode(token, _secret, algorithms=[ALGORITHM], options={"require": ["exp", "sid", "role"]})
    except jwt.PyJWTError:                       # bad signature, expired, malformed, wrong algorithm...
        return None
    if c["role"] not in ROLES:
        return None
    return Access(c["role"], c.get("subject"), c.get("label", "")), c["sid"]


def cookie_kwargs() -> dict:
    return {"key": COOKIE_NAME, "httponly": True, "samesite": "lax", "secure": settings.cookie_secure,
            "max_age": settings.session_hours * 3600, "path": "/"}
