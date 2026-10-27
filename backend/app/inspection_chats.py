"""Private inspection conversations, with current recipient and photo access checked on every request."""

from hashlib import sha256
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import Field, model_validator
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.auth import AdminUser, Db
from app.db import database_engine
from app.domain import now
from app.inspection_auth import InspectorUser
from app.inspections import admin_router, owner_router, require_visible_photo, router
from app.media import media_path
from app.models import (
    InspectionAgency,
    InspectionGrant,
    InspectionMessage,
    Inspector,
    Organization,
    PlatformOwner,
    User,
)
from app.organization_context import current_organization, organization_scope, workspace_url
from app.organization_registry import control_session, scope_for
from app.organizations import Owner
from app.schemas import StrictModel


class MessageInput(StrictModel):
    body: str = Field(default="", max_length=4000)
    client_id: UUID
    photo_organization_id: UUID | None = None
    photo_id: int | None = Field(default=None, gt=0)
    forward_message_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def content(self):
        self.body = self.body.strip()
        if (self.photo_id is None) != (self.photo_organization_id is None):
            raise ValueError("Укажите фотографию и её организацию")
        if self.forward_message_id and (self.body or self.photo_id):
            raise ValueError("Пересылаемое сообщение нельзя изменять")
        if not (self.body or self.photo_id or self.forward_message_id):
            raise ValueError("Напишите сообщение или выберите фотографию")
        return self


class ReadInput(StrictModel):
    through_id: int = Field(gt=0)


def pair(actor, peer):
    return or_(and_(InspectionMessage.sender_key == actor, InspectionMessage.recipient_key == peer),
               and_(InspectionMessage.sender_key == peer, InspectionMessage.recipient_key == actor))


def contact(key, name, kind, organization, avatar, base="/api/inspection"):
    return {"key": key, "name": name, "kind": kind, "organization_name": organization,
            "avatar_url": base + "/contact-avatar?" + urlencode({"peer": key, "v": sha256(avatar).hexdigest()[:16]})
            if avatar else None}


def inspector_contacts(db, account):
    contacts = [contact(f"o:{owner.id}", owner.name, "Владелец сервиса", None, owner.avatar_image)
                for owner in db.scalars(select(User).join(PlatformOwner, PlatformOwner.user_id == User.id)
                                        .where(User.active).order_by(User.name))]
    contacts += [contact(f"i:{a.id}", a.name, "Проверяющий", None, a.avatar_image)
                 for a in db.scalars(select(Inspector).where(Inspector.agency_id == account.agency_id,
                                     Inspector.id != account.id, Inspector.active).order_by(Inspector.name))]
    orgs = db.scalars(select(Organization).join(InspectionGrant, InspectionGrant.organization_id == Organization.id)
                     .where(InspectionGrant.inspector_id == account.id, Organization.status == "ACTIVE"))
    for org in orgs:
        scope = scope_for(org)
        with Session(database_engine(scope.database_url)) as tenant:
            for admin in tenant.scalars(select(User).where(User.active, User.role == "ADMIN_OPERATOR",
                                                         User.id != scope.owner_user_id).order_by(User.name)):
                contacts.append(contact(f"a:{org.id}:{admin.id}", admin.name,
                                        "Администратор организации", org.name, admin.avatar_image))
    return contacts


def admin_identity(user):
    org = current_organization()
    if not org:
        raise HTTPException(404)
    return f"a:{org.id}:{user.id}", org.id


def admin_contacts(db, org_id):
    return [contact(f"i:{account.id}", account.name, "Проверяющий", agency.name, account.avatar_image,
                    workspace_url("/api/inspection-admin"))
            for account, agency in db.execute(select(Inspector, InspectionAgency).join(InspectionAgency)
                .join(InspectionGrant, InspectionGrant.inspector_id == Inspector.id)
                .join(Organization, Organization.id == InspectionGrant.organization_id)
                .where(InspectionGrant.organization_id == org_id, Organization.status == "ACTIVE",
                       Inspector.active, InspectionAgency.active).order_by(Inspector.name))]


