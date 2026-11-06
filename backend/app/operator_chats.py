"""Private operator conversations, scoped to the signed-in participant."""

import hashlib
from datetime import UTC
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import Field, model_validator
from sqlalchemy import and_, case, func, or_, select, text, update
from sqlalchemy.orm import load_only

from app.auth import CurrentUser, Db
from app.chat_access import chat_condition
from app.chat_messages import Screenshots, prepare_screenshots, quote, screenshot_response
from app.domain import now
from app.models import OperatorMessage, Photo, User
from app.organization_context import workspace_url
from app.permissions import Permission, has_permission
from app.photo_scope import active_cohort_condition
from app.schemas import StrictModel

router = APIRouter(prefix="/api/operator-chats", tags=["operator-chats"])


class MessageInput(StrictModel):
    body: str = Field(default="", max_length=4000)
    client_id: UUID
    photo_id: int | None = Field(default=None, gt=0)

    screenshots: Screenshots = Field(default_factory=list)
    reply_to_id: int | None = Field(default=None, gt=0)
    forward_message_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def content(self):
        if self.forward_message_id and (self.body or self.photo_id or self.screenshots or self.reply_to_id):
            raise ValueError("Пересылаемое сообщение нельзя изменять")
        if not (self.body or self.photo_id or self.screenshots or self.forward_message_id):
            raise ValueError("Напишите сообщение или выберите фотографию")
        return self


class ReadInput(StrictModel):
    through_id: int = Field(gt=0)


def conversation(user_id: int, peer_id: int):
    return or_(
        and_(OperatorMessage.sender_id == user_id, OperatorMessage.recipient_id == peer_id),
        and_(OperatorMessage.sender_id == peer_id, OperatorMessage.recipient_id == user_id),
    )


def peer_user(db, user_id, peer_id, sending=False):
    if peer_id == user_id:
        raise HTTPException(422, "Выберите другого оператора")
    peer = db.get(User, peer_id)
    if not peer:
        raise HTTPException(404, "Оператор не найден")
    if not peer.active:
        if sending:
            raise HTTPException(409, "Аккаунт оператора отключён. Отправка сообщений недоступна.")
        if not db.scalar(select(OperatorMessage.id).where(conversation(user_id, peer_id)).limit(1)):
            raise HTTPException(404, "Переписка не найдена")
    return peer


def visible_photos(db, user, ids):
    ids = {id for id in ids if id is not None}
    if not ids or not has_permission(user, Permission.PHOTOS_VIEW):
        return {}
    stmt = select(Photo).options(load_only(Photo.id, Photo.sha256)).where(
        Photo.id.in_(ids), Photo.preview_removed_at.is_(None), chat_condition(user), active_cohort_condition(),
    )
    if not has_permission(user, Permission.SPAM_VIEW):
        stmt = stmt.where(Photo.is_spam.is_(False))
    return {photo.id: photo for photo in db.scalars(stmt)}


def message_dict(message, photos=None):
    photo = (photos or {}).get(message.photo_id)
    return {
        "id": message.id, "sender_id": message.sender_id, "recipient_id": message.recipient_id,
        "client_id": message.client_id, "body": message.body,
        "reply": message.reply, "forwarded": message.forwarded_from_id is not None,
        "forwarded_name": message.forwarded_name,
        "screenshots": [workspace_url(f"/api/operator-chats/messages/{message.id}/screenshots/{number}")
                        for number in range(1, message.screenshot_count + 1)],
        "photo": {
            "id": message.photo_id, "available": photo is not None,
            "preview_url": workspace_url(f"/api/photos/{photo.id}/preview") if photo is not None and photo.sha256 else None,
        } if message.photo_id is not None else None,
        "created_at": message.created_at.replace(tzinfo=UTC) if message.created_at.tzinfo is None
        else message.created_at,
        "read_at": message.read_at.replace(tzinfo=UTC) if message.read_at and message.read_at.tzinfo is None
        else message.read_at,
    }


