import json
import secrets
from datetime import timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from geoalchemy2.shape import from_shape
from shapely.geometry import mapping
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.auth import AdminUser, CurrentUser, Db, hasher, user_dict
from app.auth import router as auth_router
from app.catalog import WORK_TYPES, Role, Status
from app.config import settings
from app.domain import audit, enqueue, now, reassess
from app.intake import ingest
from app.integrations import YandexDisk, safe_url
from app.media import media_path
from app.models import Audit, Chat, District, Job, LoginSession, Photo, User
from app.receiver import connection_status, received
from app.reports import export_excel, filtered, photo_dict, summarize
from app.schemas import (
    ChatInput,
    DistrictInput,
    PhotoEdit,
    PhotoFilters,
    UserCreate,
    UserUpdate,
    validate_polygon,
)

app = FastAPI(
    title="MAX Фото · операторская панель",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.include_router(auth_router)
Filters = Annotated[PhotoFilters, Query()]


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(IntegrityError)
async def integrity_error(_request, _exc):
    return JSONResponse(
        status_code=409,
        content={"detail": "Запись с такими данными уже существует или связана с другими записями"},
    )


@app.get("/api/health")
def health(db: Db):
    db.execute(text("SELECT 1"))
    return {"ok": True}


@app.post("/api/webhooks/max")
async def webhook(request: Request, db: Db):
    expected = settings().max_webhook_secret
    if len(expected) < 32:
        raise HTTPException(503, "Webhook не настроен")
    if not secrets.compare_digest(request.headers.get("x-max-bot-api-secret", ""), expected):
        raise HTTPException(403, "Неверный секрет webhook")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 2_000_000:
            raise HTTPException(413, "Слишком большое событие")
    try:
        update = json.loads(raw)
        if not isinstance(update, dict):
            raise ValueError("object required")
        accepted = ingest(db, update)
        received(db, 1, int(accepted is not None))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "Некорректное событие MAX") from exc
    db.commit()
    return {"ok": True}


@app.get("/api/max/status")
def max_status(db: Db, user: AdminUser):
    return connection_status(db)


@app.get("/api/meta")
def meta(db: Db, user: CurrentUser):
    return {
        "work_types": [{"code": k, "name": v[0]} for k, v in WORK_TYPES.items()],
        "statuses": list(Status),
        "timezone": settings().app_timezone,
        "yandex_maps_api_key": settings().yandex_maps_api_key,
        "today": now().astimezone(ZoneInfo(settings().app_timezone)).date(),
        "chats": [
            {"id": c.id, "max_chat_id": c.max_chat_id, "name": c.name, "active": c.active}
            for c in db.scalars(select(Chat).order_by(Chat.name))
        ],
        "districts": [
            {"id": d.id, "name": d.name, "active": d.active}
            for d in db.scalars(select(District).order_by(District.name))
        ],
        "operators": [{"id": u.id, "name": u.name} for u in db.scalars(select(User).order_by(User.name))],
    }


def dictionaries(db):
    return dict(db.execute(select(District.id, District.name)).all()), dict(
        db.execute(select(User.id, User.name)).all()
    )


@app.get("/api/photos")
def photos(db: Db, user: CurrentUser, filters: Filters):
    stmt = filtered(filters)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Photo.received_at.desc(), Photo.id.desc())
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    )
    districts, operators = dictionaries(db)
    return {
        "items": [photo_dict(p, districts, operators) for p in rows],
        "total": total,
        "page": filters.page,
        "page_size": filters.page_size,
    }


def require_photo(db, photo_id):
    photo = db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(404, "Фотография не найдена")
    return photo


@app.get("/api/photos/{photo_id}")
def get_photo(photo_id: int, db: Db, user: CurrentUser):
    photo = require_photo(db, photo_id)
    districts, operators = dictionaries(db)
    result = photo_dict(photo, districts, operators, detail=True)
    result["history"] = [
        audit_dict(a)
        for a in db.scalars(
            select(Audit).where(Audit.photo_id == photo_id).order_by(Audit.id.desc()).limit(100)
        )
    ]
    return result


@app.get("/api/photos/{photo_id}/preview")
def preview(photo_id: int, db: Db, user: CurrentUser):
    require_photo(db, photo_id)
    path = media_path(photo_id, preview=True)
    if not path.is_file():
        raise HTTPException(404, "Превью пока недоступно")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/photos/{photo_id}/original")
def original(photo_id: int, db: Db, user: CurrentUser):
    photo = require_photo(db, photo_id)
    if not photo.yandex_disk_path:
        raise HTTPException(409, "Загрузка оригинала ещё не завершена")
    response = YandexDisk().request("GET", "/resources/download", params={"path": photo.yandex_disk_path})
    response.raise_for_status()
    url = safe_url(response.json()["href"], ("yandex.net", "yandex.ru", "yandex.com"))
    return RedirectResponse(url, status_code=302)