def owner_contacts(db):
    return [contact(f"i:{account.id}", account.name, "Проверяющий", agency.name, account.avatar_image,
                    "/api/platform/inspection/chat")
            for account, agency in db.execute(select(Inspector, InspectionAgency).join(InspectionAgency)
                .where(Inspector.active, InspectionAgency.active).order_by(InspectionAgency.name, Inspector.name))]


def validate_peer(contacts, peer):
    if not any(c["key"] == peer for c in contacts):
        raise HTTPException(404, "Собеседник недоступен")


def can_view_photo(db, actor, org_id, photo_id, cache=None):
    key = (actor, org_id, photo_id)
    if cache is not None and key in cache:
        return cache[key]
    org = db.get(Organization, org_id)
    allowed = bool(org and org.status == "ACTIVE")
    parts = actor.split(":")
    if allowed and parts[0] == "i":
        account = db.get(Inspector, int(parts[1]))
        agency = db.get(InspectionAgency, account.agency_id) if account else None
        allowed = bool(account and account.active and agency and agency.active and db.get(InspectionGrant, (account.id, org_id)))
    elif allowed and parts[0] == "o":
        account = db.get(User, int(parts[1]))
        allowed = bool(account and account.active and db.get(PlatformOwner, account.id))
    elif allowed and parts[0] == "a":
        allowed = parts[1] == org_id
        if allowed:
            scope = scope_for(org)
            with Session(database_engine(scope.database_url)) as tenant:
                account = tenant.get(User, int(parts[2]))
                allowed = bool(account and account.active and account.role == "ADMIN_OPERATOR" and account.id != scope.owner_user_id)
    else:
        allowed = False
    if allowed:
        scope = scope_for(org)
        with organization_scope(scope), Session(database_engine(scope.database_url)) as tenant:
            tenant.execute(text("SET TRANSACTION READ ONLY"))
            try:
                require_visible_photo(tenant, photo_id)
            except HTTPException:
                allowed = False
    if cache is not None:
        cache[key] = allowed
    return allowed


def source_message(db, actor, contacts, message_id):
    source = db.get(InspectionMessage, message_id)
    if not source or actor not in (source.sender_key, source.recipient_key):
        raise HTTPException(404, "Сообщение недоступно")
    validate_peer(contacts, source.recipient_key if source.sender_key == actor else source.sender_key)
    return source


def eligible_contacts(db, actor, contacts, org_id=None, photo_id=None, forward_id=None):
    if forward_id:
        if photo_id is not None or org_id is not None:
            raise HTTPException(422, "Выберите сообщение или фотографию")
        source = source_message(db, actor, contacts, forward_id)
        org_id, photo_id = source.photo_organization_id, source.photo_id
    if (org_id is None) != (photo_id is None):
        raise HTTPException(422, "Укажите фотографию и её организацию")
    if photo_id is not None:
        org_id = str(org_id)
        cache = {}
        if not can_view_photo(db, actor, org_id, photo_id, cache):
            raise HTTPException(404, "Фотография недоступна")
        contacts = [c for c in contacts if can_view_photo(db, c["key"], org_id, photo_id, cache)]
    return contacts


def message_dict(message, actor, db, base="/api/inspection", cache=None, viewer=None):
    result = {"id": message.id, "body": message.body, "created_at": message.created_at,
              "outgoing": message.sender_key == actor, "read_at": message.read_at, "client_id": message.client_id,
              "forwarded": message.forwarded_from_id is not None, "photo": None}
    if message.photo_id is not None:
        available = can_view_photo(db, viewer or actor, message.photo_organization_id, message.photo_id, cache)
        photo = {"id": message.photo_id, "available": available, "organization_id": None,
                 "organization_name": None, "preview_url": None, "detail_url": None}
        if available:
            org = db.get(Organization, message.photo_organization_id)
            other = message.recipient_key if message.sender_key == actor else message.sender_key
            photo.update(organization_id=org.id, organization_name=org.name,
                         preview_url=f"{base}/messages/{message.id}/photo",
                         detail_url=f"/inspection/photos/{message.photo_id}?" + urlencode({
                             "org": org.id, "tab": "messages", "with": other, "inspection_chat": other})
                         if (viewer or actor).startswith("i:") else f"/org/{org.id}/photos/{message.photo_id}")
        result["photo"] = photo
    return result


