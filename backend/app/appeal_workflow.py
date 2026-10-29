"""Public map intake and wall; private organization assignments and evidence."""

from datetime import timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from geoalchemy2.shape import from_shape
from pydantic import Field, ValidationError, field_validator
from shapely.geometry import Point
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.appeal_catalog import organization_catalog, territory_choice_id, validate_recipient
from app.appeal_events import CommentInput, add_comment, event_page, record_event
from app.appeal_images import MAX_PHOTO_BYTES, MAX_PHOTOS, prepare_upload
from app.appeal_search import appeal_search
from app.appeals import (
    AppealReader,
    capture_session,
    check_public_request,
    create_capture_session,
    find_appeal,
    organization_router,
    owner_router,
    public_available,
    public_router,
    rate_limit,
    receipt,
)
from app.db import database_engine
from app.domain import audit, now
from app.models import (
    AppealAddress,
    AppealAttachment,
    AppealCaptureSession,
    AppealPhoto,
    AppealTask,
    CitizenAppeal,
    District,
    Organization,
    User,
)
from app.organization_context import current_organization
from app.organization_registry import control_session, scope_for
from app.schemas import StrictModel


class AppealFields(StrictModel):
    organization_id: UUID
    city: str = Field(min_length=2, max_length=150)
    address_id: UUID
    address: str = Field(min_length=1, max_length=300)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    place: str = Field(default="", max_length=300)
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=4000)
    contact: str = Field(default="", max_length=200)
    website: str = Field(default="", max_length=0)

    @field_validator("description")
    @classmethod
    def nonempty_description(cls, value):
        if not value.strip():
            raise ValueError("Опишите проблему")
        return value.strip()


class GalleryInput(AppealFields):
    category: str = Field(default="", max_length=60)
    capture_source: Literal["gallery"]
    public_consent: Literal[True] = True


class InspectorAppealInput(AppealFields):
    client_id: UUID
    contact: str = Field(default="", max_length=0)


class AddressInput(StrictModel):
    label: str = Field(min_length=2, max_length=300)
    district_id: int = Field(gt=0)


class AssignmentInput(StrictModel):
    operator_id: int = Field(gt=0)
    instruction: str = Field(default="", max_length=4000)
    expected_version: int = Field(ge=1)


class ResultInput(StrictModel):
    status: Literal["COMPLETED", "REJECTED", "CANCELLED"]
    comment: str = Field(min_length=1, max_length=4000)
    expected_version: int = Field(ge=1)


class CloseInput(StrictModel):
    status: Literal["RESOLVED", "DECLINED"] = "RESOLVED"
    comment: str = Field(min_length=1, max_length=4000)
    operator_photo_ids: list[UUID] = Field(default_factory=list, max_length=MAX_PHOTOS)
    expected_version: int = Field(ge=1)


class TaskStatusInput(StrictModel):
    status: Literal["ASSIGNED", "IN_PROGRESS"]
    expected_version: int = Field(ge=1)


class ArchiveInput(StrictModel):
    archived: bool
    expected_version: int = Field(ge=1)


def manager(user):
    if user.role != "ADMIN_OPERATOR":
        raise HTTPException(403, "Действие доступно администратору организации")


def versioned(appeal, version):
    if appeal.version != version:
        raise HTTPException(409, "Обращение изменилось. Обновите карточку.")


def changed(db, appeal, user, action):
    appeal.version += 1
    appeal.updated_at = now()
    audit(db, None, action, "citizen_appeal", appeal.id, None,
          {"organization_id": appeal.organization_id, "actor_user_id": user.id,
           "actor_name": user.name, "status": appeal.status, "version": appeal.version})


def tenant_scope(db, organization_id):
    record = db.get(Organization, organization_id)
    if not record or record.status != "ACTIVE":
        raise HTTPException(409, "Организация недоступна")
    return scope_for(record)


def latest_task(db, appeal_id):
    return db.scalar(select(AppealTask).where(AppealTask.appeal_id == appeal_id).order_by(AppealTask.id.desc()).limit(1))


