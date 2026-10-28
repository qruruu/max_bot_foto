"""Inspector sessions never authorize any organization/operator API."""

import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select, text

from app.auth import Db, check_origin, digest, hasher, verify_password
from app.config import base_settings
from app.domain import now
from app.models import InspectionAgency, InspectionSession, Inspector
from app.organization_context import current_organization
from app.session_details import client_address

INSPECTION_MENU = ["/inspectors", "/", "/photos", "/photo-map", "/districts", "/appeals", "/messages", "/users"]


def lock_inspector(db, id):
    db.execute(text("SELECT pg_advisory_xact_lock(7040, :id)"), {"id": id})


def inspector_dict(account, agency):
    return {"id": account.id, "login": account.login, "name": account.name, "role": "INSPECTOR",
            "active": account.active, "agency_id": agency.id, "agency_name": agency.name,
            "can_create_accounts": account.can_create_accounts, "created_by": account.created_by,
            "is_platform_owner": False, "organization": None, "permissions": [],
            "sidebar_order": account.sidebar_order or INSPECTION_MENU,
            "avatar_url": f"/api/inspection/avatar?v={hashlib.sha256(account.avatar_image).hexdigest()[:16]}"
            if account.avatar_image else None, "allowed_chat_ids": []}


def authenticated_inspector(request, db):
    token = request.cookies.get("inspection_session")
    session = db.get(InspectionSession, digest(token)) if token else None
    if not session or session.expires_at <= now():
        return None
    account = db.get(Inspector, session.inspector_id)
    agency = db.get(InspectionAgency, account.agency_id) if account else None
    if not account or not account.active or not agency or not agency.active:
        return None
    return account, agency, session


def current_inspector(request: Request, db: Db):
    if not base_settings().organizations_enabled or current_organization():
        raise HTTPException(404)
    identity = authenticated_inspector(request, db)
    if identity is None:
        raise HTTPException(401, "Войдите в кабинет проверяющего")
    account, agency, session = identity
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        if not secrets.compare_digest(session.csrf_hash, digest(request.headers.get("x-csrf-token", ""))):
            raise HTTPException(403, "Недействительный CSRF-токен")
    request.state.inspection_session = session
    if session.last_seen_at is None or session.last_seen_at < now() - timedelta(minutes=1):
        db.info["session_activity"] = {"inspection": True, "token_hash": session.token_hash, "at": now(),
                                       "user_agent": request.headers.get("user-agent", "")[:512] or None,
                                       "ip_address": client_address(request)}
    account._agency = agency
    return account


InspectorUser = Annotated[Inspector, Depends(current_inspector)]


def try_inspector_login(body, request, response, db):
    account = db.scalar(select(Inspector).where(Inspector.login == body.login.lower()))
    if account:
        lock_inspector(db, account.id)
        db.refresh(account)
    if account is None or not verify_password(account.password_hash, body.password):
        return None
    agency = db.get(InspectionAgency, account.agency_id)
    if not account.active or not agency or not agency.active:
        raise HTTPException(401, "Аккаунт проверяющего приостановлен")
    if hasher.check_needs_rehash(account.password_hash):
        account.password_hash = hasher.hash(body.password)
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    instant = now()
    db.execute(delete(InspectionSession).where(InspectionSession.expires_at <= instant))
    db.add(InspectionSession(token_hash=digest(token), csrf_hash=digest(csrf), inspector_id=account.id,
                             created_at=instant, last_seen_at=instant,
                             user_agent=request.headers.get("user-agent", "")[:512] or None,
                             ip_address=client_address(request),
                             expires_at=instant + timedelta(hours=base_settings().session_hours)))
    db.commit()
    for name in ("platform_session", "platform_csrf", "workspace_session", "workspace_csrf",
                 "login_choice", "login_choice_csrf"):
        response.delete_cookie(name, path="/")
    for name, value, http_only in (("inspection_session", token, True), ("inspection_csrf", csrf, False)):
        response.set_cookie(name, value, httponly=http_only, secure=base_settings().cookie_secure,
                            samesite="strict", path="/", max_age=base_settings().session_hours * 3600)
    return inspector_dict(account, agency)
