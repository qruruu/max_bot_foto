"""Only orphan previews can be removed; healthy originals are never mutated."""

import hashlib

import httpx
import pytest
from sqlalchemy import select
from test_exchange import index_and_items, publication
from test_integration import FakeMax, GoodAI, GoodOCR, intake_photo
from test_missing_original import stored_photo

from app.domain import audit
from app.exchange import publish
from app.media import media_path
from app.models import Audit, Job, Photo
from app.processing import process_photo, regeo_all, sync_photo
from app.worker import run_once

pytestmark = pytest.mark.integration


def fixture_missing(db, monkeypatch):
    photo, disk = stored_photo(db, monkeypatch)
    disk.files.clear()
    photo.storage_status, photo.processing_error = "ERROR", "ORIGINAL_MISSING"
    db.add(
        Job(
            kind="SYNC",
            object_id=photo.id,
            dedupe_key="orphan-sync",
            status="BLOCKED",
            last_error="ORIGINAL_MISSING",
        )
    )
    db.commit()
    db.refresh(photo)

    def metadata(path):
        data = disk.files.get(path)
        return {"type": "file", "sha256": hashlib.sha256(data).hexdigest()} if data else None

    disk.metadata = metadata
    monkeypatch.setattr("app.api.YandexDisk", lambda: disk)
    return photo, disk


def remove(admin, photo):
    return admin.post(f"/api/photos/{photo.id}/remove-missing-preview", json={"version": photo.version})


def test_remove_only_orphan_preview_hides_card_cancels_jobs_preserves_tombstone(db, monkeypatch, admin):
    photo, disk = fixture_missing(db, monkeypatch)
    original_id, original_hash, version = photo.id, photo.sha256, photo.version
    preview = media_path(photo.id, preview=True)
    assert preview.is_file()
    assert remove(admin, photo).status_code == 202
    db.refresh(photo)
    assert photo.preview_removed_at and photo.version > version
    assert photo.id == original_id and photo.sha256 == original_hash
    assert photo.status == "REJECTED" and photo.storage_status == "NOT_REQUIRED"
    assert photo.review_reason == ["PREVIEW_REMOVED_ORIGINAL_MISSING"]
    assert admin.get("/api/photos?date_from=2020-01-01&date_to=2100-01-01").json()["total"] == 0
    assert admin.get("/api/reports?date_from=2020-01-01&date_to=2100-01-01").json()["total"] == 0
    assert admin.get(f"/api/photos/{photo.id}").status_code == 404
    assert admin.get(f"/api/photos/{photo.id}/preview").status_code == 404
    assert admin.get(f"/api/photos/{photo.id}/original").status_code == 404
    assert admin.post(f"/api/photos/{photo.id}/retry").status_code == 404
    assert all(j.status == "DONE" for j in db.scalars(select(Job).where(Job.kind == "SYNC")))
    assert run_once()
    assert not preview.exists()
    assert not disk.files
    assert db.scalar(select(Audit).where(Audit.action == "PHOTO_PREVIEW_REMOVED")).user_id
    # The ARM snapshot retains the same identity and a new excluded version, without an original ref.
    pub = publication(db)
    publish(pub.id, disk)
    _, items = index_and_items(disk, pub, db)
    assert len(items) == 1 and items[0].source_photo_id == str(original_id)
    assert items[0].status == "REJECTED" and items[0].original_disk_path is None
    assert items[0].source_version > version


def test_healthy_photo_and_other_errors_have_no_removal(db, monkeypatch, admin):
    photo, disk = fixture_missing(db, monkeypatch)
    for error, status in [
        (None, "SYNCED"),
        ("HTTP_404", "ERROR"),
        ("HTTP_503", "ERROR"),
        ("ORIGINAL_MISSING", "PENDING"),
    ]:
        photo.processing_error, photo.storage_status = error, status
        db.commit()
        db.refresh(photo)
        assert remove(admin, photo).status_code == 409
        db.refresh(photo)
        assert photo.preview_removed_at is None
        assert media_path(photo.id, preview=True).is_file()
    assert not disk.files


def test_restored_original_or_local_copy_prevents_removal(db, monkeypatch, admin):
    photo, disk = fixture_missing(db, monkeypatch)
    disk.files[photo.yandex_disk_path] = FakeMax().content
    assert remove(admin, photo).status_code == 409
    assert disk.files[photo.yandex_disk_path] == FakeMax().content
    disk.files.clear()
    media_path(photo.id).write_bytes(FakeMax().content)
    assert remove(admin, photo).status_code == 409
    assert media_path(photo.id).read_bytes() == FakeMax().content
    assert media_path(photo.id, preview=True).is_file()