def workflow_detail(db, appeal, url, *, private, operator_id=None):
    tasks = list(db.scalars(select(AppealTask).where(AppealTask.appeal_id == appeal.id).order_by(AppealTask.id.desc())))
    attachments = list(db.scalars(select(AppealAttachment).where(AppealAttachment.appeal_id == appeal.id)
                                  .order_by(AppealAttachment.created_at, AppealAttachment.id)))
    def task_dict(task):
        result = {key: getattr(task, key) for key in (
            "id", "operator_id", "operator_name", "status", "result_comment", "created_at", "updated_at")}
        if private:
            result["instruction"] = task.instruction
        result["photos"] = [{"id": photo.id, "url": url(f"/{appeal.id}/attachments/{photo.id}"),
                              "preview_url": url(f"/{appeal.id}/attachments/{photo.id}?variant=preview")}
                             for photo in attachments if photo.task_id == task.id]
        return result
    return {"task": task_dict(tasks[0]) if tasks else None,
            "task_history": [task_dict(task) for task in tasks if operator_id is None or task.operator_id == operator_id] if private else [],
            "response_photos": [{"id": photo.id, "url": url(f"/{appeal.id}/attachments/{photo.id}"),
                                  "preview_url": url(f"/{appeal.id}/attachments/{photo.id}?variant=preview")}
                                 for photo in attachments if photo.published]}


@organization_router.get("/workflow/settings")
def settings(user: AppealReader):
    manager(user)
    scope = current_organization()
    if not scope:
        raise HTTPException(404)
    with control_session() as db:
        catalog = organization_catalog(db.get(Organization, scope.id))
        return {"addresses": [{"id": row.id, "label": row.label, "district_id": row.district_id}
                              for row in db.scalars(select(AppealAddress).where(
                                  AppealAddress.organization_id == scope.id, AppealAddress.active)
                                  .order_by(AppealAddress.label))], "territories": catalog["territories"]}


@organization_router.post("/workflow/addresses", status_code=201)
def add_address(body: AddressInput, user: AppealReader):
    manager(user)
    scope = current_organization()
    if not scope:
        raise HTTPException(404)
    with Session(database_engine(scope.database_url)) as tenant:
        if not tenant.scalar(select(District.id).where(District.id == body.district_id, District.active)):
            raise HTTPException(422, "Выберите действующую территорию этой организации")
    with control_session() as db:
        label = " ".join(body.label.split())
        if len(label) < 2:
            raise HTTPException(422, "Укажите улицу и адрес")
        # Serialize duplicate submissions as well as writes from two administrator tabs.
        db.get(Organization, scope.id, with_for_update=True)
        existing = db.scalar(select(AppealAddress).where(AppealAddress.organization_id == scope.id,
                                                       AppealAddress.label == label))
        if existing:
            existing.district_id, existing.active = body.district_id, True
            row = existing
        else:
            row = AppealAddress(id=str(uuid4()), organization_id=scope.id, label=label, district_id=body.district_id)
            db.add(row)
        audit(db, None, "APPEAL_ADDRESS_CONFIGURED", "organization", 0, None,
              {"organization_id": scope.id, "address": label, "district_id": body.district_id, "actor_user_id": user.id})
        db.commit()
        return {"id": row.id, "label": row.label, "district_id": row.district_id}


@organization_router.delete("/workflow/addresses/{address_id}")
def remove_address(address_id: UUID, user: AppealReader):
    manager(user)
    scope = current_organization()
    with control_session() as db:
        row = db.get(AppealAddress, str(address_id), with_for_update=True)
        if not scope or not row or row.organization_id != scope.id:
            raise HTTPException(404)
        row.active = False
        db.commit()
    return {"ok": True}


@public_router.post("/sessions", status_code=201)
def submission_session(request: Request):
    result = create_capture_session(request)
    with control_session() as db:
        row = db.get(AppealCaptureSession, sha256(result["token"].encode()).hexdigest())
        row.expires_at = now() + timedelta(days=1)
        result["expires_at"] = row.expires_at.isoformat()
        db.commit()
    return result


