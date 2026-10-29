import hashlib
import secrets
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, attributes

from app.avatars import MAX_AVATAR_BYTES, normalize_avatar
from app.chat_access import allowed_chat_ids, require_all_chats
from app.config import settings
from app.db import get_db
from app.domain import audit, now
from app.models import LoginAttempt, LoginSession, User
from app.organization_context import current_organization, workspace_url
from app.permissions import Permission, effective_permissions, has_permission
from app.schemas import LoginInput, PasswordInput, SidebarOrderInput
from app.security_telemetry import identify
from app.session_details import client_address, session_dict

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


def cookie_names():
    organization = current_organization()
    if organization:
        return "workspace_session", "workspace_csrf"
    return ("platform_session", "platform_csrf") if settings().organizations_enabled else ("session", "csrf")


def current_user(request: Request, db: Db):
    organization = current_organization()
    platform_session = getattr(request.state, "platform_login_session", None)
    platform_login = settings().organizations_enabled and organization is None
    token = request.cookies.get(cookie_names()[0])
    token_hash = getattr(request.state, "workspace_token_hash", None) if organization else digest(token) if token else None
    session = platform_session or (db.get(LoginSession, token_hash) if token_hash else None)
    if not session or session.expires_at <= now():
        raise HTTPException(401, "Войдите в систему")
    user = db.get(User, organization.owner_user_id if platform_session else session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Пользователь заблокирован")
    if platform_login:
        from app.models import PlatformOwner
        if db.get(PlatformOwner, user.id) is None:
            raise HTTPException(403, "Вход в общий кабинет доступен только владельцу")
    user._platform_owner = bool(platform_session or platform_login)
    user._platform_user_id = platform_session.user_id if platform_session else None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(session.csrf_hash, digest(csrf)):
            raise HTTPException(403, "Недействительный CSRF-токен")
    instant = now()
    cutoff = instant - timedelta(minutes=1)
    if not platform_session and (session.last_seen_at is None or session.last_seen_at < cutoff):
        # Persist after the handler finishes, without committing its business transaction.
        observed_ua = request.headers.get("user-agent", "")[:512] or None
        observed_ip = client_address(request)
        db.info["session_activity"] = {
            "token_hash": session.token_hash,
            "at": instant,
            "user_agent": observed_ua,
            "ip_address": observed_ip,
        }
        attributes.set_committed_value(session, "last_seen_at", instant)
        if session.user_agent is None and observed_ua:
            attributes.set_committed_value(session, "user_agent", observed_ua)
        if observed_ip:
            attributes.set_committed_value(session, "ip_address", observed_ip)
    request.state.login_session = session
    identify(request, platform_session.user_id if platform_session else user.id,
             "owner" if user._platform_owner else "administrator" if user.role == "ADMIN_OPERATOR" else "operator")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def is_platform_owner(user: User) -> bool:
    # Set only by the verified platform session, never by a tenant role or request body.
    return bool(getattr(user, "_platform_owner", False))


def workspace_owner(user: CurrentUser):
    if current_organization() is None or not is_platform_owner(user):
        raise HTTPException(403, "Доступно только владельцу сервиса")
    return user


WorkspaceOwner = Annotated[User, Depends(workspace_owner)]


def admin_user(user: CurrentUser):
    if user.role != "ADMIN_OPERATOR":
        raise HTTPException(403, "Требуется роль администратора")
    return user


AdminUser = Annotated[User, Depends(admin_user)]


def check_permission(user: User, code):
    if not has_permission(user, code):
        raise HTTPException(403, "Нет доступа к этой функции")


def require_permission(code):
    def allowed(user: CurrentUser):
        check_permission(user, code)
        if code in {Permission.EXCHANGE_MANAGE, Permission.LEARNING_MANAGE,
                    Permission.DAILY_REPORTS_VIEW, Permission.DAILY_REPORTS_EDIT,
                    Permission.DAILY_REPORTS_CONFIGURE}:
            require_all_chats(user)
        return user

    return allowed


PhotosReader = Annotated[User, Depends(require_permission(Permission.PHOTOS_VIEW))]
OriginalsReader = Annotated[User, Depends(require_permission(Permission.ORIGINALS_VIEW))]
PhotoEditor = Annotated[User, Depends(require_permission(Permission.PHOTOS_EDIT))]
ReportsReader = Annotated[User, Depends(require_permission(Permission.REPORTS_VIEW))]
ReportsExporter = Annotated[User, Depends(require_permission(Permission.REPORTS_EXPORT))]
PreviewRemover = Annotated[User, Depends(require_permission(Permission.PREVIEWS_REMOVE))]
DistrictReader = Annotated[User, Depends(require_permission(Permission.DISTRICTS_VIEW))]
DistrictEditor = Annotated[User, Depends(require_permission(Permission.DISTRICTS_EDIT))]
ChatManager = Annotated[User, Depends(require_permission(Permission.CHATS_MANAGE))]
AuditReader = Annotated[User, Depends(require_permission(Permission.AUDIT_VIEW))]
JobManager = Annotated[User, Depends(require_permission(Permission.JOBS_MANAGE))]
ExchangeManager = Annotated[User, Depends(require_permission(Permission.EXCHANGE_MANAGE))]
LearningManager = Annotated[User, Depends(require_permission(Permission.LEARNING_MANAGE))]


def user_dict(user: User):
    result = {
        "id": user.id,
        "login": user.login,
        "name": user.name,
        "role": user.role,
        "active": user.active,
        "permissions": effective_permissions(user),
        "allowed_chat_ids": allowed_chat_ids(user),
        "sidebar_order": user.sidebar_order or [],
        "avatar_url": workspace_url(f"/api/auth/avatar/{user.id}?v={hashlib.sha256(user.avatar_image).hexdigest()[:16]}")
        if user.avatar_image else None,
    }
    if settings().organizations_enabled:
        organization = current_organization()
        result.update(is_platform_owner=getattr(user, "_platform_owner", False),
                      organization={"id": organization.id, "name": organization.name} if organization else None)
        result["managed_by_platform"] = bool(organization and organization.owner_user_id == user.id)
        if organization and getattr(user, "_platform_user_id", None):
            from app.organization_registry import control_session
            with control_session() as control:
                owner = control.get(User, user._platform_user_id)
                result.update(name=owner.name, login=owner.login, sidebar_order=owner.sidebar_order or [],
                              avatar_url=f"/api/auth/avatar/{owner.id}?v={hashlib.sha256(owner.avatar_image).hexdigest()[:16]}"
                              if owner.avatar_image else None)
    return result


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
    if settings().organizations_enabled and current_organization() is None:
        from app.signin import common_login
        return common_login(body, request, response, db)
    check_origin(request)
    rate_limit_login(db, request, body.login)
    # Serialize issuance with password/permission changes and explicit session revocation.
    db.execute(text("SELECT pg_advisory_xact_lock(7004, 1)"))
    user = db.scalar(select(User).where(User.login == body.login.lower()))
    valid = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if not valid or not user or not user.active:
        raise HTTPException(401, "Неверный логин или пароль")
    platform_login = settings().organizations_enabled and current_organization() is None
    if platform_login:
        from app.models import PlatformOwner
        if db.get(PlatformOwner, user.id) is None:
            raise HTTPException(401, "Неверный логин или пароль")
    user._platform_owner = platform_login
    return issue_login(user, request, response, db, password=body.password)


def issue_login(user, request, response, db, *, password=None):
    platform_login = settings().organizations_enabled and current_organization() is None
    user._platform_owner = platform_login
    if password is not None and hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(password)
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    instant = now()
    db.add(
        LoginSession(
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            user_id=user.id,
            expires_at=instant + timedelta(hours=settings().session_hours),
            created_at=instant,
            last_seen_at=instant,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
            ip_address=client_address(request),
        )
    )
    db.execute(delete(LoginSession).where(LoginSession.expires_at < now()))
    db.commit()
    if current_organization():
        from app.models import WorkspaceSession
        from app.organization_registry import control_session
        with control_session() as control:
            control.execute(delete(WorkspaceSession).where(WorkspaceSession.expires_at < instant))
            control.add(WorkspaceSession(token_hash=digest(token), organization_id=current_organization().id,
                                         expires_at=instant + timedelta(hours=settings().session_hours)))
            control.commit()
    if settings().organizations_enabled:
        # Switching accounts must not leave a previous owner's authority in this browser.
        for name in ("inspection_session", "inspection_csrf"):
            response.delete_cookie(name, path="/")
        for name in (("workspace_session", "workspace_csrf") if platform_login else ("platform_session", "platform_csrf")):
            response.delete_cookie(name, path="/")
        for name in ("login_choice", "login_choice_csrf"):
            response.delete_cookie(name, path="/")
    session_name, csrf_name = cookie_names()
    cookies = [(session_name, token, True), (csrf_name, csrf, False)]
    for name, value, http_only in cookies:
        response.set_cookie(
            name,
            value,
            httponly=http_only,
            secure=settings().cookie_secure,
            samesite="strict",
            max_age=settings().session_hours * 3600,
            path="/",
        )
    identify(request, user.id, "owner" if platform_login else "administrator" if user.role == "ADMIN_OPERATOR" else "operator", login=True)
    return user_dict(user)


@router.get("/me")
def me(user: CurrentUser):
    return user_dict(user)


@router.put("/sidebar-order")
def update_sidebar_order(body: SidebarOrderInput, db: Db, user: CurrentUser):
    # A personal display preference never changes permissions or other accounts.
    user.sidebar_order = body.sidebar_order
    db.commit()
    return {"sidebar_order": user.sidebar_order}


@router.get("/avatar/{user_id}")
def avatar(user_id: int, user: CurrentUser):
    if user_id != user.id or not user.avatar_image:
        raise HTTPException(404, "Аватарка не установлена")
    return Response(
        content=user.avatar_image,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/avatar")
async def update_avatar(request: Request, db: Db, user: CurrentUser):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_AVATAR_BYTES:
            raise HTTPException(413, "Размер фотографии должен быть не больше 5 МБ.")
        data.extend(chunk)
    try:
        image = await run_in_threadpool(normalize_avatar, bytes(data))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    before = {"has_avatar": bool(user.avatar_image)}
    user.avatar_image = image
    audit(db, user.id, "USER_AVATAR_UPDATED", "user", user.id, before, {"has_avatar": True})
    db.commit()
    return user_dict(user)


@router.delete("/avatar")
def remove_avatar(db: Db, user: CurrentUser):
    before = {"has_avatar": bool(user.avatar_image)}
    user.avatar_image = None
    audit(db, user.id, "USER_AVATAR_REMOVED", "user", user.id, before, {"has_avatar": False})
    db.commit()
    return user_dict(user)


@router.get("/sessions")
def sessions(request: Request, db: Db, user: CurrentUser):
    current_id = request.state.login_session.id
    rows = db.scalars(
        select(LoginSession)
        .where(LoginSession.user_id == user.id, LoginSession.expires_at > now())
        .order_by(
            (LoginSession.id == current_id).desc(),
            LoginSession.last_seen_at.desc().nullslast(),
            LoginSession.created_at.desc().nullslast(),
            LoginSession.id,
        )
    )
    return {
        "items": [session_dict(session, current_id) for session in rows],
        "session_hours": settings().session_hours,
    }


@router.post("/sessions/revoke-others")
def revoke_other_sessions(request: Request, db: Db, user: CurrentUser):
    db.execute(text("SELECT pg_advisory_xact_lock(7004, 1)"))
    count = db.execute(
        delete(LoginSession).where(
            LoginSession.user_id == user.id,
            LoginSession.id != request.state.login_session.id,
            LoginSession.expires_at > now(),
        )
    ).rowcount
    if count:
        audit(db, user.id, "OTHER_SESSIONS_REVOKED", "user", user.id, None, {"sessions_revoked": count})
    db.commit()
    return {"revoked": count}


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: UUID, request: Request, db: Db, user: CurrentUser):
    if str(session_id) == request.state.login_session.id:
        raise HTTPException(409, "Для завершения текущего сеанса используйте кнопку «Выйти».")
    db.execute(text("SELECT pg_advisory_xact_lock(7004, 1)"))
    count = db.execute(
        delete(LoginSession).where(
            LoginSession.id == str(session_id),
            LoginSession.user_id == user.id,
            LoginSession.expires_at > now(),
        )
    ).rowcount
    if not count:
        raise HTTPException(404, "Сеанс не найден или уже завершён")
    audit(db, user.id, "SESSION_REVOKED", "user", user.id, None, {"session_id": str(session_id)})
    db.commit()
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, db: Db, user: CurrentUser):
    db.delete(request.state.login_session)
    db.commit()
    cookie_path = "/"
    session_name, csrf_name = cookie_names()
    response.delete_cookie(session_name, path=cookie_path)
    response.delete_cookie(csrf_name, path=cookie_path)
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
