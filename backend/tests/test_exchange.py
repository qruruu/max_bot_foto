"""Transport contract, isolation, classifier snapshots and durable publication recovery."""

import hashlib
import runpy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_integration import FakeDisk, FakeMax, GoodAI, GoodOCR, intake_photo, setup_chat, setup_district

from app.domain import now
from app.exchange import Dictionary, Index, Partition, prepare, publish
from app.models import ExchangeState, Job, Photo, Publication
from app.processing import process_photo

pytestmark = pytest.mark.integration


def publication(db, cohort="test"):
    pub = Publication(cohort=cohort)
    db.add(pub)
    db.commit()
    return pub


@pytest.mark.parametrize("status", ["RETIRED", "PRUNED", "PRUNING", "SUPERSEDED", "DONE"])
def test_finished_publications_cannot_be_recreated_by_a_stale_job(db, status):
    pub, disk = publication(db), FakeDisk()
    pub.status = status
    db.commit()
    publish(pub.id, disk)
    db.refresh(pub)
    assert pub.status == status and pub.payload is None
    assert not disk.files and disk.upload_calls == 0


def index_and_items(disk, pub, db):
    db.refresh(pub)
    doc = Index.model_validate_json(disk.files[pub.index_path])
    assert doc.photo_count == sum(ref.photo_count for ref in doc.partitions)
    base = pub.payload["root"]
    items = []
    for ref in doc.partitions:
        data = disk.files[f"{base}/{ref.file_ref}"]
        assert hashlib.sha256(data).hexdigest() == ref.sha256
        part = Partition.model_validate_json(data)
        assert len(part.items) == ref.photo_count == part.photo_count
        assert part.source_instance_id == doc.source_instance_id
        assert part.cohort == doc.cohort
        items += part.items
    Dictionary.model_validate_json(disk.files[f"{base}/{doc.dictionaries.file_ref}"])
    return doc, items


def test_edit_existing_chat_and_snapshot_rule_before_queue_processing(db, admin):
    chat = setup_chat(db)
    setup_district(db)
    first = intake_photo(db, "before")
    response = admin.put(
        f"/api/chats/{chat.id}",
        json={
            "max_chat_id": 123,
            "name": chat.name,
            "active": True,
            "cv_work_type_enabled": False,
            "fixed_work_type_code": "SNOW_MECHANICAL",
        },
    )
    assert response.status_code == 200
    db.refresh(chat)
    assert chat.work_rule_version == 2
    second = intake_photo(db, "after")
    # Editing the name with an old client preserves the configured classifier rule.
    assert (
        admin.put(
            f"/api/chats/{chat.id}",
            json={
                "max_chat_id": 123,
                "name": "Renamed",
                "active": True,
            },
        ).status_code
        == 200
    )
    db.refresh(chat)
    assert not chat.cv_work_type_enabled and chat.work_rule_version == 2
    process_photo(first.id, FakeMax("red"), FakeDisk(), GoodOCR(), GoodAI())

    class NeverAI:
        def classify(self, path):
            pytest.fail("Fixed chats must skip work-type classifier")

    process_photo(second.id, FakeMax("blue"), FakeDisk(), GoodOCR(), NeverAI())
    db.refresh(first)
    db.refresh(second)
    assert first.classification_mode == "AI" and first.work_type == "BIN_EMPTYING"
    assert second.classification_mode == "CHAT_FIXED" and second.work_type == "SNOW_MECHANICAL"
    assert second.work_type_source == "CHAT_FIXED" and second.ai_confidence is None
    assert second.photo_date == date(2026, 9, 30) and second.latitude is not None
    assert second.sha256 and second.storage_status == "SYNCED"
    assert second.work_rule_version == 2 and first.work_rule_version == 1


