"""Anonymous camera intake; private reads are exclusively for the platform owner."""

import secrets
from datetime import timedelta
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import AwareDatetime, Field, ValidationError, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from starlette.datastructures import UploadFile

from app.appeal_images import MAX_PHOTO_BYTES, MAX_PHOTOS, prepare_photo
from app.auth import CurrentUser, is_platform_owner
from app.config import base_settings
from app.domain import audit, now
from app.models import AppealCaptureSession, AppealPhoto, AppealRateLimit, CitizenAppeal, PlatformOwner
from app.organization_context import current_organization
from app.organization_registry import control_session
from app.schemas import StrictModel

public_router = APIRouter(prefix="/api/public/appeals", tags=["citizen appeals"])
owner_router = APIRouter(prefix="/api/platform/appeals", tags=["owner appeals"])
CATEGORIES = {
    "waste": "Мусор и урны", "cleaning": "Уборка территории", "landscaping": "Деревья и озеленение",
    "roads": "Дороги и тротуары", "lighting": "Освещение", "playgrounds": "Детские и спортивные площадки",
    "building": "Дом и подъезд", "other": "Другая проблема",
}
AppealStatus = Literal["NEW", "IN_REVIEW", "RESOLVED", "SPAM"]


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


class AppealInput(StrictModel):
    capture_source: Literal["camera"]
    city: str = Field(min_length=2, max_length=150)
    address: str = Field(min_length=5, max_length=300)
    place: str = Field(min_length=2, max_length=300)
    category: Literal["waste", "cleaning", "landscaping", "roads", "lighting", "playgrounds", "building", "other"]
    description: str = Field(min_length=10, max_length=4000)
    organization_hint: str = Field(default="", max_length=200)
    contact: str = Field(default="", max_length=200)
    website: str = Field(default="", max_length=0)
    captures: list[Capture] = Field(min_length=1, max_length=MAX_PHOTOS)


class OwnerEdit(StrictModel):
    status: AppealStatus
    owner_note: str = Field(max_length=4000)
    expected_version: int = Field(ge=1)


def require_owner(user: CurrentUser):
    if current_organization() is not None or not is_platform_owner(user):
        raise HTTPException(403, "Обращения граждан доступны только владельцу сервиса")
    return user


Owner = Annotated[object, Depends(require_owner)]


def check_public_request(request):
    origins = {base_settings().app_origin.rstrip("/"), base_settings().public_appeals_origin.rstrip("/")}
    if request.headers.get("origin", "") not in origins - {""} or request.headers.get("x-appeal-request") != "camera":
        raise HTTPException(403, "Откройте страницу обращений и разрешите доступ к камере")


def public_available(db):
    if not base_settings().organizations_enabled or db.scalar(select(PlatformOwner.user_id).limit(1)) is None:
        raise HTTPException(503, "Приём обращений пока не настроен. Попробуйте позже.")


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
            "timezone": base_settings().app_timezone, "categories": CATEGORIES,
            "max_photos": MAX_PHOTOS, "max_photo_bytes": MAX_PHOTO_BYTES}


def capture_session(token, request):
    if not token or len(token) > 100:
        raise HTTPException(422, "Сначала сделайте снимок через встроенную камеру")
    with control_session() as db:
        public_available(db)
        rate_limit(db, request, "submit", 20, 60)
        session = db.get(AppealCaptureSession, sha256(token.encode()).hexdigest())
        if session is None or session.expires_at < now() - (timedelta(days=1) if session.appeal_id else timedelta()):
            raise HTTPException(409, "Время съёмки истекло. Откройте камеру и сделайте снимки ещё раз.")
        return session


@public_router.post("/capture-sessions/resume")
def resume_capture_session(request: Request):
    """Resync a restored mobile draft; never expose questionnaire or photo data."""
    check_public_request(request)
    token = request.headers.get("x-capture-token", "")
    if not token or len(token) > 100:
        raise HTTPException(422, "Сессия съёмки не найдена")
    with control_session() as db:
        public_available(db)
        rate_limit(db, request, "resume", 120, 60)
        session = db.get(AppealCaptureSession, sha256(token.encode()).hexdigest(), with_for_update=True)
        instant = now()
        if session is None or session.expires_at < instant - timedelta(days=1):
            raise HTTPException(409, "Сессия съёмки истекла. Сделайте снимки заново; анкета сохранена.")
        return {"token": token, "server_time": instant.isoformat(), "expires_at": session.expires_at.isoformat(),
                "timezone": base_settings().app_timezone, "expired": session.expires_at <= instant,
                "submitted": receipt(session.appeal_id) if session.appeal_id else None}


def check_capture_times(body, session):
    instant = now()
    for capture in body.captures:
        if not session.issued_at - timedelta(seconds=2) <= capture.captured_at <= min(
            session.expires_at, instant + timedelta(seconds=5)
        ):
            raise HTTPException(422, "Снимки должны быть сделаны в текущем обращении. Откройте камеру ещё раз.")


def save_submission(token, body, photos):
    with control_session() as db:
        session = db.scalar(select(AppealCaptureSession).where(
            AppealCaptureSession.token_hash == sha256(token.encode()).hexdigest()).with_for_update())
        if not session or (session.expires_at < now() and not session.appeal_id):
            raise HTTPException(409, "Время съёмки истекло. Сделайте снимки ещё раз.")
        if session.appeal_id:
            return receipt(session.appeal_id)
        check_capture_times(body, session)
        appeal = CitizenAppeal(**body.model_dump(exclude={"captures", "capture_source", "website"}),
                              photo_count=len(photos), status="NEW", owner_note="", version=1)
        db.add(appeal)
        db.flush()
        for position, (capture, prepared) in enumerate(zip(body.captures, photos, strict=True)):
            db.add(AppealPhoto(id=str(uuid4()), appeal_id=appeal.id, position=position,
                               **capture.model_dump(), **prepared))
        session.appeal_id = appeal.id
        db.commit()
        return receipt(appeal.id)


