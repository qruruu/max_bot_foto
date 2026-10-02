"""Local MAX long polling, sharing the same durable intake pipeline as webhooks."""

import hashlib
import logging
import signal
import time
from datetime import timedelta

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.domain import now
from app.intake import ingest
from app.integrations import MaxClient
from app.models import Chat, MaxReceiverState

log = logging.getLogger(__name__)


def locked_state(db: Session) -> MaxReceiverState:
    db.execute(insert(MaxReceiverState).values(id=1, events_received=0, inbox_received=0).on_conflict_do_nothing())
    return db.scalar(select(MaxReceiverState).where(MaxReceiverState.id == 1).with_for_update())


def received(db: Session, count: int, accepted: int):
    state = locked_state(db)
    state.heartbeat_at = state.last_success_at = now()
    state.last_error = None
    state.events_received += count
    state.inbox_received += accepted
    if count:
        state.last_event_at = now()
    return state


def connection_status(db: Session):
    state = db.get(MaxReceiverState, 1)
    cfg = settings()
    return {
        "mode": cfg.max_transport,
        "token_configured": bool(cfg.max_bot_token),
        "disk_configured": bool(cfg.yandex_disk_token),
        "active_chats": db.scalar(select(func.count()).select_from(Chat).where(Chat.active)),
        "poller_alive": bool(state and state.heartbeat_at and state.heartbeat_at > now() - timedelta(seconds=90)),
        "last_success_at": state.last_success_at if state else None,
        "last_event_at": state.last_event_at if state else None,
        "last_error": state.last_error if state else None,
        "events_received": state.events_received if state else 0,
        "inbox_received": state.inbox_received if state else 0,
    }


def connection_error(exc: Exception):
    if isinstance(exc, httpx.HTTPStatusError):
        return "MAX_HTTP_" + str(exc.response.status_code)
    if isinstance(exc, httpx.TimeoutException):
        return "MAX_TIMEOUT"
    if isinstance(exc, httpx.ConnectError):
        return "MAX_TLS_HANDSHAKE_FAILED" if "SSL" in str(exc).upper() else "MAX_NETWORK_ERROR"
    if isinstance(exc, RuntimeError) and str(exc) in {"MAX_WEBHOOK_ACTIVE", "MAX_NOT_CONFIGURED", "MAX_INVALID_UPDATES"}:
        return str(exc)
    return type(exc).__name__


def poll_once(client=None) -> bool:
    cfg = settings()
    if cfg.max_transport != "polling":
        return False
    client = client or MaxClient()
    # A session lock prevents two receivers from acknowledging each other's uncommitted page.
    with engine().connect() as lock:
        acquired = lock.scalar(text("SELECT pg_try_advisory_lock(7007, 1)"))
        lock.commit()
        if not acquired:
            return False
        try:
            fingerprint = hashlib.sha256(cfg.max_bot_token.encode()).hexdigest()
            with Session(engine()) as db:
                state = locked_state(db)
                if state.token_fingerprint != fingerprint:
                    state.marker = None
                    state.token_fingerprint = fingerprint
                marker = state.marker
                state.heartbeat_at = now()
                db.commit()
            try:
                # Never delete an existing webhook implicitly or poll alongside it.
                if client.request("GET", "/subscriptions").get("subscriptions"):
                    raise RuntimeError("MAX_WEBHOOK_ACTIVE")
                params = {"timeout": 25, "limit": 100, "types": "message_created"}
                if marker is not None:
                    params["marker"] = marker
                data = client.request("GET", "/updates", params=params)
                updates, next_marker = data.get("updates"), data.get("marker")
                if (
                    not isinstance(updates, list)
                    or any(not isinstance(update, dict) for update in updates)
                    or (next_marker is not None and type(next_marker) is not int)
                    or (updates and next_marker is None)
                ):
                    raise RuntimeError("MAX_INVALID_UPDATES")
                with Session(engine()) as db:
                    accepted = sum(ingest(db, update) is not None for update in updates)
                    state = received(db, len(updates), accepted)
                    if next_marker is not None:
                        state.marker = next_marker
                    # Checkpoint only after every inbox/photo/job is durable, in the same transaction.
                    db.commit()
                if updates:
                    log.info("MAX events=%s photo_batches=%s", len(updates), accepted)
                return True
            except Exception as exc:
                code = connection_error(exc)
                with Session(engine()) as db:
                    state = locked_state(db)
                    state.heartbeat_at, state.last_error = now(), code
                    db.commit()
                log.warning("MAX connection error=%s", code)
                return False
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(7007, 1)"))
            lock.commit()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    mode = settings().max_transport
    log.info("MAX receiver mode=%s", mode)
    while not stopping:
        try:
            success = poll_once() if mode == "polling" else False
        except Exception as exc:
            log.warning("MAX receiver error=%s", connection_error(exc))
            success = False
        time.sleep(0.5 if success else 10)


if __name__ == "__main__":
    main()
