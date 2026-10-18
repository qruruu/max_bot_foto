"""Server-side MAX chat boundaries, independent of function permissions."""

from fastapi import HTTPException
from sqlalchemy import select, true

from app.models import Chat, Photo


def allowed_chat_ids(user):
    if user is None or user.role == "ADMIN_OPERATOR":
        return None
    return getattr(user, "allowed_chat_ids", None)


def chat_condition(user, column=Photo.max_chat_id):
    ids = allowed_chat_ids(user)
    if ids is None:
        return true()
    return column.in_(select(Chat.max_chat_id).where(Chat.id.in_(ids)))


def can_access_chat(db, user, max_chat_id):
    ids = allowed_chat_ids(user)
    return ids is None or db.scalar(
        select(Chat.id).where(Chat.id.in_(ids), Chat.max_chat_id == max_chat_id).limit(1)
    ) is not None


def require_all_chats(user):
    if allowed_chat_ids(user) is not None:
        raise HTTPException(403, "Для этой общей настройки нужен доступ ко всем чатам MAX")


def validate_chat_access(db, ids):
    if ids is not None and set(db.scalars(select(Chat.id).where(Chat.id.in_(ids)))) != set(ids):
        raise HTTPException(422, "Один из выбранных чатов не найден. Обновите список чатов.")
