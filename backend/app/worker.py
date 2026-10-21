import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.domain import now
from app.integrations import MaxClient, OriginalMissing
from app.models import Chat, Inbox, Job, Photo
from app.processing import error_code, process_batch, regeo_all, sync_photo

log = logging.getLogger(__name__)
stop = False


def send_reply(inbox_id: int):
    with Session(engine()) as db:
        inbox = db.get(Inbox, inbox_id)
        if inbox.reply_sent_at or not inbox.reply_text:
            return
        if not db.scalar(select(Photo.id).where(
            Photo.inbox_id == inbox_id, Photo.preview_removed_at.is_(None)
        ).limit(1)):
            return
        # Serialize per-chat replies across all workers and respect the MAX 2 messages/s limit.
        chat = db.scalar(select(Chat).where(Chat.max_chat_id == inbox.max_chat_id).with_for_update())
        if chat.last_reply_at:
            delay = 0.6 - (now() - chat.last_reply_at).total_seconds()
            if delay > 0:
                time.sleep(delay)
        # MAX doesn't expose an idempotency key. A crash after HTTP success can duplicate a reply.
        MaxClient().reply(inbox.max_chat_id, inbox.message_id, inbox.reply_text)
        inbox.reply_sent_at = chat.last_reply_at = now()
        db.commit()


def run_once(kinds: list[str] | None = None) -> bool:
    with Session(engine()) as db:
        ids = list(
            db.scalars(
                select(Job.id)
                .where(
                    Job.status.in_(["PENDING", "RUNNING"]),
                    Job.next_run_at <= now(),
                    Job.kind.in_(kinds) if kinds else Job.kind.not_in(["TRAIN", "PUBLISH", "EXCHANGE_GC", "ARCHIVE_ORGANIZE"]),
                )
                .order_by(Job.next_run_at, Job.id)
                .limit(30)
            )
        )
    for job_id in ids:
        with engine().connect() as lock:
            acquired = lock.scalar(text("SELECT pg_try_advisory_lock(7001, :id)"), {"id": job_id})
            lock.commit()
            if not acquired:
                continue
            try:
                with Session(engine(), expire_on_commit=False) as db:
                    job = db.get(Job, job_id, with_for_update=True)
                    if job.status not in {"PENDING", "RUNNING"} or job.next_run_at > now():
                        continue
                    job.status, job.attempts = "RUNNING", job.attempts + 1
                    db.commit()
                    kind, object_id = job.kind, job.object_id
                try:
                    if kind == "BATCH":
                        process_batch(object_id)
                    elif kind == "SYNC":
                        sync_photo(object_id, job_id=job_id)
                    elif kind == "REMOVE_PREVIEW":
                        from app.preview_cleanup import remove_missing_preview

                        remove_missing_preview(object_id)
                    elif kind == "REPLY":
                        send_reply(object_id)
                    elif kind == "REGEO":
                        regeo_all()
                    elif kind == "PUBLISH":
                        from app.exchange import publish

                        publish(object_id)
                    elif kind == "EXCHANGE_GC":
                        from app.exchange_housekeeping import collect_generations

                        collect_generations()
                    elif kind == "ARCHIVE_ORGANIZE":
                        from app.exchange_housekeeping import organize_archive

                        organize_archive()
                    elif kind == "TRAIN":
                        from app.ml import train_model

                        train_model(force=bool(object_id))
                    else:
                        raise ValueError("UNKNOWN_JOB_KIND")
                    with Session(engine()) as db:
                        job = db.get(Job, job_id)
                        if job.status == "RUNNING":
                            job.status, job.last_error = "DONE", None
                        db.commit()
                except OriginalMissing:
                    # sync_photo already persisted BLOCKED under its photo lock. Do not overwrite
                    # a manual retry that might have been requested after that lock was released.
                    with Session(engine()) as db:
                        job = db.get(Job, job_id)
                        if job.status == "RUNNING":
                            job.status, job.last_error = "BLOCKED", "ORIGINAL_MISSING"
                            db.commit()
                    log.warning("job=%s kind=%s error=ORIGINAL_MISSING (paused)", job_id, kind)
                except Exception as exc:
                    with Session(engine()) as db:
                        job = db.get(Job, job_id)
                        if job.status != "RUNNING":
                            return True
                        job.status, job.last_error = "PENDING", error_code(exc)
                        job.next_run_at = now() + timedelta(seconds=min(3600, 5 * 2 ** min(job.attempts, 10)))
                        db.commit()
                    log.warning("job=%s kind=%s error=%s (will retry)", job_id, kind, error_code(exc))
                return True
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(7001, :id)"), {"id": job_id})
                lock.commit()
    return False


def main(kinds: list[str] | None = None):
    global stop
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Storage downloads use signed URLs; keep them out of routine logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    def shutdown(*_):
        global stop
        stop = True

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log.info("Worker started")
    while not stop:
        try:
            if not run_workspaces_once(kinds):
                time.sleep(settings().worker_idle_seconds)
        except Exception as exc:
            log.error("worker_error=%s", error_code(exc))
            time.sleep(5)


def run_workspaces_once(kinds=None):
    if not settings().organizations_enabled:
        return run_once(kinds)
    from app.organization_context import organization_scope
    from app.organization_intake import dispatch_once
    from app.organization_registry import scopes

    worked = False
    if kinds is None:
        for _ in range(25):
            if not dispatch_once():
                break
            worked = True
    for scope in scopes():
        if stop:
            break
        try:
            with organization_scope(scope):
                worked = run_once(kinds) or worked
        except Exception as exc:
            log.error("organization_worker_error=%s error=%s", scope.id, type(exc).__name__)
    return worked


if __name__ == "__main__":
    main()