def contact_previews(db, actor, contacts):
    for item in contacts:
        peer = item["key"]
        latest = db.scalar(select(InspectionMessage).where(pair(actor, peer)).order_by(InspectionMessage.id.desc()).limit(1))
        item["last_message"] = ((f"Фото #{latest.photo_id}" + (" · " if latest.body else "") if latest.photo_id else "") + latest.body)[:140] if latest else None
        item["last_message_at"] = latest.created_at if latest else None
        item["last_message_outgoing"] = latest.sender_key == actor if latest else False
        item["unread"] = db.scalar(select(func.count()).select_from(InspectionMessage).where(
            InspectionMessage.sender_key == peer, InspectionMessage.recipient_key == actor, InspectionMessage.read_at.is_(None)))
    return sorted(contacts, key=lambda c: (c["last_message_at"] is not None,
                  c["last_message_at"].timestamp() if c["last_message_at"] else 0), reverse=True)


def messages(db, actor, peer, before_id, after_id=None, base="/api/inspection"):
    if before_id and after_id is not None:
        raise HTTPException(422, "Выберите одно направление загрузки истории")
    condition = [pair(actor, peer)]
    if before_id:
        condition.append(InspectionMessage.id < before_id)
    if after_id is not None:
        condition.append(InspectionMessage.id > after_id)
    order = InspectionMessage.id.asc() if after_id is not None else InspectionMessage.id.desc()
    rows = list(db.scalars(select(InspectionMessage).where(*condition).order_by(order).limit(51)))
    more, rows = len(rows) > 50, rows[:50]
    read_through = db.scalar(select(func.max(InspectionMessage.id)).where(
        InspectionMessage.sender_key == actor, InspectionMessage.recipient_key == peer,
        InspectionMessage.read_at.is_not(None))) or 0
    cache = {}
    return {"items": [message_dict(m, actor, db, base, cache) for m in (rows if after_id is not None else reversed(rows))],
            "next_before_id": rows[-1].id if more and after_id is None else None,
            "has_newer": bool(after_id is not None and more), "peer_read_through_id": read_through}


def contact_avatar(db, peer):
    parts = peer.split(":")  # The key has already been validated against current contacts.
    if parts[0] == "i":
        image = db.get(Inspector, int(parts[1])).avatar_image
    elif parts[0] == "o":
        image = db.get(User, int(parts[1])).avatar_image
    else:
        organization = db.get(Organization, parts[1])
        with Session(database_engine(scope_for(organization).database_url)) as tenant:
            image = tenant.get(User, int(parts[2])).avatar_image
    if not image:
        raise HTTPException(404, "Аватарка не установлена")
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


def send(db, actor, peer, body, contacts, base="/api/inspection"):
    validate_peer(contacts, peer)
    content, org_id, photo_id = body.body, str(body.photo_organization_id) if body.photo_organization_id else None, body.photo_id
    if body.forward_message_id:
        source = source_message(db, actor, contacts, body.forward_message_id)
        content, org_id, photo_id = source.body, source.photo_organization_id, source.photo_id
    if photo_id is not None and not all(can_view_photo(db, key, org_id, photo_id) for key in (actor, peer)):
        raise HTTPException(404, "Фотография недоступна отправителю или получателю")
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:actor, 7011))"), {"actor": actor})
    existing = db.scalar(select(InspectionMessage).where(InspectionMessage.sender_key == actor,
                                                        InspectionMessage.client_id == str(body.client_id)))
    if existing:
        if (existing.recipient_key, existing.body, existing.photo_organization_id, existing.photo_id, existing.forwarded_from_id) != (peer, content, org_id, photo_id, body.forward_message_id):
            raise HTTPException(409, "Идентификатор сообщения уже использован")
        return message_dict(existing, actor, db, base)
    message = InspectionMessage(sender_key=actor, recipient_key=peer, client_id=str(body.client_id), body=content,
                                photo_organization_id=org_id, photo_id=photo_id, forwarded_from_id=body.forward_message_id)
    db.add(message)
    db.commit()
    return message_dict(message, actor, db, base)


def mark_read(db, actor, peer, through):
    db.execute(update(InspectionMessage).where(InspectionMessage.sender_key == peer,
        InspectionMessage.recipient_key == actor, InspectionMessage.id <= through, InspectionMessage.read_at.is_(None))
        .values(read_at=now()))
    db.commit()
    return {"ok": True}


