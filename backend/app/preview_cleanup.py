"""Clear orphan previews only. This module never deletes or moves any Disk resource."""

from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.domain import audit, storage_path
from app.media import media_path
from app.models import Audit, District, Photo
from app.processing import photo_lock
from app.work_types import work_catalog


def known_original_paths(db: Session, photo: Photo) -> set[str]:
    district = db.get(District, photo.district_id) if photo.district_id else None
    paths = {storage_path(photo, district.name if district else None, work_catalog(db))}
    if photo.yandex_disk_path:
        paths.add(photo.yandex_disk_path)
    # A process may have moved bytes successfully but died before committing the new path.
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
        and (plan.old_value or {}).get("path") == photo.yandex_disk_path
        and (plan.new_value or {}).get("sha256") == photo.sha256
    ):
        path = (plan.new_value or {}).get("path", "")
        roots = (settings().yandex_disk_root, settings().training_folder, settings().spam_folder)
        if ".." in PurePosixPath(path).parts or not any(path.startswith(f"disk:/{root}/") for root in roots):
            raise RuntimeError("INVALID_STORAGE_TRANSFER_PATH")
        paths.add(path)
    return paths


def remove_missing_preview(photo_id: int):
    with photo_lock(photo_id), Session(engine()) as db:
        photo = db.get(Photo, photo_id)
        if not photo or photo.preview_removed_at is None:
            return
        preview = media_path(photo.id, preview=True)
        preview.unlink(missing_ok=True)
        preview.with_suffix(".tmp").unlink(missing_ok=True)
        audit(db, None, "PHOTO_PREVIEW_CLEANED", "photo", photo.id, None, {"preview_removed": True})
        db.commit()
