"""Verified JSON retention and resumable relocation out of the customer's photo folder."""

import logging
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import timedelta
from pathlib import PurePosixPath

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.domain import audit, now, reassess, storage_path
from app.exchange import exchange_root
from app.exchange_files import checked_files, register_existing
from app.integrations import OriginalMissing, YandexDisk
from app.legacy_exchange import recover_manifest
from app.models import District, ExchangeFile, ExchangeState, Photo, Publication
from app.processing import error_code, photo_lock, storage_lock, synchronize, transfer_target

ARCHIVE_JOB_KEY = "archive-organize:v4"
log = logging.getLogger(__name__)


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


def verify_file(disk, root, ref, digest, verified):
    if (ref, digest) not in verified:
        if not disk.matches(f"{root}/{ref}", digest):
            raise RuntimeError("RETENTION_GENERATION_NOT_HEALTHY")
        verified.add((ref, digest))


def index_expired(db, pub, root, cutoff):
    newer = list(
        db.scalars(
            select(Publication)
            .where(
                Publication.id > pub.id,
                Publication.cohort == pub.cohort,
                Publication.status.in_(["DONE", "PRUNING", "PRUNED"]),
                Publication.index_path.startswith(root + "/indexes/", autoescape=True),
            )
            .order_by(Publication.id)
            .limit(3)
        )
    )
    return (
        len(newer) == 3
        and pub.finished_at is not None
        and pub.finished_at <= cutoff
        and newer[2].finished_at is not None
        and newer[2].finished_at <= cutoff
    )


def remove_exchange_file(db, disk, item):
    # Pending orphans cannot displace a published fallback, including after a crash.
    if item.status != "PENDING":
        item.status = "DELETING"
        db.commit()
    disk.trash_exchange_file(f"{item.root}/{item.file_ref}", item.sha256)
    item.status, item.document = "DELETED", None
    db.commit()


def collect_generations(disk=None):
    disk = disk or YandexDisk()
    with publisher_lock(), Session(engine(), expire_on_commit=False) as db:
        state = db.get(ExchangeState, 1)
        cutoff = now() - timedelta(hours=settings().exchange_read_window_hours)
        for cohort in ("test", "production"):
            root = exchange_root(state, cohort)
            register_existing(db, root)
            db.commit()
            publications = list(
                db.scalars(
                    select(Publication)
                    .where(
                        Publication.cohort == cohort,
                        Publication.payload["root"].astext == root,
                    )
                    .order_by(Publication.id.desc())
                )
            )
            manifests = {pub.id: checked_files(pub, root) for pub in publications}
            healthy = [pub.id for pub in publications if pub.status == "DONE"][:3]
            if len(healthy) < 3:
                continue
            verified = set()
            for pub_id in healthy:
                for item in manifests[pub_id]:
                    verify_file(disk, root, item["file_ref"], item["sha256"], verified)
            sections = defaultdict(list)
            for item in db.scalars(
                select(ExchangeFile)
                .where(
                    ExchangeFile.root == root,
                    ExchangeFile.status.in_(["AVAILABLE", "DELETING"]),
                )
                .order_by(ExchangeFile.publication_id.desc())
            ):
                sections[item.section].append(item)
            # Keep three data generations per day/dictionary, even if their indexes are long retired.
            for versions in sections.values():
                for item in [v for v in versions if v.status == "AVAILABLE"][:3]:
                    verify_file(disk, root, item.file_ref, item.sha256, verified)

            for pub in publications:
                if pub.id in healthy or pub.status not in {"DONE", "PRUNING", "SUPERSEDED"}:
                    continue
                if not index_expired(db, pub, root, cutoff):
                    continue
                index = manifests[pub.id][-1]
                pub.status = "PRUNING"
                db.commit()
                disk.trash_exchange_file(f"{root}/{index['file_ref']}", index["sha256"])
                pub.status, pub.payload = "PRUNED", None
                db.commit()

            # Recent indexes and frozen/retrying publications may still depend on an older file.
            referenced = {
                item["file_ref"]
                for pub in publications
                if pub.payload is not None
                for item in manifests[pub.id][:-1]
            }

            for versions in sections.values():
                available = [v for v in versions if v.status == "AVAILABLE"]
                keep = {v.id for v in available[:3]}
                for item in reversed(versions):
                    if item.id in keep or item.file_ref in referenced:
                        continue
                    newer = [v for v in reversed(available) if v.publication_id > item.publication_id][:3]
                    creator = db.get(Publication, item.publication_id)
                    displaced = db.get(Publication, newer[2].publication_id) if len(newer) == 3 else None
                    if (
                        not displaced
                        or not displaced.finished_at
                        or displaced.finished_at > cutoff
                        or not creator.finished_at
                        or creator.finished_at > cutoff
                    ):
                        continue
                    remove_exchange_file(db, disk, item)

            for item in db.scalars(
                select(ExchangeFile).where(
                    ExchangeFile.root == root,
                    ExchangeFile.status == "PENDING",
                )
            ):
                creator = db.get(Publication, item.publication_id)
                if (
                    item.file_ref not in referenced
                    and creator.status == "PRUNED"
                    and index_expired(db, creator, root, cutoff)
                ):
                    remove_exchange_file(db, disk, item)


