"""Owner-only organization administration. Company administrators cannot enter here."""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, Db
from app.config import base_settings
from app.db import database_engine
from app.domain import audit
from app.models import (
    Chat,
    DiscoveredChat,
    ExchangeState,
    ModelVersion,
    Organization,
    OrganizationChat,
    OrganizationEvent,
    Photo,
    PlatformOwner,
    User,
    WorkType,
)
from app.organization_context import current_organization, organization_scope
from app.organization_registry import control_session, provision, scope_for
from app.schemas import StrictModel

router = APIRouter(prefix="/api/platform", tags=["organizations"])


def owner_only(user: CurrentUser, db: Db):
    if not base_settings().organizations_enabled or current_organization() or not db.get(PlatformOwner, user.id):
        raise HTTPException(403, "Доступно только владельцу сервиса")
    return user


Owner = Annotated[User, Depends(owner_only)]


class OrganizationInput(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    city: str = Field(min_length=2, max_length=150)
    # Older browser versions may still send this field; new forms only need a name.
    slug: str | None = Field(default=None, min_length=2, max_length=60, pattern=r"^[a-z0-9][a-z0-9-]+$")
    disk_account_id: UUID | None = None


class OrganizationUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=150)
    city: str | None = Field(default=None, min_length=2, max_length=150)
    status: Literal["ACTIVE", "PAUSED"]
    disk_account_id: UUID | None = None


class ChatBinding(StrictModel):
    max_chat_id: int = Field(ge=-(2**63), lt=2**63)
    name: str = Field(min_length=1, max_length=150)


def organization_dict(record, *, stats=False):
    result = {key: getattr(record, key) for key in ("id", "name", "city", "slug", "status", "last_error", "legacy", "disk_account_id")}
    result["url"] = f"/org/{record.id}/"
    result["stats"] = None
    if stats and record.status in {"ACTIVE", "PAUSED"}:
        try:
            scope = scope_for(record)
            with Session(database_engine(scope.database_url)) as tenant:
                result["stats"] = {
                    "intake_cohort": (tenant.get(ExchangeState, 1).intake_cohort
                                      if tenant.get(ExchangeState, 1) else "test"),
                    "photos": tenant.scalar(select(func.count()).select_from(Photo)),
                    "operators": tenant.scalar(select(func.count()).select_from(User).where(
                        User.id != record.owner_user_id)),
                    "chats": tenant.scalar(select(func.count()).select_from(Chat)),
                    "work_types": tenant.scalar(select(func.count()).select_from(WorkType)),
                    "model_ready": bool(tenant.scalar(select(ModelVersion.id).where(ModelVersion.status == "ACTIVE"))),
                }
        except Exception:
            # Neither database credentials nor a failed company connection may escape this boundary.
            result["unavailable"] = True
    return result


@router.get("/status")
def status():
    return {"enabled": base_settings().organizations_enabled}


@router.get("/organizations")
def organizations(db: Db, user: Owner):
    return [organization_dict(record, stats=True) for record in db.scalars(
        select(Organization).order_by(Organization.created_at, Organization.id)
    )]


@router.post("/organizations", status_code=201)
def create_organization(body: OrganizationInput, db: Db, user: Owner):
    from app.disk_accounts import validate_selection
    disk_id = validate_selection(db, None, body.disk_account_id)
    if body.slug and db.scalar(select(Organization.id).where(Organization.slug == body.slug)):
        raise HTTPException(409, "Такое короткое имя уже занято")
    id = uuid4()
    record = Organization(id=str(id), name=body.name, city=body.city, slug=body.slug or "org-" + id.hex, disk_account_id=disk_id, database_name="org_" + id.hex,
                          database_role="org_" + id.hex, status="PROVISIONING")
    db.add(record)
    audit(db, user.id, "ORGANIZATION_CREATED", "organization", 0, None,
          {"id": record.id, "name": record.name, "city": record.city})
    db.commit()
    try:
        provision(record.id)
    except (ValueError, RuntimeError):
        pass  # The durable record shows ERROR/PROVISIONING and can be retried safely.
    db.refresh(record)
    return organization_dict(record, stats=True)


