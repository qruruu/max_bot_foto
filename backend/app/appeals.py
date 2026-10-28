"""Organization appeal inbox, receipt recovery and authenticated access boundaries."""

import secrets
from datetime import timedelta
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.appeal_catalog import public_organizations
from app.appeal_images import MAX_PHOTO_BYTES, MAX_PHOTOS
from app.auth import CurrentUser, is_platform_owner
from app.config import base_settings
from app.domain import audit, now
from app.models import AppealCaptureSession, AppealPhoto, AppealRateLimit, CitizenAppeal, PlatformOwner
from app.organization_context import current_organization, workspace_url
from app.organization_registry import control_session
from app.schemas import StrictModel

public_router = APIRouter(prefix="/api/public/appeals", tags=["citizen appeals"])
owner_router = APIRouter(prefix="/api/platform/appeals", tags=["owner appeals"])
organization_router = APIRouter(prefix="/api/appeals", tags=["organization appeals"])
CATEGORIES = {
    "waste": "Мусор и урны", "cleaning": "Уборка территории", "landscaping": "Деревья и озеленение",
    "roads": "Дороги и тротуары", "lighting": "Освещение", "playgrounds": "Детские и спортивные площадки",
    "building": "Дом и подъезд", "other": "Другая проблема",
}
AppealStatus = Literal["NEW", "IN_REVIEW", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "REJECTED", "CANCELLED", "RESOLVED", "SPAM"]


