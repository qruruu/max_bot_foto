import logging
from contextlib import contextmanager
from pathlib import PurePosixPath

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.catalog import ACCEPTED_STATUSES, IMAGE_EXTENSIONS, REJECTED_STATUSES, WORK_TYPES, Status
from app.config import settings
from app.db import engine
from app.domain import audit, bot_reply, enqueue, now, reassess, storage_path
from app.integrations import DownloadRejected, MaxClient, OriginalMissing, YandexDisk
from app.media import InvalidImage, digest_file, inspect_image, media_path, write_preview
from app.ml import LocalClassifier
from app.models import Audit, District, Inbox, Job, Photo
from app.parsers import CoordinateParser, DateTimeParser, parse_address
from app.recognition import OCRService, TesseractOCR, WorkTypeClassifier

log = logging.getLogger(__name__)

PUBLIC_ERROR_CODES = frozenset(
    {
        "LEGACY_TEST_TREE_HAS_PENDING_PHOTOS",
        "LEGACY_EXCHANGE_UNMANAGED_FILE",
        "LEGACY_EXCHANGE_FILE_CHANGED",
        "LEGACY_EXCHANGE_INVALID_DOCUMENT",
        "LEGACY_EXCHANGE_CONTAINS_ORIGINAL_REFERENCE",
        "INVALID_LEGACY_EXCHANGE_REFERENCE",
        "INVALID_LEGACY_EXCHANGE_CHECKSUM",
        "YANDEX_INVALID_SERVICE_PATH",
        "YANDEX_INVALID_PHOTO_FOLDER_LISTING",
        "YANDEX_FOLDER_CHANGED_DURING_LISTING",
        "YANDEX_FOLDER_MOVE_CONFLICT",
        "YANDEX_FOLDER_MOVE_NOT_READY",
        "YANDEX_DELETE_NOT_READY",
        "YANDEX_DESTINATION_CONFLICT",
        "YANDEX_FOLDER_CONFLICT",
        "YANDEX_OPERATION_FAILED",
        "YANDEX_OPERATION_PENDING",
        "YANDEX_FILE_NOT_READY",
        "YANDEX_DISK_NOT_CONFIGURED",
        "LOCAL_ORIGINAL_HASH_MISMATCH",
        "INVALID_STORAGE_TRANSFER_PATH",
    }
)


@contextmanager
def photo_lock(photo_id: int):
    # Session locks survive checkpoint commits, and PostgreSQL releases them on worker death.
    with engine().connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(7002, :id)"), {"id": photo_id})
        conn.commit()
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(7002, :id)"), {"id": photo_id})
            conn.commit()


@contextmanager
def storage_lock(*, shared=True):
    # Allow parallel transfers, but keep service writes out of the empty-folder cleanup window.
    suffix = "_shared" if shared else ""
    with engine().connect() as conn:
        conn.execute(text(f"SELECT pg_advisory_lock{suffix}(7010, 1)"))
        conn.commit()
        try:
            yield
        finally:
            conn.execute(text(f"SELECT pg_advisory_unlock{suffix}(7010, 1)"))
            conn.commit()


def error_code(exc: Exception) -> str:
    # No URLs, query signatures, tokens or upstream response bodies in logs/UI.
    if isinstance(exc, OriginalMissing):
        return "ORIGINAL_MISSING"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP_{exc.response.status_code}"
    if isinstance(exc, RuntimeError) and str(exc) in PUBLIC_ERROR_CODES:
        return str(exc)
    return type(exc).__name__