def create_appeal(db, body, photos, *, is_public, inspector=None):
    organization, work = validate_recipient(db, body, require_work_type=inspector is not None)
    scope = scope_for(organization)
    with Session(database_engine(scope.database_url)) as tenant:
        selected = next(((id, name) for id, name in tenant.execute(select(District.id, District.name)
                         .where(District.active)) if territory_choice_id(organization.id, id) == str(body.address_id)), None)
        if selected:
            district_id, label = selected
        else:
            # Already saved drafts from the earlier address-book form can still finish.
            # New forms require no duplicate address records or configuration.
            legacy = db.get(AppealAddress, str(body.address_id), with_for_update=True)
            if not legacy or not legacy.active or legacy.organization_id != organization.id:
                raise HTTPException(422, "Выберите территорию этой организации из списка")
            district_id, label = legacy.district_id, legacy.label
        if body.address != label:
            raise HTTPException(422, "Список территорий изменился. Выберите территорию ещё раз")
        point = from_shape(Point(body.longitude, body.latitude), srid=4326)
        covered = tenant.scalar(select(District.id).where(District.id == district_id, District.active,
                                                          func.ST_Covers(District.geometry, point)))
        if not covered:
            raise HTTPException(422, "Отметьте проблему внутри выбранной территории организации")
    appeal = CitizenAppeal(organization_id=organization.id, organization_name=organization.name,
        work_type_name=work["name"] if work else "", city=organization.city, address_id=str(body.address_id), address=label,
        place=body.place, category=body.category, description=body.description, contact=body.contact,
        latitude=body.latitude, longitude=body.longitude, is_public=is_public,
        photo_count=len(photos), status="NEW", owner_note="", version=1,
        submitted_by_inspector_id=inspector.id if inspector else None,
        submitted_by_inspector_name=inspector.name if inspector else "",
        inspector_submission_id=str(body.client_id) if inspector else None)
    db.add(appeal)
    db.flush()
    record_event(db, appeal, "CREATED", inspector, inspector=bool(inspector))
    for index, prepared in enumerate(photos):
        db.add(AppealPhoto(id=str(uuid4()), appeal_id=appeal.id, position=index, captured_at=now(), position_at=now(),
                          latitude=body.latitude, longitude=body.longitude, accuracy=0, **prepared))
    return appeal


def save_gallery(token, body, photos):
    with control_session() as db:
        session = db.get(AppealCaptureSession, sha256(token.encode()).hexdigest(), with_for_update=True)
        if not session or (session.expires_at < now() and not session.appeal_id):
            raise HTTPException(409, "Время отправки истекло. Повторите отправку, фотографии сохранены.")
        if session.appeal_id:
            return receipt(session.appeal_id)
        appeal = create_appeal(db, body, photos, is_public=True)
        session.appeal_id = appeal.id
        db.commit()
        return receipt(appeal.id)


async def multipart(request, schema, *, require_photos=True):
    async with request.form(max_files=MAX_PHOTOS, max_fields=1, max_part_size=32 * 1024) as form:
        metadata, files = form.get("metadata"), form.getlist("photos")
        if not isinstance(metadata, str) or set(form) - {"metadata", "photos"} or (require_photos and not files):
            raise HTTPException(422, "Заполните форму и приложите фотографии")
        try:
            body = schema.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(422, "Проверьте адрес, точку на карте, описание и фотографии") from exc
        photos = []
        for file in files:
            if not isinstance(file, UploadFile):
                raise HTTPException(422, "Выберите фотографию")
            content = await file.read(MAX_PHOTO_BYTES + 1)
            photos.append(await run_in_threadpool(prepare_upload, content))
    return body, photos


@public_router.post("/submissions", status_code=201)
async def gallery_submission(request: Request):
    check_public_request(request)
    token = request.headers.get("x-capture-token", "")
    session = await run_in_threadpool(capture_session, token, request)
    if session.appeal_id:
        return receipt(session.appeal_id)
    body, photos = await multipart(request, GalleryInput)
    return await run_in_threadpool(save_gallery, token, body, photos)


def public_conditions(city=None, organization_id=None):
    conditions = [CitizenAppeal.is_public, CitizenAppeal.submitted_by_inspector_id.is_(None), CitizenAppeal.status != "SPAM",
                  CitizenAppeal.organization_id.in_(select(Organization.id).where(Organization.status == "ACTIVE"))]
    if city:
        conditions.append(CitizenAppeal.city == city)
    if organization_id:
        conditions.append(CitizenAppeal.organization_id == str(organization_id))
    return conditions


