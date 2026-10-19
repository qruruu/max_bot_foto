"""A missing original is a recoverable data problem, never an endless queue retry."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event

import httpx
import pytest
import respx
from sqlalchemy import select
from test_integration import FakeDisk, FakeMax, GoodAI, GoodOCR, intake_photo, setup_chat, setup_district

from app.config import settings
from app.domain import enqueue, now
from app.integrations import OriginalMissing, YandexDisk
from app.media import media_path
from app.models import Job
from app.processing import sync_photo
from app.worker import run_once


class Storage(FakeDisk):
    def matches(self, path, digest):
        if path not in self.files:
            return False
        assert hashlib.sha256(self.files[path]).hexdigest() == digest
        return True

    def move(self, source, target, digest):
        if self.matches(target, digest):
            return
        if source not in self.files:
            raise OriginalMissing("ORIGINAL_MISSING")
        super().move(source, target, digest)


def stored_photo(db, monkeypatch):
    from app.processing import process_photo

    setup_chat(db)
    setup_district(db)
    photo = intake_photo(db)
    disk = Storage()
    process_photo(photo.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(photo)
    for job in db.scalars(select(Job)):
        job.status = "DONE"
    db.commit()
    monkeypatch.setattr("app.processing.YandexDisk", lambda: disk)
    return photo, disk


@pytest.mark.parametrize("upstream, expected", [(404, 409), (401, 502), (429, 502), (503, 502)])
def test_open_original_handles_disk_failure_without_server_error(db, monkeypatch, admin, upstream, expected):
    photo, _ = stored_photo(db, monkeypatch)
    monkeypatch.setattr(YandexDisk, "request", lambda *_a, **_k: httpx.Response(upstream))
    response = admin.get(f"/api/photos/{photo.id}/original", follow_redirects=False)
    assert response.status_code == expected and "Яндекс.Диск" in response.json()["detail"]


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError])
def test_open_original_handles_network_failures_without_leaking_details(db, monkeypatch, admin, failure):
    photo, _ = stored_photo(db, monkeypatch)

    def offline(*_args, **_kwargs):
        raise failure("private signed URL and upstream credentials")

    monkeypatch.setattr(YandexDisk, "request", offline)
    response = admin.get(f"/api/photos/{photo.id}/original", follow_redirects=False)
    assert response.status_code == 502
    assert "private" not in response.text and "Яндекс.Диск" in response.json()["detail"]


@pytest.mark.parametrize("payload", [{}, [], {"href": None}, {"href": "http://private.invalid/secret"}])
def test_open_original_handles_invalid_download_response(db, monkeypatch, admin, payload):
    photo, _ = stored_photo(db, monkeypatch)
    upstream = httpx.Response(200, json=payload, request=httpx.Request("GET", YandexDisk.API))
    monkeypatch.setattr(YandexDisk, "request", lambda *_args, **_kwargs: upstream)
    response = admin.get(f"/api/photos/{photo.id}/original", follow_redirects=False)
    assert response.status_code == 502
    assert "private" not in response.text


@respx.mock
def test_confirmed_missing_source_and_target_not_generic_404(monkeypatch):
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "test")
    settings.cache_clear()
    api = YandexDisk.API
    meta = respx.get(api + "/resources").mock(return_value=httpx.Response(404))
    with pytest.raises(OriginalMissing):
        YandexDisk().move("disk:/old", "disk:/new", "digest")
    assert meta.call_count == 2


@respx.mock
def test_same_path_still_checks_original_exists(monkeypatch):
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "test")
    settings.cache_clear()
    route = respx.get(YandexDisk.API + "/resources").mock(return_value=httpx.Response(404))
    with pytest.raises(OriginalMissing):
        YandexDisk().move("disk:/old", "disk:/old", "digest")
    assert route.call_count == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
@respx.mock
def test_disk_access_and_transient_errors_are_not_missing_files(monkeypatch, status):
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "test")
    settings.cache_clear()
    respx.get(YandexDisk.API + "/resources").mock(return_value=httpx.Response(status))
    with pytest.raises(httpx.HTTPStatusError):
        YandexDisk().move("disk:/old", "disk:/new", "digest")


@respx.mock
def test_404_move_race_checks_verified_destination_before_pausing(monkeypatch):
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "test")
    settings.cache_clear()
    respx.get(YandexDisk.API + "/resources").mock(
        side_effect=[
            httpx.Response(404),
            httpx.Response(200, json={"sha256": "digest"}),
            httpx.Response(200, json={"sha256": "digest"}),
        ]
    )
    respx.put(YandexDisk.API + "/resources").mock(return_value=httpx.Response(201))
    respx.post(YandexDisk.API + "/resources/move").mock(return_value=httpx.Response(404))
    YandexDisk().move("disk:/old", "disk:/new", "digest")


def test_missing_original_pauses_one_job_and_finishes_redundant_legacy_jobs(db, monkeypatch, admin):
    photo, disk = stored_photo(db, monkeypatch)
    disk.files.clear()
    version = photo.version
    # Simulate duplicate legacy tasks from the screenshot; they all concern the same current photo.
    for i in range(8):
        db.add(Job(kind="SYNC", object_id=photo.id, dedupe_key=f"legacy:{i}", status="PENDING", attempts=90))
    db.commit()
    assert run_once()
    db.expire_all()
    jobs = list(db.scalars(select(Job).where(Job.kind == "SYNC").order_by(Job.id)))
    assert [j.status for j in jobs] == ["BLOCKED"] + ["DONE"] * 7
    assert jobs[0].last_error == "ORIGINAL_MISSING" and jobs[0].attempts == 91
    assert not run_once()  # No more calls or attempts while paused.
    db.refresh(photo)
    assert photo.version > version and photo.processing_error == "ORIGINAL_MISSING"
    assert photo.storage_status == "ERROR" and photo.yandex_disk_path
    assert media_path(photo.id, preview=True).is_file()
    assert admin.get(f"/api/photos/{photo.id}/original", follow_redirects=False).status_code == 409
    response = admin.get("/api/jobs").json()
    assert len(response) == 1 and response[0]["status"] == "BLOCKED"
    # Restoring the original at its former path makes the explicit retry succeed.
    disk.files[photo.yandex_disk_path] = FakeMax().content
    assert admin.post(f"/api/jobs/{jobs[0].id}/retry").status_code == 200
    assert run_once()
    db.refresh(photo)
    db.refresh(jobs[0])
    assert photo.storage_status == "SYNCED" and photo.processing_error is None
    assert jobs[0].status == "DONE"


def test_network_failure_keeps_one_automatic_retry(db, monkeypatch):
    photo, disk = stored_photo(db, monkeypatch)
    enqueue(db, "SYNC", photo.id, "sync:network")
    db.commit()

    def fail(*_):
        raise httpx.ReadTimeout("private upstream URL must not reach the UI")

    monkeypatch.setattr(disk, "move", fail)
    assert run_once()
    db.expire_all()
    job = db.scalar(select(Job).where(Job.kind == "SYNC"))
    assert job.status == "PENDING" and job.next_run_at > now() and job.last_error == "ReadTimeout"


def test_deleted_disk_original_recovers_only_from_exact_local_original(db, monkeypatch):
    photo, disk = stored_photo(db, monkeypatch)
    disk.files.clear()
    media_path(photo.id).write_bytes(FakeMax().content)
    sync_photo(photo.id)
    db.refresh(photo)
    assert photo.storage_status == "SYNCED" and disk.files[photo.yandex_disk_path] == FakeMax().content
    assert not media_path(photo.id).exists()


def test_local_preview_or_changed_bytes_never_replace_missing_original(db, monkeypatch):
    photo, disk = stored_photo(db, monkeypatch)
    disk.files.clear()
    media_path(photo.id).write_bytes(b"not the same original")
    with pytest.raises(RuntimeError, match="LOCAL_ORIGINAL_HASH_MISMATCH"):
        sync_photo(photo.id)
    assert not disk.files and media_path(photo.id).read_bytes() == b"not the same original"


def test_two_manual_photo_retries_reuse_one_pending_job(db, monkeypatch, admin):
    photo, _ = stored_photo(db, monkeypatch)
    for _ in range(3):
        assert admin.post(f"/api/photos/{photo.id}/retry").status_code == 200
    assert len(list(db.scalars(select(Job).where(Job.kind == "SYNC", Job.status == "PENDING")))) == 1


def test_concurrent_sync_workers_make_one_disk_call(db, monkeypatch):
    photo, disk = stored_photo(db, monkeypatch)
    for i in range(2):
        db.add(Job(kind="SYNC", object_id=photo.id, dedupe_key=f"race:{i}", status="RUNNING"))
    db.commit()
    jobs = list(db.scalars(select(Job).where(Job.kind == "SYNC").order_by(Job.id)))
    entered, proceed = Event(), Event()
    original_move = disk.move
    calls = []

    def slow_move(*args):
        calls.append(args)
        entered.set()
        assert proceed.wait(5)
        original_move(*args)

    monkeypatch.setattr(disk, "move", slow_move)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sync_photo, photo.id, jobs[0].id)
        assert entered.wait(5)
        second = pool.submit(sync_photo, photo.id, jobs[1].id)
        proceed.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert len(calls) == 1
    db.refresh(jobs[1])
    assert jobs[1].status == "DONE"


@respx.mock
def test_unexplained_move_404_is_retryable_when_source_still_exists(monkeypatch):
    monkeypatch.setenv("YANDEX_DISK_TOKEN", "test")
    settings.cache_clear()
    respx.get(YandexDisk.API + "/resources").mock(
        side_effect=[
            httpx.Response(404),
            httpx.Response(200, json={"sha256": "digest"}),
            httpx.Response(404),
            httpx.Response(200, json={"sha256": "digest"}),
        ]
    )
    respx.put(YandexDisk.API + "/resources").mock(return_value=httpx.Response(201))
    respx.post(YandexDisk.API + "/resources/move").mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        YandexDisk().move("disk:/old", "disk:/new", "digest")


def test_move_recovers_after_remote_success_then_another_operator_edit(db, monkeypatch, admin):
    photo, disk = stored_photo(db, monkeypatch)
    original_path = photo.yandex_disk_path
    move = disk.move

    def crash_after_move(*args):
        move(*args)
        raise RuntimeError("lost connection after successful move")

    photo.photo_date = date(2026, 10, 1)
    db.commit()
    monkeypatch.setattr(disk, "move", crash_after_move)
    with pytest.raises(RuntimeError):
        sync_photo(photo.id)
    db.refresh(photo)
    assert photo.yandex_disk_path == original_path and original_path not in disk.files
    response = admin.patch(
        f"/api/photos/{photo.id}", json={"version": photo.version, "photo_date": "2026-10-02"}
    )
    assert response.status_code == 200
    monkeypatch.setattr(disk, "move", move)
    sync_photo(photo.id)
    db.refresh(photo)
    assert photo.storage_status == "SYNCED" and photo.processing_error is None
    assert "/2026-10-02/" in photo.yandex_disk_path
    assert list(disk.files) == [photo.yandex_disk_path]
    assert disk.files[photo.yandex_disk_path] == FakeMax().content


def test_upload_recovers_old_destination_before_applying_a_correction(db, monkeypatch):
    from app.processing import process_photo

    setup_chat(db)
    setup_district(db)
    photo, disk = intake_photo(db), Storage()
    disk.fail = True
    with pytest.raises(RuntimeError):
        process_photo(photo.id, FakeMax(), disk, GoodOCR(), GoodAI())
    db.refresh(photo)
    assert photo.yandex_disk_path is None and len(disk.files) == 1
    photo.photo_date = date(2026, 10, 3)
    db.commit()
    disk.fail = False
    monkeypatch.setattr("app.processing.YandexDisk", lambda: disk)
    sync_photo(photo.id)
    db.refresh(photo)
    assert "/2026-10-03/" in photo.yandex_disk_path
    assert list(disk.files) == [photo.yandex_disk_path]
    assert not media_path(photo.id).exists()