def source_message(db, user, message_id):
    source = db.get(OperatorMessage, message_id)
    if not source or user.id not in (source.sender_id, source.recipient_id):
        raise HTTPException(404, "Сообщение недоступно")
    return source


@router.get("/messages/{message_id}/screenshots/{number}")
def message_screenshot(message_id: int, number: int, db: Db, user: CurrentUser):
    return screenshot_response(source_message(db, user, message_id), number)


@router.get("")
def contacts(db: Db, user: CurrentUser, photo_id: Annotated[int | None, Query(gt=0)] = None,
             forward_message_id: Annotated[int | None, Query(gt=0)] = None):
    if forward_message_id:
        if photo_id is not None:
            raise HTTPException(422, "Выберите сообщение или фотографию")
        photo_id = source_message(db, user, forward_message_id).photo_id
    if photo_id is not None and photo_id not in visible_photos(db, user, [photo_id]):
        raise HTTPException(404, "Фотография недоступна для пересылки")
    peer_id = case(
        (OperatorMessage.sender_id == user.id, OperatorMessage.recipient_id),
        else_=OperatorMessage.sender_id,
    )
    threads = select(
        peer_id.label("peer_id"), func.max(OperatorMessage.id).label("last_id"),
        func.count().filter(
            OperatorMessage.recipient_id == user.id, OperatorMessage.read_at.is_(None),
        ).label("unread"),
    ).where(or_(OperatorMessage.sender_id == user.id, OperatorMessage.recipient_id == user.id)) \
        .group_by(peer_id).subquery()
    rows = db.execute(
        select(User, OperatorMessage, threads.c.unread).select_from(User)
        .outerjoin(threads, threads.c.peer_id == User.id)
        .outerjoin(OperatorMessage, OperatorMessage.id == threads.c.last_id)
        .where(User.id != user.id, or_(User.active, threads.c.last_id.is_not(None)))
        .order_by(threads.c.last_id.desc().nullslast(), func.lower(User.name), User.id)
    ).all()
    photos = visible_photos(db, user, [latest.photo_id for _, latest, _ in rows if latest])
    items = []
    for peer, latest, unread in rows:
        if photo_id is not None and (not peer.active or photo_id not in visible_photos(db, peer, [photo_id])):
            continue
        avatar = workspace_url(f"/api/operator-chats/avatars/{peer.id}?v={hashlib.sha256(peer.avatar_image).hexdigest()[:16]}") \
            if peer.active and peer.avatar_image else None
        items.append({
            "id": peer.id, "name": peer.name, "role": peer.role, "active": peer.active,
            "avatar_url": avatar, "unread": unread or 0,
            "last_message": {**message_dict(latest, photos), "body": latest.body[:140]} if latest else None,
        })
    return {"items": items, "unread": sum(item["unread"] for item in items)}


@router.get("/unread")
def unread_count(db: Db, user: CurrentUser):
    return {"unread": db.scalar(
        select(func.count()).select_from(OperatorMessage).where(
            OperatorMessage.recipient_id == user.id, OperatorMessage.read_at.is_(None),
        )
    )}