def wall_dict(db, appeal):
    from app.appeal_sharing import appeal_url

    # Explicit allowlist: never publish contact, internal notes, identities or task instructions.
    result = {key: getattr(appeal, key) for key in (
        "id", "organization_id", "organization_name", "city", "address", "place", "category",
        "description", "work_type_name", "status", "latitude", "longitude", "created_at", "updated_at")}
    result["number"] = receipt(appeal.id)["number"]
    result["share_url"] = appeal_url(appeal.id)
    result["photos"] = [{"id": photo.id, "url": f"/api/public/appeals/wall/{appeal.id}/photos/{photo.id}",
                         "preview_url": f"/api/public/appeals/wall/{appeal.id}/photos/{photo.id}?variant=preview"}
                        for photo in db.scalars(select(AppealPhoto).where(AppealPhoto.appeal_id == appeal.id)
                                                .order_by(AppealPhoto.position))]
    result["response"] = None
    if appeal.status in {"RESOLVED", "DECLINED"}:
        result["response"] = {"comment": appeal.public_response, "at": appeal.resolved_at,
            "photos": [{"id": photo.id, "url": f"/api/public/appeals/wall/{appeal.id}/results/{photo.id}",
                        "preview_url": f"/api/public/appeals/wall/{appeal.id}/results/{photo.id}?variant=preview"}
                       for photo in db.scalars(select(AppealAttachment).where(
                           AppealAttachment.appeal_id == appeal.id, AppealAttachment.published))]}
    return result


@public_router.get("/wall")
def wall(request: Request, city: str = Query(min_length=2, max_length=150), organization_id: UUID | None = None,
         page: int = Query(default=1, ge=1), sort: Literal["newest", "oldest", "organization"] = "newest",
         q: str = Query(default="", max_length=200)):
    with control_session() as db:
        public_available(db)
        rate_limit(db, request, "wall", 120, 1)
        conditions = public_conditions(city, organization_id)
        conditions.extend(appeal_search(q))
        order = [CitizenAppeal.id.desc()] if sort == "newest" else [CitizenAppeal.id] if sort == "oldest" else [CitizenAppeal.organization_name, CitizenAppeal.id.desc()]
        return {"total": db.scalar(select(func.count()).select_from(CitizenAppeal).where(*conditions)),
                "page": page, "page_size": 20, "items": [wall_dict(db, row) for row in db.scalars(
                    select(CitizenAppeal).where(*conditions).order_by(*order).offset((page - 1) * 20).limit(20))]}


def public_appeal(db, appeal_id):
    appeal = db.scalar(select(CitizenAppeal).where(CitizenAppeal.id == appeal_id, *public_conditions()))
    if not appeal:
        raise HTTPException(404, "Обращение недоступно")
    return appeal


@public_router.get("/wall/{appeal_id}")
def wall_detail(appeal_id: int):
    with control_session() as db:
        public_available(db)
        return wall_dict(db, public_appeal(db, appeal_id))


def image_response(content):
    return Response(content, media_type="image/jpeg", headers={"Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff", "Content-Disposition": 'inline; filename="photo.jpg"'})


@public_router.get("/wall/{appeal_id}/photos/{photo_id}")
def wall_photo(appeal_id: int, photo_id: UUID, variant: Literal["original", "preview"] = "original"):
    with control_session() as db:
        public_available(db)
        public_appeal(db, appeal_id)
        photo = db.get(AppealPhoto, str(photo_id))
        if not photo or photo.appeal_id != appeal_id:
            raise HTTPException(404)
        return image_response(getattr(photo, variant))


@public_router.get("/wall/{appeal_id}/results/{photo_id}")
def wall_result(appeal_id: int, photo_id: UUID, variant: Literal["content", "preview"] = "content"):
    with control_session() as db:
        public_available(db)
        appeal = public_appeal(db, appeal_id)
        photo = db.get(AppealAttachment, str(photo_id))
        if appeal.status not in {"RESOLVED", "DECLINED"} or not photo or photo.appeal_id != appeal_id or not photo.published:
            raise HTTPException(404)
        return image_response(getattr(photo, variant))


@owner_router.get("/{appeal_id}/operators")
@organization_router.get("/{appeal_id}/operators")
def operators(appeal_id: int, user: AppealReader):
    manager(user)
    with control_session() as db:
        appeal = find_appeal(db, appeal_id, user=user)
        scope = tenant_scope(db, appeal.organization_id)
        with Session(database_engine(scope.database_url)) as tenant:
            return [{"id": row.id, "name": row.name} for row in tenant.scalars(select(User).where(
                User.active, User.role == "OPERATOR").order_by(User.name, User.id))]


