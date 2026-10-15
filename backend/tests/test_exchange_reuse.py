"""Changed sections only, with independent retention and protection of shared references."""

import copy
import json
import runpy
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, select
from test_exchange import index_and_items, publication
from test_exchange_housekeeping import Disk
from test_integration import intake_photo, setup_chat, setup_district

from app.domain import now
from app.exchange import Index, prepare, publish
from app.exchange_files import checked_files
from app.exchange_housekeeping import collect_generations
from app.models import ExchangeFile, ExchangeState, Job, Photo

pytestmark = pytest.mark.integration


def two_days(db):
    setup_chat(db)
    first = intake_photo(db)
    second = Photo(
        inbox_id=first.inbox_id,
        attachment_index=1,
        attachment={},
        max_chat_id=123,
        chat_name=first.chat_name,
        max_message_id=first.max_message_id,
        received_at=first.received_at - timedelta(days=1),
    )
    db.add(second)
    db.commit()
    return first, second


def completed(db, disk):
    pub = publication(db)
    publish(pub.id, disk)
    db.refresh(pub)
    pub.finished_at = now() - timedelta(hours=50)
    db.commit()
    return pub, Index.model_validate_json(disk.files[pub.index_path])


def test_unchanged_publish_uploads_only_index_and_keeps_original_partition_timestamp(db):
    two_days(db)
    disk = Disk()
    first, before = completed(db, disk)
    old_files = dict(disk.files)
    uploads = disk.upload_calls
    second, after = completed(db, disk)
    assert disk.upload_calls == uploads + 1
    assert set(disk.files) - old_files.keys() == {second.index_path}
    assert after.partitions == before.partitions and after.dictionaries == before.dictionaries
    assert after.as_of > before.as_of
    assert all(disk.files[path] == data for path, data in old_files.items())
    assert after.index_generation_id != before.index_generation_id
    assert first.payload["files"][:-1] == second.payload["files"][:-1]


def test_correction_rewrites_only_received_day_and_preserves_source_identity(db):
    _, photo = two_days(db)
    disk = Disk()
    first, before = completed(db, disk)
    _, old_records = index_and_items(disk, first, db)
    uploads = disk.upload_calls
    photo.photo_date = date(2020, 1, 1)
    photo.latitude, photo.longitude = 61.1, 72.6
    db.commit()
    second, after = completed(db, disk)
    _, new_records = index_and_items(disk, second, db)
    assert disk.upload_calls == uploads + 2  # one day plus the index
    assert after.partitions[0] != before.partitions[0]
    assert after.partitions[0].received_date == before.partitions[0].received_date
    assert after.partitions[1] == before.partitions[1]
    assert after.dictionaries == before.dictionaries
    old = next(p for p in old_records if p.source_photo_id == str(photo.id))
    new = next(p for p in new_records if p.source_photo_id == str(photo.id))
    assert new.source_version > old.source_version and new.photo_date == date(2020, 1, 1)


def test_dictionary_change_does_not_rewrite_photo_partitions(db):
    two_days(db)
    district = setup_district(db)
    disk = Disk()
    _, before = completed(db, disk)
    uploads = disk.upload_calls
    district.name = "Новое название"
    db.commit()
    _, after = completed(db, disk)
    assert disk.upload_calls == uploads + 2
    assert after.partitions == before.partitions and after.dictionaries != before.dictionaries


def test_new_day_does_not_rewrite_previous_days(db):
    first, _ = two_days(db)
    disk = Disk()
    _, before = completed(db, disk)
    db.add(
        Photo(
            inbox_id=first.inbox_id,
            attachment_index=2,
            attachment={},
            max_chat_id=123,
            chat_name=first.chat_name,
            max_message_id=first.max_message_id,
            received_at=first.received_at + timedelta(days=1),
        )
    )
    db.commit()
    uploads = disk.upload_calls
    _, after = completed(db, disk)
    assert disk.upload_calls == uploads + 2
    assert after.partitions[:-1] == before.partitions


def test_shared_file_is_restored_with_frozen_bytes_if_missing(db):
    two_days(db)
    disk = Disk()
    first, before = completed(db, disk)
    ref = before.partitions[0]
    path = f"{first.payload['root']}/{ref.file_ref}"
    original = disk.files.pop(path)
    _, after = completed(db, disk)
    assert after.partitions == before.partitions and disk.files[path] == original


def test_corrupt_shared_file_blocks_new_index_instead_of_overwriting_it(db):
    two_days(db)
    disk = Disk()
    first, before = completed(db, disk)
    path = f"{first.payload['root']}/{before.partitions[0].file_ref}"
    disk.files[path] = b"unexpected data"
    second = publication(db)
    with pytest.raises(RuntimeError, match="HASH_CONFLICT"):
        publish(second.id, disk)
    db.refresh(second)
    assert second.status == "RETRY" and second.index_path not in disk.files
    assert disk.files[path] == b"unexpected data"