@router.post("/organizations/{organization_id}/retry")
def retry_organization(organization_id: UUID, db: Db, user: Owner):
    record = db.get(Organization, str(organization_id))
    if not record:
        raise HTTPException(404, "Организация не найдена")
    try:
        provision(record.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError:
        pass
    db.refresh(record)
    return organization_dict(record, stats=True)


@router.patch("/organizations/{organization_id}")
def edit_organization(organization_id: UUID, body: OrganizationUpdate, db: Db, user: Owner):
    record = db.get(Organization, str(organization_id), with_for_update=True)
    if not record:
        raise HTTPException(404, "Организация не найдена")
    if record.status not in {"ACTIVE", "PAUSED"}:
        raise HTTPException(409, "Сначала завершите создание организации")
    before = {"name": record.name, "status": record.status, "city": record.city}
    if "disk_account_id" in body.model_fields_set:
        from app.disk_accounts import validate_selection
        record.disk_account_id = validate_selection(db, record, body.disk_account_id)
    record.name, record.status = body.name, body.status
    if body.city is not None:
        record.city = body.city
    audit(db, user.id, "ORGANIZATION_UPDATED", "organization", 0, before,
          {"id": record.id, "name": record.name, "city": record.city, "status": record.status, "disk_account_id": record.disk_account_id})
    db.commit()
    return organization_dict(record, stats=True)


@router.get("/chats")
def chats(db: Db, user: Owner):
    bindings = {row.max_chat_id: row for row in db.scalars(select(OrganizationChat))}
    discovered = {row.max_chat_id: row for row in db.scalars(select(DiscoveredChat))}
    waiting = dict(db.execute(select(OrganizationEvent.max_chat_id, func.count()).where(
        OrganizationEvent.status != "DELIVERED").group_by(OrganizationEvent.max_chat_id)).all())
    return [{"max_chat_id": str(id), "name": bindings[id].name if id in bindings else None,
             "organization_id": bindings[id].organization_id if id in bindings else None,
             "message_preview": discovered[id].message_preview if id in discovered else None,
             "waiting": waiting.get(id, 0)} for id in sorted(bindings.keys() | discovered.keys() | waiting.keys())]


@router.post("/organizations/{organization_id}/chats", status_code=201)
def bind_chat(organization_id: UUID, body: ChatBinding, db: Db, user: Owner):
    record = db.get(Organization, str(organization_id))
    if not record or record.status not in {"ACTIVE", "PAUSED"}:
        raise HTTPException(409, "Организация ещё не готова")
    # One transaction serializes every claim for the same MAX chat, across API processes.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:chat, 7010))"),
               {"chat": str(body.max_chat_id)})
    binding = db.get(OrganizationChat, body.max_chat_id)
    if binding and binding.organization_id != record.id:
        raise HTTPException(409, "Чат уже закреплён за другой организацией. Перенос с фотографиями требует отдельной процедуры.")
    if not binding:
        binding = OrganizationChat(max_chat_id=body.max_chat_id, organization_id=record.id, name=body.name)
        db.add(binding)
    binding.name = body.name
    audit(db, user.id, "ORGANIZATION_CHAT_BOUND", "organization", 0, None,
          {"id": record.id, "max_chat_id": str(body.max_chat_id)})
    db.commit()
    # Claim first: a crash cannot accidentally make the same chat available to another company.
    scope = scope_for(record)
    with organization_scope(scope), Session(database_engine(scope.database_url)) as tenant:
        chat = tenant.scalar(select(Chat).where(Chat.max_chat_id == body.max_chat_id))
        if chat is None:
            chat = Chat(max_chat_id=body.max_chat_id, name=body.name, active=True)
            tenant.add(chat)
        else:
            chat.name = body.name
        tenant.commit()
    return {"ok": True}


def require_chat_binding(max_chat_id):
    organization = current_organization()
    with control_session() as db:
        binding = db.get(OrganizationChat, max_chat_id)
        if not binding or binding.organization_id != organization.id:
            raise HTTPException(409, "Сначала закрепите этот чат за организацией в кабинете владельца")
