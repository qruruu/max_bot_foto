import hashlib
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog import IMAGE_EXTENSIONS, Status
from app.domain import enqueue, now
from app.models import Chat, DiscoveredChat, ExchangeState, Inbox, Photo


def discover_chat(db: Session, chat_id: int, update: dict, message: dict):
    """Store just enough to identify a new group; do not queue or retain its attachments."""
    if (message.get("recipient") or {}).get("chat_type") == "dialog":
        return
    instant = now()
    timestamp = update.get("timestamp")
    message_at = instant
    if type(timestamp) is int and 0 <= timestamp < 253402300800000:
        message_at = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
    body = message.get("body") or {}
    preview = body.get("text")
    preview = " ".join(preview.split())[:200] if isinstance(preview, str) else None
    if not preview and body.get("attachments"):
        preview = "Сообщение с вложением"
    statement = insert(DiscoveredChat).values(
        max_chat_id=chat_id,
        message_preview=preview,
        last_message_at=message_at,
        first_seen_at=instant,
        last_seen_at=instant,
    )
    newer = statement.excluded.last_message_at >= DiscoveredChat.last_message_at
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[DiscoveredChat.max_chat_id],
            set_={
                "last_seen_at": instant,
                "last_message_at": case(
                    (newer, statement.excluded.last_message_at), else_=DiscoveredChat.last_message_at
                ),
                "message_preview": case(
                    (newer, statement.excluded.message_preview), else_=DiscoveredChat.message_preview
                ),
            },
        )
    )


def ingest(db: Session, update: dict) -> int | None:
    if update.get("update_type") != "message_created":
        return None
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    if sender.get("is_bot"):
        return None
    chat_id = (message.get("recipient") or {}).get("chat_id")
    if type(chat_id) is not int or not -(2**63) <= chat_id < 2**63:
        return None
    chat = db.scalar(select(Chat).where(Chat.max_chat_id == chat_id).with_for_update(read=True))
    if chat is None:
        discover_chat(db, chat_id, update, message)
        return None
    if not chat.active:
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
    # Shared lock serializes the cutover with intake, without serializing chats against each other.
    exchange = db.scalar(select(ExchangeState).where(ExchangeState.id == 1).with_for_update(read=True))
    if exchange is None:
        raise RuntimeError("EXCHANGE_MIGRATION_REQUIRED")
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
                cohort=exchange.intake_cohort,
                archive_layout="district_v1",
                classification_mode="AI" if chat.cv_work_type_enabled else "CHAT_FIXED",
                fixed_work_type_snapshot=None if chat.cv_work_type_enabled else chat.fixed_work_type_code,
                work_rule_version=chat.work_rule_version,
                status=status,
                review_reason=["UNSUPPORTED_FORMAT"] if unsupported and not forwarded else [],
                storage_status="NOT_REQUIRED" if forwarded or unsupported else "PENDING",
            )
        )
    # Inbox, photo rows, and durable job are committed atomically by the caller.
    enqueue(db, "BATCH", inbox_id, f"batch:{inbox_id}")
    return inbox_id
