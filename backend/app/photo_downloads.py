"""Resource admission, small download tickets and short-lived database reads."""

import asyncio
import fcntl
import hashlib
import json
import re
import secrets
import shutil
import time
from asyncio import Semaphore
from contextlib import contextmanager, suppress

from anyio import CancelScope
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, load_only

from app.auth import check_permission
from app.config import base_settings
from app.models import Photo, User
from app.organization_context import current_organization
from app.permissions import Permission
from app.photo_archive import stream_image, stream_zip
from app.photo_ordering import photo_order
from app.reports import filtered
from app.schemas import PhotoSelectionFilters, StrictModel

BUSY = "Скачивание сейчас занято. Попробуйте через несколько секунд."
DOWNLOAD_PATH = re.compile(r"(?:/org/[0-9a-f-]{36})?/api/photos/(?:selection|downloads(?:/[^/]+(?:/status)?)?)")
TOKEN = re.compile(r"[a-f0-9]{64}-[a-f0-9]{32}")
BODY_LIMIT = 256 * 1024
BATCH_SIZE = 256
MAX_SECONDS = 300
MAX_DOWNLOAD_PHOTOS = 50
PARALLEL_DOWNLOADS = 2
QUEUE_SECONDS = 300
MAX_PENDING = 32
TICKET_SECONDS = QUEUE_SECONDS + MAX_SECONDS + 300


class PhotoDownloadInput(StrictModel):
    filters: PhotoSelectionFilters | None = None
    ids: list[int] | None = None
    excluded_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_selection(self):
        if (self.filters is None) == (self.ids is None):
            raise ValueError("Укажите фильтр или номера выбранных фотографий")
        if any(id <= 0 or id >= 2**31 for id in [*(self.ids or []), *self.excluded_ids]):
            raise ValueError("Некорректный номер фотографии")
        if self.ids is not None:
            self.ids = sorted(set(self.ids))
        self.excluded_ids = sorted(set(self.excluded_ids))
        return self


class PhotoDownloadAdmission:
    """Wait asynchronously, before authentication can occupy a DB connection."""

    def __init__(self, app):
        self.app = app
        self.reads = Semaphore(1)
        self.downloads = Semaphore(PARALLEL_DOWNLOADS)
        self.pending = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not DOWNLOAD_PATH.fullmatch(scope["path"]):
            return await self.app(scope, receive, send)
        downloading = scope["method"] == "GET" and "/downloads/" in scope["path"] and not scope["path"].endswith('/status')
        slots = self.downloads if downloading else self.reads
        if self.pending >= MAX_PENDING:
            return await JSONResponse({"detail": "Слишком много ожидающих загрузок. Попробуйте позже."},
                                      503, headers={"Retry-After": "5"})(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > BODY_LIMIT:
                raise HTTPException(413, "Слишком много отдельных отметок. Используйте «Выбрать все» и фильтры.")
            return message

        self.pending += 1
        lease = None
        entered = False
        dispatched = False
        disconnect_scope = CancelScope()

        async def enter():
            nonlocal lease, entered
            await slots.acquire()
            entered = True
            if downloading:
                while lease is None:
                    try:
                        lease = acquire_download()
                    except DownloadBusy:
                        await asyncio.sleep(0.25)

        async def disconnected():
            with disconnect_scope:
                while not disconnect_scope.cancel_called:
                    if (await receive())["type"] == "http.disconnect":
                        return

        start = asyncio.create_task(enter())
        disconnect = asyncio.create_task(disconnected()) if downloading else None
        try:
            async with asyncio.timeout(QUEUE_SECONDS if downloading else 15):
                if disconnect is not None:
                    done, _ = await asyncio.wait([start, disconnect], return_when=asyncio.FIRST_COMPLETED)
                    if disconnect in done:
                        return
                await start
            # Stop listening before passing receive to the application.
            if disconnect:
                # BaseHTTPMiddleware's receive wrapper can swallow a one-shot
                # Task.cancel() when its own task group finishes concurrently.
                # A dedicated cancellation scope remains cancelled until the
                # listener exits, rather than waiting for the response it blocks.
                disconnect_scope.cancel()
                with suppress(asyncio.CancelledError):
                    await disconnect
            if lease is not None:
                scope.setdefault("state", {})["photo_download_lease"] = lease
            dispatched = True
            return await self.app(scope, bounded_receive, send)
        except TimeoutError:
            if dispatched:
                raise
            return await JSONResponse({"detail": "Время ожидания скачивания истекло. Попробуйте позже."},
                                      503)(scope, receive, send)
        except HTTPException as exc:
            if dispatched:
                raise
            return await JSONResponse({"detail": exc.detail}, exc.status_code, headers=exc.headers)(scope, receive, send)
        finally:
            start.cancel()
            disconnect_scope.cancel()
            with CancelScope(shield=True):
                await asyncio.gather(*(task for task in (start, disconnect) if task), return_exceptions=True)
            if lease is not None:
                lease.close()
            if entered:
                slots.release()
            self.pending -= 1


class DownloadBusy(HTTPException):
    def __init__(self):
        super().__init__(503, BUSY, headers={"Retry-After": "3"})


class SelectionBusy(DownloadBusy):
    pass


@contextmanager
def selection_read(db):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL statement_timeout = '2s'"))
        db.execute(text("SET LOCAL lock_timeout = '250ms'"))
        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(7042, 1)")):
            raise SelectionBusy()
    try:
        yield
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) not in {"57014", "55P03"}:
            raise
        raise HTTPException(503, "Выборка слишком тяжёлая. Уточните фильтры и повторите скачивание.") from exc


