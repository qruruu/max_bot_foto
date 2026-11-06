"""Shared content for private chat messages."""

from base64 import b64decode
from binascii import Error as Base64Error
from typing import Annotated

from fastapi import HTTPException, Response
from pydantic import Field
from sqlalchemy import delete, or_, select, text, update

from app.appeal_images import MAX_PHOTOS, prepare_upload

Screenshots = Annotated[list[Annotated[str, Field(max_length=2_000_000)]], Field(max_length=MAX_PHOTOS)]


def prepare_screenshots(values):
    images = []
    for encoded in values:
        try:
            content = b64decode(encoded, validate=True)
        except (ValueError, Base64Error) as exc:
            raise HTTPException(422, "Не удалось прочитать скриншот") from exc
        images.append(prepare_upload(content, min_side=1)["original"])
    return images


def screenshot_response(message, number):
    if not 1 <= number <= message.screenshot_count:
        raise HTTPException(404, "Скриншот недоступен")
    return Response(message.screenshots[number - 1], media_type="image/jpeg",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


def quote(message_id, author, body, attachment=False):
    return {"id": message_id, "author": author, "body": body[:180] or ("Вложение" if attachment else "")}

def lock_chat_identity(db, key):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 7012))"), {"key": key})


def remove_conversations(db, model, sender, recipient, identity):
    # Forwarded copies in other conversations remain with their attribution.
    condition = or_(sender == identity, recipient == identity)
    source_ids = select(model.id).where(condition)
    db.execute(update(model).where(model.forwarded_from_id.in_(source_ids)).values(forwarded_from_id=None))
    db.execute(delete(model).where(condition))