@owner_router.post("/{appeal_id}/assign")
@organization_router.post("/{appeal_id}/assign")
def assign(appeal_id: int, body: AssignmentInput, user: AppealReader):
    manager(user)
    with control_session() as db:
        appeal = find_appeal(db, appeal_id, lock=True, user=user)
        versioned(appeal, body.expected_version)
        if appeal.status in {"RESOLVED", "DECLINED", "SPAM"}:
            raise HTTPException(409, "Сначала верните обращение на рассмотрение")
        scope = tenant_scope(db, appeal.organization_id)
        with Session(database_engine(scope.database_url)) as tenant:
            operator = tenant.get(User, body.operator_id)
            if not operator or not operator.active or operator.role != "OPERATOR":
                raise HTTPException(422, "Выберите действующего оператора этой организации")
            db.add(AppealTask(appeal_id=appeal.id, operator_id=operator.id, operator_name=operator.name,
                             instruction=body.instruction, status="ASSIGNED", result_comment=""))
        appeal.status = "ASSIGNED"
        record_event(db, appeal, "ASSIGNED", user, comment="Исполнитель: " + operator.name)
        if body.instruction.strip():
            record_event(db, appeal, "INSTRUCTION", user, comment=body.instruction.strip(),
                         visibility="TASK", operator_id=operator.id)
        changed(db, appeal, user, "APPEAL_ASSIGNED")
        db.commit()
        return {"ok": True, "version": appeal.version}


@organization_router.post("/{appeal_id}/start")
def start_task(appeal_id: int, user: AppealReader, expected_version: int = Query(ge=1)):
    with control_session() as db:
        appeal = find_appeal(db, appeal_id, lock=True, user=user)
        task = latest_task(db, appeal.id)
        versioned(appeal, expected_version)
        if user.role != "OPERATOR" or not task or task.operator_id != user.id or appeal.status != "ASSIGNED":
            raise HTTPException(409, "Задача недоступна для начала работы")
        task.status = appeal.status = "IN_PROGRESS"
        record_event(db, appeal, "STATUS", user)
        changed(db, appeal, user, "APPEAL_TASK_STARTED")
        db.commit()
    return {"ok": True}


@organization_router.post("/{appeal_id}/task-status")
def task_status(appeal_id: int, body: TaskStatusInput, user: AppealReader):
    with control_session() as db:
        appeal = find_appeal(db, appeal_id, lock=True, user=user)
        versioned(appeal, body.expected_version)
        task = latest_task(db, appeal.id)
        if (user.role != "OPERATOR" or not task or task.operator_id != user.id
                or appeal.archived_at or appeal.status not in {"ASSIGNED", "IN_PROGRESS"}):
            raise HTTPException(409, "Статус этой задачи изменить нельзя")
        if appeal.status != body.status:
            task.status = appeal.status = body.status
            record_event(db, appeal, "STATUS", user)
            changed(db, appeal, user, "APPEAL_TASK_STATUS")
        db.commit()
    return {"ok": True}


def save_result(appeal_id, body, photos, user):
    with control_session() as db:
        appeal = find_appeal(db, appeal_id, lock=True, user=user)
        versioned(appeal, body.expected_version)
        task = latest_task(db, appeal.id)
        if user.role != "OPERATOR" or not task or task.operator_id != user.id or appeal.status not in {"ASSIGNED", "IN_PROGRESS"}:
            raise HTTPException(409, "Задача недоступна для отчёта")
        if not body.comment.strip():
            raise HTTPException(422, "Напишите комментарий к результату")
        task.status = appeal.status = body.status
        task.result_comment = body.comment.strip()
        record_event(db, appeal, "RESULT", user, comment=task.result_comment)
        for photo in photos:
            db.add(AppealAttachment(id=str(uuid4()), appeal_id=appeal.id, task_id=task.id,
                content=photo["original"], preview=photo["preview"], width=photo["width"], height=photo["height"], published=False))
        changed(db, appeal, user, "APPEAL_TASK_REPORTED")
        db.commit()
    return {"ok": True}


@organization_router.post("/{appeal_id}/result")
async def report_result(appeal_id: int, request: Request, user: AppealReader):
    # Authorization before decoding photos; repeated after taking the row lock.
    with control_session() as db:
        find_appeal(db, appeal_id, user=user)
    body, photos = await multipart(request, ResultInput)
    return await run_in_threadpool(save_result, appeal_id, body, photos, user)