def organize_archive(disk=None):
    disk = disk or YandexDisk()
    cfg = settings()
    old_root = f"disk:/{cfg.yandex_disk_root}/"
    photo_roots = (cfg.yandex_disk_root, cfg.training_folder, cfg.spam_folder)
    with publisher_lock():
        failures = []
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
                if (
                    source == desired
                    and photo.storage_status == "SYNCED"
                    and photo.processing_error is None
                    and transfer_target(db, photo, desired) == source
                ):
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
                except Exception as exc:
                    db.rollback()
                    photo = db.get(Photo, photo_id)
                    photo.storage_status, photo.processing_error = "ERROR", error_code(exc)
                    db.commit()
                    failures.append(exc)
                    log.warning("archive_photo=%s error=%s", photo_id, error_code(exc))
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
        # Independent stages still complete when one obsolete service folder is blocked.
        for stage, operation in (
            ("legacy_test_tree", lambda: move_legacy_test_tree(disk)),
            ("legacy_exchange", lambda: retire_legacy_exchange(disk)),
            ("empty_photo_folders", lambda: prune_empty_photo_folders(disk)),
            ("empty_archive_copies", lambda: prune_empty_archive_copies(disk)),
        ):
            try:
                log.info("archive_stage=%s started", stage)
                operation()
                log.info("archive_stage=%s completed", stage)
            except Exception as exc:
                failures.append(exc)
                log.warning("archive_stage=%s error=%s", stage, error_code(exc))
        if failures:
            raise failures[0]


def move_legacy_test_tree(disk):
    cfg = settings()
    source = f"disk:/{cfg.yandex_disk_root}/ТЕСТОВЫЕ"
    with storage_lock(shared=False):
        with Session(engine()) as db:
            if db.scalar(
                select(Photo.id)
                .where(
                    Photo.preview_removed_at.is_(None),
                    Photo.yandex_disk_path.startswith(source + "/", autoescape=True),
                )
                .limit(1)
            ):
                # A failed photo transfer must not lose its source to a later bulk folder move.
                raise RuntimeError("LEGACY_TEST_TREE_HAS_PENDING_PHOTOS")
        disk.move_folder(source, f"disk:/{cfg.training_folder}/legacy_test_tree")


def retire_legacy_exchange(disk):
    cfg = settings()
    roots = (f"disk:/{cfg.yandex_disk_root}/ARM_EXCHANGE", f"disk:/{cfg.exchange_folder}/legacy/ARM_EXCHANGE")
    with Session(engine()) as db:
        state = db.get(ExchangeState, 1)
        publications = list(
            db.scalars(
                select(Publication).where(
                    or_(
                        *[
                            condition
                            for root in roots
                            for condition in (
                                Publication.index_path.startswith(root + "/", autoescape=True),
                                Publication.payload["root"]
                                .as_string()
                                .startswith(root + "/", autoescape=True),
                            )
                        ]
                    )
                )
            )
        )
        expected = {root: {} for root in roots}
        for pub in publications:
            payload = pub.payload or {}
            original_root = payload.get("root", "")
            old_base = next((root for root in roots if original_root.startswith(root + "/")), None)
            if old_base is None:
                continue
            # The tree may have moved before its database transaction committed. Check both locations.
            for item in payload.get("files", []):
                ref = PurePosixPath(item["file_ref"])
                if ref.is_absolute() or str(ref) != item["file_ref"] or ".." in ref.parts:
                    raise RuntimeError("INVALID_LEGACY_EXCHANGE_REFERENCE")
                for root in roots:
                    file = root + original_root[len(old_base) :] + "/" + str(ref)
                    if file in expected[root] and expected[root][file] != item["sha256"]:
                        raise RuntimeError("INVALID_LEGACY_EXCHANGE_CHECKSUM")
                    expected[root][file] = item["sha256"]
        for root in roots:
            if db.scalar(
                select(Photo.id)
                .where(Photo.yandex_disk_path.startswith(root + "/", autoescape=True))
                .limit(1)
            ):
                raise RuntimeError("LEGACY_EXCHANGE_CONTAINS_ORIGINAL_REFERENCE")
            # A previous version could already have discarded the DB payload of a copied generation.
            expected[root] = recover_manifest(disk, root, expected[root], state.instance_id)
        for root in roots:
            disk.trash_legacy_exchange_folder(root, expected[root])
        # Keep hashes until BOTH locations are gone; a crash/retry never loses its verification data.
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


def prune_empty_archive_copies(disk):
    cfg = settings()
    roots = (cfg.yandex_disk_root, cfg.training_folder, cfg.spam_folder, cfg.exchange_folder)
    pattern = re.compile(r"disk:/(?:" + "|".join(re.escape(root) for root in roots) + r") \([1-9]\d*\)")
    with storage_lock(shared=False):
        for item in disk.folder_items("disk:/") or []:
            path = item.get("path", "")
            if item.get("type") == "dir" and pattern.fullmatch(path):
                disk.trash_empty_photo_folder(path)  # Nonempty copies are always preserved.
