import hashlib
from datetime import timedelta
from pathlib import PurePosixPath

import pytest
from test_exchange import publication
from test_integration import FakeDisk, FakeMax, GoodAI, GoodOCR, intake_photo, setup_chat, setup_district

from app.config import Settings, settings
from app.domain import now, storage_path
from app.exchange import Partition, publish
from app.exchange_housekeeping import collect_generations, organize_archive
from app.models import ExchangeState, Publication
from app.processing import process_photo

pytestmark = pytest.mark.integration


class Disk(FakeDisk):
    def __init__(self):
        super().__init__()
        self.deleted = []
        self.folders = set()
        self.deleted_folders = []
        self.fail_delete = False

    def remember_parents(self, path):
        self.folders.update(str(p) for p in PurePosixPath(path).parents if str(p) != "disk:")

    def upload(self, original, target, digest):
        self.remember_parents(target)
        super().upload(original, target, digest)

    def move(self, source, target, digest):
        from app.integrations import OriginalMissing

        self.remember_parents(source)
        self.remember_parents(target)
        if not self.matches(target, digest):
            if not self.matches(source, digest):
                raise OriginalMissing("ORIGINAL_MISSING")
            super().move(source, target, digest)

    def matches(self, path, digest):
        if path not in self.files:
            return False
        if hashlib.sha256(self.files[path]).hexdigest() != digest:
            raise RuntimeError("HASH_CONFLICT")
        return True

    def trash_exchange_file(self, path, digest):
        if self.matches(path, digest):
            self.files.pop(path)
            self.deleted.append(path)
        if self.fail_delete:
            self.fail_delete = False
            raise RuntimeError("network after delete")

    def move_folder(self, source, target):
        self.folders.update(target + p[len(source) :] for p in list(self.folders) if p == source or p.startswith(source + "/"))
        self.folders.difference_update(p for p in list(self.folders) if p == source or p.startswith(source + "/"))
        for path in list(self.files):
            if path.startswith(source + "/"):
                self.files[target + path[len(source) :]] = self.files.pop(path)
                self.remember_parents(target + path[len(source) :])

    def folder_items(self, path):
        for file in self.files:
            self.remember_parents(file)
        if path not in self.folders:
            return None
        return [
            {"path": p, "type": "file", "sha256": hashlib.sha256(data).hexdigest()}
            for p, data in self.files.items()
            if str(PurePosixPath(p).parent) == path
        ] + [{"path": p, "type": "dir"} for p in sorted(self.folders) if str(PurePosixPath(p).parent) == path]

    def trash_empty_photo_folder(self, path):
        if self.folder_items(path) == []:
            self.folders.remove(path)
            self.deleted_folders.append(path)

    def trash_legacy_exchange_folder(self, path, expected_files):
        files = [p for p in self.files if p.startswith(path + "/")]
        for file in files:
            if not file.endswith(".json") or file not in expected_files:
                raise RuntimeError("LEGACY_EXCHANGE_UNMANAGED_FILE")
            assert self.matches(file, expected_files[file])
        for file in files:
            self.files.pop(file)
            self.deleted.append(file)
        self.folders.difference_update(p for p in list(self.folders) if p == path or p.startswith(path + "/"))
        if self.fail_delete:
            self.fail_delete = False
            raise RuntimeError("network after delete")


def generations(db, count=5):
    setup_chat(db)
    intake_photo(db)
    disk = Disk()
    publications = []
    for _ in range(count):
        pub = publication(db)
        publish(pub.id, disk)
        db.refresh(pub)
        pub.finished_at = now() - timedelta(hours=50)
        db.commit()
        publications.append(pub)
    return disk, publications


def test_retention_leaves_three_verified_generations_and_only_removes_json(db):
    disk, pubs = generations(db)
    original = "disk:/MAX_PHOTOS/date/district/photo.jpg"
    disk.files[original] = b"original"
    collect_generations(disk)
    db.expire_all()
    assert [p.status for p in pubs] == ["PRUNED", "PRUNED", "DONE", "DONE", "DONE"]
    assert disk.files[original] == b"original"
    for pub in pubs[2:]:
        assert pub.index_path in disk.files
        assert all(f"{pub.payload['root']}/{f['file_ref']}" in disk.files for f in pub.payload["files"])
    assert all("/MAX_PHOTOS_ARM_EXCHANGE/" in path and path.endswith(".json") for path in disk.deleted)
    collect_generations(disk)  # idempotent after DB payload compaction


