"""Shared MAX sender labels, with participant lists and photo counts scoped to each chat."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from sqlalchemy import delete, func, select, text

from app.auth import ChatManager, Db
from app.chat_access import can_access_chat
from app.domain import audit
from app.models import Chat, ChatSender, MaxSender, Photo
from app.permissions import Permission, has_permission
from app.schemas import ChatSenderInput

router = APIRouter(prefix="/api/chats", tags=["chat-senders"])
SenderId = Annotated[int, Path(gt=0, lt=2**63)]


def require_chat(db, user, chat_id, *, lock=False):
    stmt = select(Chat).where(Chat.id == chat_id)
    if lock:
        stmt = stmt.with_for_update()
    chat = db.scalar(stmt)
    if chat is None or not can_access_chat(db, user, chat.max_chat_id):
        raise HTTPException(404, "Чат не найден")
    return chat


@router.get("/{chat_id}/senders")
def chat_senders(chat_id: int, db: Db, user: ChatManager):
    chat = require_chat(db, user, chat_id)
    registered = set(db.scalars(select(ChatSender.sender_id).where(ChatSender.chat_id == chat.id)))
    source = select(Photo.sender_id, func.count(), func.max(Photo.received_at)).where(
        Photo.max_chat_id == chat.max_chat_id, Photo.sender_id > 0, Photo.preview_removed_at.is_(None),
    )
    if not has_permission(user, Permission.SPAM_VIEW):
        source = source.where(Photo.is_spam.is_(False))
    seen = {sender_id: (count, latest) for sender_id, count, latest in db.execute(source.group_by(Photo.sender_id))}
    ids = registered | seen.keys()
    # Names are shared, but a participant list must never enumerate unrelated users
    # or expose photo counts from another chat.
    names = dict(db.execute(select(MaxSender.sender_id, MaxSender.name).where(MaxSender.sender_id.in_(ids))).all())
    return [
        {"sender_id": str(id), "name": names.get(id), "photo_count": seen.get(id, (0, None))[0],
         "last_photo_at": seen.get(id, (0, None))[1]}
        for id in sorted(ids, key=lambda id: (id not in names, (names.get(id) or "").casefold(), id))
    ]


def lock_sender(db, sender_id):
    # Serialize writes to the same user even when they arrive through different chats.
    # This lock's second integer is bounded; the stored/query ID retains all 64 bits.
    db.execute(text("SELECT pg_advisory_xact_lock(7010, :id)"), {"id": sender_id % (2**31)})


@router.put("/{chat_id}/senders/{sender_id}")
def save_chat_sender(chat_id: int, sender_id: SenderId, body: ChatSenderInput, db: Db, user: ChatManager):
    chat = require_chat(db, user, chat_id)
    lock_sender(db, sender_id)
    record = db.get(MaxSender, sender_id)
    before = {"sender_id": str(sender_id), "name": record.name} if record else None
    if record is None:
        db.add(MaxSender(sender_id=sender_id, name=body.name))
    else:
        record.name = body.name
    registration = db.get(ChatSender, (chat.id, sender_id))
    if registration is None:
        db.add(ChatSender(chat_id=chat.id, sender_id=sender_id, name=body.name))
    result = {"sender_id": str(sender_id), "name": body.name}
    audit(db, user.id, "CHAT_SENDER_SAVED", "chat", chat.id, before, {**result, "scope": "ALL_CHATS"})
    db.commit()
    return result


@router.delete("/{chat_id}/senders/{sender_id}")
def remove_chat_sender(chat_id: int, sender_id: SenderId, db: Db, user: ChatManager):
    chat = require_chat(db, user, chat_id)
    lock_sender(db, sender_id)
    record = db.get(MaxSender, sender_id)
    if record is not None:
        audit(db, user.id, "CHAT_SENDER_REMOVED", "chat", chat.id,
              {"sender_id": str(sender_id), "name": record.name, "scope": "ALL_CHATS"}, None)
        db.delete(record)
    db.execute(delete(ChatSender).where(ChatSender.sender_id == sender_id))
    db.commit()
    return {"ok": True}


def photo_sender_name(db, photo):
    if photo.sender_id is None:
        return None
    return db.scalar(
        select(MaxSender.name).where(MaxSender.sender_id == photo.sender_id)
    )