def unread_count(db, actor, contacts):
    return {"unread": db.scalar(select(func.count()).select_from(InspectionMessage).where(
        InspectionMessage.recipient_key == actor, InspectionMessage.sender_key.in_([c["key"] for c in contacts]),
        InspectionMessage.read_at.is_(None)))}


def message_photo(db, actor, contacts, message_id, owner=False):
    message = db.get(InspectionMessage, message_id)
    if not message or not message.photo_id:
        raise HTTPException(404, "Фотография недоступна")
    if not owner:
        source_message(db, actor, contacts, message_id)
    if not can_view_photo(db, actor, message.photo_organization_id, message.photo_id):
        raise HTTPException(404, "Фотография недоступна")
    scope = scope_for(db.get(Organization, message.photo_organization_id))
    with organization_scope(scope):
        path = media_path(message.photo_id, True)
        if not path.is_file():
            raise HTTPException(404, "Превью временно недоступно")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.get("/contacts")
def contacts(db: Db, user: InspectorUser, photo_organization_id: UUID | None = None,
             photo_id: Annotated[int | None, Query(gt=0)] = None,
             forward_message_id: Annotated[int | None, Query(gt=0)] = None):
    actor = f"i:{user.id}"
    return contact_previews(db, actor, eligible_contacts(db, actor, inspector_contacts(db, user), photo_organization_id, photo_id, forward_message_id))


@router.get("/contact-avatar")
def inspector_contact_avatar(db: Db, user: InspectorUser, peer: str = Query(max_length=100)):
    validate_peer(inspector_contacts(db, user), peer)
    return contact_avatar(db, peer)


@router.get("/unread")
def inspector_unread(db: Db, user: InspectorUser):
    return unread_count(db, f"i:{user.id}", inspector_contacts(db, user))


@router.get("/messages")
def get_messages(db: Db, user: InspectorUser, peer: str = Query(max_length=100),
                 before_id: Annotated[int | None, Query(gt=0)] = None,
                 after_id: Annotated[int | None, Query(ge=0)] = None):
    validate_peer(inspector_contacts(db, user), peer)
    return messages(db, f"i:{user.id}", peer, before_id, after_id)


@router.post("/messages", status_code=201)
def post_message(body: MessageInput, db: Db, user: InspectorUser, peer: str = Query(max_length=100)):
    return send(db, f"i:{user.id}", peer, body, inspector_contacts(db, user))


@router.post("/messages/read")
def read_messages(body: ReadInput, db: Db, user: InspectorUser, peer: str = Query(max_length=100)):
    validate_peer(inspector_contacts(db, user), peer)
    return mark_read(db, f"i:{user.id}", peer, body.through_id)


@router.get("/messages/{message_id}/photo")
def inspector_message_photo(message_id: int, db: Db, user: InspectorUser):
    return message_photo(db, f"i:{user.id}", inspector_contacts(db, user), message_id)


@admin_router.get("/contacts")
def organization_contacts(user: AdminUser, photo_organization_id: UUID | None = None,
                          photo_id: Annotated[int | None, Query(gt=0)] = None,
                          forward_message_id: Annotated[int | None, Query(gt=0)] = None):
    actor, org = admin_identity(user)
    with control_session() as db:
        return contact_previews(db, actor, eligible_contacts(db, actor, admin_contacts(db, org), photo_organization_id, photo_id, forward_message_id))


@admin_router.get("/messages")
def organization_messages(user: AdminUser, peer: str = Query(max_length=100),
                          before_id: Annotated[int | None, Query(gt=0)] = None,
                          after_id: Annotated[int | None, Query(ge=0)] = None):
    actor, org = admin_identity(user)
    with control_session() as db:
        validate_peer(admin_contacts(db, org), peer)
        return messages(db, actor, peer, before_id, after_id, workspace_url("/api/inspection-admin"))


@admin_router.get("/contact-avatar")
def organization_contact_avatar(user: AdminUser, peer: str = Query(max_length=100)):
    _, org = admin_identity(user)
    with control_session() as db:
        validate_peer(admin_contacts(db, org), peer)
        return contact_avatar(db, peer)


