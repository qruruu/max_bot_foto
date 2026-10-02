import logging
from contextlib import contextmanager

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.catalog import ACCEPTED_STATUSES, IMAGE_EXTENSIONS, REJECTED_STATUSES, Status
from app.config import settings
from app.db import engine
from app.domain import audit, bot_reply, enqueue, now, reassess, storage_path
from app.integrations import DownloadRejected, MaxClient, YandexDisk
from app.media import InvalidImage, digest_file, inspect_image, media_path, write_preview
from app.ml import LocalClassifier
from app.models import District, Inbox, Photo
from app.parsers import CoordinateParser, DateTimeParser, parse_address
from app.recognition import OCRService, TesseractOCR, WorkTypeClassifier

log = logging.getLogger(__name__)


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


def error_code(exc: Exception) -> str:
    # No URLs, query signatures, tokens or upstream response bodies in logs/UI.
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP_{exc.response.status_code}"
    return type(exc).__name__


def synchronize(db: Session, photo: Photo, disk: YandexDisk):
    district = db.get(District, photo.district_id) if photo.district_id else None
    target = storage_path(photo, district.name if district else None)
    original = media_path(photo.id)
    if photo.yandex_disk_path:
        disk.move(photo.yandex_disk_path, target, photo.sha256)
    else:
        disk.upload(original, target, photo.sha256)
    photo.yandex_disk_path = target
    photo.stored_filename = target.rsplit("/", 1)[-1]
    photo.storage_status = "SYNCED"
    photo.processing_error = None
    photo.version += 1
    db.commit()
    # Original only removed after remote hash confirmation AND database commit.
    original.unlink(missing_ok=True)


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
            photo.status in ACCEPTED_STATUSES and photo.storage_status == "SYNCED"
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
                existing = db.scalar(select(Photo.id).where(Photo.sha256 == digest, Photo.id != photo.id))
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
            photo.status, photo.processing_error = Status.ERROR, "DOWNLOAD_POLICY_OR_SIZE"
            db.commit()
            raise
        except Exception as exc:
            db.rollback()
            photo = db.get(Photo, photo_id)
            photo.status, photo.processing_error = Status.ERROR, error_code(exc)
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
        except Exception as exc:
            failed = True
            log.warning("photo=%s processing_error=%s", photo_id, error_code(exc))
    if failed:
        raise RuntimeError("BATCH_RETRY_REQUIRED")
    with Session(engine()) as db:
        inbox = db.get(Inbox, inbox_id)
        photos = list(db.scalars(select(Photo).where(Photo.inbox_id == inbox_id).order_by(Photo.id)))
        districts = dict(db.execute(select(District.id, District.name)).all())
        if not inbox.reply_text:
            inbox.reply_text = bot_reply(photos, districts)
        enqueue(db, "REPLY", inbox_id, f"reply:{inbox_id}")
        # Signed attachment URLs are no longer needed after durable storage.
        inbox.payload = {}
        db.commit()


def sync_photo(photo_id: int):
    with photo_lock(photo_id), Session(engine(), expire_on_commit=False) as db:
        photo = db.get(Photo, photo_id)
        if not photo or not photo.sha256 or not photo.analyzed_at:
            return
        try:
            synchronize(db, photo, YandexDisk())
            reassess(db, photo)
            db.commit()
        except Exception as exc:
            db.rollback()
            photo = db.get(Photo, photo_id)
            photo.storage_status, photo.processing_error = "ERROR", error_code(exc)
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
