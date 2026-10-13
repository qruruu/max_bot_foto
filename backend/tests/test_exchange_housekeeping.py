import hashlib
from datetime import timedelta

import pytest
from test_exchange import publication
from test_integration import FakeDisk, FakeMax, GoodAI, GoodOCR, intake_photo, setup_chat, setup_district

from app.config import Settings, settings
from app.domain import now
from app.exchange import Partition, publish
from app.exchange_housekeeping import collect_generations, organize_archive
from app.models import ExchangeState, Publication
from app.processing import process_photo

pytestmark = pytest.mark.integration


class Disk(FakeDisk):
    def __init__(self):
        super().__init__()
        self.deleted = []
        self.fail_delete = False

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
        for path in list(self.files):
            if path.startswith(source + "/"):
                self.files[target + path[len(source) :]] = self.files.pop(path)

    def folder_items(self, path):
        return [
            {"path": p, "type": "file", "sha256": hashlib.sha256(data).hexdigest()}
            for p, data in self.files.items()
            if p.startswith(path + "/")
        ] or None

    def trash_legacy_exchange_folder(self, path, expected_files):
        files = [p for p in self.files if p.startswith(path + "/")]
        for file in files:
            if not file.endswith(".json") or file not in expected_files:
                raise RuntimeError("LEGACY_EXCHANGE_UNMANAGED_FILE")
            assert self.matches(file, expected_files[file])
        for file in files:
            self.files.pop(file)
            self.deleted.append(file)
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
