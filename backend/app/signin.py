"""A common sign-in: resolve verified accounts, never a public directory of companies."""

import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import (
    DUMMY_HASH,
    Db,
    check_origin,
    digest,
    issue_login,
    rate_limit_login,
    user_dict,
    verify_password,
)
from app.config import settings
from app.db import database_engine
from app.domain import now
from app.models import (
    LoginChoice,
    LoginSession,
    Organization,
    OrganizationLogin,
    PlatformOwner,
    User,
    WorkspaceSession,
)
from app.organization_context import current_organization, organization_scope
from app.organization_middleware import platform_login_session
from app.organization_registry import scope_for
from app.schemas import StrictModel

router = APIRouter(prefix="/api/auth", tags=["auth"])
INVALID = "Неверный логин или пароль"


class ChoiceInput(StrictModel):
    organization_id: UUID


def common_login(body, request, response, control):
    check_origin(request)
    rate_limit_login(control, request, body.login)
    control.execute(text("SELECT pg_advisory_xact_lock(7004, 1)"))
    owner = control.scalar(select(User).join(PlatformOwner, PlatformOwner.user_id == User.id).where(
        User.login == body.login.lower(), User.active))
    if verify_password(owner.password_hash if owner else DUMMY_HASH, body.password) and owner:
        return issue_login(owner, request, response, control, password=body.password)
    from app.inspection_auth import try_inspector_login
    inspector = try_inspector_login(body, request, response, control)
    if inspector is not None:
        return inspector
    candidates = []
    rows = list(control.execute(select(OrganizationLogin, Organization).join(Organization).where(
        OrganizationLogin.login == body.login.lower(), Organization.status == "ACTIVE")))
    control.commit()
    try:
        for entry, record in rows:
            scope = scope_for(record)
            with organization_scope(scope), Session(database_engine(scope.database_url)) as tenant:
                user = tenant.get(User, entry.user_id)
                encoded = user.password_hash if user and user.active and user.login.lower() == body.login.lower() else DUMMY_HASH
                valid = verify_password(encoded, body.password)
                if valid and user and user.active and user.login.lower() == body.login.lower() and user.id != scope.owner_user_id:
                    candidates.append({"organization_id": scope.id, "user_id": user.id,
                                       "password_hash": digest(user.password_hash), "name": record.name})
    except (SQLAlchemyError, OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(503, "Не удалось проверить вход. Повторите немного позже.") from exc
    if not candidates:
        raise HTTPException(401, INVALID)
    if len(candidates) == 1:
        return complete(candidates[0], request, response, control, password=body.password)
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    control.execute(delete(LoginChoice).where(LoginChoice.expires_at < now()))
    control.add(LoginChoice(token_hash=digest(token), csrf_hash=digest(csrf),
                            ip_hash=digest(request.client.host if request.client else "unknown"),
                            candidates=candidates, expires_at=now() + timedelta(minutes=5)))
    control.commit()
    for name, value, httponly in (("login_choice", token, True), ("login_choice_csrf", csrf, False)):
        response.set_cookie(name, value, httponly=httponly, secure=settings().cookie_secure,
                            samesite="strict", max_age=300, path="/")
    return {"requires_organization": True, "choices": [{"id": item["organization_id"], "name": item["name"]}
                                                       for item in candidates]}


def complete(candidate, request, response, control, *, password=None):
    record = control.get(Organization, candidate["organization_id"])
    if record is None or record.status != "ACTIVE":
        raise HTTPException(401, "Вход устарел. Введите логин и пароль снова.")
    scope = scope_for(record)
    with organization_scope(scope), Session(database_engine(scope.database_url)) as tenant:
        tenant.execute(text("SELECT pg_advisory_xact_lock(7004, 1)"))
        user = tenant.get(User, candidate["user_id"])
        if not user or not user.active or user.id == scope.owner_user_id or digest(user.password_hash) != candidate["password_hash"]:
            raise HTTPException(401, "Вход устарел. Введите логин и пароль снова.")
        return issue_login(user, request, response, tenant, password=password)


@router.post("/choose-organization")
def choose_organization(body: ChoiceInput, request: Request, response: Response, db: Db):
    if current_organization() or not settings().organizations_enabled:
        raise HTTPException(404)
    check_origin(request)
    token = request.cookies.get("login_choice", "")
    choice = db.get(LoginChoice, digest(token), with_for_update=True)
    if not choice or choice.expires_at <= now() or choice.ip_hash != digest(request.client.host if request.client else "unknown"):
        raise HTTPException(401, "Вход устарел. Введите логин и пароль снова.")
    if not secrets.compare_digest(choice.csrf_hash, digest(request.headers.get("x-csrf-token", ""))):
        raise HTTPException(403, "Недействительный CSRF-токен")
    candidate = next((item for item in choice.candidates if item["organization_id"] == str(body.organization_id)), None)
    if candidate is None:
        raise HTTPException(403, "Нет доступа к этой организации")
    # Consume before issuing. Concurrent/replayed requests cannot reuse a verified password.
    db.delete(choice)
    db.commit()
    return complete(candidate, request, response, db)


@router.get("/entry")
def entry(request: Request, db: Db):
    if current_organization() or not settings().organizations_enabled:
        raise HTTPException(404)
    owner_session = platform_login_session(request)
    if owner_session:
        user = db.get(User, owner_session.user_id)
        user._platform_owner = True
        return {"user": user_dict(user)}
    from app.inspection_auth import authenticated_inspector, inspector_dict
    identity = authenticated_inspector(request, db)
    if identity:
        return {"user": inspector_dict(identity[0], identity[1])}
    token = request.cookies.get("workspace_session", "")
    session = db.get(WorkspaceSession, digest(token)) if token else None
    record = db.get(Organization, session.organization_id) if session and session.expires_at > now() else None
    if record and record.status == "ACTIVE":
        scope = scope_for(record)
        with organization_scope(scope), Session(database_engine(scope.database_url)) as tenant:
            login_session = tenant.get(LoginSession, session.token_hash)
            user = tenant.get(User, login_session.user_id) if login_session and login_session.expires_at > now() else None
            if user and user.active:
                return {"user": user_dict(user)}
    return {"user": None}
