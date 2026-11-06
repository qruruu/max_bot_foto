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

from app.appeal_events import personal_forward_source
from app.auth import AdminUser, Db
from app.chat_messages import Screenshots, prepare_screenshots, quote, screenshot_response
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

    screenshots: Screenshots = Field(default_factory=list)
    reply_to_id: int | None = Field(default=None, gt=0)

    def forwarded_id(self):
        return self.forward_message_id

    @model_validator(mode="after")
    def content(self):
        self.body = self.body.strip()
        if (self.photo_id is None) != (self.photo_organization_id is None):
            raise ValueError("Укажите фотографию и её организацию")
        if self.forwarded_id() and (self.body or self.photo_id or self.screenshots or self.reply_to_id):
            raise ValueError("Пересылаемое сообщение нельзя изменять")
        if not (self.body or self.photo_id or self.forwarded_id() or self.screenshots):
            raise ValueError("Напишите сообщение или выберите фотографию")
        return self


class AdminMessageInput(MessageInput):
    forward_operator_message_id: int | None = Field(default=None, gt=0)
    forward_task_message_id: int | None = Field(default=None, gt=0)

    def forwarded_id(self):
        forwards = [self.forward_message_id, self.forward_operator_message_id, self.forward_task_message_id]
        if sum(value is not None for value in forwards) > 1:
            raise ValueError("Выберите одно исходное сообщение")
        return next((value for value in forwards if value is not None), None)


class ReadInput(StrictModel):
    through_id: int = Field(gt=0)


def pair(actor, peer, aliases=()):
    peers = [peer, *aliases]
    return or_(and_(InspectionMessage.sender_key == actor, InspectionMessage.recipient_key.in_(peers)),
               and_(InspectionMessage.sender_key.in_(peers), InspectionMessage.recipient_key == actor))


def other_participant(message, actor):
    return message.recipient_key if message.sender_key == actor else message.sender_key


def contact(key, name, kind, organization, avatar, base="/api/inspection"):
    return {"key": key, "name": name, "kind": kind, "organization_name": organization,
            "avatar_url": base + "/contact-avatar?" + urlencode({"peer": key, "v": sha256(avatar).hexdigest()[:16]})
            if avatar else None}


