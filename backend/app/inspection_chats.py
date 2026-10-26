"""Direct inspector conversations; tenant contacts are always active organization administrators."""

from hashlib import sha256
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException, Query, Response
from pydantic import Field
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.auth import AdminUser, Db
from app.db import database_engine
from app.domain import now
from app.inspection_auth import InspectorUser
from app.inspections import admin_router, owner_router, router
from app.models import InspectionAgency, InspectionGrant, InspectionMessage, Inspector, Organization, User
from app.organization_context import current_organization, workspace_url
from app.organization_registry import control_session, scope_for
from app.organizations import Owner
from app.schemas import StrictModel


class MessageInput(StrictModel):
    body: str = Field(min_length=1, max_length=4000)
    client_id: UUID


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
    contacts = [contact(f"i:{a.id}", a.name, "Проверяющий", None, a.avatar_image)
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


def validate_peer(contacts, peer):
    if not any(c["key"] == peer for c in contacts):
        raise HTTPException(404, "Собеседник недоступен")


def message_dict(message, actor):
    return {"id": message.id, "body": message.body, "created_at": message.created_at,
            "outgoing": message.sender_key == actor, "read_at": message.read_at, "client_id": message.client_id}


def contact_previews(db, actor, contacts):
    for contact in contacts:
        peer = contact["key"]
        latest = db.scalar(select(InspectionMessage).where(pair(actor, peer)).order_by(InspectionMessage.id.desc()).limit(1))
        contact["last_message"] = latest.body[:140] if latest else None
        contact["last_message_at"] = latest.created_at if latest else None
        contact["last_message_outgoing"] = latest.sender_key == actor if latest else False
        contact["unread"] = db.scalar(select(func.count()).select_from(InspectionMessage).where(
            InspectionMessage.sender_key == peer, InspectionMessage.recipient_key == actor, InspectionMessage.read_at.is_(None)))
    return sorted(contacts, key=lambda c: (c["last_message_at"] is not None,
                  c["last_message_at"].timestamp() if c["last_message_at"] else 0), reverse=True)


def messages(db, actor, peer, before_id, after_id=None):
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
    return {"items": [message_dict(m, actor) for m in (rows if after_id is not None else reversed(rows))],
            "next_before_id": rows[-1].id if more and after_id is None else None,
            "has_newer": bool(after_id is not None and more), "peer_read_through_id": read_through}


def contact_avatar(db, peer):
    # Caller must validate this key against the actor's current contact list first.
    parts = peer.split(":")
    if parts[0] == "i":
        image = db.get(Inspector, int(parts[1])).avatar_image
    else:
        organization = db.get(Organization, parts[1])
        with Session(database_engine(scope_for(organization).database_url)) as tenant:
            image = tenant.get(User, int(parts[2])).avatar_image
    if not image:
        raise HTTPException(404, "Аватарка не установлена")
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


def send(db, actor, peer, body):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:actor, 7011))"), {"actor": actor})
    existing = db.scalar(select(InspectionMessage).where(InspectionMessage.sender_key == actor,
                                                        InspectionMessage.client_id == str(body.client_id)))
    if existing:
        if existing.recipient_key != peer or existing.body != body.body:
            raise HTTPException(409, "Идентификатор сообщения уже использован")
        return message_dict(existing, actor)
    message = InspectionMessage(sender_key=actor, recipient_key=peer, client_id=str(body.client_id), body=body.body)
    db.add(message)
    db.commit()
    return message_dict(message, actor)


def mark_read(db, actor, peer, through):
    db.execute(update(InspectionMessage).where(InspectionMessage.sender_key == peer,
        InspectionMessage.recipient_key == actor, InspectionMessage.id <= through, InspectionMessage.read_at.is_(None))
        .values(read_at=now()))
    db.commit()
    return {"ok": True}


@router.get("/contacts")
def contacts(db: Db, user: InspectorUser):
    return contact_previews(db, f"i:{user.id}", inspector_contacts(db, user))


@router.get("/contact-avatar")
def inspector_contact_avatar(db: Db, user: InspectorUser, peer: str = Query(max_length=100)):
    validate_peer(inspector_contacts(db, user), peer)
    return contact_avatar(db, peer)


@router.get("/unread")
def inspector_unread(db: Db, user: InspectorUser):
    peers = [c["key"] for c in inspector_contacts(db, user)]
    unread = db.scalar(select(func.count()).select_from(InspectionMessage).where(
        InspectionMessage.recipient_key == f"i:{user.id}", InspectionMessage.sender_key.in_(peers),
        InspectionMessage.read_at.is_(None)))
    return {"unread": unread}


@router.get("/messages")
def get_messages(db: Db, user: InspectorUser, peer: str = Query(max_length=100),
                 before_id: Annotated[int | None, Query(gt=0)] = None,
                 after_id: Annotated[int | None, Query(ge=0)] = None):
    validate_peer(inspector_contacts(db, user), peer)
    return messages(db, f"i:{user.id}", peer, before_id, after_id)


@router.post("/messages", status_code=201)
def post_message(body: MessageInput, db: Db, user: InspectorUser, peer: str = Query(max_length=100)):
    validate_peer(inspector_contacts(db, user), peer)
    return send(db, f"i:{user.id}", peer, body)


@router.post("/messages/read")
def read_messages(body: ReadInput, db: Db, user: InspectorUser, peer: str = Query(max_length=100)):
    validate_peer(inspector_contacts(db, user), peer)
    return mark_read(db, f"i:{user.id}", peer, body.through_id)


@admin_router.get("/contacts")
def organization_contacts(user: AdminUser):
    actor, org = admin_identity(user)
    with control_session() as db:
        return contact_previews(db, actor, admin_contacts(db, org))


@admin_router.get("/messages")
def organization_messages(user: AdminUser, peer: str = Query(max_length=100),
                          before_id: Annotated[int | None, Query(gt=0)] = None,
                          after_id: Annotated[int | None, Query(ge=0)] = None):
    actor, org = admin_identity(user)
    with control_session() as db:
        validate_peer(admin_contacts(db, org), peer)
        return messages(db, actor, peer, before_id, after_id)


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
        validate_peer(admin_contacts(db, org), peer)
        return send(db, actor, peer, body)


@admin_router.post("/messages/read")
def organization_read(body: ReadInput, user: AdminUser, peer: str = Query(max_length=100)):
    actor, org = admin_identity(user)
    with control_session() as db:
        validate_peer(admin_contacts(db, org), peer)
        return mark_read(db, actor, peer, body.through_id)


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
    return {"items": [message_dict(m, actor) | {"peer_name": names.get(
                m.recipient_key if m.sender_key == actor else m.sender_key, "Бывший собеседник")}
                       for m in reversed(rows)], "next_before_id": rows[-1].id if len(rows) == 100 else None}