@admin_router.post("/messages", status_code=201)
def organization_send(body: MessageInput, user: AdminUser, peer: str = Query(max_length=100)):
    actor, org = admin_identity(user)
    with control_session() as db:
        return send(db, actor, peer, body, admin_contacts(db, org), workspace_url("/api/inspection-admin"))


@admin_router.post("/messages/read")
def organization_read(body: ReadInput, user: AdminUser, peer: str = Query(max_length=100)):
    actor, org = admin_identity(user)
    with control_session() as db:
        validate_peer(admin_contacts(db, org), peer)
        return mark_read(db, actor, peer, body.through_id)


@admin_router.get("/messages/{message_id}/photo")
def organization_message_photo(message_id: int, user: AdminUser):
    actor, org = admin_identity(user)
    with control_session() as db:
        return message_photo(db, actor, admin_contacts(db, org), message_id)


@owner_router.get("/chat/contacts")
def owner_chat_contacts(db: Db, user: Owner, photo_organization_id: UUID | None = None,
                         photo_id: Annotated[int | None, Query(gt=0)] = None,
                         forward_message_id: Annotated[int | None, Query(gt=0)] = None):
    actor = f"o:{user.id}"
    return contact_previews(db, actor, eligible_contacts(db, actor, owner_contacts(db), photo_organization_id, photo_id, forward_message_id))


@owner_router.get("/chat/unread")
def owner_chat_unread(db: Db, user: Owner):
    return unread_count(db, f"o:{user.id}", owner_contacts(db))


@owner_router.get("/chat/contact-avatar")
def owner_chat_avatar(db: Db, user: Owner, peer: str = Query(max_length=100)):
    validate_peer(owner_contacts(db), peer)
    return contact_avatar(db, peer)


@owner_router.get("/chat/messages")
def owner_chat_messages(db: Db, user: Owner, peer: str = Query(max_length=100),
                        before_id: Annotated[int | None, Query(gt=0)] = None,
                        after_id: Annotated[int | None, Query(ge=0)] = None):
    validate_peer(owner_contacts(db), peer)
    return messages(db, f"o:{user.id}", peer, before_id, after_id, "/api/platform/inspection/chat")


@owner_router.post("/chat/messages", status_code=201)
def owner_chat_send(body: MessageInput, db: Db, user: Owner, peer: str = Query(max_length=100)):
    return send(db, f"o:{user.id}", peer, body, owner_contacts(db), "/api/platform/inspection/chat")


@owner_router.post("/chat/messages/read")
def owner_chat_read(body: ReadInput, db: Db, user: Owner, peer: str = Query(max_length=100)):
    validate_peer(owner_contacts(db), peer)
    return mark_read(db, f"o:{user.id}", peer, body.through_id)


@owner_router.get("/chat/messages/{message_id}/photo")
def owner_chat_photo(message_id: int, db: Db, user: Owner):
    return message_photo(db, f"o:{user.id}", owner_contacts(db), message_id, owner=True)


@owner_router.get("/accounts/{account_id}/messages")
def owner_messages(account_id: int, db: Db, user: Owner, before_id: Annotated[int | None, Query(gt=0)] = None):
    account = db.get(Inspector, account_id)
    if not account:
        raise HTTPException(404, "Проверяющий не найден")
    actor = f"i:{account.id}"
    condition = [or_(InspectionMessage.sender_key == actor, InspectionMessage.recipient_key == actor)]
    if before_id:
        condition.append(InspectionMessage.id < before_id)
    rows = list(db.scalars(select(InspectionMessage).where(*condition).order_by(InspectionMessage.id.desc()).limit(100)))
    names = {c["key"]: c["name"] + (" · " + c["organization_name"] if c["organization_name"] else "")
             for c in inspector_contacts(db, account)}
    cache = {}
    return {"items": [message_dict(m, actor, db, "/api/platform/inspection/chat", cache, f"o:{user.id}") | {"peer_name": names.get(
                m.recipient_key if m.sender_key == actor else m.sender_key, "Бывший собеседник")}
                       for m in reversed(rows)], "next_before_id": rows[-1].id if len(rows) == 100 else None}