def inspector_contacts(db, account):
    contacts = [contact(f"o:{owner.id}", owner.name, "Владелец сервиса", None, owner.avatar_image)
                for owner in db.scalars(select(User).join(PlatformOwner, PlatformOwner.user_id == User.id)
                                        .where(User.active).order_by(User.name))]
    # Workspace messages use a shared account. Keep that history attached to the original owner.
    primary_id = db.scalar(select(Organization.owner_user_id).where(Organization.legacy).limit(1))
    primary_owner = next((item for item in contacts if item["key"] == f"o:{primary_id}"), None)
    if primary_id is None and len(contacts) == 1 and db.scalar(select(func.count()).select_from(PlatformOwner)) == 1:
        primary_owner = contacts[0]
    contacts += [contact(f"i:{a.id}", a.name, "Проверяющий", None, a.avatar_image)
                 for a in db.scalars(select(Inspector).where(Inspector.agency_id == account.agency_id,
                                     Inspector.id != account.id, Inspector.active).order_by(Inspector.name))]
    orgs = db.scalars(select(Organization).join(InspectionGrant, InspectionGrant.organization_id == Organization.id)
                     .where(InspectionGrant.inspector_id == account.id, Organization.status == "ACTIVE"))
    for org in orgs:
        scope = scope_for(org)
        with Session(database_engine(scope.database_url)) as tenant:
            for admin in tenant.scalars(select(User).where(User.active, User.role == "ADMIN_OPERATOR").order_by(User.name)):
                key = f"a:{org.id}:{admin.id}"
                if primary_owner is not None and admin.id == scope.owner_user_id:
                    primary_owner.setdefault("aliases", []).append(key)
                    continue
                name = "Администратор" if admin.id == scope.owner_user_id and admin.name == "Владелец сервиса" else admin.name
                contacts.append(contact(key, name,
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


def contact_keys(item):
    return [item["key"], *item.get("aliases", ())]


def validate_peer(contacts, peer):
    for item in contacts:
        if peer in contact_keys(item):
            return item
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
                allowed = bool(account and account.active and account.role == "ADMIN_OPERATOR")
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
    validate_peer(contacts, other_participant(source, actor))
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
        contacts = [c for c in contacts if any(can_view_photo(db, key, org_id, photo_id, cache) for key in contact_keys(c))]
    return contacts


def sender_name(db, key):
    parts = key.split(":")
    if parts[0] in {"i", "o"}:
        account = db.get(Inspector if parts[0] == "i" else User, int(parts[1]))
        return account.name if account else "Бывший собеседник"
    organization = db.get(Organization, parts[1])
    if organization and organization.status == "ACTIVE":
        with Session(database_engine(scope_for(organization).database_url)) as tenant:
            account = tenant.get(User, int(parts[2]))
            if account:
                return account.name
    return "Бывший собеседник"


def forwarded_author(db, message):
    # Older forwards predate the stored author name.
    while message and not message.forwarded_name and message.forwarded_from_id:
        message = db.get(InspectionMessage, message.forwarded_from_id)
    return (message.forwarded_name or sender_name(db, message.sender_key)) if message else "Бывший собеседник"


def message_dict(message, actor, db, base="/api/inspection", cache=None, viewer=None, peer_key=None):
    result = {"id": message.id, "body": message.body, "created_at": message.created_at,
              "outgoing": message.sender_key == actor, "read_at": message.read_at, "client_id": message.client_id,
              "forwarded": bool(message.forwarded_from_id or message.forwarded_name), "photo": None, "reply": message.reply,
              "forwarded_name": message.forwarded_name or (forwarded_author(db, message) if message.forwarded_from_id else None),
              "screenshots": [f"{base}/messages/{message.id}/screenshots/{number}"
                              for number in range(1, message.screenshot_count + 1)]}
    if message.photo_id is not None:
        available = can_view_photo(db, viewer or actor, message.photo_organization_id, message.photo_id, cache)
        photo = {"id": message.photo_id, "available": available, "organization_id": None,
                 "organization_name": None, "preview_url": None, "detail_url": None}
        if available:
            org = db.get(Organization, message.photo_organization_id)
            other = peer_key or other_participant(message, actor)
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
        latest = db.scalar(select(InspectionMessage).where(pair(actor, peer, item.get("aliases", ())))
                           .order_by(InspectionMessage.id.desc()).limit(1))
        item["last_message"] = ((f"Фото #{latest.photo_id}" + (" · " if latest.body else "") if latest.photo_id else "") + (latest.body or ("Скриншот" if latest.screenshot_count else "")))[:140] if latest else None
        item["last_message_at"] = latest.created_at if latest else None
        item["last_message_outgoing"] = latest.sender_key == actor if latest else False
        item["unread"] = db.scalar(select(func.count()).select_from(InspectionMessage).where(
            InspectionMessage.sender_key.in_(contact_keys(item)), InspectionMessage.recipient_key == actor, InspectionMessage.read_at.is_(None)))
    return sorted(contacts, key=lambda c: (c["last_message_at"] is not None,
                  c["last_message_at"].timestamp() if c["last_message_at"] else 0), reverse=True)


def messages(db, actor, peer, before_id, after_id=None, base="/api/inspection", *, aliases=()):
    if before_id and after_id is not None:
        raise HTTPException(422, "Выберите одно направление загрузки истории")
    condition = [pair(actor, peer, aliases)]
    if before_id:
        condition.append(InspectionMessage.id < before_id)
    if after_id is not None:
        condition.append(InspectionMessage.id > after_id)
    order = InspectionMessage.id.asc() if after_id is not None else InspectionMessage.id.desc()
    rows = list(db.scalars(select(InspectionMessage).where(*condition).order_by(order).limit(51)))
    more, rows = len(rows) > 50, rows[:50]
    outgoing = (InspectionMessage.sender_key == actor, InspectionMessage.recipient_key.in_([peer, *aliases]))
    read = select(func.max(InspectionMessage.id)).where(*outgoing, InspectionMessage.read_at.is_not(None))
    if aliases:
        # A receipt from one inbox cannot acknowledge messages sent to another inbox.
        unread = select(func.min(InspectionMessage.id)).where(*outgoing, InspectionMessage.read_at.is_(None)).scalar_subquery()
        read = read.where(or_(unread.is_(None), InspectionMessage.id < unread))
    read_through = db.scalar(read) or 0
    receipts = list(db.scalars(select(InspectionMessage.id).where(
        *outgoing, InspectionMessage.read_at.is_not(None), InspectionMessage.id > read_through,
    ).order_by(InspectionMessage.id.desc()).limit(100))) if aliases else []
    cache = {}
    return {"items": [message_dict(m, actor, db, base, cache, peer_key=peer if aliases else None)
                      for m in (rows if after_id is not None else reversed(rows))],
            "next_before_id": rows[-1].id if more and after_id is None else None,
            "has_newer": bool(after_id is not None and more), "peer_read_through_id": read_through,
            **({"peer_read_ids": receipts} if receipts else {})}


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


def lock_inspector_inboxes(db, actor, peer):
    inspector = actor if actor.startswith("i:") else peer
    if actor.startswith("i:") != peer.startswith("i:"):
        # The inspector reads all owner inboxes with a shared message-ID cursor.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:inspector, 7012))"), {"inspector": inspector})


def send(db, actor, peer, body, contacts, base="/api/inspection", *, external_source=None):
    validate_peer(contacts, peer)
    content, org_id, photo_id = body.body, str(body.photo_organization_id) if body.photo_organization_id else None, body.photo_id
    forward_name, reply = None, None
    screenshots = prepare_screenshots(body.screenshots) or None
    if body.forward_message_id:
        source = source_message(db, actor, contacts, body.forward_message_id)
        content, org_id, photo_id = source.body, source.photo_organization_id, source.photo_id
        screenshots, forward_name = source.screenshots, forwarded_author(db, source)
    if external_source:
        content, org_id, photo_id, screenshots, forward_name = external_source
    if body.reply_to_id:
        source = db.scalar(select(InspectionMessage).where(InspectionMessage.id == body.reply_to_id, pair(actor, peer)))
        if source is None:
            raise HTTPException(404, "Сообщение для ответа недоступно")
        reply = quote(source.id, sender_name(db, source.sender_key), source.body, source.photo_id or source.screenshot_count)
    if photo_id is not None and not all(can_view_photo(db, key, org_id, photo_id) for key in (actor, peer)):
        raise HTTPException(404, "Фотография недоступна отправителю или получателю")
    # Commit in conversation order so polling by ID cannot miss an incoming message.
    lock_inspector_inboxes(db, actor, peer)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:pair, 7010))"), {"pair": "|".join(sorted((actor, peer)))})
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:actor, 7011))"), {"actor": actor})
    existing = db.scalar(select(InspectionMessage).where(InspectionMessage.sender_key == actor,
                                                        InspectionMessage.client_id == str(body.client_id)))
    if existing:
        if (existing.recipient_key, existing.body, existing.photo_organization_id, existing.photo_id,
                existing.forwarded_from_id, (existing.reply or {}).get("id"), existing.screenshots) != (
                peer, content, org_id, photo_id, body.forward_message_id, body.reply_to_id, screenshots):
            raise HTTPException(409, "Идентификатор сообщения уже использован")
        if not body.forward_message_id and existing.forwarded_name != forward_name:
            raise HTTPException(409, "Идентификатор сообщения уже использован")
        return message_dict(existing, actor, db, base)
    message = InspectionMessage(sender_key=actor, recipient_key=peer, client_id=str(body.client_id), body=content,
                                photo_organization_id=org_id, photo_id=photo_id, forwarded_from_id=body.forward_message_id,
                                forwarded_name=forward_name, reply=reply, screenshots=screenshots)
    db.add(message)
    db.commit()
    return message_dict(message, actor, db, base)