def transfer_target(db: Session, photo: Photo, desired: str) -> str:
    """Resume the last durable transfer before applying a later operator correction."""
    plan = db.scalar(
        select(Audit)
        .where(
            Audit.photo_id == photo.id,
            Audit.action.in_(["STORAGE_TRANSFER_PLANNED", "TRAINING_RELOCATION_PLANNED"]),
        )
        .order_by(Audit.id.desc())
        .limit(1)
    )
    if (
        plan
        and plan.old_value.get("path") == photo.yandex_disk_path
        and plan.new_value.get("sha256") == photo.sha256
    ):
        target = plan.new_value.get("path", "")
        roots = (settings().yandex_disk_root, settings().training_folder, settings().spam_folder)
        if ".." in PurePosixPath(target).parts or not any(
            target.startswith(f"disk:/{root}/") for root in roots
        ):
            raise RuntimeError("INVALID_STORAGE_TRANSFER_PATH")
        return target
    if photo.yandex_disk_path != desired:
        audit(
            db,
            None,
            "STORAGE_TRANSFER_PLANNED",
            "photo",
            photo.id,
            {"path": photo.yandex_disk_path},
            {"path": desired, "sha256": photo.sha256},
        )
        db.commit()  # The remote operation must never precede its recovery journal.
    return desired


def transfer_original(db: Session, photo: Photo, disk: YandexDisk, target: str):
    original = media_path(photo.id)

    def upload_original():
        if digest_file(original) != photo.sha256:
            raise RuntimeError("LOCAL_ORIGINAL_HASH_MISMATCH")
        disk.upload(original, target, photo.sha256)

    if photo.yandex_disk_path:
        try:
            disk.move(photo.yandex_disk_path, target, photo.sha256)
        except OriginalMissing:
            # A preview is never a replacement for the original. Recover only exact original bytes.
            if not original.is_file():
                raise
            upload_original()
    elif not original.is_file():
        if not disk.matches(target, photo.sha256):
            raise OriginalMissing("ORIGINAL_MISSING")
    else:
        upload_original()
    photo.yandex_disk_path = target
    photo.stored_filename = target.rsplit("/", 1)[-1]
    db.commit()


def synchronize(db: Session, photo: Photo, disk: YandexDisk):
    with storage_lock():
        _synchronize(db, photo, disk)


def _synchronize(db: Session, photo: Photo, disk: YandexDisk):
    if photo.preview_removed_at is not None:
        return
    district = db.get(District, photo.district_id) if photo.district_id else None
    desired = storage_path(photo, district.name if district else None)
    target = transfer_target(db, photo, desired)
    transfer_original(db, photo, disk, target)
    if target != desired:
        transfer_original(db, photo, disk, transfer_target(db, photo, desired))
    photo.storage_status = "SYNCED"
    photo.processing_error = None
    photo.version += 1
    db.commit()
    # Original only removed after remote hash confirmation AND database commit.
    media_path(photo.id).unlink(missing_ok=True)


