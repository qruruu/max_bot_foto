import hashlib
import json
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog import IMAGE_EXTENSIONS, Status
from app.domain import enqueue, now
from app.models import Chat, Inbox, Photo


def ingest(db: Session, update: dict) -> int | None:
    if update.get("update_type") != "message_created":
        return None
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    if sender.get("is_bot"):
        return None
    chat_id = (message.get("recipient") or {}).get("chat_id")
    if not isinstance(chat_id, int):
        return None
    chat = db.scalar(select(Chat).where(Chat.max_chat_id == chat_id, Chat.active))
    if chat is None:
        return None
    body = message.get("body") or {}
    link = message.get("link") or {}
    forwarded = str(link.get("type", "")).lower() == "forward"
    attachments = body.get("attachments") or []
    if forwarded and not attachments:
        attachments = (link.get("message") or {}).get("attachments") or []
    # Reject a forwarded message even when the API hides its original attachments.
    if forwarded and not attachments:
        attachments = [{"type": "image"}]
    candidates = [
        (i, a) for i, a in enumerate(attachments) if a.get("type") in {"image", "file", "video", "audio"}
    ]
    if not candidates:
        return None
    mid = (
        body.get("mid") or "event-" + hashlib.sha256(json.dumps(message, sort_keys=True).encode()).hexdigest()
    )
    result = db.execute(
        insert(Inbox)
        .values(max_chat_id=chat_id, message_id=mid, payload=update)
        .on_conflict_do_nothing(index_elements=[Inbox.max_chat_id, Inbox.message_id])
        .returning(Inbox.id)
    )
    inbox_id = result.scalar_one_or_none()
    if inbox_id is None:
        return None
    for index, attachment in candidates:
        filename = attachment.get("filename") or (attachment.get("payload") or {}).get("filename")
        extension = PurePosixPath(filename or "").suffix.lower()
        unsupported = attachment.get("type") != "image" and (
            attachment.get("type") != "file" or extension not in IMAGE_EXTENSIONS
        )
        status = Status.FORWARDED if forwarded else Status.REJECTED if unsupported else Status.RECEIVED
        db.add(
            Photo(
                inbox_id=inbox_id,
                attachment_index=index,
                attachment={} if forwarded or unsupported else attachment,
                original_filename=filename,
                extension=extension or None,
                max_chat_id=chat_id,
                chat_name=chat.name,
                max_message_id=mid,
                sender_id=sender.get("user_id"),
                received_at=now(),
                is_forwarded=forwarded,
                status=status,
                review_reason=["UNSUPPORTED_FORMAT"] if unsupported and not forwarded else [],
                storage_status="NOT_REQUIRED" if forwarded or unsupported else "PENDING",
            )
        )
    # Inbox, photo rows, and durable job are committed atomically by the caller.
    enqueue(db, "BATCH", inbox_id, f"batch:{inbox_id}")
    return inbox_id