@router.get("/avatars/{peer_id}")
def peer_avatar(peer_id: int, db: Db, user: CurrentUser):
    peer = db.get(User, peer_id)
    if not peer or not peer.active or not peer.avatar_image:
        raise HTTPException(404, "Аватарка не установлена")
    return Response(content=peer.avatar_image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{peer_id}/messages")
def messages(
    peer_id: int, db: Db, user: CurrentUser,
    before_id: Annotated[int | None, Query(gt=0)] = None,
    after_id: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    peer_user(db, user.id, peer_id)
    if before_id is not None and after_id is not None:
        raise HTTPException(422, "Выберите одно направление загрузки сообщений")
    stmt = select(OperatorMessage).where(conversation(user.id, peer_id))
    if before_id is not None:
        stmt = stmt.where(OperatorMessage.id < before_id)
    if after_id is not None:
        stmt = stmt.where(OperatorMessage.id > after_id).order_by(OperatorMessage.id)
    else:
        stmt = stmt.order_by(OperatorMessage.id.desc())
    rows = list(db.scalars(stmt.limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    if after_id is None:
        rows.reverse()
    read_through = db.scalar(select(func.max(OperatorMessage.id)).where(
        OperatorMessage.sender_id == user.id, OperatorMessage.recipient_id == peer_id,
        OperatorMessage.read_at.is_not(None),
    )) or 0
    photos = visible_photos(db, user, [message.photo_id for message in rows])
    return {
        "items": [message_dict(message, photos) for message in rows],
        "has_older": more if after_id is None else False,
        "has_newer": more if after_id is not None else False,
        "peer_read_through_id": read_through,
    }


@router.post("/{peer_id}/messages", status_code=201)
def send_message(peer_id: int, body: MessageInput, db: Db, user: CurrentUser):
    peer = peer_user(db, user.id, peer_id, sending=True)
    content, photo_id = body.body, body.photo_id
    forward_name, reply = None, None
    screenshots = prepare_screenshots(body.screenshots) or None
    if body.forward_message_id:
        source = source_message(db, user, body.forward_message_id)
        content, photo_id, screenshots = source.body, source.photo_id, source.screenshots
        forward_name = source.forwarded_name or db.get(User, source.sender_id).name
    if body.reply_to_id:
        source = db.scalar(select(OperatorMessage).where(
            OperatorMessage.id == body.reply_to_id, conversation(user.id, peer_id)))
        if source is None:
            raise HTTPException(404, "Сообщение для ответа недоступно")
        reply = quote(source.id, db.get(User, source.sender_id).name, source.body,
                      source.photo_id or source.screenshot_count)
    # Serialize each pair until commit, so an ID cursor cannot skip a late-committing message.
    pair_key = (min(user.id, peer_id) << 32) | max(user.id, peer_id)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": pair_key})
    db.execute(text("SELECT pg_advisory_xact_lock(:sender)"), {"sender": -user.id})
    existing = db.scalar(select(OperatorMessage).where(
        OperatorMessage.sender_id == user.id, OperatorMessage.client_id == str(body.client_id),
    ))
    if existing:
        if (existing.recipient_id, existing.body, existing.photo_id, existing.forwarded_from_id,
                (existing.reply or {}).get("id"), existing.screenshots) != (
                peer_id, content, photo_id, body.forward_message_id, body.reply_to_id, screenshots):
            raise HTTPException(409, "Идентификатор сообщения уже использован")
        return message_dict(existing, visible_photos(db, user, [existing.photo_id]))
    photos = visible_photos(db, user, [photo_id])
    if photo_id is not None:
        if photo_id not in photos:
            raise HTTPException(404, "Фотография недоступна для пересылки")
        if photo_id not in visible_photos(db, peer, [photo_id]):
            raise HTTPException(422, "У этого оператора нет доступа к фотографии. Выберите другого оператора.")
    message = OperatorMessage(
        sender_id=user.id, recipient_id=peer_id, body=content, client_id=str(body.client_id), photo_id=photo_id,
        forwarded_from_id=body.forward_message_id, forwarded_name=forward_name, reply=reply, screenshots=screenshots,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message_dict(message, photos)


@router.post("/{peer_id}/read")
def mark_read(peer_id: int, body: ReadInput, db: Db, user: CurrentUser):
    peer_user(db, user.id, peer_id)
    if not db.scalar(select(OperatorMessage.id).where(
        OperatorMessage.id == body.through_id, conversation(user.id, peer_id),
    )):
        raise HTTPException(404, "Сообщение не найдено")
    db.execute(update(OperatorMessage).where(
        OperatorMessage.sender_id == peer_id, OperatorMessage.recipient_id == user.id,
        OperatorMessage.id <= body.through_id, OperatorMessage.read_at.is_(None),
    ).values(read_at=now()))
    db.commit()
    return {"ok": True}
