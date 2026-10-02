import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.domain import now
from app.integrations import MaxClient
from app.models import Chat, Inbox, Job
from app.processing import error_code, process_batch, regeo_all, sync_photo

log = logging.getLogger(__name__)
stop = False


def send_reply(inbox_id: int):
    with Session(engine()) as db:
        inbox = db.get(Inbox, inbox_id)
        if inbox.reply_sent_at or not inbox.reply_text:
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
                    Job.kind.in_(kinds) if kinds else Job.kind != "TRAIN",
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
                    job = db.get(Job, job_id)
                    if job.status == "DONE" or job.next_run_at > now():
                        continue
                    job.status, job.attempts = "RUNNING", job.attempts + 1
                    db.commit()
                    kind, object_id = job.kind, job.object_id
                try:
                    if kind == "BATCH":
                        process_batch(object_id)
                    elif kind == "SYNC":
                        sync_photo(object_id)
                    elif kind == "REPLY":
                        send_reply(object_id)
                    elif kind == "REGEO":
                        regeo_all()
                    elif kind == "TRAIN":
                        from app.ml import train_model

                        train_model(force=bool(object_id))
                    else:
                        raise ValueError("UNKNOWN_JOB_KIND")
                    with Session(engine()) as db:
                        job = db.get(Job, job_id)
                        job.status, job.last_error = "DONE", None
                        db.commit()
                except Exception as exc:
                    with Session(engine()) as db:
                        job = db.get(Job, job_id)
                        job.status, job.last_error = "PENDING", error_code(exc)
                        job.next_run_at = now() + timedelta(seconds=min(3600, 5 * 2 ** min(job.attempts, 10)))
                        db.commit()
                    log.warning("job=%s kind=%s error=%s (will retry)", job_id, kind, error_code(exc))
                return True
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(7001, :id)"), {"id": job_id})
                lock.commit()
    return False


def main():
    global stop
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    def shutdown(*_):
        global stop
        stop = True

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    log.info("Worker started")
    while not stop:
        try:
            if not run_once():
                time.sleep(settings().worker_idle_seconds)
        except Exception as exc:
            log.error("worker_error=%s", error_code(exc))
            time.sleep(5)


if __name__ == "__main__":
    main()
