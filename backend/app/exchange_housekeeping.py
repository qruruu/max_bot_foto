"""Verified JSON retention and resumable relocation out of the customer's photo folder."""

from contextlib import contextmanager
from datetime import timedelta
from pathlib import PurePosixPath

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.domain import audit, enqueue, now, storage_path
from app.exchange import Dictionary, Index, Partition, exchange_root, json_bytes
from app.integrations import OriginalMissing, YandexDisk
from app.models import Audit, ExchangeState, Photo, Publication
from app.processing import photo_lock


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
    with publisher_lock():
        with Session(engine()) as db:
            ids = list(
                db.scalars(
                    select(Photo.id)
                    .where(
                        Photo.cohort == "test", Photo.yandex_disk_path.startswith(old_root, autoescape=True)
                    )
                    .order_by(Photo.id)
                )
            )
        for photo_id in ids:
            with photo_lock(photo_id), Session(engine()) as db:
                photo = db.get(Photo, photo_id)
                source = photo.yandex_disk_path
                if photo.cohort != "test" or not source or not source.startswith(old_root):
                    continue
                desired = storage_path(photo, photo.district_name_snapshot)
                plan = db.scalar(
                    select(Audit)
                    .where(Audit.photo_id == photo.id, Audit.action == "TRAINING_RELOCATION_PLANNED")
                    .order_by(Audit.id.desc())
                    .limit(1)
                )
                if (
                    plan
                    and plan.old_value.get("path") == source
                    and plan.new_value.get("sha256") == photo.sha256
                    and plan.new_value.get("path", "").startswith(f"disk:/{cfg.training_folder}/")
                ):
                    target = plan.new_value["path"]
                else:
                    target = desired
                    audit(
                        db,
                        None,
                        "TRAINING_RELOCATION_PLANNED",
                        "photo",
                        photo.id,
                        {"path": source},
                        {"path": target, "sha256": photo.sha256},
                    )
                    # Persist the destination before moving bytes; a later operator edit cannot hide it.
                    db.commit()
                try:
                    disk.move(source, target, photo.sha256)
                except OriginalMissing:
                    # There are no original bytes to relocate; preserve the existing missing-file state.
                    audit(
                        db,
                        None,
                        "TRAINING_RELOCATION_MISSING",
                        "photo",
                        photo.id,
                        {"path": source},
                        {"error": "ORIGINAL_MISSING"},
                    )
                    db.commit()
                    continue
                photo.yandex_disk_path, photo.stored_filename = target, target.rsplit("/", 1)[-1]
                if target != desired:
                    photo.storage_status = "PENDING"
                    enqueue(db, "SYNC", photo.id, f"organize-sync:{photo.id}:{photo.version}")
                audit(
                    db,
                    None,
                    "TRAINING_ORIGINAL_RELOCATED",
                    "photo",
                    photo.id,
                    {"path": source},
                    {"path": target},
                )
                db.commit()
        # Old JSON retains its legacy bytes outside both the customer archive and the new ARM stream.
        source = old_root + "ARM_EXCHANGE"
        target = f"disk:/{cfg.exchange_folder}/legacy/ARM_EXCHANGE"
        disk.move_folder(source, target)
        with Session(engine()) as db:
            for pub in db.scalars(
                select(Publication).where(Publication.index_path.startswith(source + "/", autoescape=True))
            ):
                pub.index_path = target + pub.index_path[len(source) :]
                if pub.payload:
                    pub.payload = {**pub.payload, "root": target + pub.payload["root"][len(source) :]}
            db.commit()
        # Moves empty directories and any untracked test files as a tree, never deletes originals.
        disk.move_folder(old_root + "ТЕСТОВЫЕ", f"disk:/{cfg.training_folder}/legacy_test_tree")