def test_three_versions_per_day_survive_retirement_of_their_indexes(db):
    first, second = two_days(db)
    disk = Disk()
    day_versions = []
    pubs = []
    for n in range(4):
        second.photo_date = date(2020, 1, n + 1)
        db.commit()
        pub, index = completed(db, disk)
        pubs.append(pub)
        day_versions.append(f"{pub.payload['root']}/{index.partitions[0].file_ref}")
    for n in range(4):
        first.photo_date = date(2021, 1, n + 1)
        db.commit()
        pub, _ = completed(db, disk)
        pubs.append(pub)
    collect_generations(disk)
    db.expire_all()
    assert all(pub.status == "PRUNED" for pub in pubs[:-3])
    assert day_versions[0] not in disk.files
    assert all(path in disk.files for path in day_versions[1:])
    # The two old fallbacks have no surviving index but are still retained for this day.
    assert pubs[1].payload is None and pubs[2].payload is None
    root = pubs[-1].payload["root"]
    assert len([p for p in disk.files if p.startswith(root + "/dictionaries/")]) == 1
    assert len([p for p in disk.files if p.startswith(root + "/snapshots/")]) == 6
    collect_generations(disk)
    latest, _ = completed(db, disk)  # retained file whose creator's payload was cleared remains reusable
    index_and_items(disk, latest, db)


def test_day_retention_window_starts_when_fourth_data_version_is_published(db):
    _, photo = two_days(db)
    disk = Disk()
    for n in range(3):
        photo.photo_date = date(2020, 1, n + 1)
        db.commit()
        pub, index = completed(db, disk)
        if n == 0:
            oldest = f"{pub.payload['root']}/{index.partitions[0].file_ref}"
    for _ in range(4):
        completed(db, disk)
    collect_generations(disk)
    photo.photo_date = date(2020, 1, 4)
    db.commit()
    newest, _ = completed(db, disk)
    newest.finished_at = now()
    db.commit()
    collect_generations(disk)
    assert oldest in disk.files  # old index retired long ago, but fourth data version is fresh
    newest.finished_at = now() - timedelta(hours=50)
    db.commit()
    collect_generations(disk)
    assert oldest not in disk.files


def test_missing_historical_fallback_blocks_cleanup_even_without_a_live_index(db):
    _, photo = two_days(db)
    disk = Disk()
    paths = []
    for n in range(3):
        photo.photo_date = date(2020, 1, n + 1)
        db.commit()
        pub, index = completed(db, disk)
        paths.append(f"{pub.payload['root']}/{index.partitions[0].file_ref}")
    for _ in range(4):
        completed(db, disk)
    collect_generations(disk)
    disk.files.pop(paths[0])
    before = list(disk.deleted)
    completed(db, disk)
    with pytest.raises(RuntimeError, match="NOT_HEALTHY"):
        collect_generations(disk)
    assert disk.deleted == before


def test_frozen_retry_protects_old_shared_file_until_it_is_superseded(db):
    first, second = two_days(db)
    disk = Disk()
    owner, index = completed(db, disk)
    protected = f"{owner.payload['root']}/{index.partitions[0].file_ref}"
    retry = publication(db)
    prepare(retry.id)
    for n in range(4):
        second.photo_date = date(2020, 1, n + 1)
        first.photo_date = date(2021, 1, n + 1)
        db.commit()
        completed(db, disk)
    collect_generations(disk)
    assert protected in disk.files  # not one of the three latest versions; frozen publication needs it
    publish(retry.id, disk)
    db.refresh(retry)
    assert retry.status == "SUPERSEDED"
    retry.finished_at = now() - timedelta(hours=50)
    db.commit()
    collect_generations(disk)
    assert protected not in disk.files


def test_existing_manifest_is_imported_and_reused_without_republishing_old_files(db):
    two_days(db)
    disk = Disk()
    first, before = completed(db, disk)
    db.execute(delete(ExchangeFile))
    first.payload = {k: v for k, v in first.payload.items() if k != "registry_version"}
    db.commit()
    uploads = disk.upload_calls
    _, after = completed(db, disk)
    assert disk.upload_calls == uploads + 1
    assert after.partitions == before.partitions and after.dictionaries == before.dictionaries
    assert len(list(db.scalars(select(ExchangeFile)))) == 3


def test_old_full_generations_are_imported_then_cleaned_per_section(db, monkeypatch):
    two_days(db)
    disk = Disk()
    pubs = []
    # The previous publisher made a fresh file for every section, even when content was identical.
    with monkeypatch.context() as patch:
        patch.setattr("app.exchange.content_hash", lambda _: "always-new-legacy-generation")
        for _ in range(5):
            pub, _ = completed(db, disk)
            pubs.append(pub)
    db.execute(delete(ExchangeFile))
    for pub in pubs:
        pub.payload = {k: v for k, v in pub.payload.items() if k != "registry_version"}
    db.commit()
    collect_generations(disk)
    db.expire_all()
    assert [p.status for p in pubs] == ["PRUNED", "PRUNED", "DONE", "DONE", "DONE"]
    root = pubs[-1].payload["root"]
    assert len([p for p in disk.files if p.startswith(root + "/snapshots/")]) == 6
    assert len([p for p in disk.files if p.startswith(root + "/dictionaries/")]) == 3
    uploads = disk.upload_calls
    latest, _ = completed(db, disk)
    assert disk.upload_calls == uploads + 1
    index_and_items(disk, latest, db)


