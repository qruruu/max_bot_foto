"""Verified JSON retention and resumable relocation out of the customer's photo folder."""

from contextlib import contextmanager
from datetime import timedelta
from pathlib import PurePosixPath

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.domain import audit, now, reassess, storage_path
from app.exchange import Dictionary, Index, Partition, exchange_root, json_bytes
from app.integrations import OriginalMissing, YandexDisk
from app.models import District, ExchangeState, Photo, Publication
from app.processing import photo_lock, storage_lock, synchronize, transfer_target

ARCHIVE_JOB_KEY = "archive-organize:v4"


@contextmanager
def publisher_lock():
    with engine().connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(7008, 1)"))
        conn.commit()
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(7008, 1)"))
            conn.commit()


def checked_files(pub, root):
    """Never delete paths taken blindly from a stored payload; accept only this generation's JSON."""
    if not pub.payload or pub.payload.get("root") != root:
        raise ValueError("LEGACY_PUBLICATION")
    files = pub.payload["files"]
    generation = f"{pub.id:020d}"
    for item in files:
        ref = item["file_ref"]
        path = PurePosixPath(ref)
        if path.is_absolute() or ".." in path.parts or path.name != generation + ".json":
            raise ValueError("INVALID_EXCHANGE_REFERENCE")
        if path.parts[0] not in {"indexes", "snapshots", "dictionaries"}:
            raise ValueError("INVALID_EXCHANGE_REFERENCE")
        model = {"indexes": Index, "snapshots": Partition, "dictionaries": Dictionary}[path.parts[0]]
        model.model_validate(item["document"])
        import hashlib

        if hashlib.sha256(json_bytes(item["document"])).hexdigest() != item["sha256"]:
            raise ValueError("INVALID_EXCHANGE_CHECKSUM")
    if files[-1]["file_ref"] != f"indexes/{generation}.json":
        raise ValueError("INVALID_INDEX_ORDER")
    return files


def collect_generations(disk=None):
    disk = disk or YandexDisk()
    with publisher_lock(), Session(engine(), expire_on_commit=False) as db:
        state = db.get(ExchangeState, 1)
        cutoff = now() - timedelta(hours=settings().exchange_read_window_hours)
        for cohort in ("test", "production"):
            root = exchange_root(state, cohort)
            publications = list(
                db.scalars(
                    select(Publication)
                    .where(
                        Publication.cohort == cohort,
                        Publication.status.in_(["DONE", "PRUNING", "SUPERSEDED"]),
                    )
                    .order_by(Publication.id.desc())
                )
            )
            healthy, candidates = [], []
            for pub in publications:
                try:
                    files = checked_files(pub, root)
                except ValueError:
                    continue  # old contract/unrelated root is not a deletion target
                if pub.status in {"PRUNING", "SUPERSEDED"}:
                    candidates.append((pub, files))
                    continue
                if len(healthy) < 3:
                    if not all(disk.matches(f"{root}/{f['file_ref']}", f["sha256"]) for f in files):
                        # An incomplete latest set never permits deletion of fallback generations.
                        raise RuntimeError("RETENTION_GENERATION_NOT_HEALTHY")
                    healthy.append(pub.id)
                else:
                    candidates.append((pub, files))
            if len(healthy) < 3:
                continue
            for pub, files in candidates:
                # Keep a full reading window after the publication that displaced this generation.
                newer = list(
                    db.scalars(
                        select(Publication)
                        .where(
                            Publication.id > pub.id,
                            Publication.cohort == cohort,
                            Publication.status.in_(["DONE", "PRUNING", "PRUNED"]),
                            Publication.index_path.startswith(root + "/indexes/", autoescape=True),
                        )
                        .order_by(Publication.id)
                        .limit(3)
                    )
                )
                if len(newer) < 3:
                    continue
                displaced_at = newer[2].finished_at
                if not pub.finished_at or pub.finished_at > cutoff or displaced_at > cutoff:
                    continue
                pub.status = "PRUNING"
                db.commit()
                # Remove the discoverable index first; no new reader starts this retired generation.
                for item in reversed(files):
                    disk.trash_exchange_file(f"{root}/{item['file_ref']}", item["sha256"])
                pub.status, pub.payload = "PRUNED", None
                db.commit()