def test_read_window_is_counted_from_displacement_not_old_file_age(db):
    disk, pubs = generations(db, 4)
    pubs[-1].finished_at = now()
    db.commit()
    collect_generations(disk)
    assert not disk.deleted
    db.refresh(pubs[0])
    assert pubs[0].status == "DONE"


def test_many_recent_publications_do_not_prevent_cleanup_of_long_displaced_generations(db):
    disk, pubs = generations(db, 6)
    pubs[-1].finished_at = now()
    db.commit()
    collect_generations(disk)
    db.expire_all()
    assert pubs[0].status == "PRUNED" and pubs[1].status == "PRUNED"
    assert pubs[2].status == "DONE"  # was displaced only by the sixth generation, just now


def test_unhealthy_new_generation_cannot_remove_fallbacks(db):
    disk, pubs = generations(db, 4)
    disk.files.pop(pubs[-1].index_path)
    with pytest.raises(RuntimeError, match="NOT_HEALTHY"):
        collect_generations(disk)
    assert not disk.deleted


def test_cleanup_crash_is_resumable_and_index_is_removed_first(db):
    disk, pubs = generations(db, 4)
    disk.fail_delete = True
    with pytest.raises(RuntimeError, match="network"):
        collect_generations(disk)
    assert disk.deleted == [pubs[0].index_path]
    db.refresh(pubs[0])
    assert pubs[0].status == "PRUNING"
    collect_generations(disk)
    db.refresh(pubs[0])
    assert pubs[0].status == "PRUNED"
    assert all(p.index_path in disk.files for p in pubs[1:])


def test_archive_organization_moves_existing_test_materials_and_updates_refs(db):
    setup_chat(db)
    setup_district(db)
    photo = intake_photo(db)
    disk = Disk()
    process_photo(photo.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(photo)
    old = f"disk:/MAX_PHOTOS/ТЕСТОВЫЕ/2026-09-30/12_мкр/test_{photo.id}.png"
    disk.files[old] = disk.files.pop(photo.yandex_disk_path)
    photo.yandex_disk_path = old
    state = db.get(ExchangeState, 1)
    state.intake_cohort = "production"
    db.commit()
    working = intake_photo(db, "working")
    process_photo(working.id, FakeMax("blue"), disk, GoodOCR(), GoodAI())
    db.refresh(working)
    working_path = working.yandex_disk_path
    legacy_root = "disk:/MAX_PHOTOS/ARM_EXCHANGE/test/source"
    legacy_index = legacy_root + "/indexes/1.json"
    disk.files[legacy_index] = b"legacy-json"
    pub = Publication(
        cohort="test",
        status="DONE",
        index_path=legacy_index,
        payload={
            "root": legacy_root,
            "files": [{"file_ref": "indexes/1.json", "sha256": hashlib.sha256(b"legacy-json").hexdigest()}],
        },
    )
    db.add(pub)
    db.commit()
    before_version, digest = photo.version, photo.sha256
    organize_archive(disk)
    db.refresh(photo)
    db.refresh(pub)
    assert photo.yandex_disk_path.startswith("disk:/MAX_PHOTOS_TRAINING/")
    assert photo.version > before_version and photo.sha256 == digest
    assert old not in disk.files and photo.yandex_disk_path in disk.files
    assert working_path in disk.files
    assert pub.index_path is None and pub.payload is None and pub.status == "RETIRED"
    assert legacy_index not in disk.files
    assert not any("/legacy/ARM_EXCHANGE/" in p for p in disk.files)
    assert not any("/MAX_PHOTOS/ARM_EXCHANGE/" in p or "/MAX_PHOTOS/ТЕСТОВЫЕ/" in p for p in disk.files)
    before = dict(disk.files)
    organize_archive(disk)
    assert disk.files == before


def test_json_contract_has_original_names_and_separate_roots(db):
    setup_chat(db)
    photo = intake_photo(db)
    disk = Disk()
    pub = publication(db)
    publish(pub.id, disk)
    db.refresh(pub)
    part_file = pub.payload["files"][0]["document"]
    assert "produced_at" in part_file and "published_at" not in part_file
    assert part_file["cohort"] == part_file["items"][0]["cohort"] == "training"
    assert part_file["items"][0]["source_photo_id"] == str(photo.id)
    assert pub.payload["root"].startswith("disk:/MAX_PHOTOS_ARM_EXCHANGE/training/")
    # Header naming changes do not invent another source identity for existing data.
    assert part_file["source_instance_id"].endswith("-test")
    Partition.model_validate(part_file)


@pytest.mark.parametrize("root", ["MAX_PHOTOS", "MAX_PHOTOS/subfolder", ".."])
def test_separate_root_configuration_is_validated(root):
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="test", yandex_exchange_root=root)
    assert settings().training_folder != settings().exchange_folder != settings().yandex_disk_root