def test_training_and_production_never_share_dictionary_files(db):
    two_days(db)
    state = db.get(ExchangeState, 1)
    state.intake_cohort = "production"
    db.commit()
    intake_photo(db, "production-photo")
    disk = Disk()
    training, _ = completed(db, disk)
    production = publication(db, "production")
    publish(production.id, disk)
    db.refresh(production)
    assert training.payload["root"] != production.payload["root"]
    assert all(f["document"]["cohort"] == "production" for f in production.payload["files"])
    index_and_items(disk, production, db)


def test_invalid_reference_cannot_be_registered_or_deleted(db):
    two_days(db)
    disk = Disk()
    pub, _ = completed(db, disk)
    payload = copy.deepcopy(pub.payload)
    payload["files"][0]["file_ref"] = "../../MAX_PHOTOS/original.json"
    pub.payload = payload
    db.commit()
    with pytest.raises(ValueError, match="INVALID_EXCHANGE_REFERENCE"):
        collect_generations(disk)
    assert not disk.deleted


def test_data_deletion_crash_resumes_without_losing_shared_fallbacks(db):
    _, photo = two_days(db)

    class CrashDisk(Disk):
        crash = True

        def trash_exchange_file(self, path, digest):
            super().trash_exchange_file(path, digest)
            if "/snapshots/" in path and self.crash:
                self.crash = False
                raise RuntimeError("network after data deletion")

    disk = CrashDisk()
    paths = []
    for n in range(4):
        photo.photo_date = date(2020, 1, n + 1)
        db.commit()
        pub, index = completed(db, disk)
        paths.append(f"{pub.payload['root']}/{index.partitions[0].file_ref}")
    with pytest.raises(RuntimeError, match="network after data"):
        collect_generations(disk)
    collect_generations(disk)
    assert paths[0] not in disk.files and all(p in disk.files for p in paths[1:])
    assert not list(db.scalars(select(ExchangeFile).where(ExchangeFile.status == "DELETING")))


def test_registry_migration_does_not_allow_unsafe_rollback_after_publication(db):
    two_days(db)
    completed(db, Disk())
    migration = runpy.run_path(
        str(Path(__file__).parents[1] / "alembic/versions/0011_shared_exchange_files.py")
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        with pytest.raises(RuntimeError, match="current publisher"):
            migration["downgrade"]()


def test_upgrade_queues_cleanup_and_preserves_preexisting_manifest(db):
    two_days(db)
    disk = Disk()
    pub, _ = completed(db, disk)
    db.execute(delete(ExchangeFile))
    pub.payload = {k: v for k, v in pub.payload.items() if k != "registry_version"}
    before = copy.deepcopy(pub.payload)
    db.commit()
    migration = runpy.run_path(
        str(Path(__file__).parents[1] / "alembic/versions/0011_shared_exchange_files.py")
    )
    with Operations.context(MigrationContext.configure(db.connection())):
        migration["downgrade"]()
        migration["upgrade"]()
    db.commit()
    db.refresh(pub)
    assert pub.payload == before
    job = db.scalar(select(Job).where(Job.dedupe_key == "exchange-gc:shared-files-v1"))
    assert job.kind == "EXCHANGE_GC" and job.status == "PENDING"
    uploads = disk.upload_calls
    collect_generations(disk)
    assert disk.upload_calls == uploads and not disk.deleted
    assert len(list(db.scalars(select(ExchangeFile)))) == 3


def test_partial_upload_orphan_is_cleaned_after_supersession_and_read_window(db):
    two_days(db)
    disk = Disk()
    orphan = publication(db)
    disk.fail = True
    with pytest.raises(RuntimeError, match="connection loss"):
        publish(orphan.id, disk)
    orphan_paths = set(disk.files)
    assert len(orphan_paths) == 1
    disk.fail = False
    for _ in range(3):
        completed(db, disk)
    publish(orphan.id, disk)
    db.refresh(orphan)
    assert orphan.status == "SUPERSEDED"
    collect_generations(disk)
    assert orphan_paths.issubset(disk.files)  # safety window has not elapsed
    orphan.finished_at = now() - timedelta(hours=50)
    db.commit()
    collect_generations(disk)
    db.refresh(orphan)
    assert orphan.status == "PRUNED" and orphan_paths.isdisjoint(disk.files)
    assert all(
        item.status == "DELETED"
        for item in db.scalars(select(ExchangeFile).where(ExchangeFile.publication_id == orphan.id))
    )


def test_published_documents_still_match_existing_contract(db):
    two_days(db)
    disk = Disk()
    completed(db, disk)
    pub, _ = completed(db, disk)
    assert checked_files(pub, pub.payload["root"]) == pub.payload["files"]
    for file in pub.payload["files"]:
        assert json.loads(disk.files[f"{pub.payload['root']}/{file['file_ref']}"]) == file["document"]
