"""Authentication routes — login, register, current user."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import text

from aimw.api.auth import create_token, hash_password, verify_password
from aimw.api.deps import RequestIdDep, SessionmakerDep
from aimw.db.session import writer_lock

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    role: str = "analyst"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    role: str


class UserInfo(BaseModel):
    user_id: int
    email: str
    role: str


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, sm: SessionmakerDep) -> TokenResponse:
    async with sm() as session:
        result = await session.execute(
            text("SELECT id, email, password_hash, role FROM users WHERE email = :email"),
            {"email": body.email},
        )
        row = result.first()

    if not row or not verify_password(body.password, row[2]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(user_id=row[0], email=row[1], role=row[3])
    return TokenResponse(
        access_token=token,
        user_id=row[0],
        email=row[1],
        role=row[3],
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, sm: SessionmakerDep) -> TokenResponse:
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    async with sm() as session:
        existing = await session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": body.email},
        )
        if existing.first():
            raise HTTPException(status_code=409, detail="Email already registered")

    hashed = hash_password(body.password)
    now = dt.datetime.now(dt.UTC)

    async with writer_lock(), sm() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO users (email, password_hash, role, created_at) "
                "VALUES (:email, :pw, :role, :at)"
            ),
            {"email": body.email, "pw": hashed, "role": body.role, "at": now},
        )
        result = await session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": body.email},
        )
        user_id = result.scalar()

    token = create_token(user_id=user_id, email=body.email, role=body.role)
    return TokenResponse(
        access_token=token,
        user_id=user_id,
        email=body.email,
        role=body.role,
    )


__all__ = ["router"]
