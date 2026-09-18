"""Admin auth — httpOnly cookie sessions (AC-76/77).

Provider/broker credentials live only in backend/.env and are never returned to the
client (AC-75). Settings mutations require an authenticated admin.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import timedelta

from fastapi import Cookie, HTTPException

from lib.db import db
from lib.dates import now_utc

SESSION_COOKIE = "fno_session"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@quantpulse.in")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "QuantPulse@2026")
SESSION_TTL_HOURS = 12


def _hash(password: str) -> str:
    salt = os.environ.get("AUTH_SALT", "quantpulse-static-salt")
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def verify_credentials(email: str, password: str) -> bool:
    return hmac.compare_digest(email.strip().lower(), ADMIN_EMAIL.lower()) and \
        hmac.compare_digest(_hash(password), _hash(ADMIN_PASSWORD))


async def create_session(email: str) -> str:
    token = str(uuid.uuid4())
    await db.sessions.insert_one({
        "token": token, "email": email, "created_at": now_utc(),
        "expires_at": now_utc() + timedelta(hours=SESSION_TTL_HOURS),
    })
    return token


async def destroy_session(token: str | None) -> None:
    if token:
        await db.sessions.delete_one({"token": token})


async def current_admin(fno_session: str | None = Cookie(default=None)) -> str | None:
    """Returns the admin email, or None when not signed in."""
    if not fno_session:
        return None
    doc = await db.sessions.find_one({"token": fno_session})
    if not doc:
        return None
    exp = doc["expires_at"]
    if exp.tzinfo is None:
        from lib.dates import UTC

        exp = exp.replace(tzinfo=UTC)
    if exp < now_utc():
        await db.sessions.delete_one({"token": fno_session})
        return None
    return doc["email"]


async def require_admin(fno_session: str | None = Cookie(default=None)) -> str:
    email = await current_admin(fno_session)
    if not email:
        raise HTTPException(status_code=401, detail="Admin authentication required to change configuration.")
    return email