def receipt(id):
    return {"number": f"ОБ-{id:06d}", "message": "Обращение получено владельцем сервиса"}


@public_router.post("", status_code=201)
async def submit_appeal(request: Request):
    check_public_request(request)
    token = request.headers.get("x-capture-token", "")
    session = await run_in_threadpool(capture_session, token, request)
    if session.appeal_id:
        return receipt(session.appeal_id)
    async with request.form(max_files=MAX_PHOTOS, max_fields=1, max_part_size=32 * 1024) as form:
        metadata, files = form.get("metadata"), form.getlist("photos")
        if not isinstance(metadata, str) or not 1 <= len(files) <= MAX_PHOTOS or set(form) != {"metadata", "photos"}:
            raise HTTPException(422, "Заполните анкету и сделайте хотя бы один снимок через камеру")
        try:
            body = AppealInput.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(422, "Проверьте анкету, координаты и время съёмки. Фото и свежая геопозиция обязательны.") from exc
        if len(files) != len(body.captures):
            raise HTTPException(422, "У каждого снимка должны быть собственные данные съёмки")
        check_capture_times(body, session)
        photos = []
        for file, capture in zip(files, body.captures, strict=True):
            if not isinstance(file, UploadFile):
                raise HTTPException(422, "Сделайте снимки через встроенную камеру")
            content = await file.read(MAX_PHOTO_BYTES + 1)
            photos.append(await run_in_threadpool(prepare_photo, content, capture, base_settings().app_timezone))
    return await run_in_threadpool(save_submission, token, body, photos)


def appeal_dict(appeal):
    return {"id": appeal.id, "number": receipt(appeal.id)["number"],
            **{key: getattr(appeal, key) for key in ("city", "address", "place", "category", "description",
                "organization_hint", "contact", "photo_count", "status", "owner_note", "version",
                "created_at", "updated_at")}}


def photo_dict(photo):
    url = f"/api/platform/appeals/{photo.appeal_id}/photos/{photo.id}"
    return {"id": photo.id, "preview_url": url + "?variant=preview", "url": url,
            "original_url": url + "?variant=original", **{key: getattr(photo, key) for key in (
                "captured_at", "latitude", "longitude", "accuracy", "width", "height")}}


@owner_router.get("")
def list_appeals(user: Owner, status: AppealStatus | None = None, page: int = Query(default=1, ge=1)):
    with control_session() as db:
        conditions = [CitizenAppeal.status == status] if status else []
        total = db.scalar(select(func.count()).select_from(CitizenAppeal).where(*conditions))
        rows = db.execute(select(CitizenAppeal, AppealPhoto.id).outerjoin(AppealPhoto,
            (AppealPhoto.appeal_id == CitizenAppeal.id) & (AppealPhoto.position == 0)).where(*conditions)
            .order_by(CitizenAppeal.created_at.desc(), CitizenAppeal.id.desc()).offset((page - 1) * 20).limit(20))
        return {"items": [{**appeal_dict(appeal), "preview_url":
            f"/api/platform/appeals/{appeal.id}/photos/{photo_id}?variant=preview"} for appeal, photo_id in rows],
            "total": total, "page": page, "page_size": 20, "categories": CATEGORIES,
            "public_url": base_settings().public_appeals_origin.rstrip("/") or "/appeals"}


@owner_router.get("/{appeal_id}")
def appeal_detail(appeal_id: int, user: Owner):
    with control_session() as db:
        appeal = db.get(CitizenAppeal, appeal_id)
        if not appeal:
            raise HTTPException(404, "Обращение не найдено")
        return {**appeal_dict(appeal), "photos": [photo_dict(photo) for photo in db.scalars(
            select(AppealPhoto).where(AppealPhoto.appeal_id == appeal.id).order_by(AppealPhoto.position))]}


@owner_router.patch("/{appeal_id}")
def edit_appeal(appeal_id: int, body: OwnerEdit, user: Owner):
    with control_session() as db:
        appeal = db.get(CitizenAppeal, appeal_id, with_for_update=True)
        if not appeal:
            raise HTTPException(404, "Обращение не найдено")
        if appeal.version != body.expected_version:
            raise HTTPException(409, "Обращение изменилось. Обновите карточку перед сохранением.")
        before = {"status": appeal.status, "owner_note": appeal.owner_note}
        appeal.status, appeal.owner_note = body.status, body.owner_note
        appeal.version += 1
        appeal.updated_at = now()
        audit(db, user.id, "CITIZEN_APPEAL_UPDATED", "citizen_appeal", appeal.id, before,
              {"status": appeal.status, "owner_note": appeal.owner_note})
        db.commit()
        return appeal_dict(appeal)


@owner_router.get("/{appeal_id}/photos/{photo_id}")
def appeal_photo(appeal_id: int, photo_id: UUID, user: Owner,
                 variant: Literal["stamped", "preview", "original"] = "stamped"):
    with control_session() as db:
        photo = db.get(AppealPhoto, str(photo_id))
        if not photo or photo.appeal_id != appeal_id:
            raise HTTPException(404, "Фотография не найдена")
        return Response(getattr(photo, variant), media_type="image/jpeg", headers={
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="appeal-{appeal_id}-{photo.position + 1}-{variant}.jpg"'})
