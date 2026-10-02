import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.domain import audit, now
from app.models import LoginAttempt, LoginSession, User
from app.schemas import LoginInput, PasswordInput

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(24))
router = APIRouter(prefix="/api/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_db)]


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != settings().app_origin.rstrip("/"):
        raise HTTPException(403, "Недопустимый источник запроса")


def current_user(request: Request, db: Db):
    token = request.cookies.get("session")
    session = db.get(LoginSession, digest(token)) if token else None
    if not session or session.expires_at <= now():
        raise HTTPException(401, "Войдите в систему")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Пользователь заблокирован")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(session.csrf_hash, digest(csrf)):
            raise HTTPException(403, "Недействительный CSRF-токен")
    request.state.login_session = session
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def admin_user(user: CurrentUser):
    if user.role != "ADMIN_OPERATOR":
        raise HTTPException(403, "Требуется роль администратора")
    return user


AdminUser = Annotated[User, Depends(admin_user)]


def user_dict(user: User):
    return {"id": user.id, "login": user.login, "name": user.name, "role": user.role, "active": user.active}


def verify_password(encoded: str, password: str):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def rate_limit_login(db: Session, request: Request, login: str):
    ip = request.client.host if request.client else "unknown"
    keys = [(digest("ip:" + ip), 30), (digest("login:" + login.casefold()), 8)]
    # Stable lock order prevents deadlocks when simultaneous logins share a key.
    for key, maximum in sorted(keys):
        db.execute(insert(LoginAttempt).values(key=key, count=0).on_conflict_do_nothing())
        attempt = db.scalar(select(LoginAttempt).where(LoginAttempt.key == key).with_for_update())
        if now() - attempt.started_at > timedelta(minutes=15):
            attempt.count, attempt.started_at = 0, now()
        if attempt.count >= maximum:
            db.commit()
            raise HTTPException(429, "Слишком много попыток. Повторите через 15 минут.")
        attempt.count += 1
    db.execute(delete(LoginAttempt).where(LoginAttempt.started_at < now() - timedelta(days=1)))
    db.commit()


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response, db: Db):
    check_origin(request)
    rate_limit_login(db, request, body.login)
    user = db.scalar(select(User).where(User.login == body.login.lower()))
    valid = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if not valid or not user or not user.active:
        raise HTTPException(401, "Неверный логин или пароль")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(body.password)
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            user_id=user.id,
            expires_at=now() + timedelta(hours=settings().session_hours),
        )
    )
    db.execute(delete(LoginSession).where(LoginSession.expires_at < now()))
    db.commit()
    for name, value, http_only in [("session", token, True), ("csrf", csrf, False)]:
        response.set_cookie(
            name,
            value,
            httponly=http_only,
            secure=settings().cookie_secure,
            samesite="strict",
            max_age=settings().session_hours * 3600,
            path="/",
        )
    return user_dict(user)


@router.get("/me")
def me(user: CurrentUser):
    return user_dict(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Db, user: CurrentUser):
    db.delete(request.state.login_session)
    db.commit()
    response.delete_cookie("session", path="/")
    response.delete_cookie("csrf", path="/")
    return {"ok": True}


@router.post("/password")
def password(body: PasswordInput, db: Db, user: CurrentUser):
    db.execute(text("SELECT pg_advisory_xact_lock(7004, 1)"))
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Неверный текущий пароль")
    user.password_hash = hasher.hash(body.new_password)
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    audit(db, user.id, "PASSWORD_CHANGED", "user", user.id, None, {"sessions_revoked": True})
    db.commit()
    return {"ok": True}