def selection_query(body, user):
    filters = body.filters or PhotoSelectionFilters()
    statement = filtered(filters, user).with_only_columns(Photo.id).where(Photo.sha256.is_not(None))
    # Individual selections may span dates and explicit archive statuses. Apply the
    # same per-photo access boundary rather than the normal work-list exclusions.
    if body.ids is not None:
        from app.chat_access import chat_condition
        from app.photo_scope import active_cohort_condition
        statement = select(Photo.id).where(Photo.preview_removed_at.is_(None), Photo.sha256.is_not(None),
                                           chat_condition(user), active_cohort_condition(), Photo.id.in_(body.ids))
        from app.permissions import has_permission
        if not has_permission(user, Permission.SPAM_VIEW):
            statement = statement.where(Photo.is_spam.is_(False))
    elif filters.snapshot_id is not None:
        statement = statement.where(Photo.id <= filters.snapshot_id)
    if body.excluded_ids:
        statement = statement.where(Photo.id.not_in(body.excluded_ids))
    return statement


def selection_summary(db, user, body):
    with selection_read(db):
        source = selection_query(body, user).subquery()
        count, snapshot = db.execute(select(func.count(), func.max(source.c.id))).one()
        # Only the small set needed by forwarding ever travels to the browser.
        ids = list(db.scalars(select(source.c.id).order_by(source.c.id))) if count <= 10 else []
    return {"count": count, "snapshot_id": body.filters.snapshot_id
            if body.filters and body.filters.snapshot_id is not None else snapshot or 0, "ids": ids}


def bounded_selection(db, user, body):
    with selection_read(db):
        ids = list(db.scalars(selection_query(body, user).order_by(
            *photo_order(body.filters or PhotoSelectionFilters())
        ).limit(MAX_DOWNLOAD_PHOTOS)))
    return {"count": len(ids), "ids": ids, "snapshot_id": max(ids, default=0)}


def download_directory():
    directory = base_settings().data_dir / "photo-downloads"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def acquire_download():
    """Two archives across API processes and tenants sharing the data volume."""
    directory = download_directory()
    for slot in range(PARALLEL_DOWNLOADS):
        lease = (directory / f"archive-{slot}.lock").open("a+b")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if shutil.disk_usage(directory).free < 32 * 1024 * 1024:
                raise HTTPException(503, "Недостаточно свободного места для скачивания. Попробуйте позже.")
            return lease
        except BlockingIOError:
            lease.close()
        except BaseException:
            lease.close()
            raise
    raise DownloadBusy()