@app.patch("/api/photos/{photo_id}")
def edit_photo(photo_id: int, body: PhotoEdit, db: Db, user: CurrentUser):
    db.execute(text("SELECT pg_advisory_xact_lock(7002, :id)"), {"id": photo_id})
    photo = require_photo(db, photo_id)
    if not photo.analyzed_at or photo.status in {Status.REJECTED, Status.DUPLICATE, Status.FORWARDED}:
        raise HTTPException(409, "Эту фотографию пока нельзя редактировать")
    if photo.version != body.version:
        raise HTTPException(409, "Фото изменено другим оператором. Обновите карточку.")
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    before = {key: getattr(photo, key) for key in changes}
    before.update(district_id=photo.district_id, status=photo.status, work_type_source=photo.work_type_source)
    for key, value in changes.items():
        setattr(photo, key, value)
    if "work_type" in changes:
        photo.work_type_source = "OPERATOR" if photo.work_type else None
    photo.reviewed_by, photo.reviewed_at = user.id, now()
    reassess(db, photo)
    photo.version += 1
    photo.storage_status = "PENDING"
    after = {key: getattr(photo, key) for key in before}
    audit(db, user.id, "PHOTO_REVIEWED", "photo", photo.id, before, after)
    enqueue(db, "SYNC", photo.id, f"sync:{photo.id}:{photo.version}")
    db.commit()
    return {
        "id": photo.id,
        "status": photo.status,
        "version": photo.version,
        "review_reason": photo.review_reason,
        "storage_status": photo.storage_status,
    }


@app.post("/api/photos/{photo_id}/retry")
def retry_photo(photo_id: int, db: Db, user: CurrentUser):
    photo = require_photo(db, photo_id)
    kind, object_id = ("SYNC", photo.id) if photo.analyzed_at else ("BATCH", photo.inbox_id)
    if photo.status in {Status.REJECTED, Status.DUPLICATE, Status.FORWARDED}:
        raise HTTPException(409, "Повторная обработка не требуется")
    enqueue(db, kind, object_id, f"retry:{photo.id}:{secrets.token_hex(8)}")
    audit(db, user.id, "PHOTO_RETRY", "photo", photo.id, None, {"kind": kind})
    db.commit()
    return {"ok": True}


@app.get("/api/reports")
def reports(db: Db, user: CurrentUser, filters: Filters):
    return summarize(db, filters)


@app.get("/api/export.xlsx")
def excel(db: Db, user: CurrentUser, filters: Filters):
    # One snapshot keeps detailed rows and the summary sheets consistent during concurrent review.
    db.commit()
    db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    data = export_excel(db, filters)
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="max-photos.xlsx"'},
    )


@app.get("/api/chats")
def chats(db: Db, user: AdminUser):
    return [
        {
            "id": c.id,
            "max_chat_id": c.max_chat_id,
            "name": c.name,
            "active": c.active,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in db.scalars(select(Chat).order_by(Chat.name))
    ]


@app.post("/api/chats", status_code=201)
def create_chat(body: ChatInput, db: Db, user: AdminUser):
    chat = Chat(**body.model_dump())
    db.add(chat)
    db.flush()
    audit(db, user.id, "CHAT_CREATED", "chat", chat.id, None, body.model_dump())
    db.commit()
    return {"id": chat.id}


@app.put("/api/chats/{chat_id}")
def edit_chat(chat_id: int, body: ChatInput, db: Db, user: AdminUser):
    chat = db.get(Chat, chat_id)
    if not chat:
        raise HTTPException(404, "Чат не найден")
    if chat.max_chat_id != body.max_chat_id:
        raise HTTPException(422, "Для другого MAX chat ID создайте новый чат")
    old = {"name": chat.name, "active": chat.active}
    chat.name, chat.active = body.name, body.active
    audit(db, user.id, "CHAT_UPDATED", "chat", chat.id, old, body.model_dump())
    db.commit()
    return {"ok": True}


@app.get("/api/districts")
def districts(db: Db, user: CurrentUser):
    rows = db.execute(
        select(District.id, District.name, District.active, func.ST_AsGeoJSON(District.geometry))
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": did,
                "properties": {"id": did, "name": name, "active": active},
                "geometry": json.loads(geo),
            }
            for did, name, active, geo in rows
        ],
    }


def save_district(db, user, body, district=None):
    # Prevent concurrent boundary writes bypassing the overlap check.
    db.execute(text("SELECT pg_advisory_xact_lock(7003, 1)"))
    try:
        polygon = validate_polygon(body.geometry)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    geometry = from_shape(polygon, srid=4326)
    stmt = select(District.id, District.name).where(
        District.active,
        func.ST_Intersects(District.geometry, geometry),
        func.ST_Area(func.ST_Intersection(District.geometry, geometry)) > 0,
    )
    if district:
        stmt = stmt.where(District.id != district.id)
    overlaps = [{"id": did, "name": name} for did, name in db.execute(stmt)] if body.active else []
    if overlaps and not body.confirm_overlap:
        raise HTTPException(
            409, {"message": "Границы пересекаются. Подтвердите сохранение.", "overlaps": overlaps}
        )
    old = None
    if district:
        old = {
            "name": district.name,
            "active": district.active,
            "geometry": json.loads(
                db.scalar(select(func.ST_AsGeoJSON(District.geometry)).where(District.id == district.id))
            ),
        }
    else:
        district = District()
        db.add(district)
    district.name, district.active, district.geometry = body.name, body.active, geometry
    db.flush()
    audit(
        db,
        user.id,
        "DISTRICT_UPDATED" if old else "DISTRICT_CREATED",
        "district",
        district.id,
        old,
        {
            "name": body.name,
            "active": body.active,
            "geometry": mapping(polygon),
            "overlaps_confirmed": bool(overlaps),
        },
    )
    enqueue(db, "REGEO", district.id, f"regeo:{secrets.token_hex(12)}")
    db.commit()
    return {"id": district.id, "overlaps": overlaps}