def save_close(appeal_id, body, photos, user):
    manager(user)
    with control_session() as db:
        appeal = find_appeal(db, appeal_id, lock=True, user=user)
        versioned(appeal, body.expected_version)
        task = latest_task(db, appeal.id)
        if appeal.status in {"RESOLVED", "DECLINED", "SPAM"}:
            raise HTTPException(409, "Обращение уже закрыто или находится в спаме")
        if body.status != "DECLINED" and task and task.status not in {"COMPLETED", "REJECTED", "CANCELLED"}:
            raise HTTPException(409, "Сначала дождитесь результата исполнителя")
        if not body.comment.strip():
            raise HTTPException(422, "Напишите публичный ответ жителю")
        selected = set(map(str, body.operator_photo_ids))
        allowed = set(db.scalars(select(AppealAttachment.id).where(AppealAttachment.appeal_id == appeal.id,
                         AppealAttachment.task_id == task.id))) if task and task.status in {"COMPLETED", "REJECTED", "CANCELLED"} else set()
        if not selected <= allowed or len(selected) + len(photos) > MAX_PHOTOS:
            raise HTTPException(422, "Выберите до трёх фотографий текущего результата исполнителя или своих")
        db.execute(update(AppealAttachment).where(AppealAttachment.appeal_id == appeal.id).values(published=False))
        if selected:
            db.execute(update(AppealAttachment).where(AppealAttachment.id.in_(selected)).values(published=True))
        for photo in photos:
            db.add(AppealAttachment(id=str(uuid4()), appeal_id=appeal.id, content=photo["original"],
                preview=photo["preview"], width=photo["width"], height=photo["height"], published=True))
        if body.status == "DECLINED" and task and task.status in {"ASSIGNED", "IN_PROGRESS"}:
            task.status = "CANCELLED"
        appeal.status, appeal.public_response, appeal.resolved_at = body.status, body.comment.strip(), now()
        record_event(db, appeal, "CLOSED", user, comment=appeal.public_response)
        changed(db, appeal, user, "APPEAL_CLOSED")
        db.commit()
    return {"ok": True}


@owner_router.post("/{appeal_id}/close")
@organization_router.post("/{appeal_id}/close")
async def close_appeal(appeal_id: int, request: Request, user: AppealReader):
    manager(user)
    with control_session() as db:
        find_appeal(db, appeal_id, user=user)
    body, photos = await multipart(request, CloseInput, require_photos=False)
    return await run_in_threadpool(save_close, appeal_id, body, photos, user)


@owner_router.post("/{appeal_id}/archive")
@organization_router.post("/{appeal_id}/archive")
def archive_appeal(appeal_id: int, body: ArchiveInput, user: AppealReader):
    manager(user)
    with control_session() as db:
        appeal = find_appeal(db, appeal_id, lock=True, user=user)
        versioned(appeal, body.expected_version)
        if appeal.status not in {"RESOLVED", "DECLINED", "SPAM"}:
            raise HTTPException(409, "В архив можно перенести закрытое обращение или спам")
        if bool(appeal.archived_at) != body.archived:
            appeal.archived_at = now() if body.archived else None
            record_event(db, appeal, "ARCHIVED" if body.archived else "RESTORED", user)
            changed(db, appeal, user, "APPEAL_ARCHIVE_CHANGED")
        db.commit()
    return {"ok": True}


@owner_router.get("/{appeal_id}/events")
@organization_router.get("/{appeal_id}/events")
def events(appeal_id: int, user: AppealReader, before: int = Query(default=0, ge=0), after: int = Query(default=0, ge=0)):
    with control_session() as db:
        return event_page(db, find_appeal(db, appeal_id, user=user), user=user, before=before, after=after)


@owner_router.post("/{appeal_id}/comments", status_code=201)
@organization_router.post("/{appeal_id}/comments", status_code=201)
def comment(appeal_id: int, body: CommentInput, user: AppealReader):
    with control_session() as db:
        return add_comment(db, find_appeal(db, appeal_id, lock=True, user=user), body, user)


@owner_router.get("/{appeal_id}/attachments/{photo_id}")
@organization_router.get("/{appeal_id}/attachments/{photo_id}")
def attachment(appeal_id: int, photo_id: UUID, user: AppealReader, variant: Literal["content", "preview"] = "content"):
    with control_session() as db:
        find_appeal(db, appeal_id, user=user)
        photo = db.get(AppealAttachment, str(photo_id))
        if not photo or photo.appeal_id != appeal_id:
            raise HTTPException(404)
        return image_response(getattr(photo, variant))