def test_chat_fixed_input_and_permissions(db, admin, client):
    assert (
        admin.post(
            "/api/chats",
            json={
                "max_chat_id": 123,
                "name": "Mechanized",
                "cv_work_type_enabled": False,
            },
        ).status_code
        == 422
    )
    assert (
        admin.post(
            "/api/chats",
            json={
                "max_chat_id": 123,
                "name": "Mechanized",
                "cv_work_type_enabled": False,
                "fixed_work_type_code": "made_up",
            },
        ).status_code
        == 422
    )
    assert (
        admin.post(
            "/api/chats",
            json={
                "max_chat_id": 123,
                "name": "Mechanized",
                "cv_work_type_enabled": False,
                "fixed_work_type_code": "SNOW_MECHANICAL",
            },
        ).status_code
        == 201
    )
    chat = admin.get("/api/chats").json()[0]
    assert chat["fixed_work_type_code"] == "SNOW_MECHANICAL" and not chat["cv_work_type_enabled"]
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/exchange").status_code == 401
    client.post("/api/auth/login", json={"login": "operator", "password": "test-password-123"})
    client.headers["X-CSRF-Token"] = client.cookies["csrf"]
    assert client.get("/api/exchange").status_code == 403
    assert client.put("/api/exchange/mode", json={"cohort": "production"}).status_code == 403
    assert client.post("/api/exchange/publish", json={"cohort": "test"}).status_code == 403