def process_photo(
    photo_id: int,
    max_client: MaxClient | None = None,
    disk: YandexDisk | None = None,
    ocr: OCRService | None = None,
    classifier: WorkTypeClassifier | None = None,
):
    max_client, disk = max_client or MaxClient(), disk or YandexDisk()
    ocr, classifier = ocr or TesseractOCR(), classifier or LocalClassifier()
    with photo_lock(photo_id), Session(engine(), expire_on_commit=False) as db:
        photo = db.get(Photo, photo_id)
        if photo.status in REJECTED_STATUSES or (
            photo.status in ACCEPTED_STATUSES | {Status.SPAM} and photo.storage_status == "SYNCED"
        ):
            return
        original = media_path(photo.id)
        try:
            if photo.analyzed_at is None:
                photo.status = Status.PROCESSING
                db.commit()
                if not original.exists():
                    try:
                        max_client.download(photo.attachment, original)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code not in (401, 403, 404, 410):
                            raise
                        photo.attachment = max_client.refresh_attachment(
                            photo.max_message_id, photo.attachment_index
                        )
                        db.commit()
                        max_client.download(photo.attachment, original)
                digest = digest_file(original)
                # Serialize competing hashes globally. Unique SHA-256 index is a second guard.
                hash_lock = int.from_bytes(bytes.fromhex(digest)[:8], "big", signed=True)
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": hash_lock})
                existing = db.scalar(
                    select(Photo.id).where(
                        Photo.sha256 == digest,
                        Photo.cohort == photo.cohort,
                        Photo.id != photo.id,
                        Photo.preview_removed_at.is_(None),
                    )
                )
                if existing:
                    photo.status, photo.duplicate_of, photo.storage_status = (
                        Status.DUPLICATE,
                        existing,
                        "NOT_REQUIRED",
                    )
                    photo.attachment = {}
                    db.commit()
                    original.unlink(missing_ok=True)
                    return
                ext, mime = inspect_image(original)
                photo.sha256 = digest
                photo.extension = photo.extension if photo.extension in IMAGE_EXTENSIONS else ext
                photo.mime_type, photo.file_size = mime, original.stat().st_size
                photo.original_filename = photo.original_filename or f"photo_{photo.id}{ext}"
                db.commit()
                write_preview(photo.id, original)
                recognition_errors = []
                try:
                    photo.ocr_raw_text = ocr.recognize(original)
                    parsed_date = DateTimeParser().parse(photo.ocr_raw_text)
                    coords = CoordinateParser().parse(photo.ocr_raw_text)
                    photo.photo_date, photo.photo_time, photo.ocr_date_raw = (
                        parsed_date.photo_date,
                        parsed_date.photo_time,
                        parsed_date.raw,
                    )
                    photo.latitude, photo.longitude = coords.latitude, coords.longitude
                    photo.ocr_coordinates_raw = coords.raw
                    photo.coordinate_format, photo.coordinate_parse_confidence = (
                        coords.coordinate_format,
                        coords.confidence,
                    )
                    photo.ocr_address_raw, photo.detected_address, photo.detected_city = parse_address(
                        photo.ocr_raw_text
                    )
                except Exception as exc:
                    recognition_errors.append("OCR_" + error_code(exc))
                try:
                    if photo.classification_mode == "CHAT_FIXED":
                        code = photo.fixed_work_type_snapshot
                        photo.work_type = code if code in WORK_TYPES else None
                        photo.work_type_source = "CHAT_FIXED" if photo.work_type else None
                        photo.ai_confidence, photo.ai_alternatives = None, []
                        photo.ai_result = {
                            "provider": "chat_rule",
                            "work_type": photo.work_type,
                            "work_rule_version": photo.work_rule_version,
                        }
                    else:
                        result = classifier.classify(original)
                        classification = result.classification
                        photo.ai_result = {
                            "raw": result.raw,
                            "classification": classification.model_dump() if classification else {},
                        }
                        if classification:
                            photo.ai_confidence, photo.ai_alternatives = (
                                classification.confidence,
                                classification.alternatives,
                            )
                            photo.work_type = classification.automatic_work_type(
                                settings().work_type_confidence_threshold
                            )
                            photo.work_type_source = "AI" if photo.work_type else None
                        else:
                            recognition_errors.append("AI_INVALID_RESPONSE")
                except Exception as exc:
                    recognition_errors.append("AI_" + error_code(exc))
                    photo.ai_result = {"error": error_code(exc)}
                if recognition_errors:
                    photo.ai_result = {**(photo.ai_result or {}), "recognition_errors": recognition_errors}
                photo.analyzed_at = now()
                reassess(db, photo)
                photo.version += 1
                db.commit()
            # OCR/AI failures do not prevent this upload. Storage failures are retried separately.
            synchronize(db, photo, disk)
            reassess(db, photo)
            photo.attachment = {}
            db.commit()
        except InvalidImage:
            db.rollback()
            photo = db.get(Photo, photo_id)
            photo.status, photo.review_reason, photo.storage_status = (
                Status.REJECTED,
                ["CORRUPT_IMAGE"],
                "NOT_REQUIRED",
            )
            photo.attachment = {}
            db.commit()
            original.unlink(missing_ok=True)
        except DownloadRejected:
            # A transport policy/size failure is visible and retryable; never mislabel it as a corrupt file.
            db.rollback()
            photo = db.get(Photo, photo_id)
            photo.status, photo.processing_error = (
                Status.SPAM if photo.is_spam else Status.ERROR,
                "DOWNLOAD_POLICY_OR_SIZE",
            )
            db.commit()
            raise
        except Exception as exc:
            db.rollback()
            photo = db.get(Photo, photo_id)
            photo.status, photo.processing_error = (
                Status.SPAM if photo.is_spam else Status.ERROR,
                error_code(exc),
            )
            photo.storage_status = "ERROR" if photo.analyzed_at else "PENDING"
            db.commit()
            raise