def mark_read(db, actor, peer, through, aliases=()):
    db.execute(update(InspectionMessage).where(InspectionMessage.sender_key.in_([peer, *aliases]),
        InspectionMessage.recipient_key == actor, InspectionMessage.id <= through, InspectionMessage.read_at.is_(None))
        .values(read_at=now()))
    db.commit()
    return {"ok": True}


def unread_count(db, actor, contacts):
    return {"unread": db.scalar(select(func.count()).select_from(InspectionMessage).where(
        InspectionMessage.recipient_key == actor, InspectionMessage.sender_key.in_([key for item in contacts for key in contact_keys(item)]),
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


@router.get("/messages/{message_id}/screenshots/{number}")
def inspector_message_screenshot(message_id: int, number: int, db: Db, user: InspectorUser):
    return screenshot_response(source_message(db, f"i:{user.id}", inspector_contacts(db, user), message_id), number)


@admin_router.get("/messages/{message_id}/screenshots/{number}")
def organization_message_screenshot(message_id: int, number: int, user: AdminUser):
    actor, org = admin_identity(user)
    with control_session() as db:
        return screenshot_response(source_message(db, actor, admin_contacts(db, org), message_id), number)


@owner_router.get("/chat/messages/{message_id}/screenshots/{number}")
def owner_message_screenshot(message_id: int, number: int, db: Db, user: Owner):
    actor = f"o:{user.id}"
    return screenshot_response(source_message(db, actor, owner_contacts(db), message_id), number)


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
    item = validate_peer(inspector_contacts(db, user), peer)
    return messages(db, f"i:{user.id}", item["key"], before_id, after_id, aliases=item.get("aliases", ()))


def inspector_send_peer(db, actor, requested, item, body, contacts):
    keys = contact_keys(item)
    existing = db.scalar(select(InspectionMessage.recipient_key).where(
        InspectionMessage.sender_key == actor, InspectionMessage.client_id == str(body.client_id)))
    if existing in keys:
        return existing
    history = select(InspectionMessage).where(pair(actor, item["key"], item["aliases"]))
    if body.reply_to_id:
        quoted = db.scalar(history.where(InspectionMessage.id == body.reply_to_id))
        if quoted is None:
            raise HTTPException(404, "Сообщение для ответа недоступно")
        return other_participant(quoted, actor)
    if requested != item["key"]:
        return requested
    org_id, photo_id = body.photo_organization_id, body.photo_id
    if body.forward_message_id:
        source = source_message(db, actor, contacts, body.forward_message_id)
        org_id, photo_id = source.photo_organization_id, source.photo_id
    if photo_id:
        keys = [key for key in keys if can_view_photo(db, key, str(org_id), photo_id)]
    if not keys:
        return requested
    latest = db.scalar(select(InspectionMessage).where(pair(actor, keys[0], keys[1:]))
                       .order_by(InspectionMessage.id.desc()).limit(1))
    return other_participant(latest, actor) if latest else requested


@router.post("/messages", status_code=201)
def post_message(body: MessageInput, db: Db, user: InspectorUser, peer: str = Query(max_length=100)):
    actor = f"i:{user.id}"
    contacts = inspector_contacts(db, user)
    item = validate_peer(contacts, peer)
    aliases = item.get("aliases", ())
    if aliases:
        lock_inspector_inboxes(db, actor, item["key"])
        peer = inspector_send_peer(db, actor, peer, item, body, contacts)
    return send(db, actor, peer, body, contacts)


@router.post("/messages/read")
def read_messages(body: ReadInput, db: Db, user: InspectorUser, peer: str = Query(max_length=100)):
    item = validate_peer(inspector_contacts(db, user), peer)
    return mark_read(db, f"i:{user.id}", item["key"], body.through_id, item.get("aliases", ()))


@router.get("/messages/{message_id}/photo")
def inspector_message_photo(message_id: int, db: Db, user: InspectorUser):
    return message_photo(db, f"i:{user.id}", inspector_contacts(db, user), message_id)


def operator_forward(db, user, org, message_id):
    from app import operator_chats

    source = operator_chats.source_message(db, user, message_id)
    if source.photo_id and source.photo_id not in operator_chats.visible_photos(db, user, [source.photo_id]):
        raise HTTPException(422, "Фотография недоступна для пересылки")
    name = source.forwarded_name or db.get(User, source.sender_id).name
    return source.body, str(org) if source.photo_id else None, source.photo_id, source.screenshots, name


@admin_router.get("/contacts")
def organization_contacts(user: AdminUser, tenant: Db, photo_organization_id: UUID | None = None,
                          photo_id: Annotated[int | None, Query(gt=0)] = None,
                          forward_message_id: Annotated[int | None, Query(gt=0)] = None,
                          forward_operator_message_id: Annotated[int | None, Query(gt=0)] = None,
                          forward_task_message_id: Annotated[int | None, Query(gt=0)] = None):
    actor, org = admin_identity(user)
    sources = [photo_id or photo_organization_id, forward_message_id, forward_operator_message_id, forward_task_message_id]
    if sum(value is not None for value in sources) > 1:
        raise HTTPException(422, "Выберите одно исходное сообщение")
    with control_session() as db:
        contacts = admin_contacts(db, org)
        if forward_task_message_id:
            personal_forward_source(db, user, forward_task_message_id, include_content=False)
        if forward_operator_message_id:
            try:
                _, photo_organization_id, photo_id, _, _ = operator_forward(tenant, user, org, forward_operator_message_id)
            except HTTPException as error:
                if error.status_code != 422:
                    raise
                return []
            if photo_id and not can_view_photo(db, actor, str(org), photo_id):
                return []
        return contact_previews(db, actor, eligible_contacts(db, actor, contacts, photo_organization_id, photo_id, forward_message_id))


@admin_router.get("/unread")
def organization_chat_unread(user: AdminUser):
    actor, org = admin_identity(user)
    with control_session() as db:
        return unread_count(db, actor, admin_contacts(db, org))


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
def organization_send(body: AdminMessageInput, user: AdminUser, tenant: Db, peer: str = Query(max_length=100)):
    actor, org = admin_identity(user)
    source = operator_forward(tenant, user, org, body.forward_operator_message_id) if body.forward_operator_message_id else None
    with control_session() as db:
        if body.forward_task_message_id:
            content, screenshots, name = personal_forward_source(db, user, body.forward_task_message_id)
            source = (content, None, None, screenshots, name)
        return send(db, actor, peer, body, admin_contacts(db, org), workspace_url("/api/inspection-admin"), external_source=source)


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
    names = {key: c["name"] + (" · " + c["organization_name"] if c["organization_name"] else "")
             for c in inspector_contacts(db, account) for key in contact_keys(c)}
    cache = {}
    return {"items": [message_dict(m, actor, db, "/api/platform/inspection/chat", cache, f"o:{user.id}") | {
                "screenshots": [f"/api/platform/inspection/accounts/{account_id}/messages/{m.id}/screenshots/{number}"
                                for number in range(1, m.screenshot_count + 1)],
                "peer_name": names.get(
                m.recipient_key if m.sender_key == actor else m.sender_key, "Бывший собеседник")}
                       for m in reversed(rows)], "next_before_id": rows[-1].id if len(rows) == 100 else None}


@owner_router.get("/accounts/{account_id}/messages/{message_id}/screenshots/{number}")
def owner_audit_screenshot(account_id: int, message_id: int, number: int, db: Db, user: Owner):
    message = db.get(InspectionMessage, message_id)
    if not message or f"i:{account_id}" not in (message.sender_key, message.recipient_key):
        raise HTTPException(404, "Скриншот недоступен")
    return screenshot_response(message, number)
