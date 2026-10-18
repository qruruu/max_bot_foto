"""Manual labels for MAX senders, scoped to the chat where the photo was sent."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from sqlalchemy import func, select

from app.auth import ChatManager, Db
from app.chat_access import can_access_chat
from app.domain import audit
from app.models import Chat, ChatSender, Photo
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
    names = dict(db.execute(select(ChatSender.sender_id, ChatSender.name).where(ChatSender.chat_id == chat.id)).all())
    source = select(Photo.sender_id, func.count(), func.max(Photo.received_at)).where(
        Photo.max_chat_id == chat.max_chat_id, Photo.sender_id > 0, Photo.preview_removed_at.is_(None),
    )
    if not has_permission(user, Permission.SPAM_VIEW):
        source = source.where(Photo.is_spam.is_(False))
    seen = {sender_id: (count, latest) for sender_id, count, latest in db.execute(source.group_by(Photo.sender_id))}
    ids = names.keys() | seen.keys()
    return [
        {"sender_id": str(id), "name": names.get(id), "photo_count": seen.get(id, (0, None))[0],
         "last_photo_at": seen.get(id, (0, None))[1]}
        for id in sorted(ids, key=lambda id: (id not in names, (names.get(id) or "").casefold(), id))
    ]


@router.put("/{chat_id}/senders/{sender_id}")
def save_chat_sender(chat_id: int, sender_id: SenderId, body: ChatSenderInput, db: Db, user: ChatManager):
    chat = require_chat(db, user, chat_id, lock=True)
    record = db.get(ChatSender, (chat.id, sender_id))
    before = {"sender_id": str(sender_id), "name": record.name} if record else None
    if record is None:
        db.add(ChatSender(chat_id=chat.id, sender_id=sender_id, name=body.name))
    else:
        record.name = body.name
    result = {"sender_id": str(sender_id), "name": body.name}
    audit(db, user.id, "CHAT_SENDER_SAVED", "chat", chat.id, before, result)
    db.commit()
    return result


@router.delete("/{chat_id}/senders/{sender_id}")
def remove_chat_sender(chat_id: int, sender_id: SenderId, db: Db, user: ChatManager):
    chat = require_chat(db, user, chat_id, lock=True)
    record = db.get(ChatSender, (chat.id, sender_id))
    if record is not None:
        audit(db, user.id, "CHAT_SENDER_REMOVED", "chat", chat.id,
              {"sender_id": str(sender_id), "name": record.name}, None)
        db.delete(record)
        db.commit()
    return {"ok": True}


def photo_sender_name(db, photo):
    if photo.sender_id is None:
        return None
    return db.scalar(
        select(ChatSender.name).join(Chat, Chat.id == ChatSender.chat_id)
        .where(Chat.max_chat_id == photo.max_chat_id, ChatSender.sender_id == photo.sender_id)
    )
