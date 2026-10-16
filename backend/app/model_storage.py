"""Remove obsolete classifier checkpoints while preserving training examples and history."""

import errno
import logging
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session, load_only

from app.config import settings
from app.db import engine
from app.domain import audit, now
from app.models import ModelVersion

log = logging.getLogger(__name__)
PREVIOUS_MODELS_TO_KEEP = 3
MODEL_FILE_LOCK = 7011
FINISHED_STATUSES = {"SUPERSEDED", "REJECTED", "ERROR", "INTERRUPTED"}


def weights_available(version):
    try:
        return bool(version.model_path and Path(version.model_path).is_file())
    except OSError:
        return False


def _managed_weights(root, version):
    path = root / f"version-{version.id}" / "weights.pt"
    if (
        root.is_symlink()
        or path.parent.is_symlink()
        or path.is_symlink()
        or path.with_suffix(".tmp").is_symlink()
    ):
        return None
    if version.model_path and Path(version.model_path).absolute() != path.absolute():
        return None
    return path


def _remove_empty_directory(path):
    try:
        path.rmdir()
    except OSError as exc:
        if exc.errno not in {errno.ENOENT, errno.ENOTEMPTY}:
            log.warning("model_directory_cleanup_error=%s", type(exc).__name__)


def _cleanup_locked(db):
    # Dataset snapshots can be large. Cleanup needs only checkpoint metadata.
    versions = list(
        db.scalars(
            select(ModelVersion)
            .options(
                load_only(
                    ModelVersion.id,
                    ModelVersion.status,
                    ModelVersion.model_path,
                    ModelVersion.weights_removed_at,
                    ModelVersion.metrics,
                )
            )
            .order_by(ModelVersion.id.desc())
        )
    )
    active = next((v for v in versions if v.status == "ACTIVE"), None)
    if active and not weights_available(active):
        log.warning("model_cleanup_skipped=ACTIVE_WEIGHTS_MISSING model=%s", active.id)
        return 0
    if active:
        previous = [
            v
            for v in versions
            if v.status == "SUPERSEDED"
            and v.metrics.get("architecture") == active.metrics.get("architecture")
            and weights_available(v)
        ][:PREVIOUS_MODELS_TO_KEEP]
        keep = {active.id, *(v.id for v in previous)}
    else:
        # Before a first successful activation, retain the latest completed candidates.
        keep = {
            v.id
            for v in [v for v in versions if v.status in FINISHED_STATUSES and weights_available(v)][
                : PREVIOUS_MODELS_TO_KEEP + 1
            ]
        }

    root = settings().data_dir / "models"
    candidates = []
    for version in versions:
        if version.id in keep or version.status not in FINISHED_STATUSES or version.weights_removed_at:
            continue
        path = _managed_weights(root, version)
        if path is not None:
            candidates.append((version, path))
    candidate_ids = {v.id for v, _ in candidates}
    # Never remove a file referenced by another protected or non-managed record.
    protected_paths = {
        Path(v.model_path).resolve() for v in versions if v.model_path and v.id not in candidate_ids
    }
    if settings().ml_backbone_path:
        protected_paths.add(settings().ml_backbone_path.resolve())
    removed = 0
    for version, path in candidates:
        temporary = path.with_suffix(".tmp")
        if path.resolve() in protected_paths or temporary.resolve() in protected_paths:
            continue
        had_file = path.exists() or temporary.exists()
        if not version.model_path and not had_file:
            continue
        before = {"model_path": version.model_path, "status": version.status}
        try:
            path.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("model_cleanup_failed model=%s error=%s", version.id, type(exc).__name__)
            continue
        _remove_empty_directory(path.parent)
        version.model_path = None
        version.weights_removed_at = now()
        audit(
            db,
            None,
            "MODEL_WEIGHTS_REMOVED",
            "model",
            version.id,
            before,
            {
                "weights_removed_at": version.weights_removed_at.isoformat(),
                "file_was_missing": not had_file,
                "previous_versions_to_keep": PREVIOUS_MODELS_TO_KEEP,
            },
        )
        db.commit()
        removed += 1
    if removed:
        log.info("model_cleanup_removed=%s", removed)
    return removed


def cleanup_model_files():
    """Serialize with training and file loading; failures never disable a working model."""
    try:
        with engine().connect() as lock:
            if not lock.scalar(text("SELECT pg_try_advisory_lock(7005, 1)")):
                lock.commit()
                return 0
            lock.commit()
            files_locked = False
            try:
                files_locked = lock.scalar(
                    text("SELECT pg_try_advisory_lock(:key, 1)"), {"key": MODEL_FILE_LOCK}
                )
                lock.commit()
                if not files_locked:
                    return 0
                with Session(engine(), expire_on_commit=False) as db:
                    return _cleanup_locked(db)
            finally:
                if files_locked:
                    lock.execute(text("SELECT pg_advisory_unlock(:key, 1)"), {"key": MODEL_FILE_LOCK})
                lock.execute(text("SELECT pg_advisory_unlock(7005, 1)"))
                lock.commit()
    except Exception as exc:
        log.warning("model_cleanup_error=%s", type(exc).__name__)
        return 0