def test_durable_transfer_destination_prevents_removal_after_move_crash(db, monkeypatch, admin):
    photo, disk = fixture_missing(db, monkeypatch)
    target = "disk:/MAX_PHOTOS/recovered/photo.jpg"
    audit(
        db,
        None,
        "STORAGE_TRANSFER_PLANNED",
        "photo",
        photo.id,
        {"path": photo.yandex_disk_path},
        {"path": target, "sha256": photo.sha256},
    )
    db.commit()
    disk.files[target] = FakeMax().content
    assert remove(admin, photo).status_code == 409
    assert media_path(photo.id, preview=True).is_file()


@pytest.mark.parametrize("code", [401, 403, 429, 500, 503])
def test_disk_failure_never_proves_absence_and_never_removes_preview(db, monkeypatch, admin, code):
    photo, disk = fixture_missing(db, monkeypatch)

    def fail(_):
        raise httpx.HTTPStatusError(
            "private data",
            request=httpx.Request("GET", "https://example.test"),
            response=httpx.Response(code),
        )

    disk.metadata = fail
    response = remove(admin, photo)
    assert response.status_code == 502 and "private" not in response.text
    db.refresh(photo)
    assert photo.preview_removed_at is None and media_path(photo.id, preview=True).is_file()
    assert db.scalar(select(Job).where(Job.kind == "SYNC")).status == "BLOCKED"


def test_stale_version_and_unauthenticated_request_cannot_remove_preview(db, monkeypatch, admin):
    photo, _ = fixture_missing(db, monkeypatch)
    assert (
        admin.post(
            f"/api/photos/{photo.id}/remove-missing-preview", json={"version": photo.version + 1}
        ).status_code
        == 409
    )
    assert admin.post("/api/auth/logout").status_code == 200
    assert remove(admin, photo).status_code == 401
    assert media_path(photo.id, preview=True).is_file()


def test_removal_is_idempotent_cleanup_resumes_and_never_deletes_a_local_original(db, monkeypatch, admin):
    from app.preview_cleanup import remove_missing_preview

    photo, disk = fixture_missing(db, monkeypatch)
    assert remove(admin, photo).status_code == 202
    assert remove(admin, photo).status_code == 202
    assert len(list(db.scalars(select(Job).where(Job.kind == "REMOVE_PREVIEW")))) == 1
    # Even a newly restored local original is not a deletion target of preview cleanup.
    original = media_path(photo.id)
    original.write_bytes(b"preserve these bytes")
    remove_missing_preview(photo.id)
    remove_missing_preview(photo.id)
    assert (
        not media_path(photo.id, preview=True).exists() and original.read_bytes() == b"preserve these bytes"
    )
    assert not disk.files
    remove_missing_preview(999999)


def test_same_file_can_be_received_again_and_duplicates_keep_valid_reference(db, monkeypatch, admin):
    photo, disk = fixture_missing(db, monkeypatch)
    dup = intake_photo(db, "duplicate")
    dup.status, dup.duplicate_of = "DUPLICATE", photo.id
    db.commit()
    assert remove(admin, photo).status_code == 202
    assert run_once()
    new = intake_photo(db, "new-copy")
    process_photo(new.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(new)
    db.refresh(dup)
    assert new.sha256 == photo.sha256 and new.duplicate_of is None and new.storage_status == "SYNCED"
    assert dup.duplicate_of == photo.id and db.get(Photo, photo.id) is not None
    # Stale worker jobs cannot resurrect the hidden photo or move a new original.
    calls = disk.upload_calls
    sync_photo(photo.id)
    regeo_all()
    assert disk.upload_calls == calls
    db.refresh(photo)
    assert photo.status == "REJECTED" and photo.storage_status == "NOT_REQUIRED"


def test_album_other_photos_and_jobs_are_not_removed(db, monkeypatch, admin):
    photo, _ = fixture_missing(db, monkeypatch)
    other = Photo(
        inbox_id=photo.inbox_id,
        attachment_index=1,
        max_chat_id=photo.max_chat_id,
        chat_name=photo.chat_name,
        max_message_id=photo.max_message_id,
    )
    db.add(other)
    job = Job(kind="BATCH", object_id=photo.inbox_id, dedupe_key="album-work", status="PENDING")
    db.add(job)
    db.commit()
    assert remove(admin, photo).status_code == 202
    db.refresh(job)
    assert job.status == "PENDING"
    assert admin.get(f"/api/photos/{other.id}").status_code == 200