def test_cutover_does_not_export_tests_or_duplicate_against_them(db, admin):
    setup_chat(db)
    setup_district(db)
    disk = FakeDisk()
    old = intake_photo(db, "test-old")
    # Old queued test photo is still a test, even when processed after cutover.
    assert admin.put("/api/exchange/mode", json={"cohort": "production"}).status_code == 200
    db.expire_all()
    new = intake_photo(db, "prod-new")
    process_photo(old.id, FakeMax(), disk, GoodOCR(), GoodAI())
    process_photo(new.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(old)
    db.refresh(new)
    assert old.cohort == "test" and "/MAX_PHOTOS_TRAINING/" in old.yandex_disk_path
    assert new.cohort == "production" and "/MAX_PHOTOS_TRAINING/" not in new.yandex_disk_path
    assert old.sha256 == new.sha256 and new.duplicate_of is None
    assert "/Чат_1/" not in new.yandex_disk_path
    dup = intake_photo(db, "prod-dup")
    process_photo(dup.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(dup)
    assert dup.duplicate_of == new.id
    test_pub, prod_pub = publication(db), publication(db, "production")
    publish(test_pub.id, disk)
    publish(prod_pub.id, disk)
    test_index, test_items = index_and_items(disk, test_pub, db)
    prod_index, prod_items = index_and_items(disk, prod_pub, db)
    assert test_index.source_instance_id != prod_index.source_instance_id
    assert [i.source_photo_id for i in test_items] == [str(old.id)]
    assert {i.source_photo_id for i in prod_items} == {str(new.id), str(dup.id)}
    assert all(i.cohort == "production" for i in prod_items)
    assert prod_items[-1].duplicate_of == str(new.id) and prod_items[-1].original_disk_path is None
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE photos SET cohort='production' WHERE id=:id"), {"id": old.id})
        db.commit()
    db.rollback()


def test_corrections_keep_received_partition_and_increment_version(db, admin):
    setup_chat(db)
    setup_district(db)
    photo = intake_photo(db)
    disk = FakeDisk()
    process_photo(photo.id, FakeMax(), disk, GoodOCR(), GoodAI())
    first = publication(db)
    publish(first.id, disk)
    old_index, old_items = index_and_items(disk, first, db)
    db.refresh(photo)
    response = admin.patch(
        f"/api/photos/{photo.id}",
        json={
            "version": photo.version,
            "photo_date": "2025-01-01",
            "work_type": "SWEEPING",
        },
    )
    assert response.status_code == 200
    db.refresh(photo)
    assert response.json()["version"] == photo.version
    second = publication(db)
    publish(second.id, disk)
    new_index, new_items = index_and_items(disk, second, db)
    assert old_index.partitions[0].received_date == new_index.partitions[0].received_date
    assert old_index.index_generation_id < new_index.index_generation_id
    assert new_items[0].source_photo_id == old_items[0].source_photo_id
    assert new_items[0].source_version > old_items[0].source_version
    assert new_items[0].photo_date == date(2025, 1, 1)
    assert new_items[0].work_type_source == "OPERATOR" and new_items[0].source_work_type_code == "SWEEPING"
    assert new_items[0].classification_mode == "AI"
    assert photo.ai_result["classification"]["work_type"] == "BIN_EMPTYING"
    assert new_items[0].storage_status == "PENDING"
    # Repeating the same index/version is a reader-side upsert, no new source records.
    records = {}
    for item in old_items + new_items + new_items:
        key = (new_index.source_instance_id, item.source_photo_id)
        if key not in records or records[key].source_version < item.source_version:
            records[key] = item
    assert len(records) == 1


def test_all_incomplete_states_and_late_photo_included(db):
    setup_chat(db)
    rows = []
    for i, status in enumerate(
        ["RECEIVED", "PROCESSING", "NEEDS_REVIEW", "ERROR", "REJECTED", "DUPLICATE", "SPAM", "FORWARDED"]
    ):
        row = intake_photo(db, f"state-{i}")
        row.status = status
        row.storage_status = (
            "ERROR"
            if status == "ERROR"
            else "NOT_REQUIRED"
            if status in ["REJECTED", "DUPLICATE", "FORWARDED"]
            else "PENDING"
        )
        row.is_spam = status == "SPAM"
        row.photo_date = now().date() - timedelta(days=2) if i == 0 else None
        rows.append(row)
    db.commit()
    pub, disk = publication(db), FakeDisk()
    publish(pub.id, disk)
    index, items = index_and_items(disk, pub, db)
    assert len(items) == len(rows)
    assert {i.status for i in items} == {r.status for r in rows}
    assert all(
        i.original_disk_path is None and i.district_id is None and i.source_work_type_code is None
        for i in items
    )
    assert items[0].photo_date < index.partitions[0].received_date
    assert all(i.photo_date is None for i in items[1:])


def test_retry_uses_frozen_payload_and_index_is_uploaded_last(db):
    setup_chat(db)
    photo = intake_photo(db)
    pub, disk = publication(db), FakeDisk()
    prepare(pub.id)
    db.refresh(pub)
    frozen = pub.payload
    index_path = pub.index_path
    disk.fail = True
    with pytest.raises(RuntimeError):
        publish(pub.id, disk)
    assert index_path not in disk.files
    db.refresh(pub)
    assert pub.status == "RETRY" and pub.payload == frozen
    photo.photo_date = date(2020, 1, 1)
    db.commit()
    disk.fail = False
    publish(pub.id, disk)
    assert list(disk.files)[-1] == index_path
    _, items = index_and_items(disk, pub, db)
    assert items[0].photo_date is None  # retry may not silently change already prepared generation
    later = publication(db)
    publish(later.id, disk)
    _, latest_items = index_and_items(disk, later, db)
    assert latest_items[0].photo_date == date(2020, 1, 1)


def test_crash_after_index_upload_reuses_same_bytes(db):
    setup_chat(db)
    intake_photo(db)
    pub = publication(db)

    class CrashDisk(FakeDisk):
        crash = True

        def upload(self, original, target, digest):
            assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
            if target in self.files:
                assert self.files[target] == original.read_bytes()
            super().upload(original, target, digest)
            if "/indexes/" in target and self.crash:
                self.crash = False
                raise RuntimeError("crash after index")

    disk = CrashDisk()
    with pytest.raises(RuntimeError):
        publish(pub.id, disk)
    index, _ = index_and_items(disk, pub, db)  # exposed index already references a complete set
    before = dict(disk.files)
    publish(pub.id, disk)
    assert disk.files == before
    db.refresh(pub)
    assert pub.status == "DONE"
    assert index.index_generation_id == f"{pub.id:020d}"


def test_older_retry_cannot_regress_newer_index_and_parallel_workers(db):
    setup_chat(db)
    intake_photo(db)
    old, newer = publication(db), publication(db)
    disk = FakeDisk()
    publish(newer.id, disk)
    before = dict(disk.files)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: publish(old.id, disk), range(2)))
    db.refresh(old)
    assert old.status == "SUPERSEDED" and before == disk.files
    latest = publication(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: publish(latest.id, disk), range(2)))
    index_and_items(disk, latest, db)
    db.refresh(latest)
    assert latest.status == "DONE"


def test_empty_production_and_button_is_durable_no_timer(db, admin):
    setup_chat(db)
    intake_photo(db)
    assert db.scalar(select(Publication.id)) is None
    first = admin.post("/api/exchange/publish", json={"cohort": "production"})
    again = admin.post("/api/exchange/publish", json={"cohort": "production"})
    assert first.status_code == 202 and first.json()["id"] == again.json()["id"]
    jobs = list(db.scalars(select(Job).where(Job.kind == "PUBLISH")))
    assert len(jobs) == 1
    pub = db.get(Publication, first.json()["id"])
    disk = FakeDisk()
    publish(pub.id, disk)
    index, items = index_and_items(disk, pub, db)
    assert index.photo_count == 0 and index.partitions == [] and items == []
    status = admin.get("/api/exchange").json()
    assert status["counts"] == {"test": 1, "production": 0}
    assert status["publications"][0]["status"] == "DONE"