def test_relocation_journal_recovers_after_remote_move_and_later_metadata_edit(db):
    from datetime import date

    setup_chat(db)
    setup_district(db)
    photo = intake_photo(db)

    class CrashMoveDisk(Disk):
        crash = False

        def move(self, source, target, digest):
            super().move(source, target, digest)
            if self.crash:
                self.crash = False
                raise RuntimeError("crash after move")

    disk = CrashMoveDisk()
    process_photo(photo.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(photo)
    old = f"disk:/MAX_PHOTOS/2026-09-30/old_{photo.id}.png"
    disk.files[old] = disk.files.pop(photo.yandex_disk_path)
    photo.yandex_disk_path = old
    db.commit()
    disk.crash = True
    with pytest.raises(RuntimeError, match="crash after move"):
        organize_archive(disk)
    db.refresh(photo)
    assert photo.yandex_disk_path == old
    photo.photo_date = date(2026, 10, 2)
    db.commit()
    organize_archive(disk)
    db.refresh(photo)
    assert photo.yandex_disk_path in disk.files
    assert "/2026-10-02/" in photo.yandex_disk_path  # recover old move, then apply the correction
    assert photo.storage_status == "SYNCED"
    assert len(disk.files) == 1


def test_organizer_resumes_transfer_when_correction_restores_the_old_path(db):
    from datetime import date

    from app.domain import audit

    setup_chat(db)
    district = setup_district(db)
    photo = intake_photo(db)
    disk = Disk()
    process_photo(photo.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(photo)
    source = photo.yandex_disk_path
    photo.photo_date = date(2026, 10, 2)
    intermediate = storage_path(photo, district.name)
    audit(db, None, "STORAGE_TRANSFER_PLANNED", "photo", photo.id,
          {"path": source}, {"path": intermediate, "sha256": photo.sha256})
    db.commit()
    # Remote move succeeded; DB path did not commit, and the operator then restored the date.
    disk.move(source, intermediate, photo.sha256)
    photo.photo_date = date(2026, 9, 30)
    db.commit()
    assert storage_path(photo, district.name) == source
    organize_archive(disk)
    db.refresh(photo)
    assert photo.yandex_disk_path == source and disk.matches(source, photo.sha256)
    assert intermediate not in disk.files and len(disk.files) == 1


def seed_old_exchange(db, disk, *, copied=False):
    root = (
        "disk:/MAX_PHOTOS_ARM_EXCHANGE/legacy/ARM_EXCHANGE" if copied else "disk:/MAX_PHOTOS/ARM_EXCHANGE"
    ) + "/test/old-source"
    index = root + "/indexes/1.json"
    data = b'{"old_snapshot":true}'
    disk.files[index] = data
    pub = Publication(
        cohort="test",
        status="DONE",
        index_path=index,
        payload={
            "root": root,
            "files": [{"file_ref": "indexes/1.json", "sha256": hashlib.sha256(data).hexdigest()}],
        },
    )
    db.add(pub)
    db.commit()
    return pub, root


def test_old_legacy_copy_is_retired_but_live_json_stays_on_disk(db):
    disk, current = generations(db, 1)
    pub, root = seed_old_exchange(db, disk, copied=True)
    live = dict(disk.files)
    live.pop(pub.index_path)
    organize_archive(disk)
    db.refresh(pub)
    assert pub.status == "RETIRED"
    assert disk.files == live
    assert current[0].index_path in disk.files
    assert not any(p.startswith(root) for p in disk.files)


def test_unmanaged_file_blocks_cleanup_before_any_json_is_removed(db):
    disk = Disk()
    pub, root = seed_old_exchange(db, disk)
    disk.files[root + "/original.jpg"] = b"photo"
    before = dict(disk.files)
    with pytest.raises(RuntimeError, match="UNMANAGED"):
        organize_archive(disk)
    assert disk.files == before and not disk.deleted
    db.refresh(pub)
    assert pub.status == "DONE"


def test_old_json_cleanup_is_resumable_after_trash_before_commit(db):
    disk = Disk()
    pub, _ = seed_old_exchange(db, disk)
    old_index = pub.index_path
    disk.fail_delete = True
    with pytest.raises(RuntimeError, match="network"):
        organize_archive(disk)
    db.refresh(pub)
    assert pub.status == "DONE" and pub.index_path == old_index
    assert old_index not in disk.files
    organize_archive(disk)
    db.refresh(pub)
    assert pub.status == "RETIRED" and pub.payload is None


def test_original_reference_under_service_tree_is_never_removed(db):
    from app.models import Inbox, Photo

    disk = Disk()
    pub, root = seed_old_exchange(db, disk)
    inbox = Inbox(max_chat_id=123, message_id="reference", payload={})
    db.add(inbox)
    db.flush()
    db.add(
        Photo(
            inbox_id=inbox.id,
            attachment_index=0,
            max_chat_id=123,
            chat_name="chat",
            max_message_id="reference",
            cohort="production",
            yandex_disk_path=root + "/original.jpg",
        )
    )
    db.commit()
    with pytest.raises(RuntimeError, match="ORIGINAL_REFERENCE"):
        organize_archive(disk)
    assert pub.index_path in disk.files and not disk.deleted


@pytest.mark.parametrize("cohort", ["test", "production"])
@pytest.mark.parametrize("spam", [False, True])
def test_all_legacy_photos_move_without_chat_and_keep_identity_and_metadata(db, cohort, spam):
    from app.media import media_path

    setup_chat(db)
    district = setup_district(db)
    state = db.get(ExchangeState, 1)
    state.intake_cohort = cohort
    db.commit()
    photo = intake_photo(db)
    disk = Disk()
    process_photo(photo.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(photo)
    old_root = "MAX_PHOTOS_TRAINING" if cohort == "test" else "MAX_PHOTOS"
    old = f"disk:/{old_root}/{'СПАМ/' if spam else ''}2026-09-30/Чат_1/12_мкр/old_{photo.id}.png"
    disk.files[old] = disk.files.pop(photo.yandex_disk_path)
    photo.archive_layout = "legacy"
    photo.yandex_disk_path = old
    if spam:
        photo.is_spam, photo.status = True, "SPAM"
    db.commit()
    saved = (photo.id, photo.sha256, photo.cohort, photo.work_type, photo.ai_result, photo.photo_date)
    before_version = photo.version
    preview_bytes = media_path(photo.id, preview=True).read_bytes()

    organize_archive(disk)
    db.refresh(photo)
    desired = storage_path(photo, district.name)
    assert photo.yandex_disk_path == desired and "/Чат_1/" not in desired
    assert old not in disk.files and desired in disk.files
    assert hashlib.sha256(disk.files[desired]).hexdigest() == photo.sha256
    assert (photo.id, photo.sha256, photo.cohort, photo.work_type, photo.ai_result, photo.photo_date) == saved
    assert photo.version > before_version
    assert media_path(photo.id, preview=True).read_bytes() == preview_bytes
    assert old.rsplit("/", 1)[0] in disk.deleted_folders
    assert all(root not in disk.deleted_folders for root in ("disk:/MAX_PHOTOS", "disk:/MAX_PHOTOS_TRAINING", "disk:/MAX_PHOTOS_SPAM"))
    if spam:
        expected_cohort = "training" if cohort == "test" else "production"
        assert desired.startswith(f"disk:/MAX_PHOTOS_SPAM/{expected_cohort}/")
    version = photo.version
    organize_archive(disk)
    db.refresh(photo)
    assert photo.version == version and len(disk.files) == 1

    pub = publication(db, cohort)
    publish(pub.id, disk)
    db.refresh(pub)
    record = pub.payload["files"][0]["document"]["items"][0]
    assert record["source_photo_id"] == str(photo.id)
    assert record["source_version"] == photo.version and record["original_disk_path"] == desired


def test_organizer_preserves_untracked_files_and_only_prunes_empty_directories(db):
    disk = Disk()
    empty = "disk:/MAX_PHOTOS_TRAINING/2026-04-20/ручная/12_мкр"
    disk.remember_parents(empty + "/removed.jpg")
    file = "disk:/MAX_PHOTOS_TRAINING/2026-04-21/ручная/keep.jpg"
    disk.files[file] = b"unknown file"
    organize_archive(disk)
    assert disk.files[file] == b"unknown file"
    assert empty in disk.deleted_folders
    assert "disk:/MAX_PHOTOS_TRAINING/2026-04-20/ручная" in disk.deleted_folders
    assert "disk:/MAX_PHOTOS_TRAINING/2026-04-21/ручная" not in disk.deleted_folders
    assert "disk:/MAX_PHOTOS_TRAINING" not in disk.deleted_folders


def test_missing_legacy_original_is_reported_without_losing_preview_or_blocking_other_moves(db):
    from app.media import media_path

    setup_chat(db)
    photos = [intake_photo(db, mid) for mid in ("missing", "available")]
    disk = Disk()
    for photo, color in zip(photos, ("green", "blue"), strict=True):
        process_photo(photo.id, FakeMax(color), disk, GoodOCR(), GoodAI())
        db.refresh(photo)
        source = f"disk:/MAX_PHOTOS/2026-09-30/ручная/old_{photo.id}.png"
        disk.files[source] = disk.files.pop(photo.yandex_disk_path)
        photo.yandex_disk_path = source
    db.commit()
    missing, available = photos
    disk.files.pop(missing.yandex_disk_path)
    organize_archive(disk)
    db.refresh(missing)
    db.refresh(available)
    assert missing.processing_error == "ORIGINAL_MISSING" and missing.storage_status == "ERROR"
    assert media_path(missing.id, preview=True).is_file()
    assert available.storage_status == "SYNCED" and available.yandex_disk_path in disk.files
    assert "/ручная/" not in available.yandex_disk_path


@pytest.mark.parametrize("root", ["MAX_PHOTOS", "MAX_PHOTOS_TRAINING", "MAX_PHOTOS_ARM_EXCHANGE", "MAX_PHOTOS/SPAM", ".."])
def test_spam_root_is_separate_and_customizable(root):
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="test", yandex_spam_root=root)
    assert Settings(_env_file=None, app_env="test", yandex_spam_root="SPAM").spam_folder == "SPAM"


def test_archive_api_queues_current_layout_once_and_reports_spam_root(admin, db):
    from sqlalchemy import select

    from app.exchange_housekeeping import ARCHIVE_JOB_KEY
    from app.models import Job

    assert admin.post("/api/exchange/organize").status_code == 202
    assert admin.post("/api/exchange/organize").status_code == 202
    jobs = list(db.scalars(select(Job).where(Job.dedupe_key == ARCHIVE_JOB_KEY)))
    assert len(jobs) == 1 and jobs[0].status == "PENDING"
    state = admin.get("/api/exchange").json()
    assert state["spam_root"] == "disk:/MAX_PHOTOS_SPAM" and state["organizing"] == "PENDING"


def test_layout_migration_updates_legacy_flag_and_schedules_one_resumable_job(db):
    import runpy
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import select

    from app.exchange_housekeeping import ARCHIVE_JOB_KEY
    from app.models import Job

    setup_chat(db)
    photo = intake_photo(db)
    photo.archive_layout = "legacy"
    db.commit()
    version, cohort = photo.version, photo.cohort
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic/versions/0010_unified_archive_layout.py"))
    with Operations.context(MigrationContext.configure(db.connection())):
        migration["upgrade"]()
        migration["upgrade"]()
    db.commit()
    db.refresh(photo)
    assert photo.archive_layout == "district_v1" and photo.yandex_disk_path is None
    assert photo.version == version and photo.cohort == cohort
    assert len(list(db.scalars(select(Job).where(Job.dedupe_key == ARCHIVE_JOB_KEY)))) == 1
