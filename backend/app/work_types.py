"""Persistent company catalog. Never seed or overwrite it during application startup."""

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import func, select, text

from app.auth import AdminUser, CurrentUser, Db
from app.domain import audit
from app.models import WorkType
from app.schemas import StrictModel

router = APIRouter(prefix="/api/work-types", tags=["work-types"])


def catalog_rows(db, *, model_order=False):
    order = (WorkType.model_index,) if model_order else (WorkType.sort_order, WorkType.model_index)
    return list(db.scalars(select(WorkType).order_by(*order)))


def work_catalog(db):
    return {row.code: (row.name, row.filename_label) for row in catalog_rows(db)}


def require_work_type(db, code):
    if code is not None and not db.scalar(select(WorkType.id).where(WorkType.code == code)):
        raise HTTPException(422, "Вид работы отсутствует в справочнике")


def work_dict(row):
    return {key: getattr(row, key) for key in ("id", "code", "name", "description", "sort_order", "version")}


def set_position(db, row, position):
    rows = [other for other in catalog_rows(db) if other.id != row.id]
    rows.insert(min(position - 1, len(rows)), row)
    for index, other in enumerate(rows, 1):
        if other.sort_order != index:
            other.sort_order = index
            if other.id != row.id:
                other.version += 1


class WorkTypeInput(StrictModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$")
    sort_order: int = Field(ge=1, le=1000000)
    description: str = Field(default="", max_length=2000, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$")

    @field_validator("description")
    @classmethod
    def trim_description(cls, value):
        return value.strip()


class WorkTypeEdit(WorkTypeInput):
    version: int = Field(ge=1)


@router.get("")
def list_work_types(db: Db, user: CurrentUser):
    return [work_dict(row) for row in catalog_rows(db)]


@router.post("", status_code=201)
def create_work_type(body: WorkTypeInput, db: Db, user: AdminUser):
    # Serialize class-index allocation. Display order and names never define model indices.
    db.execute(text("SELECT pg_advisory_xact_lock(7009, 1)"))
    index = db.scalar(select(func.max(WorkType.model_index)))
    row = WorkType(code="CUSTOM_" + uuid4().hex.upper(), name=body.name,
                   description=body.description,
                   filename_label=body.name, sort_order=body.sort_order,
                   model_index=0 if index is None else index + 1)
    db.add(row)
    db.flush()
    set_position(db, row, body.sort_order)
    audit(db, user.id, "WORK_TYPE_CREATED", "work_type", row.id, None, work_dict(row))
    db.commit()
    return work_dict(row)


@router.put("/{work_id}")
def edit_work_type(work_id: int, body: WorkTypeEdit, db: Db, user: AdminUser):
    db.execute(text("SELECT pg_advisory_xact_lock(7009, 1)"))
    row = db.scalar(select(WorkType).where(WorkType.id == work_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Вид работы не найден")
    if row.version != body.version:
        raise HTTPException(409, "Справочник изменён другим администратором. Обновите список.")
    before = work_dict(row)
    row.name = body.name
    # Older clients can still edit names/order without erasing existing descriptions.
    if "description" in body.model_fields_set:
        row.description = body.description
    set_position(db, row, body.sort_order)
    row.version += 1
    audit(db, user.id, "WORK_TYPE_UPDATED", "work_type", row.id, before, work_dict(row))
    db.commit()
    return work_dict(row)