def process_batch(inbox_id: int):
    with Session(engine()) as db:
        ids = list(db.scalars(select(Photo.id).where(Photo.inbox_id == inbox_id).order_by(Photo.id)))
    failed = False
    for photo_id in ids:
        try:
            process_photo(photo_id)
        except OriginalMissing:
            # The photo already records the error; retrying an entire album cannot restore deleted bytes.
            log.warning("photo=%s processing_error=ORIGINAL_MISSING (manual recovery required)", photo_id)
        except Exception as exc:
            failed = True
            log.warning("photo=%s processing_error=%s", photo_id, error_code(exc))
    if failed:
        raise RuntimeError("BATCH_RETRY_REQUIRED")
    with Session(engine()) as db:
        inbox = db.get(Inbox, inbox_id)
        photos = list(
            db.scalars(
                select(Photo)
                .where(Photo.inbox_id == inbox_id, Photo.preview_removed_at.is_(None))
                .order_by(Photo.id)
            )
        )
        if not photos:
            return
        districts = dict(db.execute(select(District.id, District.name)).all())
        if not inbox.reply_text:
            inbox.reply_text = bot_reply(photos, districts)
        enqueue(db, "REPLY", inbox_id, f"reply:{inbox_id}")
        # Signed attachment URLs are no longer needed after durable storage.
        inbox.payload = {}
        db.commit()


def sync_photo(photo_id: int, job_id: int | None = None):
    with photo_lock(photo_id), Session(engine(), expire_on_commit=False) as db:
        photo = db.get(Photo, photo_id)
        if not photo or photo.preview_removed_at is not None or not photo.sha256 or not photo.analyzed_at:
            return
        if job_id is not None:
            job = db.get(Job, job_id)
            if not job or job.status != "RUNNING":
                return
            # Under the photo lock, this job handles the latest state for every older queued SYNC.
            # A competing worker may already be waiting here; it will see DONE and skip its network call.
            db.execute(
                update(Job)
                .where(
                    Job.kind == "SYNC",
                    Job.object_id == photo_id,
                    Job.id != job_id,
                    Job.status.in_(["PENDING", "RUNNING", "BLOCKED"]),
                )
                .values(status="DONE", last_error="SYNC_SUPERSEDED")
            )
            db.commit()
        try:
            synchronize(db, photo, YandexDisk())
            reassess(db, photo)
            db.commit()
        except Exception as exc:
            db.rollback()
            photo = db.get(Photo, photo_id)
            photo.storage_status, photo.processing_error = "ERROR", error_code(exc)
            if isinstance(exc, OriginalMissing) and job_id is not None:
                job = db.get(Job, job_id)
                job.status, job.last_error = "BLOCKED", "ORIGINAL_MISSING"
            db.commit()
            raise


def regeo_all():
    # Bounded transactions: geometry changes may affect all already classified photographs.
    last_id = 0
    while True:
        with Session(engine()) as db:
            ids = list(
                db.scalars(
                    select(Photo.id)
                    .where(
                        Photo.id > last_id,
                        Photo.preview_removed_at.is_(None),
                        Photo.analyzed_at.is_not(None),
                        Photo.status.in_(list(ACCEPTED_STATUSES)),
                    )
                    .order_by(Photo.id)
                    .limit(200)
                )
            )
        if not ids:
            break
        for photo_id in ids:
            with photo_lock(photo_id), Session(engine()) as db:
                photo = db.get(Photo, photo_id)
                if photo.preview_removed_at is not None:
                    continue
                before = {
                    "district_id": photo.district_id,
                    "status": photo.status,
                    "review_reason": photo.review_reason,
                }
                reassess(db, photo)
                after = {
                    "district_id": photo.district_id,
                    "status": photo.status,
                    "review_reason": photo.review_reason,
                }
                if before != after:
                    audit(db, None, "DISTRICT_RECALCULATED", "photo", photo.id, before, after)
                photo.version += 1
                photo.storage_status = "PENDING"
                enqueue(db, "SYNC", photo.id, f"sync:{photo.id}:{photo.version}")
                db.commit()
        last_id = ids[-1]