def organize_archive(disk=None):
    disk = disk or YandexDisk()
    cfg = settings()
    old_root = f"disk:/{cfg.yandex_disk_root}/"
    photo_roots = (cfg.yandex_disk_root, cfg.training_folder, cfg.spam_folder)
    with publisher_lock():
        with Session(engine()) as db:
            ids = list(
                db.scalars(
                    select(Photo.id)
                    .where(
                        Photo.preview_removed_at.is_(None),
                        Photo.yandex_disk_path.is_not(None),
                        Photo.sha256.is_not(None),
                    )
                    .order_by(Photo.id)
                )
            )
        for photo_id in ids:
            with photo_lock(photo_id), Session(engine()) as db:
                photo = db.get(Photo, photo_id)
                source = photo.yandex_disk_path
                if (
                    photo.preview_removed_at is not None
                    or not source
                    or not any(source.startswith(f"disk:/{root}/") for root in photo_roots)
                    or source.startswith(old_root + "ARM_EXCHANGE/")
                ):
                    continue
                district = db.get(District, photo.district_id) if photo.district_id else None
                desired = storage_path(photo, district.name if district else None)
                if source == desired and transfer_target(db, photo, desired) == source:
                    continue
                try:
                    synchronize(db, photo, disk)
                except OriginalMissing:
                    # Missing bytes cannot be recovered from a preview. Do not retry them endlessly.
                    photo.storage_status, photo.processing_error = "ERROR", "ORIGINAL_MISSING"
                    audit(
                        db,
                        None,
                        "ARCHIVE_RELOCATION_MISSING",
                        "photo",
                        photo.id,
                        {"path": source},
                        {"error": "ORIGINAL_MISSING"},
                    )
                    db.commit()
                    continue
                reassess(db, photo)
                audit(
                    db,
                    None,
                    "ARCHIVE_ORIGINAL_RELOCATED",
                    "photo",
                    photo.id,
                    {"path": source},
                    {"path": photo.yandex_disk_path},
                )
                db.commit()
        # Obsolete JSON is disposable source output, not another archive to preserve on Disk.
        # Keep the live training/production JSON in its separate root, and retire old service trees.
        for source in (old_root + "ARM_EXCHANGE", f"disk:/{cfg.exchange_folder}/legacy/ARM_EXCHANGE"):
            with Session(engine()) as db:
                if db.scalar(
                    select(Photo.id)
                    .where(Photo.yandex_disk_path.startswith(source + "/", autoescape=True))
                    .limit(1)
                ):
                    raise RuntimeError("LEGACY_EXCHANGE_CONTAINS_ORIGINAL_REFERENCE")
                publications = list(
                    db.scalars(
                        select(Publication).where(
                            Publication.index_path.startswith(source + "/", autoescape=True)
                        )
                    )
                )
                expected = {}
                for pub in publications:
                    payload = pub.payload or {}
                    root = payload.get("root", "")
                    if not root.startswith(source + "/"):
                        continue
                    for item in payload.get("files", []):
                        ref = PurePosixPath(item["file_ref"])
                        if ref.is_absolute() or ".." in ref.parts:
                            raise RuntimeError("INVALID_LEGACY_EXCHANGE_REFERENCE")
                        file = root + "/" + str(ref)
                        if file in expected and expected[file] != item["sha256"]:
                            raise RuntimeError("INVALID_LEGACY_EXCHANGE_CHECKSUM")
                        expected[file] = item["sha256"]
                disk.trash_legacy_exchange_folder(source, expected)
                for pub in publications:
                    audit(
                        db,
                        None,
                        "LEGACY_EXCHANGE_RETIRED",
                        "publication",
                        pub.id,
                        {"index_path": pub.index_path},
                        {"status": "RETIRED"},
                    )
                    pub.status, pub.index_path, pub.payload = "RETIRED", None, None
                db.commit()
        legacy_parent = f"disk:/{cfg.exchange_folder}/legacy"
        if disk.folder_items(legacy_parent) == []:
            disk.trash_legacy_exchange_folder(legacy_parent, {})
        # Moves empty directories and any untracked test files as a tree, never deletes originals.
        with storage_lock(shared=False):
            disk.move_folder(old_root + "ТЕСТОВЫЕ", f"disk:/{cfg.training_folder}/legacy_test_tree")
        prune_empty_photo_folders(disk)


def prune_empty_photo_folders(disk):
    # Service transfers hold the shared lock. Cleanup runs only once they have committed their paths.
    # The complete inventory is validated before the first empty directory is retired.
    cfg = settings()
    roots = [f"disk:/{root}" for root in (cfg.yandex_disk_root, cfg.training_folder, cfg.spam_folder)]
    with storage_lock(shared=False):
        folders = list(roots)
        seen = set(folders)
        for folder in folders:
            for item in disk.folder_items(folder) or []:
                child = item.get("path", "")
                if (
                    str(PurePosixPath(child)) != child
                    or str(PurePosixPath(child).parent) != folder
                    or ".." in PurePosixPath(child).parts
                    or child in seen
                    or item.get("type") not in {"dir", "file"}
                ):
                    raise RuntimeError("YANDEX_INVALID_PHOTO_FOLDER_LISTING")
                seen.add(child)
                if item["type"] == "dir":
                    folders.append(child)
        for folder in reversed(folders[len(roots) :]):
            disk.trash_empty_photo_folder(folder)
