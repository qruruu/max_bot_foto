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
        cohort="test", status="DONE", index_path=legacy_index, payload={"root": legacy_root, "files": []}
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
    assert pub.index_path.startswith("disk:/MAX_PHOTOS_ARM_EXCHANGE/legacy/")
    assert disk.files[pub.index_path] == b"legacy-json"
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
    assert "/2026-09-30/" in photo.yandex_disk_path  # recovered persisted destination
    assert photo.storage_status == "PENDING"  # SYNC will then move to the newly corrected date