@contextmanager
def ticket_write():
    # This short metadata lock is independent of long-running archive transfers.
    with (download_directory() / "tickets.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        yield


def ticket_owner(request, user):
    organization = current_organization()
    identity = f"{organization.id if organization else ''}:{user.id}:{request.state.login_session.token_hash}"
    return hashlib.sha256(identity.encode()).hexdigest()


def write_ticket(owner, body):
    directory = download_directory()
    if shutil.disk_usage(directory).free < 8 * 1024 * 1024:
        raise HTTPException(503, "Недостаточно свободного места для скачивания. Попробуйте позже.")
    instant = time.time()
    # Only a bounded ticket store is retained, independently of user/session count.
    tickets = [*directory.glob("*.json"), *directory.glob("*.tmp")]
    for path in tickets:
        if instant - path.stat().st_mtime > TICKET_SECONDS:
            path.unlink(missing_ok=True)
        elif path.suffix == '.json' and instant - path.stat().st_mtime > 60:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("state") in {"finished", "failed"}:
                path.unlink(missing_ok=True)
    if len(list(directory.glob("*.json"))) >= 128:
        raise HTTPException(503, BUSY)
    nonce = secrets.token_hex(16)
    temp = directory / f"{owner}-{nonce}.tmp"
    try:
        temp.write_text(json.dumps({"nonce": nonce, "expires": instant + TICKET_SECONDS, "state": "queued",
                                    "selection": body.model_dump(mode="json")}), encoding="utf-8")
        temp.replace(directory / f"{owner}-{nonce}.json")
    finally:
        temp.unlink(missing_ok=True)
    return f"{owner}-{nonce}"


def read_ticket(token, owner):
    if not TOKEN.fullmatch(token) or token[:64] != owner:
        raise HTTPException(404, "Скачивание не найдено")
    path = download_directory() / f"{token}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(410, "Ссылка истекла. Нажмите «Скачать» ещё раз.") from None
    if data["nonce"] != token[65:] or data["expires"] < time.time():
        raise HTTPException(410, "Ссылка истекла. Нажмите «Скачать» ещё раз.")
    return data


def update_ticket(token, data):
    path = download_directory() / f"{token}.json"
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(data), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def consume_ticket(token, owner):
    with ticket_write():
        data = read_ticket(token, owner)
        if data["state"] != "queued":
            raise HTTPException(410, "Эта загрузка уже запущена")
        data["state"] = "streaming"
        update_ticket(token, data)
    return PhotoDownloadInput.model_validate(data["selection"])


def finish_ticket(token, owner, success):
    with ticket_write():
        try:
            data = read_ticket(token, owner)
        except HTTPException:
            return
        data["state"] = "finished" if success else "failed"
        data.pop("selection", None)
        update_ticket(token, data)


def photo_files(engine, user_id, body, data_directory):
    after = 0
    while True:
        ids = photo_batch(engine, user_id, body, after)
        if not ids:
            return
        for id in ids:
            yield f"photo-{id}.jpg", data_directory / "previews" / f"{id}.jpg"
        after = ids[-1]


def photo_batch(engine, user_id, body, after):
    deadline = time.monotonic() + 5
    while True:
        try:
            # No connection is retained while waiting for the other stream's read.
            with Session(engine) as db, selection_read(db):
                user = db.get(User, user_id, options=[load_only(
                    User.id, User.active, User.role, User.permissions, User.allowed_chat_ids,
                )])
                if user is None or not user.active:
                    raise HTTPException(403, "Нет доступа к скачиванию")
                check_permission(user, Permission.PHOTOS_VIEW)
                if body.filters:
                    if body.filters.status == "SPAM":
                        check_permission(user, Permission.SPAM_VIEW)
                    if body.filters.review_day or body.filters.day_review or body.filters.day_ai_only:
                        check_permission(user, Permission.DAYS_REVIEW)
                return list(db.scalars(selection_query(body, user).where(Photo.id > after)
                                       .order_by(Photo.id).limit(min(BATCH_SIZE, MAX_DOWNLOAD_PHOTOS + 1))))
        except SelectionBusy:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


class PhotoArchiveResponse(StreamingResponse):
    def __init__(self, files, lease, single=None, complete=None):
        self.lease = lease
        self.complete = complete
        rate = 8 * 1024 * 1024 // PARALLEL_DOWNLOADS
        self.archive = stream_image(single[1], rate) if single else stream_zip(files, download_directory(), rate)
        filename = single[0] if single else "photos.zip"
        super().__init__(self.archive, media_type="image/jpeg" if single else "application/zip", headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store", "X-Accel-Buffering": "no",
        })

    async def __call__(self, scope, receive, send):
        finished = False

        async def observed_send(message):
            nonlocal finished
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True
        try:
            async with asyncio.timeout(MAX_SECONDS):
                await super().__call__(scope, receive, observed_send)
        finally:
            with CancelScope(shield=True):
                try:
                    await run_in_threadpool(self.archive.close)
                finally:
                    self.lease.close()
                    if self.complete:
                        await run_in_threadpool(self.complete, finished)
