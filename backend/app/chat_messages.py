"""Shared content for private chat messages."""

from base64 import b64decode
from binascii import Error as Base64Error
from typing import Annotated

from fastapi import HTTPException, Response
from pydantic import Field

from app.appeal_images import prepare_upload

Screenshots = Annotated[list[Annotated[str, Field(max_length=2_000_000)]], Field(max_length=3)]


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