class Capture(StrictModel):
    captured_at: AwareDatetime
    position_at: AwareDatetime
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float = Field(gt=0, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def fresh_position(self):
        if abs((self.captured_at - self.position_at).total_seconds()) > 15:
            raise ValueError("Дождитесь свежего местоположения и сделайте снимок ещё раз")
        return self


class OwnerEdit(StrictModel):
    status: AppealStatus
    owner_note: str = Field(max_length=4000)
    expected_version: int = Field(ge=1)


def require_appeal_access(user: CurrentUser):
    organization = current_organization()
    if (organization and user.role not in {"ADMIN_OPERATOR", "OPERATOR"}) or (not organization and not is_platform_owner(user)):
        raise HTTPException(403, "Обращения доступны администраторам выбранной организации")
    return user


AppealReader = Annotated[object, Depends(require_appeal_access)]


def appeal_conditions(user=None):
    organization = current_organization()
    conditions = [CitizenAppeal.organization_id == organization.id] if organization else []
    if user and user.role == "OPERATOR":
        from app.models import AppealTask
        latest = select(func.max(AppealTask.id)).where(AppealTask.appeal_id == CitizenAppeal.id).correlate(CitizenAppeal).scalar_subquery()
        conditions.append(CitizenAppeal.id.in_(select(AppealTask.appeal_id).where(
            AppealTask.id == latest, AppealTask.operator_id == user.id)))
    return conditions


def find_appeal(db, id, *, lock=False, user=None):
    query = select(CitizenAppeal).where(CitizenAppeal.id == id, *appeal_conditions(user))
    appeal = db.scalar(query.with_for_update() if lock else query)
    if not appeal:
        raise HTTPException(404, "Обращение не найдено")
    return appeal


def private_url(path=""):
    return workspace_url(("/api/appeals" if current_organization() else "/api/platform/appeals") + path)


def check_public_request(request):
    origins = {base_settings().app_origin.rstrip("/"), base_settings().public_appeals_origin.rstrip("/")}
    if request.headers.get("origin", "") not in origins - {""} or request.headers.get("x-appeal-request") not in {"camera", "form"}:
        raise HTTPException(403, "Откройте страницу обращений")


def public_available(db):
    if not base_settings().organizations_enabled or db.scalar(select(PlatformOwner.user_id).limit(1)) is None:
        raise HTTPException(503, "Приём обращений пока не настроен. Попробуйте позже.")


@public_router.get("/catalog")
def catalog(request: Request):
    with control_session() as db:
        public_available(db)
        rate_limit(db, request, "catalog", 120, 1)
        items = public_organizations(db)
    return {"organizations": items, "yandex_maps_api_key": base_settings().yandex_maps_api_key}


def rate_limit(db, request, kind, maximum, minutes):
    # ASGI receives the address from the trusted reverse proxy, never from arbitrary HTTP headers here.
    ip = request.client.host if request.client else "unknown"
    key = sha256((kind + ":" + ip).encode()).hexdigest()
    instant = now()
    db.execute(insert(AppealRateLimit).values(key=key, count=0, started_at=instant).on_conflict_do_nothing())
    bucket = db.scalar(select(AppealRateLimit).where(AppealRateLimit.key == key).with_for_update())
    if instant - bucket.started_at > timedelta(minutes=minutes):
        bucket.count, bucket.started_at = 0, instant
    if bucket.count >= maximum:
        db.commit()
        raise HTTPException(429, "Слишком много запросов. Попробуйте позже.", headers={"Retry-After": str(minutes * 60)})
    bucket.count += 1
    db.execute(delete(AppealRateLimit).where(AppealRateLimit.started_at < instant - timedelta(days=1)))
    db.commit()


@public_router.post("/capture-sessions", status_code=201)
def create_capture_session(request: Request):
    check_public_request(request)
    with control_session() as db:
        public_available(db)
        rate_limit(db, request, "capture", 20, 10)
        instant, token = now(), secrets.token_urlsafe(32)
        expires = instant + timedelta(minutes=30)
        db.execute(delete(AppealCaptureSession).where(AppealCaptureSession.expires_at < instant - timedelta(days=1)))
        db.add(AppealCaptureSession(token_hash=sha256(token.encode()).hexdigest(), issued_at=instant, expires_at=expires))
        db.commit()
    return {"token": token, "server_time": instant.isoformat(), "expires_at": expires.isoformat(),
            "timezone": base_settings().app_timezone,
            "max_photos": MAX_PHOTOS, "max_photo_bytes": MAX_PHOTO_BYTES}


def capture_session(token, request):
    if not token or len(token) > 100:
        raise HTTPException(422, "Откройте форму обращения и начните отправку")
    with control_session() as db:
        public_available(db)
        rate_limit(db, request, "submit", 20, 60)
        session = db.get(AppealCaptureSession, sha256(token.encode()).hexdigest())
        if session is None or session.expires_at < now() - (timedelta(days=1) if session.appeal_id else timedelta()):
            raise HTTPException(409, "Время отправки истекло. Повторите отправку; анкета и фотографии сохранены.")
        return session


@public_router.post("/capture-sessions/resume")
def resume_capture_session(request: Request):
    """Resync a restored mobile draft; never expose questionnaire or photo data."""
    check_public_request(request)
    token = request.headers.get("x-capture-token", "")
    if not token or len(token) > 100:
        raise HTTPException(422, "Сессия отправки не найдена")
    with control_session() as db:
        public_available(db)
        rate_limit(db, request, "resume", 120, 60)
        session = db.get(AppealCaptureSession, sha256(token.encode()).hexdigest(), with_for_update=True)
        instant = now()
        if session is None or session.expires_at < instant - timedelta(days=1):
            raise HTTPException(409, "Сессия отправки истекла. Повторите отправку; анкета и фотографии сохранены.")
        return {"token": token, "server_time": instant.isoformat(), "expires_at": session.expires_at.isoformat(),
                "timezone": base_settings().app_timezone, "expired": session.expires_at <= instant,
                "submitted": receipt(session.appeal_id) if session.appeal_id else None}


def receipt(id):
    return {"number": f"ОБ-{id:06d}", "message": "Обращение передано администраторам выбранной организации"}


@public_router.post("", status_code=201)
async def submit_appeal(request: Request):
    # Old tabs can recover an existing receipt, but cannot bypass address/map validation.
    from app.appeal_workflow import gallery_submission
    return await gallery_submission(request)


def appeal_dict(appeal):
    return {"id": appeal.id, "number": receipt(appeal.id)["number"],
            **{key: getattr(appeal, key) for key in ("city", "address", "place", "category", "description",
                "organization_id", "organization_name", "work_type_name",
                "organization_hint", "contact", "photo_count", "status", "owner_note", "version",
                "created_at", "updated_at", "latitude", "longitude", "is_public", "public_response", "resolved_at",
                "submitted_by_inspector_id", "submitted_by_inspector_name", "archived_at")}}


def photo_dict(photo):
    url = private_url(f"/{photo.appeal_id}/photos/{photo.id}")
    return {"id": photo.id, "preview_url": url + "?variant=preview", "url": url,
            "original_url": url + "?variant=original", **{key: getattr(photo, key) for key in (
                "captured_at", "latitude", "longitude", "accuracy", "width", "height")}}


@owner_router.get("")
@organization_router.get("")
def list_appeals(user: AppealReader, status: AppealStatus | None = None, page: int = Query(default=1, ge=1), archived: bool = False):
    with control_session() as db:
        conditions = appeal_conditions(user) + ([CitizenAppeal.status == status] if status else [])
        conditions.append(CitizenAppeal.archived_at.is_not(None) if archived else CitizenAppeal.archived_at.is_(None))
        total = db.scalar(select(func.count()).select_from(CitizenAppeal).where(*conditions))
        rows = db.execute(select(CitizenAppeal, AppealPhoto.id).outerjoin(AppealPhoto,
            (AppealPhoto.appeal_id == CitizenAppeal.id) & (AppealPhoto.position == 0)).where(*conditions)
            .order_by(CitizenAppeal.created_at.desc(), CitizenAppeal.id.desc()).offset((page - 1) * 20).limit(20))
        return {"items": [{**private_appeal_dict(appeal, user), "preview_url":
            private_url(f"/{appeal.id}/photos/{photo_id}?variant=preview")} for appeal, photo_id in rows],
            "total": total, "page": page, "page_size": 20, "categories": CATEGORIES,
            "public_url": base_settings().public_appeals_origin.rstrip("/") or "/appeals",
            "can_manage": user.role == "ADMIN_OPERATOR", "can_execute": user.role == "OPERATOR"}


@organization_router.get("/notifications")
def appeal_notifications(user: AppealReader):
    with control_session() as db:
        conditions = appeal_conditions(user)
        conditions.append(CitizenAppeal.archived_at.is_(None))
        statuses = ("ASSIGNED", "IN_PROGRESS") if user.role == "OPERATOR" else ("NEW", "COMPLETED", "REJECTED", "CANCELLED")
        count = db.scalar(select(func.count()).select_from(CitizenAppeal).where(
            *conditions, CitizenAppeal.status.in_(statuses)))
        latest = db.scalar(select(func.max(CitizenAppeal.id)).where(*conditions)) or 0
        return {"new_count": count, "latest_id": latest}


@owner_router.get("/{appeal_id}")
@organization_router.get("/{appeal_id}")
def appeal_detail(appeal_id: int, user: AppealReader):
    with control_session() as db:
        from app.appeal_workflow import workflow_detail
        appeal = find_appeal(db, appeal_id, user=user)
        return {**private_appeal_dict(appeal, user), **workflow_detail(db, appeal, private_url, private=True,
                    operator_id=user.id if user.role == "OPERATOR" else None),
                "can_manage": user.role == "ADMIN_OPERATOR", "can_execute": user.role == "OPERATOR",
                "photos": [photo_dict(photo) for photo in db.scalars(
            select(AppealPhoto).where(AppealPhoto.appeal_id == appeal.id).order_by(AppealPhoto.position))]}


@owner_router.patch("/{appeal_id}")
@organization_router.patch("/{appeal_id}")
def edit_appeal(appeal_id: int, body: OwnerEdit, user: AppealReader):
    if user.role != "ADMIN_OPERATOR":
        raise HTTPException(403, "Изменять обращение может администратор")
    with control_session() as db:
        appeal = find_appeal(db, appeal_id, lock=True)
        if (appeal.is_public or appeal.submitted_by_inspector_id) and body.status not in {"NEW", "IN_REVIEW", "SPAM"} and body.status != appeal.status:
            raise HTTPException(422, "Назначьте исполнителя или используйте закрытие с публичным ответом")
        if appeal.archived_at:
            raise HTTPException(409, "Сначала верните обращение из архива")
        if appeal.version != body.expected_version:
            raise HTTPException(409, "Обращение изменилось. Обновите карточку перед сохранением.")
        before = {"status": appeal.status, "owner_note": appeal.owner_note}
        appeal.status, appeal.owner_note = body.status, body.owner_note
        from app.appeal_events import record_event
        if before["status"] != appeal.status:
            record_event(db, appeal, "STATUS", user)
        if before["owner_note"] != appeal.owner_note:
            record_event(db, appeal, "NOTE", user, comment=appeal.owner_note, visibility="ADMIN")
        appeal.version += 1
        appeal.updated_at = now()
        organization = current_organization()
        audit(db, None if organization else user.id, "CITIZEN_APPEAL_UPDATED", "citizen_appeal", appeal.id, before,
              {"status": appeal.status, "owner_note": appeal.owner_note, "organization_id": appeal.organization_id,
               "actor_user_id": user.id, "actor_name": user.name,
               "actor_organization_id": organization.id if organization else None})
        db.commit()
        return appeal_dict(appeal)


@owner_router.get("/{appeal_id}/photos/{photo_id}")
@organization_router.get("/{appeal_id}/photos/{photo_id}")
def appeal_photo(appeal_id: int, photo_id: UUID, user: AppealReader,
                 variant: Literal["stamped", "preview", "original"] = "stamped"):
    with control_session() as db:
        find_appeal(db, appeal_id, user=user)
        photo = db.get(AppealPhoto, str(photo_id))
        if not photo or photo.appeal_id != appeal_id:
            raise HTTPException(404, "Фотография не найдена")
        return Response(getattr(photo, variant), media_type="image/jpeg", headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="appeal-{appeal_id}-{photo.position + 1}-{variant}.jpg"'})


def private_appeal_dict(appeal, user):
    result = appeal_dict(appeal)
    if user.role == "OPERATOR":
        for key in ("contact", "organization_hint", "owner_note"):
            result.pop(key, None)
    return result