def test_trigger_versions_exported_changes_but_not_attachment_cleanup(db):
    setup_chat(db)
    photo = intake_photo(db)
    version, updated = photo.version, photo.updated_at
    photo.status = "ERROR"
    photo.processing_error = "RuntimeError"
    db.commit()
    db.refresh(photo)
    assert photo.version == version + 1
    version, updated = photo.version, photo.updated_at
    photo.attachment = {}
    db.commit()
    db.refresh(photo)
    assert (photo.version, photo.updated_at) == (version, updated)
    with pytest.raises(DBAPIError):
        db.execute(
            text("UPDATE photos SET received_at=received_at + interval '1 day' WHERE id=:id"),
            {"id": photo.id},
        )
        db.commit()
    db.rollback()


def test_migration_preserves_old_paths_labels_and_defaults_to_test(db):
    migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic/versions/0006_manual_exchange.py"))
    preview_migration = runpy.run_path(
        str(Path(__file__).parents[1] / "alembic/versions/0009_remove_missing_preview.py")
    )
    files_migration = runpy.run_path(
        str(Path(__file__).parents[1] / "alembic/versions/0011_shared_exchange_files.py")
    )
    db.commit()
    with Operations.context(MigrationContext.configure(db.connection())):
        files_migration["downgrade"]()
        preview_migration["downgrade"]()
        migration["downgrade"]()
        db.execute(text("INSERT INTO chats(max_chat_id,name,active) VALUES (123,'legacy',true)"))
        inbox_id = db.scalar(
            text("INSERT INTO inbox(max_chat_id,message_id,payload) VALUES (123,'old','{}') RETURNING id")
        )
        db.execute(
            text("""INSERT INTO photos(inbox_id,attachment_index,attachment,max_chat_id,chat_name,max_message_id,
            is_forwarded,is_spam,status,storage_status,version,review_reason,ai_alternatives,work_type,work_type_source,yandex_disk_path)
            VALUES (:inbox,0,'{}',123,'legacy','old',false,false,'ACCEPTED','SYNCED',7,'[]','[]',
                    'BIN_EMPTYING','OPERATOR','disk:/legacy/chat/photo.jpg')"""),
            {"inbox": inbox_id},
        )
        migration["upgrade"]()
        preview_migration["upgrade"]()
        files_migration["upgrade"]()
    db.commit()
    db.expire_all()
    photo = db.scalar(select(Photo))
    assert photo.archive_layout == "legacy" and photo.cohort == "test"
    assert photo.yandex_disk_path == "disk:/legacy/chat/photo.jpg" and photo.work_type == "BIN_EMPTYING"
    assert photo.version == 7 and photo.classification_mode == "LEGACY_UNKNOWN"
    assert db.get(ExchangeState, 1).intake_cohort == "test"


def test_500_photos_full_snapshot_matches_sql_count(db):
    from app.models import Inbox

    inbox = Inbox(max_chat_id=123, message_id="peak", payload={})
    db.add(inbox)
    db.flush()
    instant = now()
    db.add_all(
        [
            Photo(
                inbox_id=inbox.id,
                attachment_index=i,
                attachment={},
                max_chat_id=123,
                chat_name="Peak",
                max_message_id="peak",
                received_at=instant - timedelta(days=i % 2),
            )
            for i in range(500)
        ]
    )
    db.commit()
    pub, disk = publication(db), FakeDisk()
    publish(pub.id, disk)
    index, items = index_and_items(disk, pub, db)
    assert index.photo_count == len(items) == 500
    assert len(index.partitions) == 2
    assert len({i.source_photo_id for i in items}) == 500


def test_worker_routes_publications_to_dedicated_publisher(db, monkeypatch):
    from app import worker
    from app.domain import enqueue

    pub = publication(db)
    enqueue(db, "PUBLISH", pub.id, f"publish:{pub.id}")
    db.commit()
    assert worker.run_once() is False
    seen = []
    monkeypatch.setattr("app.exchange.publish", lambda object_id: seen.append(object_id))
    assert worker.run_once(["PUBLISH"]) is True
    assert seen == [pub.id]
    db.expire_all()
    assert db.scalar(select(Job).where(Job.kind == "PUBLISH")).status == "DONE"