@app.post("/api/districts", status_code=201)
def create_district(body: DistrictInput, db: Db, user: AdminUser):
    return save_district(db, user, body)


@app.put("/api/districts/{district_id}")
def edit_district(district_id: int, body: DistrictInput, db: Db, user: AdminUser):
    district = db.get(District, district_id)
    if not district:
        raise HTTPException(404, "Микрорайон не найден")
    return save_district(db, user, body, district)


@app.get("/api/users")
def users(db: Db, user: AdminUser):
    return [user_dict(u) for u in db.scalars(select(User).order_by(User.id))]


@app.post("/api/users", status_code=201)
def create_user(body: UserCreate, db: Db, user: AdminUser):
    record = User(
        login=body.login.lower(),
        name=body.name,
        password_hash=hasher.hash(body.password),
        role=body.role,
        active=body.active,
    )
    db.add(record)
    db.flush()
    audit(db, user.id, "USER_CREATED", "user", record.id, None, user_dict(record))
    db.commit()
    return user_dict(record)


@app.patch("/api/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, db: Db, user: AdminUser):
    db.execute(text("SELECT pg_advisory_xact_lock(7004, 1)"))
    record = db.get(User, user_id)
    if not record:
        raise HTTPException(404, "Пользователь не найден")
    old = user_dict(record)
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in updates.items():
        if key == "password":
            record.password_hash = hasher.hash(value)
        else:
            setattr(record, key, value)
    db.flush()
    if not db.scalar(
        select(func.count()).select_from(User).where(User.role == Role.ADMIN_OPERATOR, User.active)
    ):
        raise HTTPException(409, "Нельзя заблокировать или понизить последнего администратора")
    if any(key in updates for key in ("password", "active", "role")):
        db.execute(delete(LoginSession).where(LoginSession.user_id == record.id))
    audit(
        db,
        user.id,
        "USER_UPDATED",
        "user",
        record.id,
        old,
        {**user_dict(record), "password_changed": "password" in updates},
    )
    db.commit()
    return user_dict(record)


def audit_dict(a):
    return {
        "id": a.id,
        "user_id": a.user_id,
        "at": a.at,
        "action": a.action,
        "object_type": a.object_type,
        "object_id": a.object_id,
        "photo_id": a.photo_id,
        "old_value": a.old_value,
        "new_value": a.new_value,
    }


@app.get("/api/audit")
def audits(db: Db, user: AdminUser, page: int = Query(1, ge=1)):
    rows = db.scalars(select(Audit).order_by(Audit.id.desc()).offset((page - 1) * 100).limit(100))
    return {"items": [audit_dict(a) for a in rows], "page": page}


@app.get("/api/jobs")
def jobs(db: Db, user: AdminUser):
    return [
        {
            "id": j.id,
            "kind": j.kind,
            "object_id": j.object_id,
            "status": j.status,
            "attempts": j.attempts,
            "last_error": j.last_error,
            "next_run_at": j.next_run_at,
        }
        for j in db.scalars(select(Job).where(Job.status != "DONE").order_by(Job.next_run_at).limit(200))
    ]


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Db, user: AdminUser):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    if job.status == "PENDING":
        job.next_run_at = now() - timedelta(seconds=1)
        audit(db, user.id, "JOB_RETRY", "job", job.id, None, {"kind": job.kind})
    db.commit()
    return {"ok": True}


@app.get("/api/ml")
def ml_status(db: Db, user: AdminUser):
    from app.ml import training_status

    return training_status(db)


@app.post("/api/ml/train")
def ml_train(db: Db, user: AdminUser):
    from app.ml import collect_examples, training_plan

    db.execute(text("SELECT pg_advisory_xact_lock(7006, 1)"))
    if db.scalar(select(Job.id).where(Job.kind == "TRAIN", Job.status != "DONE").limit(1)):
        raise HTTPException(409, "Обучение уже в очереди или выполняется")
    examples, _ = collect_examples(db)
    plan = training_plan(examples)
    if not plan["ready"]:
        raise HTTPException(409, "; ".join(plan["reasons"]))
    enqueue(db, "TRAIN", 1, "train:manual:" + secrets.token_hex(16))
    audit(db, user.id, "MODEL_TRAINING_REQUESTED", "model", 0, None, {"sample_count": plan["sample_count"]})
    db.commit()
    return {"ok": True}
