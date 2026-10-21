"""Route an explicit URL workspace before any database, photo or session is opened."""

import re
from datetime import UTC

from fastapi.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from app.config import base_settings
from app.domain import now
from app.models import LoginSession, Organization, PlatformOwner, User, WorkspaceSession
from app.organization_context import organization_scope
from app.organization_registry import control_session, scope_for

PREFIX = re.compile(r"^(/org/([0-9a-f-]{36}))(/api(?:/.*)?)$")


def platform_login_session(request):
    from app.auth import digest
    token = request.cookies.get("platform_session")
    if not token:
        return None
    with control_session() as db:
        session = db.get(LoginSession, digest(token))
        if not session:
            return None
        expiry = session.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        user = db.get(User, session.user_id)
        if expiry <= now() or not user or not user.active or not db.get(PlatformOwner, user.id):
            return None
        session.expires_at = expiry
        return session


def resolve_workspace(request, id):
    owner_session = platform_login_session(request)
    with control_session() as db:
        organization = db.get(Organization, id)
        if organization is None or organization.status not in {"ACTIVE", "PAUSED"}:
            return None, owner_session
        if organization.status == "PAUSED" and owner_session is None:
            return None, None
        return scope_for(organization), owner_session


def workspace_token_hash(request, organization_id):
    from app.auth import digest
    token = request.cookies.get("workspace_session")
    if not token:
        return None
    with control_session() as db:
        session = db.get(WorkspaceSession, digest(token))
        if session and session.organization_id == organization_id and session.expires_at > now():
            return session.token_hash
    return None


class OrganizationsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not base_settings().organizations_enabled:
            return await self.app(scope, receive, send)
        path = scope["path"]
        match = PREFIX.fullmatch(path)
        if match:
            if match[3].startswith("/api/platform/") or match[3] == "/api/webhooks/max":
                return await JSONResponse({"detail": "Функция доступна в общем кабинете владельца"}, 404)(scope, receive, send)
            try:
                organization, owner_session = await run_in_threadpool(resolve_workspace, Request(scope), match[2])
            except (OSError, ValueError, RuntimeError):
                return await JSONResponse({"detail": "Организация временно недоступна"}, 503)(scope, receive, send)
            if organization is None:
                return await JSONResponse({"detail": "Организация недоступна"}, 404)(scope, receive, send)
            if match[3] == "/api/auth/login" or (owner_session and match[3].startswith("/api/auth/") and match[3] != "/api/auth/me"):
                # The owner's password, avatar and sessions live in the platform account.
                return await RedirectResponse(match[3], status_code=307)(scope, receive, send)
            child = dict(scope)
            child["path"], child["raw_path"] = match[3], match[3].encode()
            child["root_path"] = match[1]
            token_hash = await run_in_threadpool(workspace_token_hash, Request(scope), organization.id) if not owner_session else None
            child["state"] = {**scope.get("state", {}), "platform_login_session": owner_session,
                              "workspace_token_hash": token_hash}
            with organization_scope(organization):
                return await self.app(child, receive, send)
        if path.startswith("/api/") and not (
            path.startswith(("/api/platform/", "/api/auth/"))
            or path in {"/api/webhooks/max", "/api/health"}
        ):
            return await JSONResponse({"detail": "Сначала выберите организацию"}, 409)(scope, receive, send)
        return await self.app(scope, receive, send)
