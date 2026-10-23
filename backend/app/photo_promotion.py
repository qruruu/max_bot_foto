"""An explicit owner action promotes one existing photo; intake mode stays unchanged."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.auth import Db, WorkspaceOwner, check_permission
from app.catalog import REJECTED_STATUSES
from app.chat_access import can_access_chat
from app.domain import audit, enqueue
from app.models import DayPhotoReview, Photo
from app.permissions import Permission
from app.schemas import PhotoVersionInput

router = APIRouter(prefix="/api/photos", tags=["photos"])


def production_duplicate(db, photo):
    if not photo.sha256:
        return None
    return db.scalar(select(Photo.id).where(
        Photo.sha256 == photo.sha256, Photo.cohort == "production",
        Photo.id != photo.id, Photo.preview_removed_at.is_(None),
    ).limit(1))


def duplicate_error(photo_id):
    return HTTPException(409, {
        "code": "PRODUCTION_DUPLICATE", "photo_id": photo_id,
        "message": f"Такое фото уже есть в рабочем режиме: №{photo_id}. Повторно учитывать его не нужно.",
    })


@router.post("/{photo_id}/promote")
def promote(photo_id: int, body: PhotoVersionInput, db: Db, user: WorkspaceOwner):
    check_permission(user, Permission.PHOTOS_EDIT)
    # Same photo and content locks as intake/storage; a competing upload cannot create a second
    # working original between the duplicate check and the cohort change.
    db.execute(text("SELECT pg_advisory_xact_lock(7002, :id)"), {"id": photo_id})
    photo = db.get(Photo, photo_id, with_for_update=True)
    if not photo or photo.preview_removed_at is not None or not can_access_chat(db, user, photo.max_chat_id):
        raise HTTPException(404, "Фотография не найдена")
    if photo.version != body.version:
        raise HTTPException(409, "Фото изменилось. Обновите карточку.")
    if photo.cohort != "test":
        raise HTTPException(409, "Фотография уже находится в рабочем режиме")
    if not photo.sha256 or not photo.analyzed_at or photo.status in REJECTED_STATUSES:
        raise HTTPException(409, "Перевод доступен после первичной обработки фотографии")
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {
        "key": int.from_bytes(bytes.fromhex(photo.sha256)[:8], "big", signed=True),
    })
    duplicate_id = production_duplicate(db, photo)
    if duplicate_id is not None:
        raise duplicate_error(duplicate_id)
    before = {"cohort": photo.cohort, "path": photo.yandex_disk_path,
              "storage_status": photo.storage_status, "processing_error": photo.processing_error}
    db.execute(text("SELECT set_config('max_photos.promote_id', :id, true), "
                    "set_config('max_photos.promote_version', :version, true)"),
               {"id": str(photo.id), "version": str(photo.version)})
    # A confirmation of the test day must not silently confirm the working day as well.
    db.execute(delete(DayPhotoReview).where(DayPhotoReview.photo_id == photo.id))
    photo.cohort = "production"
    photo.storage_status, photo.processing_error = "PENDING", None
    photo.version += 1
    # Preserve the actual source and its recovery journal. The normal worker verifies the
    # production destination first, including originals already moved there outside this service.
    try:
        audit(db, user.id, "PHOTO_PROMOTED_TO_PRODUCTION", "photo", photo.id, before,
              {"cohort": photo.cohort, "path": photo.yandex_disk_path, "storage_status": photo.storage_status})
        enqueue(db, "SYNC", photo.id, f"sync:{photo.id}:{photo.version}")
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate_id = production_duplicate(db, db.get(Photo, photo_id))
        if duplicate_id is not None:
            raise duplicate_error(duplicate_id) from None
        raise
    return {"id": photo.id, "cohort": photo.cohort, "version": photo.version,
            "storage_status": photo.storage_status}
