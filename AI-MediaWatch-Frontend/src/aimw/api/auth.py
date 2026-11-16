"""JWT authentication — user management, token issue/verify, password hashing.

Users are stored in the SQLite DB. On first startup, a default admin is
created from AIMW_ADMIN_EMAIL / AIMW_ADMIN_PASSWORD (or a random password
is generated and logged). JWT tokens are issued on POST /api/v1/auth/login
and verified via the Authorization: Bearer header.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from typing import Any

import bcrypt
import jwt

from aimw.core.config import get_settings

_LOG = logging.getLogger("aimw.api.auth")

# bcrypt operates on at most 72 bytes; longer passwords must be truncated by
# the caller (bcrypt 5.x raises instead of silently truncating). We encode to
# UTF-8 and clip to 72 bytes so hash and verify stay consistent.
_BCRYPT_MAX_BYTES = 72


def _to_bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_to_bcrypt_bytes(password), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(user_id: int, email: str, role: str) -> str:
    cfg = get_settings()
    secret = cfg.jwt_secret
    if not secret:
        secret_val = "aimw-dev-secret-change-me"
    else:
        secret_val = secret.get_secret_value()

    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": dt.datetime.now(dt.UTC) + dt.timedelta(minutes=cfg.jwt_expire_minutes),
        "iat": dt.datetime.now(dt.UTC),
    }
    return jwt.encode(payload, secret_val, algorithm=cfg.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    cfg = get_settings()
    secret = cfg.jwt_secret
    secret_val = secret.get_secret_value() if secret else "aimw-dev-secret-change-me"
    return jwt.decode(token, secret_val, algorithms=[cfg.jwt_algorithm])


async def ensure_default_admin() -> None:
    """Create default admin user if no users exist in the DB."""
    from sqlalchemy import text

    from aimw.db.session import get_sessionmaker, writer_lock

    cfg = get_settings()
    sm = get_sessionmaker()

    async with sm() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        count = result.scalar()
        if count and count > 0:
            return

    email = cfg.admin_email
    password = cfg.admin_password
    if password:
        pw = password.get_secret_value()
    else:
        pw = secrets.token_urlsafe(16)
        _LOG.warning(
            "default_admin_created",
            extra={"email": email, "password": pw, "note": "Set AIMW_ADMIN_PASSWORD in .env"},
        )

    hashed = hash_password(pw)
    now = dt.datetime.now(dt.UTC)

    async with writer_lock(), sm() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO users (email, password_hash, role, created_at) "
                "VALUES (:email, :pw, :role, :at)"
            ),
            {"email": email, "pw": hashed, "role": "admin", "at": now},
        )

    _LOG.info("default_admin_ready", extra={"email": email})
