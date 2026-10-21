"""One durable MAX inbox, then idempotent delivery into the chat's company database."""

import hashlib
import json
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import database_engine
from app.domain import now
from app.intake import discover_chat, ingest
from app.models import Chat, Organization, OrganizationChat, OrganizationEvent
from app.organization_context import organization_scope
from app.organization_registry import control_session, scope_for

log = logging.getLogger(__name__)


def ingest_event(db, event):
    if event.get("update_type") != "message_created":
        return None
    message = event.get("message") or {}
    if (message.get("sender") or {}).get("is_bot"):
        return None
    recipient = message.get("recipient") or {}
    chat_id = recipient.get("chat_id")
    if type(chat_id) is not int or not -(2**63) <= chat_id < 2**63 or recipient.get("chat_type") == "dialog":
        return None
    discover_chat(db, chat_id, event, message)
    body, link = message.get("body") or {}, message.get("link") or {}
    attachments = body.get("attachments") or (link.get("message") or {}).get("attachments") or []
    if not any(a.get("type") in {"image", "file", "video", "audio"} for a in attachments) and link.get("type") != "forward":
        return None
    identity = str(chat_id) + ":" + (body.get("mid") or json.dumps(message, sort_keys=True))
    binding = db.get(OrganizationChat, chat_id)
    return db.scalar(insert(OrganizationEvent).values(
        digest=hashlib.sha256(identity.encode()).hexdigest(), max_chat_id=chat_id,
        organization_id=binding.organization_id if binding else None,
        payload=event, status="PENDING" if binding else "UNASSIGNED", attempts=0,
    ).on_conflict_do_nothing(index_elements=[OrganizationEvent.digest]).returning(OrganizationEvent.id))


def dispatch_once():
    event_id = None
    try:
        with control_session() as db:
            event = db.scalar(select(OrganizationEvent).join(
                OrganizationChat, OrganizationChat.max_chat_id == OrganizationEvent.max_chat_id
            ).join(Organization, Organization.id == OrganizationChat.organization_id).where(
                OrganizationEvent.status.in_(["PENDING", "UNASSIGNED"]),
                OrganizationEvent.available_at <= now(), Organization.status == "ACTIVE",
            ).order_by(OrganizationEvent.id).with_for_update(skip_locked=True, of=OrganizationEvent).limit(1))
            if event is None:
                return False
            event_id = event.id
            binding = db.get(OrganizationChat, event.max_chat_id)
            record = db.scalar(select(Organization).where(Organization.id == binding.organization_id,
                                                         Organization.status == "ACTIVE").with_for_update(read=True))
            if record is None:
                return False
            scope = scope_for(record)
            with organization_scope(scope), Session(database_engine(scope.database_url)) as tenant:
                if not tenant.scalar(select(Chat.id).where(Chat.max_chat_id == event.max_chat_id)):
                    raise RuntimeError("ORGANIZATION_CHAT_NOT_READY")
                inbox_id = ingest(tenant, event.payload, received_at=event.received_at)
                if inbox_id is not None:
                    from app.receiver import received
                    received(tenant, 1, 1)
                tenant.commit()
            # The tenant commit precedes the acknowledgement. Replays hit Inbox's unique key.
            event.organization_id, event.status = record.id, "DELIVERED"
            event.payload, event.last_error = {}, None
            db.commit()
        return True
    except Exception as exc:
        if event_id is None:
            raise
        with control_session() as db:
            event = db.get(OrganizationEvent, event_id, with_for_update=True)
            if event.status != "DELIVERED":
                event.attempts += 1
                event.last_error = type(exc).__name__[:80]
                event.available_at = now() + timedelta(seconds=min(300, 2 ** min(event.attempts, 8)))
                db.commit()
        log.warning("organization_delivery_failed=%s error=%s", event_id, type(exc).__name__)
        return True
