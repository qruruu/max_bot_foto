"""Inspector personal settings share the operator UI, never the operator authorization."""

from uuid import UUID

from fastapi import HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select

from app.auth import Db, hasher, verify_password
from app.avatars import MAX_AVATAR_BYTES, normalize_avatar
from app.config import base_settings
from app.domain import audit, now
from app.inspection_auth import InspectorUser, inspector_dict, lock_inspector
from app.inspections import router
from app.models import InspectionSession
from app.schemas import PasswordInput, SidebarOrderInput
from app.session_details import session_dict


@router.get("/avatar")
def avatar(user: InspectorUser):
    if not user.avatar_image:
        raise HTTPException(404, "Аватарка не установлена")
    return Response(user.avatar_image, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.put("/avatar")
async def update_avatar(request: Request, db: Db, user: InspectorUser):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_AVATAR_BYTES:
            raise HTTPException(413, "Размер фотографии должен быть не больше 5 МБ.")
    try:
        user.avatar_image = await run_in_threadpool(normalize_avatar, bytes(content))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(db, None, "INSPECTOR_AVATAR_UPDATED", "inspector", user.id, None, {"has_avatar": True})
    db.commit()
    return inspector_dict(user, user._agency)


@router.delete("/avatar")
def remove_avatar(db: Db, user: InspectorUser):
    user.avatar_image = None
    audit(db, None, "INSPECTOR_AVATAR_REMOVED", "inspector", user.id, None, {"has_avatar": False})
    db.commit()
    return inspector_dict(user, user._agency)


@router.put("/sidebar-order")
def sidebar_order(body: SidebarOrderInput, db: Db, user: InspectorUser):
    user.sidebar_order = body.sidebar_order
    db.commit()
    return {"sidebar_order": user.sidebar_order}


@router.post("/password")
def password(body: PasswordInput, db: Db, user: InspectorUser):
    lock_inspector(db, user.id)
    db.refresh(user)
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Неверный текущий пароль")
    user.password_hash = hasher.hash(body.new_password)
    db.execute(delete(InspectionSession).where(InspectionSession.inspector_id == user.id))
    audit(db, None, "INSPECTOR_PASSWORD_CHANGED", "inspector", user.id, None, {"sessions_revoked": True})
    db.commit()
    return {"ok": True}


@router.get("/sessions")
def sessions(request: Request, db: Db, user: InspectorUser):
    current = request.state.inspection_session.id
    rows = db.scalars(select(InspectionSession).where(InspectionSession.inspector_id == user.id,
        InspectionSession.expires_at > now()).order_by((InspectionSession.id == current).desc(),
        InspectionSession.last_seen_at.desc().nullslast(), InspectionSession.created_at.desc(), InspectionSession.id))
    return {"items": [session_dict(s, current) for s in rows], "session_hours": base_settings().session_hours}


@router.post("/sessions/revoke-others")
def revoke_others(request: Request, db: Db, user: InspectorUser):
    lock_inspector(db, user.id)
    count = db.execute(delete(InspectionSession).where(InspectionSession.inspector_id == user.id,
        InspectionSession.id != request.state.inspection_session.id, InspectionSession.expires_at > now())).rowcount
    audit(db, None, "INSPECTOR_SESSIONS_REVOKED", "inspector", user.id, None, {"revoked": count})
    db.commit()
    return {"revoked": count}


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: UUID, request: Request, db: Db, user: InspectorUser):
    if str(session_id) == request.state.inspection_session.id:
        raise HTTPException(409, "Для завершения текущего сеанса используйте кнопку «Выйти».")
    lock_inspector(db, user.id)
    count = db.execute(delete(InspectionSession).where(InspectionSession.id == str(session_id),
        InspectionSession.inspector_id == user.id, InspectionSession.expires_at > now())).rowcount
    if not count:
        raise HTTPException(404, "Сеанс не найден или уже завершён")
    audit(db, None, "INSPECTOR_SESSION_REVOKED", "inspector", user.id, None, {"id": str(session_id)})
    db.commit()
    return {"ok": True}
